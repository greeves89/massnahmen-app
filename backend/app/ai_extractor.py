"""Vision-basierte Extraktion von BSO-Formular-Feldern.

Pipeline:
  1. Preprocessing (PIL): EXIF-Rotation, Auto-Kontrast, Schärfen, Resize auf 2400px Längsseite.
  2. Pass 1 (Reasoning): Modell beschreibt Schritt-für-Schritt was es sieht (Hand-OCR + Lokalisierung).
  3. Pass 2 (JSON): Modell konvertiert Beschreibung in striktes JSON-Schema.

Zwei Passes reduzieren Halluzinationen drastisch: das Modell muss erst "denken",
bevor es formalisiert.
"""

from __future__ import annotations

import base64
import io
import json
import logging
from pathlib import Path
from typing import Any

import httpx
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from .config import settings

logger = logging.getLogger(__name__)


# ---------- Preprocessing ----------

def _preprocess_image(img_bytes: bytes, max_dim: int = 2400) -> bytes:
    img = Image.open(io.BytesIO(img_bytes))
    img.load()
    # 1) EXIF-Rotation anwenden (Handy-Fotos)
    img = ImageOps.exif_transpose(img)

    # 2) Konvertieren — RGB für Kontrast-Operationen
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")

    # 3) Resize: Längsseite auf max_dim (Vergrößern wenn klein, Verkleinern wenn riesig)
    w, h = img.size
    longest = max(w, h)
    if longest != max_dim:
        scale = max_dim / longest
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

    # 4) Auto-Kontrast (1% clipping) + Helligkeit leicht erhöhen
    img = ImageOps.autocontrast(img, cutoff=1)
    img = ImageEnhance.Brightness(img).enhance(1.05)
    img = ImageEnhance.Contrast(img).enhance(1.15)

    # 5) Unsharp-Mask für klarere Kanten von Handschrift/Druckschrift
    img = img.filter(ImageFilter.UnsharpMask(radius=1.5, percent=140, threshold=2))

    # 6) Als PNG zurückgeben (bessere OCR-Qualität als JPEG)
    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()


def _pdf_to_pngs(pdf_bytes: bytes, dpi: int = 220, max_pages: int = 3) -> list[bytes]:
    import fitz  # pymupdf

    pngs: list[bytes] = []
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            pix = page.get_pixmap(dpi=dpi)
            pngs.append(_preprocess_image(pix.tobytes("png")))
    return pngs


def file_to_image_payloads(filename: str, data: bytes) -> list[str]:
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        pngs = _pdf_to_pngs(data)
    elif ext in {".png", ".jpg", ".jpeg", ".webp", ".heic"}:
        pngs = [_preprocess_image(data)]
    else:
        raise ValueError(f"Nicht unterstützter Dateityp für KI-Analyse: {ext}")
    return [f"data:image/png;base64,{base64.b64encode(p).decode()}" for p in pngs]


# ---------- Pass 1 — Reasoning / Beschreibung ----------

DESCRIBE_PROMPT = """Du betrachtest ein deutsches BSO-Formular (Berufs- und Studienorientierung).
Ich brauche nur folgende Infos:

1) ANGEBOT: Was steht in der Linie nach "für die Teilnahme an folgendem Angebot der
   Berufs- bzw. Studienorientierung" (vor "(z.B. Vocatium)")?
   Beispiele: "Vocatium Hamburg", "BIZ-Besuch", "Tag der offenen Tür Uni Köln",
   "Praktikumstag bei Siemens".
   Wenn unklar: "sieht aus wie X". Wenn komplett unlesbar: "unleserlich".

2) DATUM: Welches Datum steht in der "am ___ (Datum)" Linie unter dem Angebot?
   Format wie es da steht (z.B. "29.09.26" oder "15. März 2026"). Wenn nicht erkennbar: "unbekannt".

3) BEWERTUNG: In der Rückmeldungs-Tabelle gibt es 5 Zeilen und 3 Spalten:
   - SPALTE 1 (links) = ☺ positiv
   - SPALTE 2 (mitte) = ☻ neutral
   - SPALTE 3 (rechts) = ☹ negativ
   Für jede Zeile: wo sitzt die Markierung (oder leer)?

Antworte ALS REINER TEXT, kurz und präzise:
Angebot: ...
Datum: ...
a) links/mitte/rechts/leer
b) ...
c) ...
d) ...
e) ..."""


# ---------- Pass 2 — Strukturierung in JSON ----------

JSON_PROMPT_TEMPLATE = """Du bekommst gleich eine kurze Beschreibung eines BSO-Formulars.
Konvertiere sie in striktes JSON nach diesem Schema:

{{
  "angebot": string | null,
  "bewertung": {{
    "informativ":   1 | 0 | -1 | null,
    "persoenlich":  1 | 0 | -1 | null,
    "orientierung": 1 | 0 | -1 | null,
    "empfehlung":   1 | 0 | -1 | null,
    "entscheidung": 1 | 0 | -1 | null
  }},
  "notizen": string | null
}}

REGELN:
- `angebot`: bester Tipp aus der Beschreibung. Wenn "unleserlich" → null.
- Bewertung: "links" → 1, "mitte" → 0, "rechts" → -1, "leer" → null.
- `notizen`: kurze Liste was unsicher war (für manuelle Prüfung). Leer wenn alles sicher.

=== BESCHREIBUNG ===
{description}
=== ENDE BESCHREIBUNG ===

Antworte AUSSCHLIESSLICH mit dem JSON."""


# ---------- Azure-OpenAI-Calls ----------

async def _call_azure(messages: list[dict[str, Any]], json_mode: bool = False, max_tokens: int = 2000) -> str:
    body = {
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}

    url = (
        f"{settings.azure_openai_endpoint.rstrip('/')}/openai/deployments/"
        f"{settings.azure_openai_deployment}/chat/completions"
        f"?api-version={settings.azure_openai_api_version}"
    )
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            url, json=body,
            headers={"api-key": settings.azure_openai_key, "Content-Type": "application/json"},
        )
        if resp.status_code != 200:
            logger.error("Azure OpenAI %s: %s", resp.status_code, resp.text[:600])
            raise RuntimeError(f"KI-Service-Fehler ({resp.status_code}).")
        data = resp.json()
    return data["choices"][0]["message"]["content"]


# ---------- Public API ----------

import re

_POS = re.compile(r"\b(links?|positiv|smile|☺|positive)\b", re.IGNORECASE)
_NEU = re.compile(r"\b(mitte|mittlere?|neutral|meh|☻)\b", re.IGNORECASE)
_NEG = re.compile(r"\b(rechts?|negativ|frown|☹|negative)\b", re.IGNORECASE)
_LEER = re.compile(r"\b(leer|keine? markierung|empty|none)\b", re.IGNORECASE)


def _parse_zeile(text: str) -> int | None:
    """Mappe eine Zeile wie 'a) mitte' auf den numerischen Wert."""
    # Priorität: explicit "leer" > spezifische Position
    if _LEER.search(text):
        return None
    if _POS.search(text):
        return 1
    if _NEG.search(text):
        return -1
    if _NEU.search(text):
        return 0
    return None


def _parse_date_str(raw: str) -> str | None:
    """Versuche '29.09.26', '29.09.2026', '15.3.2026', '15. März 2026' → YYYY-MM-DD."""
    if not raw:
        return None
    txt = raw.strip().lower()
    if any(w in txt for w in ("unbekannt", "unleserlich", "leer")):
        return None

    months = {
        "jan": 1, "januar": 1, "feb": 2, "februar": 2, "mär": 3, "maerz": 3, "märz": 3,
        "apr": 4, "april": 4, "mai": 5, "jun": 6, "juni": 6, "jul": 7, "juli": 7,
        "aug": 8, "august": 8, "sep": 9, "september": 9, "okt": 10, "oktober": 10,
        "nov": 11, "november": 11, "dez": 12, "dezember": 12,
    }

    # Versuche numerisch: 29.09.26 / 29.09.2026 / 29-9-26
    m = re.search(r"(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{2,4})", txt)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:
            y = 2000 + y if y >= 24 else 1900 + y
        try:
            from datetime import date
            return date(y, mo, d).isoformat()
        except ValueError:
            pass

    # Textuell: 15. März 2026
    m = re.search(r"(\d{1,2})\.?\s+([a-zäöüß]+)\s+(\d{4})", txt)
    if m:
        d = int(m.group(1))
        mo_name = m.group(2)[:3]
        y = int(m.group(3))
        mo = months.get(m.group(2)) or months.get(mo_name)
        if mo:
            try:
                from datetime import date
                return date(y, mo, d).isoformat()
            except ValueError:
                pass
    return None


def _deterministic_parse(description: str) -> dict[str, Any]:
    """Parse Pass-1-Beschreibung deterministisch (kein LLM, kein Mapping-Fehler)."""
    angebot: str | None = None
    angebot_datum: str | None = None
    bewertung_keys = ("informativ", "persoenlich", "orientierung", "empfehlung", "entscheidung")
    bewertung: dict[str, int | None] = dict.fromkeys(bewertung_keys, None)
    notizen_parts: list[str] = []

    for raw_line in description.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        low = line.lower()

        # Angebot
        m = re.match(r"^\s*angebot[:\-]\s*(.+)$", line, re.IGNORECASE)
        if m:
            value = m.group(1).strip().strip(".")
            value = re.sub(r"\s*\([^)]*\)\s*$", "", value).strip()
            if value and "unleserlich" not in value.lower() and "unbekannt" not in value.lower():
                angebot = value
            continue

        # Datum
        m = re.match(r"^\s*datum[:\-]\s*(.+)$", line, re.IGNORECASE)
        if m:
            angebot_datum = _parse_date_str(m.group(1))
            continue

        # Zeilen-Marker a) b) c) d) e)
        m = re.match(r"^\s*([a-e1-5])[\.\)]\s+(.+)$", line, re.IGNORECASE)
        if m:
            idx_char = m.group(1).lower()
            mapping = {"a": 0, "b": 1, "c": 2, "d": 3, "e": 4,
                       "1": 0, "2": 1, "3": 2, "4": 3, "5": 4}
            idx = mapping.get(idx_char)
            if idx is not None and idx < len(bewertung_keys):
                bewertung[bewertung_keys[idx]] = _parse_zeile(m.group(2))
            continue

        # Notizen-Hinweis
        if any(w in low for w in ("unsicher", "unleserlich", "schwer lesbar", "wahrscheinlich")):
            notizen_parts.append(line)

    return {
        "angebot": angebot,
        "angebot_datum": angebot_datum,
        "bewertung": bewertung,
        "notizen": " · ".join(notizen_parts) if notizen_parts else None,
    }


async def extract_from_file(filename: str, data: bytes) -> dict[str, Any]:
    if not settings.ai_enabled:
        raise RuntimeError("KI-Analyse ist nicht aktiviert.")
    if not (settings.azure_openai_endpoint and settings.azure_openai_key):
        raise RuntimeError("Azure-OpenAI-Konfiguration fehlt.")

    image_urls = file_to_image_payloads(filename, data)
    if not image_urls:
        raise RuntimeError("Aus der Datei konnten keine Seiten extrahiert werden.")

    # Single Pass: Modell beschreibt strukturiert, wir parsen deterministisch.
    pass1_content: list[dict[str, Any]] = [
        {"type": "image_url", "image_url": {"url": url, "detail": "high"}} for url in image_urls
    ]
    pass1_content.append({"type": "text", "text": DESCRIBE_PROMPT})
    description = await _call_azure(
        [{"role": "user", "content": pass1_content}], json_mode=False, max_tokens=600
    )
    logger.info("Description: %s", description[:300])

    return _deterministic_parse(description)

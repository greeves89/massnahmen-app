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

DESCRIBE_PROMPT = """Du betrachtest ein deutsches Schul-Formular für Berufs- und Studienorientierung (BSO).
Beschreibe jetzt SCHRITT FÜR SCHRITT was du siehst — sehr präzise und ehrlich.

Wichtige Regeln:
- Wenn Handschrift NICHT eindeutig lesbar ist, schreib "unlesbar" oder "unsicher: könnte X oder Y sein".
- Erfinde NIEMALS Wörter, die du nicht klar siehst. Lieber "unlesbar".
- Beschreibe für jedes Feld: was steht da? Bist du sicher? Welche Buchstaben siehst du?
- Bei Checkboxes: ist da deutlich ein Kreuz/Häkchen? Oder ist die Box leer?
- Bei den 3 Spalten der Bewertungs-Tabelle (LINKS=positiv, MITTE=neutral, RECHTS=negativ):
  In welcher Spalte sitzt für jede Zeile die Markierung? Oder ist die Zeile leer?

Gehe Sektion für Sektion durch:
A. Antrag auf Freistellung
   - Schüler-Name: was steht auf der Linie? (Buchstaben einzeln aufzählen wenn unsicher)
   - Angebot: was steht auf der Linie?
   - Datum: welche Zahlen siehst du?
   - Freistellungs-Checkboxes 1/2/3: ist eine angekreuzt? Wenn ja welche?
   - Unterschriften: Datum und Name (oder "unleserlich")

B. Beurlaubungs-Entscheidung
   - Ist "Beurlaubung wird erteilt" angekreuzt?
   - Ist "Beurlaubung wird nicht erteilt" angekreuzt?
   - Beides leer = "noch nicht entschieden"
   - Datum + Unterschrift Tutor

C. Bestätigung der Teilnahme
   - Name (Bestätigender)
   - Datum
   - Institution / Stempel
   - "E-Mail-Bestätigung angehängt" Checkbox: leer oder angekreuzt?

D. Rückmeldung (5 Zeilen)
   Für jede Zeile genau angeben: Markierung in LINKER (positiv), MITTLERER (neutral),
   RECHTER (negativ) Spalte — oder leer?
   1) "war informativ und qualitativ gut" → ?
   2) "hat mir persönlich geholfen" → ?
   3) "gab eine gute Orientierung" → ?
   4) "ist auch anderen zu empfehlen" → ?
   5) "hat mir bei einer Entscheidung geholfen" → ?

E. Kenntnisnahme
   - Datum + Unterschrift Tutor
   - Datum + Unterschrift Eltern

Antworte als reiner Text (KEIN JSON), eine Sektion pro Absatz."""


# ---------- Pass 2 — Strukturierung in JSON ----------

JSON_PROMPT_TEMPLATE = """Du bekommst gleich eine Beschreibung eines BSO-Formulars (siehe unten).
Konvertiere die Beschreibung in striktes JSON nach diesem Schema.

WICHTIG:
- Wenn die Beschreibung "unlesbar", "unsicher", "leer" oder ähnliches enthält → entsprechendes Feld `null` (Strings) bzw. `false` (Booleans).
- KEINE Daten erfinden, die nicht in der Beschreibung stehen.
- Datum-Format YYYY-MM-DD. "29.09.26" → "2026-09-29". Zweistellige Jahre ab 24 = 20xx.
- Bewertung: positive Spalte (links) = 1, neutrale (mitte) = 0, negative (rechts) = -1, leer = null.

Schema:
{{
  "schueler_name": string | null,
  "angebot": string | null,
  "angebot_datum": "YYYY-MM-DD" | null,
  "freistellung_nummer": 1 | 2 | 3 | null,
  "beurlaubung_status": "erteilt" | "nicht_erteilt" | null,
  "beurlaubung_begruendung": string | null,
  "teilnahme_bestaetigt": boolean,
  "teilnahme_datum": "YYYY-MM-DD" | null,
  "institution_name": string | null,
  "bestaetigung_per_email": boolean,
  "bewertung": {{
    "informativ":   1 | 0 | -1 | null,
    "persoenlich":  1 | 0 | -1 | null,
    "orientierung": 1 | 0 | -1 | null,
    "empfehlung":   1 | 0 | -1 | null,
    "entscheidung": 1 | 0 | -1 | null
  }},
  "kenntnis_tutor_datum": "YYYY-MM-DD" | null,
  "kenntnis_eltern_datum": "YYYY-MM-DD" | null,
  "notizen": string | null
}}

In `notizen` kurz festhalten, welche Felder unsicher / unlesbar waren (für menschliche Review).

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

async def extract_from_file(filename: str, data: bytes) -> dict[str, Any]:
    if not settings.ai_enabled:
        raise RuntimeError("KI-Analyse ist nicht aktiviert.")
    if not (settings.azure_openai_endpoint and settings.azure_openai_key):
        raise RuntimeError("Azure-OpenAI-Konfiguration fehlt.")

    image_urls = file_to_image_payloads(filename, data)
    if not image_urls:
        raise RuntimeError("Aus der Datei konnten keine Seiten extrahiert werden.")

    # Pass 1: Beschreibung
    pass1_content: list[dict[str, Any]] = [
        {"type": "image_url", "image_url": {"url": url, "detail": "high"}} for url in image_urls
    ]
    pass1_content.append({"type": "text", "text": DESCRIBE_PROMPT})
    description = await _call_azure(
        [{"role": "user", "content": pass1_content}], json_mode=False, max_tokens=2500
    )
    logger.info("Pass 1 description (%d chars): %s", len(description), description[:300])

    # Pass 2: Beschreibung → JSON
    json_prompt = JSON_PROMPT_TEMPLATE.format(description=description)
    raw_json = await _call_azure(
        [{"role": "user", "content": json_prompt}], json_mode=True, max_tokens=1500
    )

    try:
        return json.loads(raw_json)
    except json.JSONDecodeError as e:
        logger.error("Could not parse AI JSON: %s — raw: %s", e, raw_json[:500])
        raise RuntimeError("Antwort der KI konnte nicht gelesen werden.")

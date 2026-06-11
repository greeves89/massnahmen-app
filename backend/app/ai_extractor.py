"""Vision-basierte Extraktion von BSO-Formular-Feldern aus Bild oder PDF.

Konvertiert Eingabe zu PNG(s) und ruft Azure OpenAI gpt-4.1 mit JSON-Mode auf.
"""

from __future__ import annotations

import base64
import io
import json
import logging
from pathlib import Path
from typing import Any

import httpx

from .config import settings

logger = logging.getLogger(__name__)

EXTRACT_PROMPT = """Du analysierst ein deutsches Schul-Formular zur Berufs- und Studienorientierung (BSO).
Das Formular hat folgende Bereiche:
  1. Antrag auf Freistellung: Schüler:in-Name, Angebot (z.B. Vocatium), Datum, 1./2./3. Freistellung (Checkbox)
  2. Beurlaubungs-Entscheidung des Tutors: erteilt / nicht erteilt (Checkbox) + Begründung
  3. Bestätigung der Teilnahme: Institutionsname, Datum, ggf. "E-Mail mit Bestätigung ist angehängt" (Checkbox)
  4. Rückmeldung: 5 Aussagen, jeweils Spalte 😊 / 😐 / 😞 (Kreuz pro Zeile)
  5. Kenntnisnahme: Datum Tutor und Datum Sorgeberechtigte

Extrahiere ALLE ausgefüllten Felder. Antworte AUSSCHLIESSLICH mit JSON nach diesem Schema:
{
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
  "bewertung": {
    "informativ": 1 | 0 | -1 | null,
    "persoenlich": 1 | 0 | -1 | null,
    "orientierung": 1 | 0 | -1 | null,
    "empfehlung": 1 | 0 | -1 | null,
    "entscheidung": 1 | 0 | -1 | null
  },
  "kenntnis_tutor_datum": "YYYY-MM-DD" | null,
  "kenntnis_eltern_datum": "YYYY-MM-DD" | null,
  "notizen": string | null
}

Regeln:
- Bewertung: Kreuz/Markierung in 😊-Spalte = 1, in 😐 = 0, in 😞 = -1. Keine Markierung = null.
- Reihenfolge der Bewertungs-Aussagen ist: 1) informativ und qualitativ gut, 2) persönlich geholfen, 3) gute Orientierung, 4) anderen zu empfehlen, 5) bei Entscheidung geholfen.
- Datumsangaben strikt als YYYY-MM-DD. "15.09.2025" → "2025-09-15". Unklar/leer → null.
- teilnahme_bestaetigt: true wenn Sektion 3 (oder eine separate Bestätigungs-Unterschrift) ausgefüllt ist.
- bestaetigung_per_email: true wenn die entsprechende Checkbox angekreuzt ist.
- Leere/nicht ausgefüllte Felder = null (Strings) bzw. false (Booleans).
- Falls Formular handgeschriebene Daten enthält: nach bestem Wissen lesen, Vornamen + Nachnamen zusammen.
"""


def _pdf_to_pngs(pdf_bytes: bytes, dpi: int = 180, max_pages: int = 3) -> list[bytes]:
    import fitz  # pymupdf

    pngs: list[bytes] = []
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            pix = page.get_pixmap(dpi=dpi)
            pngs.append(pix.tobytes("png"))
    return pngs


def _normalize_image(data: bytes, max_dim: int = 1600) -> bytes:
    """Re-encode arbitrary image bytes as PNG and resize if oversized."""
    from PIL import Image

    img = Image.open(io.BytesIO(data))
    img.load()
    if img.mode not in ("RGB", "RGBA", "L"):
        img = img.convert("RGB")
    w, h = img.size
    if max(w, h) > max_dim:
        scale = max_dim / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)))
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def file_to_image_payloads(filename: str, data: bytes) -> list[str]:
    """Return list of data URLs (PNG base64) — one per page if PDF, one if image."""
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        pngs = _pdf_to_pngs(data)
    elif ext in {".png", ".jpg", ".jpeg", ".webp", ".heic"}:
        pngs = [_normalize_image(data)]
    else:
        raise ValueError(f"Nicht unterstützter Dateityp für KI-Analyse: {ext}")
    return [
        f"data:image/png;base64,{base64.b64encode(p).decode()}" for p in pngs
    ]


async def extract_from_file(filename: str, data: bytes) -> dict[str, Any]:
    """Extrahiert das BSO-Schema aus einer Datei (PDF/Bild) via Azure OpenAI.

    Raises RuntimeError mit User-freundlicher Nachricht bei Konfig- oder API-Fehlern.
    """
    if not settings.ai_enabled:
        raise RuntimeError("KI-Analyse ist nicht aktiviert (AI_ENABLED=false).")
    if not (settings.azure_openai_endpoint and settings.azure_openai_key):
        raise RuntimeError("Azure-OpenAI-Konfiguration fehlt.")

    image_urls = file_to_image_payloads(filename, data)
    if not image_urls:
        raise RuntimeError("Aus der Datei konnten keine Seiten extrahiert werden.")

    content: list[dict[str, Any]] = [
        {"type": "image_url", "image_url": {"url": url}} for url in image_urls
    ]
    content.append({"type": "text", "text": EXTRACT_PROMPT})

    body = {
        "messages": [{"role": "user", "content": content}],
        "max_tokens": 1500,
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    url = (
        f"{settings.azure_openai_endpoint.rstrip('/')}/openai/deployments/"
        f"{settings.azure_openai_deployment}/chat/completions"
        f"?api-version={settings.azure_openai_api_version}"
    )

    async with httpx.AsyncClient(timeout=90.0) as client:
        resp = await client.post(
            url,
            json=body,
            headers={"api-key": settings.azure_openai_key, "Content-Type": "application/json"},
        )
        if resp.status_code != 200:
            logger.error("Azure OpenAI %s: %s", resp.status_code, resp.text[:500])
            raise RuntimeError(f"KI-Service-Fehler ({resp.status_code}).")
        data = resp.json()

    try:
        raw = data["choices"][0]["message"]["content"]
        return json.loads(raw)
    except (KeyError, json.JSONDecodeError) as e:
        logger.error("Could not parse AI response: %s — raw: %s", e, data)
        raise RuntimeError("Antwort der KI konnte nicht gelesen werden.")

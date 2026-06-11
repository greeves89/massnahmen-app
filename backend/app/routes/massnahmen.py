import os
import re
import shutil
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..deps import get_current_user
from ..ai_extractor import extract_from_file
from ..config import settings
from ..models import Anhang, Massnahme, User
from sqlalchemy.orm import selectinload
from ..utils import SMILEY_MAP, current_schuljahr, schuljahr_for_date, smiley_label

UPLOADS_ROOT = Path(os.environ.get("UPLOADS_DIR", "/data/uploads"))
ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".eml", ".msg", ".heic"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB


def _sanitize_filename(name: str) -> str:
    name = os.path.basename(name)
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._-")
    return name or "anhang"

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError:
        return None


@router.get("/massnahmen/neu", response_class=HTMLResponse)
async def neu_form(
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    cats = await session.execute(
        select(Massnahme.kategorie).where(
            Massnahme.user_id == user.id, Massnahme.kategorie.is_not(None)
        ).distinct()
    )
    return templates.TemplateResponse(
        request,
        "massnahme_form.html",
        {
            "massnahme": None,
            "user": user,
            "schuljahr_default": current_schuljahr(),
            "today": date.today().isoformat(),
            "kategorien": sorted({c for (c,) in cats if c}),
        },
    )


@router.post("/massnahmen/neu")
async def neu_submit(
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    schueler_name: str = Form(...),
    angebot: str = Form(...),
    kategorie: str = Form(""),
    angebot_datum: str = Form(""),
    freistellung_nummer: str = Form(""),
    schuljahr: str = Form(""),
):
    angebot_d = _parse_date(angebot_datum)
    sj = schuljahr.strip() or (schuljahr_for_date(angebot_d) if angebot_d else current_schuljahr())
    massnahme = Massnahme(
        user_id=user.id,
        schueler_name=schueler_name.strip(),
        angebot=angebot.strip(),
        kategorie=kategorie.strip() or None,
        angebot_datum=angebot_d,
        freistellung_nummer=_parse_int(freistellung_nummer),
        schuljahr=sj,
    )
    session.add(massnahme)
    await session.commit()
    return RedirectResponse(url=f"/massnahmen/{massnahme.id}", status_code=303)


@router.get("/massnahmen/{massnahme_id}", response_class=HTMLResponse)
async def detail(
    massnahme_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    massnahme = await _get_owned(session, massnahme_id, user, with_anhaenge=True)
    cats = await session.execute(
        select(Massnahme.kategorie).where(
            Massnahme.user_id == user.id, Massnahme.kategorie.is_not(None)
        ).distinct()
    )
    return templates.TemplateResponse(
        request,
        "massnahme_detail.html",
        {
            "massnahme": massnahme,
            "user": user,
            "smiley_map": SMILEY_MAP,
            "smiley_label": smiley_label,
            "today": date.today().isoformat(),
            "kategorien": sorted({c for (c,) in cats if c}),
        },
    )


@router.post("/massnahmen/{massnahme_id}/edit")
async def edit_basis(
    massnahme_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    schueler_name: str = Form(...),
    angebot: str = Form(...),
    kategorie: str = Form(""),
    angebot_datum: str = Form(""),
    freistellung_nummer: str = Form(""),
    schuljahr: str = Form(""),
    notizen: str = Form(""),
):
    massnahme = await _get_owned(session, massnahme_id, user)
    massnahme.schueler_name = schueler_name.strip()
    massnahme.angebot = angebot.strip()
    massnahme.kategorie = kategorie.strip() or None
    massnahme.angebot_datum = _parse_date(angebot_datum)
    massnahme.freistellung_nummer = _parse_int(freistellung_nummer)
    massnahme.schuljahr = schuljahr.strip() or massnahme.schuljahr
    massnahme.notizen = notizen.strip() or None
    await session.commit()
    return RedirectResponse(url=f"/massnahmen/{massnahme.id}?saved=1", status_code=303)


@router.post("/massnahmen/{massnahme_id}/beurlaubung")
async def edit_beurlaubung(
    massnahme_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    beurlaubung_status: str = Form(""),
    beurlaubung_begruendung: str = Form(""),
):
    massnahme = await _get_owned(session, massnahme_id, user)
    massnahme.beurlaubung_status = beurlaubung_status.strip() or None
    massnahme.beurlaubung_begruendung = beurlaubung_begruendung.strip() or None
    await session.commit()
    return RedirectResponse(url=f"/massnahmen/{massnahme.id}?saved=1", status_code=303)


@router.post("/massnahmen/{massnahme_id}/teilnahme")
async def edit_teilnahme(
    massnahme_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    teilnahme_bestaetigt: str = Form(""),
    teilnahme_datum: str = Form(""),
    institution_name: str = Form(""),
    bestaetigung_per_email: str = Form(""),
):
    massnahme = await _get_owned(session, massnahme_id, user)
    massnahme.teilnahme_bestaetigt = teilnahme_bestaetigt == "on"
    massnahme.teilnahme_datum = _parse_date(teilnahme_datum)
    massnahme.institution_name = institution_name.strip() or None
    massnahme.bestaetigung_per_email = bestaetigung_per_email == "on"
    await session.commit()
    return RedirectResponse(url=f"/massnahmen/{massnahme.id}?saved=1", status_code=303)


VALID_BEWERTUNGS_FIELDS = {
    "informativ", "persoenlich", "orientierung", "empfehlung", "entscheidung"
}


@router.post("/massnahmen/{massnahme_id}/kategorie", response_class=HTMLResponse)
async def set_kategorie_single(
    massnahme_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    kategorie: str = Form(""),
):
    """HTMX-Endpoint: speichert nur die Kategorie und liefert den Badge zurück."""
    massnahme = await _get_owned(session, massnahme_id, user)
    massnahme.kategorie = kategorie.strip() or None
    await session.commit()
    badge = massnahme.kategorie or ""
    if badge:
        html = (
            f'<span class="text-xs bg-indigo-50 text-indigo-700 px-1.5 py-0.5 rounded inline-flex items-center gap-1">'
            f'<i data-lucide="tag" class="w-3 h-3"></i>{badge}</span>'
        )
    else:
        html = '<span class="text-xs text-slate-400">—</span>'
    return HTMLResponse(html)


@router.post("/massnahmen/{massnahme_id}/bewertung/{feld}", response_class=HTMLResponse)
async def set_bewertung_single(
    massnahme_id: int,
    feld: str,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    wert: str = Form(...),
):
    """HTMX-Endpoint: speichert eine einzelne Bewertung sofort und liefert
    den aktuellen Durchschnitt als HTML-Fragment zurück."""
    if feld not in VALID_BEWERTUNGS_FIELDS:
        raise HTTPException(status_code=400, detail="Ungültiges Bewertungsfeld")
    massnahme = await _get_owned(session, massnahme_id, user)
    setattr(massnahme, f"bewertung_{feld}", _parse_int(wert))
    await session.commit()
    return templates.TemplateResponse(
        request,
        "_bewertung_durchschnitt.html",
        {"massnahme": massnahme},
    )


@router.post("/massnahmen/{massnahme_id}/kenntnis")
async def edit_kenntnis(
    massnahme_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    kenntnis_tutor_datum: str = Form(""),
    kenntnis_eltern_datum: str = Form(""),
):
    massnahme = await _get_owned(session, massnahme_id, user)
    massnahme.kenntnis_tutor_datum = _parse_date(kenntnis_tutor_datum)
    massnahme.kenntnis_eltern_datum = _parse_date(kenntnis_eltern_datum)
    await session.commit()
    return RedirectResponse(url=f"/massnahmen/{massnahme.id}?saved=1", status_code=303)


@router.post("/massnahmen/{massnahme_id}/loeschen")
async def loeschen(
    massnahme_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    massnahme = await _get_owned(session, massnahme_id, user, with_anhaenge=True)
    for a in massnahme.anhaenge:
        _delete_attachment_file(a.pfad)
    if massnahme.anhang_pfad:
        _delete_attachment_file(massnahme.anhang_pfad)
    await session.delete(massnahme)
    await session.commit()
    return RedirectResponse(url="/?deleted=1", status_code=303)


@router.post("/massnahmen/{massnahme_id}/anhang")
async def upload_anhang(
    massnahme_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    files: list[UploadFile] = File(...),
):
    massnahme = await _get_owned(session, massnahme_id, user)
    files = [f for f in files if f and f.filename]
    if not files:
        raise HTTPException(status_code=400, detail="Keine Datei(en) ausgewählt")

    errors: list[str] = []
    for file in files:
        ext = Path(file.filename).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            errors.append(f"{file.filename}: Typ nicht erlaubt")
            continue

        safe_name = _sanitize_filename(file.filename)
        target_dir = UPLOADS_ROOT / str(user.id) / str(massnahme.id)
        target_dir.mkdir(parents=True, exist_ok=True)
        unique = uuid.uuid4().hex[:8]
        target_path = target_dir / f"{unique}_{safe_name}"

        written = 0
        too_large = False
        with target_path.open("wb") as out:
            while chunk := await file.read(64 * 1024):
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    too_large = True
                    break
                out.write(chunk)
        if too_large:
            target_path.unlink(missing_ok=True)
            errors.append(f"{file.filename}: zu groß (max 10 MB)")
            continue

        anhang = Anhang(
            massnahme_id=massnahme.id,
            dateiname=safe_name,
            pfad=str(target_path),
            mimetype=file.content_type or "application/octet-stream",
            groesse=written,
        )
        session.add(anhang)

    await session.commit()
    if errors:
        raise HTTPException(status_code=400, detail="; ".join(errors))
    return RedirectResponse(url=f"/massnahmen/{massnahme.id}?saved=1", status_code=303)


@router.get("/anhaenge/{anhang_id}")
async def download_anhang(
    anhang_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Anhang).join(Massnahme).where(
            Anhang.id == anhang_id, Massnahme.user_id == user.id
        )
    )
    anhang = result.scalar_one_or_none()
    if not anhang or not os.path.exists(anhang.pfad):
        raise HTTPException(status_code=404, detail="Anhang nicht gefunden")
    return FileResponse(
        path=anhang.pfad,
        filename=anhang.dateiname,
        media_type=anhang.mimetype or "application/octet-stream",
    )


@router.post("/anhaenge/{anhang_id}/loeschen")
async def delete_anhang(
    anhang_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Anhang).join(Massnahme).where(
            Anhang.id == anhang_id, Massnahme.user_id == user.id
        )
    )
    anhang = result.scalar_one_or_none()
    if not anhang:
        raise HTTPException(status_code=404, detail="Anhang nicht gefunden")
    massnahme_id = anhang.massnahme_id
    _delete_attachment_file(anhang.pfad)
    await session.delete(anhang)
    await session.commit()
    return RedirectResponse(url=f"/massnahmen/{massnahme_id}?saved=1", status_code=303)


@router.get("/bulk-kategorien", response_class=HTMLResponse)
async def bulk_kategorien_view(
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    only_ohne: str = "",
):
    """Bulk-Edit: alle Maßnahmen mit Inline-Kategorie-Input + Vorschlag-Button."""
    stmt = select(Massnahme).where(Massnahme.user_id == user.id)
    if only_ohne == "1":
        stmt = stmt.where(Massnahme.kategorie.is_(None))
    stmt = stmt.order_by(desc(Massnahme.schuljahr), desc(Massnahme.angebot_datum))
    result = await session.execute(stmt)
    massnahmen = result.scalars().all()

    cat_rows = await session.execute(
        select(Massnahme.kategorie).where(
            Massnahme.user_id == user.id, Massnahme.kategorie.is_not(None)
        ).distinct()
    )
    kategorien = sorted({c for (c,) in cat_rows if c})
    ohne_count = sum(1 for m in massnahmen if not m.kategorie) if only_ohne != "1" else len(massnahmen)

    return templates.TemplateResponse(
        request,
        "bulk_kategorien.html",
        {
            "user": user,
            "massnahmen": massnahmen,
            "kategorien": kategorien,
            "only_ohne": only_ohne == "1",
            "ohne_count": ohne_count,
            "total": len(massnahmen),
        },
    )


@router.post("/bulk-kategorien/vorschlaege")
async def bulk_kategorien_vorschlaege(
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Wendet _match_category() auf alle Maßnahmen ohne Kategorie an."""
    cat_rows = await session.execute(
        select(Massnahme.kategorie).where(
            Massnahme.user_id == user.id, Massnahme.kategorie.is_not(None)
        ).distinct()
    )
    existing = sorted({c for (c,) in cat_rows if c})
    if not existing:
        return RedirectResponse(
            url="/bulk-kategorien?keine_kategorien=1", status_code=303
        )
    result = await session.execute(
        select(Massnahme).where(
            Massnahme.user_id == user.id, Massnahme.kategorie.is_(None)
        )
    )
    leer = result.scalars().all()
    n_set = 0
    for m in leer:
        match = _match_category(m.angebot or "", existing)
        if match:
            m.kategorie = match
            n_set += 1
    await session.commit()
    return RedirectResponse(
        url=f"/bulk-kategorien?vorschlaege={n_set}", status_code=303
    )


@router.post("/massnahmen/analyse")
async def analyze_and_create(
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    file: UploadFile = File(...),
):
    """Akzeptiert eine Datei (PDF/Bild), lässt sie von der KI analysieren,
    erstellt daraus eine vorausgefüllte Maßnahme + Bewertung und hängt das Original an."""
    if not settings.ai_enabled:
        raise HTTPException(status_code=503, detail="KI-Analyse ist nicht aktiviert.")
    if not file.filename:
        raise HTTPException(status_code=400, detail="Keine Datei ausgewählt")
    ext = Path(file.filename).suffix.lower()
    if ext not in {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".heic"}:
        raise HTTPException(
            status_code=400,
            detail="Nur PDF und Bilder können analysiert werden (PDF/JPG/PNG/HEIC).",
        )

    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Datei zu groß (max 10 MB)")
    if not raw:
        raise HTTPException(status_code=400, detail="Leere Datei")

    try:
        extracted = await extract_from_file(file.filename, raw)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"KI-Analyse fehlgeschlagen: {e}")

    # Vereinfachtes Schema: KI liefert nur angebot + bewertung + notizen.
    # Alle anderen Felder kann Julia danach selber setzen.
    cat_rows = await session.execute(
        select(Massnahme.kategorie).where(
            Massnahme.user_id == user.id, Massnahme.kategorie.is_not(None)
        ).distinct()
    )
    existing_categories = sorted({c for (c,) in cat_rows if c})
    angebot_text = (extracted.get("angebot") or "").strip()
    suggested = _match_category(angebot_text, existing_categories)

    today = date.today()
    massnahme = Massnahme(
        user_id=user.id,
        schueler_name="—",  # Julia kann manuell setzen
        angebot=angebot_text[:500] or "(KI konnte Angebot nicht lesen)",
        kategorie=suggested,
        angebot_datum=today,  # Default: heute (Julia kann ändern)
        freistellung_nummer=None,
        schuljahr=current_schuljahr(),
        beurlaubung_status=None,
        beurlaubung_begruendung=None,
        teilnahme_bestaetigt=False,
        teilnahme_datum=None,
        institution_name=None,
        bestaetigung_per_email=False,
        kenntnis_tutor_datum=None,
        kenntnis_eltern_datum=None,
        notizen=_str_or_none(extracted.get("notizen")),
    )
    bew = extracted.get("bewertung") or {}
    massnahme.bewertung_informativ = _int_in_set(bew.get("informativ"), {-1, 0, 1})
    massnahme.bewertung_persoenlich = _int_in_set(bew.get("persoenlich"), {-1, 0, 1})
    massnahme.bewertung_orientierung = _int_in_set(bew.get("orientierung"), {-1, 0, 1})
    massnahme.bewertung_empfehlung = _int_in_set(bew.get("empfehlung"), {-1, 0, 1})
    massnahme.bewertung_entscheidung = _int_in_set(bew.get("entscheidung"), {-1, 0, 1})

    session.add(massnahme)
    await session.flush()  # need ID for attachment path

    # Original-Datei als Anhang speichern
    safe_name = _sanitize_filename(file.filename)
    target_dir = UPLOADS_ROOT / str(user.id) / str(massnahme.id)
    target_dir.mkdir(parents=True, exist_ok=True)
    unique = uuid.uuid4().hex[:8]
    target_path = target_dir / f"{unique}_{safe_name}"
    target_path.write_bytes(raw)

    anhang = Anhang(
        massnahme_id=massnahme.id,
        dateiname=safe_name,
        pfad=str(target_path),
        mimetype=file.content_type or "application/octet-stream",
        groesse=len(raw),
    )
    session.add(anhang)
    await session.commit()

    return RedirectResponse(url=f"/massnahmen/{massnahme.id}?ai=1", status_code=303)


def _safe_date(value: Any) -> date | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _int_in_set(value: Any, allowed: set[int]) -> int | None:
    try:
        v = int(value)
    except (TypeError, ValueError):
        return None
    return v if v in allowed else None


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _status_or_none(value: Any) -> str | None:
    if value in ("erteilt", "nicht_erteilt"):
        return value
    return None


def _match_category(angebot: str, existing: list[str]) -> str | None:
    """Einfaches Substring/Word-Match gegen bestehende Kategorien."""
    if not angebot or not existing:
        return None
    a_lower = angebot.lower()
    # Direct substring match
    for cat in existing:
        if cat.lower() in a_lower or a_lower in cat.lower():
            return cat
    # Token-overlap match
    tokens = set(re.findall(r"[a-zäöüß]{4,}", a_lower))
    best = None
    best_overlap = 0
    for cat in existing:
        cat_tokens = set(re.findall(r"[a-zäöüß]{4,}", cat.lower()))
        ov = len(tokens & cat_tokens)
        if ov > best_overlap:
            best_overlap = ov
            best = cat
    return best if best_overlap >= 1 else None


def _delete_attachment_file(path: str) -> None:
    try:
        p = Path(path)
        if p.exists():
            p.unlink()
            try:
                p.parent.rmdir()
            except OSError:
                pass
    except Exception:
        pass


async def _get_owned(session: AsyncSession, massnahme_id: int, user: User, with_anhaenge: bool = False) -> Massnahme:
    stmt = select(Massnahme).where(Massnahme.id == massnahme_id, Massnahme.user_id == user.id)
    if with_anhaenge:
        stmt = stmt.options(selectinload(Massnahme.anhaenge))
    result = await session.execute(stmt)
    massnahme = result.scalar_one_or_none()
    if not massnahme:
        raise HTTPException(status_code=404, detail="Maßnahme nicht gefunden")
    return massnahme

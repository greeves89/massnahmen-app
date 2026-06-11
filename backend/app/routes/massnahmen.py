from datetime import date, datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..deps import get_current_user
from ..models import Massnahme, User
from ..utils import SMILEY_MAP, current_schuljahr, schuljahr_for_date, smiley_label

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
async def neu_form(request: Request, user: User = Depends(get_current_user)):
    return templates.TemplateResponse(
        request,
        "massnahme_form.html",
        {
            "massnahme": None,
            "user": user,
            "schuljahr_default": current_schuljahr(),
            "today": date.today().isoformat(),
        },
    )


@router.post("/massnahmen/neu")
async def neu_submit(
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    schueler_name: str = Form(...),
    angebot: str = Form(...),
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
    massnahme = await _get_owned(session, massnahme_id, user)
    return templates.TemplateResponse(
        request,
        "massnahme_detail.html",
        {
            "massnahme": massnahme,
            "user": user,
            "smiley_map": SMILEY_MAP,
            "smiley_label": smiley_label,
            "today": date.today().isoformat(),
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
    angebot_datum: str = Form(""),
    freistellung_nummer: str = Form(""),
    schuljahr: str = Form(""),
    notizen: str = Form(""),
):
    massnahme = await _get_owned(session, massnahme_id, user)
    massnahme.schueler_name = schueler_name.strip()
    massnahme.angebot = angebot.strip()
    massnahme.angebot_datum = _parse_date(angebot_datum)
    massnahme.freistellung_nummer = _parse_int(freistellung_nummer)
    massnahme.schuljahr = schuljahr.strip() or massnahme.schuljahr
    massnahme.notizen = notizen.strip() or None
    await session.commit()
    return RedirectResponse(url=f"/massnahmen/{massnahme.id}", status_code=303)


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
    return RedirectResponse(url=f"/massnahmen/{massnahme.id}", status_code=303)


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
    return RedirectResponse(url=f"/massnahmen/{massnahme.id}", status_code=303)


@router.post("/massnahmen/{massnahme_id}/bewertung")
async def edit_bewertung(
    massnahme_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    bewertung_informativ: str = Form(""),
    bewertung_persoenlich: str = Form(""),
    bewertung_orientierung: str = Form(""),
    bewertung_empfehlung: str = Form(""),
    bewertung_entscheidung: str = Form(""),
):
    massnahme = await _get_owned(session, massnahme_id, user)
    massnahme.bewertung_informativ = _parse_int(bewertung_informativ)
    massnahme.bewertung_persoenlich = _parse_int(bewertung_persoenlich)
    massnahme.bewertung_orientierung = _parse_int(bewertung_orientierung)
    massnahme.bewertung_empfehlung = _parse_int(bewertung_empfehlung)
    massnahme.bewertung_entscheidung = _parse_int(bewertung_entscheidung)
    await session.commit()
    return RedirectResponse(url=f"/massnahmen/{massnahme.id}", status_code=303)


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
    return RedirectResponse(url=f"/massnahmen/{massnahme.id}", status_code=303)


@router.post("/massnahmen/{massnahme_id}/loeschen")
async def loeschen(
    massnahme_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    massnahme = await _get_owned(session, massnahme_id, user)
    await session.delete(massnahme)
    await session.commit()
    return RedirectResponse(url="/", status_code=303)


async def _get_owned(session: AsyncSession, massnahme_id: int, user: User) -> Massnahme:
    result = await session.execute(
        select(Massnahme).where(Massnahme.id == massnahme_id, Massnahme.user_id == user.id)
    )
    massnahme = result.scalar_one_or_none()
    if not massnahme:
        raise HTTPException(status_code=404, detail="Maßnahme nicht gefunden")
    return massnahme

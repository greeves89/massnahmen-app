from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..deps import get_current_user
from ..models import User
from ..security import hash_password, verify_password

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/einstellungen", response_class=HTMLResponse)
async def settings_page(request: Request, user: User = Depends(get_current_user)):
    return templates.TemplateResponse(
        request,
        "settings.html",
        {"user": user, "msg": None, "err": None},
    )


@router.post("/einstellungen/profil")
async def update_profile(
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    name: str = Form(...),
):
    user.name = name.strip()
    await session.commit()
    return templates.TemplateResponse(
        request,
        "settings.html",
        {"user": user, "msg": "Name gespeichert.", "err": None},
    )


@router.post("/einstellungen/passwort")
async def change_password(
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    aktuelles_passwort: str = Form(...),
    neues_passwort: str = Form(...),
    neues_passwort_bestaetigen: str = Form(...),
):
    if not verify_password(aktuelles_passwort, user.password_hash):
        return templates.TemplateResponse(
            request, "settings.html",
            {"user": user, "msg": None, "err": "Aktuelles Passwort ist falsch."},
            status_code=400,
        )
    if len(neues_passwort) < 8:
        return templates.TemplateResponse(
            request, "settings.html",
            {"user": user, "msg": None, "err": "Neues Passwort muss mindestens 8 Zeichen lang sein."},
            status_code=400,
        )
    if neues_passwort != neues_passwort_bestaetigen:
        return templates.TemplateResponse(
            request, "settings.html",
            {"user": user, "msg": None, "err": "Die beiden neuen Passwörter stimmen nicht überein."},
            status_code=400,
        )
    user.password_hash = hash_password(neues_passwort)
    await session.commit()
    return templates.TemplateResponse(
        request, "settings.html",
        {"user": user, "msg": "Passwort wurde geändert.", "err": None},
    )

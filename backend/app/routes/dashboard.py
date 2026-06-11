from collections import defaultdict

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..deps import get_current_user
from ..models import Massnahme, User
from ..utils import SMILEY_MAP, average_smiley, current_schuljahr, smiley_label

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

BEWERTUNGS_FIELDS = [
    ("informativ", "Informativ & qualitativ gut"),
    ("persoenlich", "Persönlich geholfen"),
    ("orientierung", "Gute Orientierung"),
    ("empfehlung", "Anderen zu empfehlen"),
    ("entscheidung", "Bei Entscheidung geholfen"),
]


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Massnahme).where(Massnahme.user_id == user.id).order_by(desc(Massnahme.angebot_datum), desc(Massnahme.id))
    )
    massnahmen = list(result.scalars().all())

    by_year: dict[str, list[Massnahme]] = defaultdict(list)
    for m in massnahmen:
        by_year[m.schuljahr].append(m)

    # Statistik pro Schuljahr
    stats = []
    for sj in sorted(by_year.keys(), reverse=True):
        items = by_year[sj]
        feld_averages = {}
        for key, label in BEWERTUNGS_FIELDS:
            werte = [getattr(m, f"bewertung_{key}") for m in items]
            werte = [w for w in werte if w is not None]
            avg = sum(werte) / len(werte) if werte else None
            feld_averages[key] = {
                "label": label,
                "avg": avg,
                "smiley": average_smiley(avg),
                "count": len(werte),
            }
        gesamt = [m.bewertung_average for m in items if m.bewertung_average is not None]
        gesamt_avg = sum(gesamt) / len(gesamt) if gesamt else None
        stats.append({
            "schuljahr": sj,
            "anzahl": len(items),
            "feld_averages": feld_averages,
            "gesamt_avg": gesamt_avg,
            "gesamt_smiley": average_smiley(gesamt_avg),
            "massnahmen": items,
        })

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "user": user,
            "stats": stats,
            "current_schuljahr": current_schuljahr(),
            "smiley_label": smiley_label,
            "bewertungs_fields": BEWERTUNGS_FIELDS,
            "total": len(massnahmen),
        },
    )

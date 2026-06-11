from collections import defaultdict

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..deps import get_current_user
from ..models import Massnahme, User
from ..utils import average_smiley

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

BEWERTUNGS_FIELDS = [
    ("informativ", "Informativ"),
    ("persoenlich", "Persönlich geholfen"),
    ("orientierung", "Orientierung"),
    ("empfehlung", "Empfehlung"),
    ("entscheidung", "Entscheidung"),
]


def _avg(values: list[float | int]) -> float | None:
    nums = [v for v in values if v is not None]
    return sum(nums) / len(nums) if nums else None


@router.get("/analyse", response_class=HTMLResponse)
async def analyse(
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Massnahme).where(Massnahme.user_id == user.id)
    )
    massnahmen = list(result.scalars().all())

    if not massnahmen:
        return templates.TemplateResponse(
            request,
            "analyse.html",
            {"user": user, "empty": True},
        )

    # === Schuljahr-Trend (gesamt) ===
    by_year: dict[str, list[float]] = defaultdict(list)
    by_year_count: dict[str, int] = defaultdict(int)
    for m in massnahmen:
        by_year_count[m.schuljahr] += 1
        avg = m.bewertung_average
        if avg is not None:
            by_year[m.schuljahr].append(avg)

    schuljahre = sorted(by_year_count.keys())  # chronologisch aufsteigend
    schuljahr_trend = [
        {
            "schuljahr": sj,
            "anzahl": by_year_count[sj],
            "avg": _avg(by_year.get(sj, [])),
            "smiley": average_smiley(_avg(by_year.get(sj, []))),
        }
        for sj in schuljahre
    ]

    # === Pro Kategorie über Schuljahre ===
    # massnahmen ohne Kategorie → Kategorie "(ohne Kategorie)"
    cat_to_year_avg: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    cat_count: dict[str, int] = defaultdict(int)
    for m in massnahmen:
        cat = m.kategorie or "(ohne Kategorie)"
        cat_count[cat] += 1
        avg = m.bewertung_average
        if avg is not None:
            cat_to_year_avg[cat][m.schuljahr].append(avg)

    kategorien = sorted(cat_count.keys(), key=lambda c: (-cat_count[c], c))

    kategorie_zeitreihe = []
    for cat in kategorien:
        per_year = []
        for sj in schuljahre:
            werte = cat_to_year_avg[cat].get(sj, [])
            avg = _avg(werte)
            per_year.append({"schuljahr": sj, "avg": avg, "n": len(werte)})
        # Trend: Vergleich frühestes vs spätestes Jahr mit Wert
        years_with_values = [p for p in per_year if p["avg"] is not None]
        trend_delta = None
        if len(years_with_values) >= 2:
            trend_delta = years_with_values[-1]["avg"] - years_with_values[0]["avg"]
        all_values = [v for ys in cat_to_year_avg[cat].values() for v in ys]
        kategorie_zeitreihe.append({
            "kategorie": cat,
            "anzahl": cat_count[cat],
            "per_year": per_year,
            "gesamt_avg": _avg(all_values),
            "gesamt_smiley": average_smiley(_avg(all_values)),
            "trend_delta": trend_delta,
        })

    # === Pro Bewertungs-Frage über Schuljahre ===
    pro_frage = []
    for key, label in BEWERTUNGS_FIELDS:
        per_year = []
        for sj in schuljahre:
            werte = [getattr(m, f"bewertung_{key}") for m in massnahmen if m.schuljahr == sj]
            werte = [w for w in werte if w is not None]
            avg = _avg(werte)
            per_year.append({"schuljahr": sj, "avg": avg, "n": len(werte)})
        pro_frage.append({"key": key, "label": label, "per_year": per_year})

    # === Top / Flop Kategorien ===
    cat_avg_list = [(cat["kategorie"], cat["gesamt_avg"], cat["anzahl"]) for cat in kategorie_zeitreihe if cat["gesamt_avg"] is not None and cat["anzahl"] >= 1]
    top = sorted(cat_avg_list, key=lambda x: -x[1])[:5]
    flop = sorted(cat_avg_list, key=lambda x: x[1])[:5]

    return templates.TemplateResponse(
        request,
        "analyse.html",
        {
            "user": user,
            "empty": False,
            "schuljahre": schuljahre,
            "schuljahr_trend": schuljahr_trend,
            "kategorie_zeitreihe": kategorie_zeitreihe,
            "pro_frage": pro_frage,
            "top": top,
            "flop": flop,
            "total_massnahmen": len(massnahmen),
            "total_kategorien": len([c for c in cat_count.keys() if c != "(ohne Kategorie)"]),
        },
    )

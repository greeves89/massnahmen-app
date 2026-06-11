from datetime import date


def schuljahr_for_date(d: date) -> str:
    """Schuljahr läuft 1. August bis 31. Juli.

    Beispiel: 15.09.2025 → "2025/2026", 12.03.2026 → "2025/2026"
    """
    if d.month >= 8:
        start = d.year
    else:
        start = d.year - 1
    return f"{start}/{start + 1}"


def current_schuljahr() -> str:
    return schuljahr_for_date(date.today())


SMILEY_MAP = {1: "😊", 0: "😐", -1: "😞"}


def smiley_label(value: int | None) -> str:
    if value is None:
        return "—"
    return SMILEY_MAP.get(value, "—")


def average_smiley(avg: float | None) -> str:
    if avg is None:
        return "—"
    if avg >= 0.34:
        return "😊"
    if avg <= -0.34:
        return "😞"
    return "😐"

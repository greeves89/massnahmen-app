from datetime import date


def schuljahr_for_date(d: date) -> str:
    if d.month >= 8:
        start = d.year
    else:
        start = d.year - 1
    return f"{start}/{start + 1}"


def current_schuljahr() -> str:
    return schuljahr_for_date(date.today())


# Lucide-Icon-Namen statt Emojis
SMILEY_ICON_MAP = {1: "smile", 0: "meh", -1: "frown"}
SMILEY_COLOR_CLASS = {1: "icon-pos", 0: "icon-neu", -1: "icon-neg"}


def smiley_icon_name(value: int | None) -> str | None:
    if value is None:
        return None
    return SMILEY_ICON_MAP.get(value)


def smiley_color_class(value: int | None) -> str:
    if value is None:
        return "text-slate-300"
    return SMILEY_COLOR_CLASS.get(value, "text-slate-400")


def average_icon_name(avg: float | None) -> str | None:
    if avg is None:
        return None
    if avg >= 0.34:
        return "smile"
    if avg <= -0.34:
        return "frown"
    return "meh"


def average_color_class(avg: float | None) -> str:
    if avg is None:
        return "text-slate-300"
    if avg >= 0.34:
        return "icon-pos"
    if avg <= -0.34:
        return "icon-neg"
    return "icon-neu"


# Legacy aliases for older imports
SMILEY_MAP = SMILEY_ICON_MAP
smiley_label = smiley_icon_name


def average_smiley(avg: float | None) -> str:
    """Legacy: gibt Lucide-Icon-Name zurück (für Templates die noch das alte API nutzen)."""
    return average_icon_name(avg) or "minus"

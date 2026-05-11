"""Utilidades de fecha y formato para uso interno."""
from datetime import date, datetime, timedelta

_ES_MONTHS = [
    "ene", "feb", "mar", "abr", "may", "jun",
    "jul", "ago", "sep", "oct", "nov", "dic",
]


def monday_of_week(d: date) -> date:
    """Devuelve el lunes de la semana ISO a la que pertenece la fecha."""
    return d - timedelta(days=d.weekday())


def now_iso() -> str:
    """Timestamp actual en ISO 8601 sin tz (hora local)."""
    return datetime.now().replace(microsecond=0).isoformat()


def format_human_es(dt: datetime) -> str:
    """Formato 'DD mmm HH:MM' para mostrar al usuario en español."""
    return f"{dt.day} {_ES_MONTHS[dt.month - 1]} {dt:%H:%M}"

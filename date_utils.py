"""Utilidades de fecha y formato para uso interno."""
from datetime import date, datetime, timedelta

import pytz

_ES_MONTHS = [
    "ene", "feb", "mar", "abr", "may", "jun",
    "jul", "ago", "sep", "oct", "nov", "dic",
]

_MADRID = pytz.timezone("Europe/Madrid")


def _now_utc() -> datetime:
    """Indirección que tests pueden monkeypatchear."""
    return datetime.now(pytz.UTC)


def now_madrid() -> datetime:
    """Datetime tz-aware en zona horaria Europe/Madrid."""
    return _now_utc().astimezone(_MADRID)


def now_madrid_naive() -> datetime:
    """Reloj de pared de Madrid como datetime naive (para comparar con valores naive en BD)."""
    return now_madrid().replace(tzinfo=None)


def today_madrid() -> date:
    """Fecha actual en zona horaria de Madrid."""
    return now_madrid().date()


def monday_of_week(d: date) -> date:
    """Devuelve el lunes de la semana ISO a la que pertenece la fecha."""
    return d - timedelta(days=d.weekday())


def now_iso() -> str:
    """Timestamp actual en ISO 8601 sin tz (hora Madrid)."""
    return now_madrid_naive().replace(microsecond=0).isoformat()


def format_human_es(dt: datetime) -> str:
    """Formato 'DD mmm HH:MM' para mostrar al usuario en español."""
    return f"{dt.day} {_ES_MONTHS[dt.month - 1]} {dt:%H:%M}"

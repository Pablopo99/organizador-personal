"""Jobs programados: mensaje matutino y recordatorios proactivos."""
import logging
from datetime import datetime, timedelta

from telegram.constants import ParseMode
from telegram.ext import ContextTypes

import db
from config import ALLOWED_USER_ID

log = logging.getLogger("scheduler")

_WEEKDAYS_ES = [
    "lunes", "martes", "miércoles", "jueves",
    "viernes", "sábado", "domingo",
]

_ES_MONTHS = [
    "ene", "feb", "mar", "abr", "may", "jun",
    "jul", "ago", "sep", "oct", "nov", "dic",
]


async def morning_summary(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Envía el saludo matutino con la vista de hoy."""
    import date_utils
    import views

    today = date_utils.today_madrid()
    weekday = _WEEKDAYS_ES[today.weekday()]
    date_str = f"{today.day} {_ES_MONTHS[today.month - 1]}"
    greeting = f"Buenos días Pablo 🌅 — <b>{weekday}, {date_str}</b>\n\n"

    try:
        with db.connect() as conn:
            body, keyboard = views.render_today_view(today, conn)
    except Exception:
        log.exception("Error generando el saludo matutino")
        return

    try:
        await context.bot.send_message(
            chat_id=ALLOWED_USER_ID,
            text=greeting + body,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )
    except Exception:
        log.exception("Error enviando el saludo matutino")


async def weekly_objectives_reminder(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Domingo a las 13:00 Madrid: pídele a Pablo pensar los 3 objetivos de la semana que entra."""
    text = (
        "🎯 <b>Domingo de objetivos</b>\n\n"
        "Para la semana que empieza mañana, párate y piensa tus <b>3 objetivos</b>. "
        "Cuéntamelos cuando los tengas claros y los apunto."
    )
    try:
        await context.bot.send_message(
            chat_id=ALLOWED_USER_ID,
            text=text,
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        log.exception("Error enviando recordatorio semanal de objetivos")


_DAY_REMINDER_MIN_HOURS = 23.0
_DAY_REMINDER_MAX_HOURS = 25.0
_HOUR_REMINDER_MIN_MIN = 50.0
_HOUR_REMINDER_MAX_MIN = 70.0


async def check_reminders(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Cada 5 min: revisa eventos próximos y manda recordatorios pendientes."""
    now = datetime.now()
    upper = now + timedelta(hours=26)

    with db.connect() as conn:
        rows = conn.execute(
            """
            SELECT id, title, datetime, reminder_1d_sent, reminder_1h_sent
            FROM events
            WHERE done = 0
              AND recurring_rule IS NULL
              AND datetime >= ?
              AND datetime <= ?
            """,
            (now.isoformat(timespec="seconds"), upper.isoformat(timespec="seconds")),
        ).fetchall()

    for row in rows:
        try:
            event_dt = datetime.fromisoformat(row["datetime"])
        except ValueError:
            log.warning("Evento %s con datetime inválido: %r", row["id"], row["datetime"])
            continue

        delta = event_dt - now
        hours = delta.total_seconds() / 3600.0
        minutes = delta.total_seconds() / 60.0

        if (_DAY_REMINDER_MIN_HOURS <= hours <= _DAY_REMINDER_MAX_HOURS
                and row["reminder_1d_sent"] == 0):
            time_str = event_dt.strftime("%H:%M")
            text = f"📅 Mañana a las {time_str} tienes: <b>{row['title']}</b>"
            await _safe_send_and_mark(context, text, row["id"], "reminder_1d_sent")

        if (_HOUR_REMINDER_MIN_MIN <= minutes <= _HOUR_REMINDER_MAX_MIN
                and row["reminder_1h_sent"] == 0):
            text = f"⏰ En 1h tienes: <b>{row['title']}</b>"
            await _safe_send_and_mark(context, text, row["id"], "reminder_1h_sent")


async def _safe_send_and_mark(context, text: str, event_id: int, flag_column: str) -> None:
    """Envía el recordatorio y marca el flag. Si falla, loguea pero no levanta."""
    try:
        await context.bot.send_message(
            chat_id=ALLOWED_USER_ID,
            text=text,
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        log.exception("Error enviando recordatorio para evento %s", event_id)
        return

    with db.connect() as conn:
        conn.execute(
            f"UPDATE events SET {flag_column} = 1 WHERE id = ?",
            (event_id,),
        )

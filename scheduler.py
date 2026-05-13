"""Jobs programados: mensaje matutino y recordatorios proactivos."""
import logging
from datetime import datetime, timedelta

from telegram.constants import ParseMode
from telegram.ext import ContextTypes

import brain
import db
from config import ALLOWED_USER_ID
from formatting import markdown_to_html

log = logging.getLogger("scheduler")

# User id interno (no real) para aislar la memoria conversacional del scheduler
# del chat normal del usuario. Cada matutino se genera con historial limpio.
_SCHEDULER_USER_ID = -1

_WEEKDAYS_ES = [
    "lunes", "martes", "miércoles", "jueves",
    "viernes", "sábado", "domingo",
]


def _morning_prompt() -> str:
    today = datetime.now()
    weekday = _WEEKDAYS_ES[today.weekday()]
    date_str = today.strftime("%Y-%m-%d")
    return (
        f"Es {weekday}, {date_str}. Genera el saludo matutino para Pablo. "
        "Empieza con 'Buenos días Pablo 🌅' y a continuación aplica el formato del resumen del día "
        "siguiendo EXACTAMENTE estos pasos:\n"
        "1. Llama a query_events(date_from=hoy 00:00, date_to=hoy 23:59, include_done=true).\n"
        "2. Llama a list_tasks(include_done=true).\n"
        "3. Construye las secciones (OMITE las vacías sin decir nada):\n"
        "   📅 HOY = eventos del paso 1 con done=0\n"
        "   📝 PENDIENTES = tareas del paso 2 con done=0\n"
        "   ✅ COMPLETADO HOY = eventos del paso 1 con done=1 + tareas del paso 2 con done_at de hoy\n"
        "4. Si no hay nada en ninguna sección, di solo que puede disfrutar del día libre.\n"
        "5. Cierra con una frase motivadora breve si encaja."
    )


async def morning_summary(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Envía el saludo matutino con el resumen del día."""
    # Aislamos el contexto del scheduler: nada de memoria heredada del chat.
    brain.reset_history(_SCHEDULER_USER_ID)
    try:
        reply = brain.handle_message(_morning_prompt(), user_id=_SCHEDULER_USER_ID)
    except Exception:
        log.exception("Error generando el saludo matutino")
        return

    text = markdown_to_html(reply)
    try:
        await context.bot.send_message(
            chat_id=ALLOWED_USER_ID,
            text=text,
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        log.exception("Error enviando el saludo matutino")


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

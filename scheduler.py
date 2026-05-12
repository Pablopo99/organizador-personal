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
    try:
        reply = brain.handle_message(_morning_prompt(), user_id=ALLOWED_USER_ID)
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

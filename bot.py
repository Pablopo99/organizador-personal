"""Listener de Telegram. Filtra por usuario autorizado y delega en el cerebro."""
import asyncio
import html
import logging
from typing import Optional

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import anthropic

import brain
import date_utils
import db
import tools
import transcriber
import views
from config import ALLOWED_USER_ID, TELEGRAM_TOKEN, USER_NAME
from formatting import markdown_to_html

_RATE_LIMIT_MSG = (
    "⏳ He alcanzado el límite de la API de Anthropic por un instante. "
    "Espera ~1 minuto y reenvíame el mensaje."
)

# Store en memoria para "Deshacer" borrados de /duplicados. Mapea un token
# entero → snapshot del item borrado (capturado antes de borrar). Se pierde
# al reiniciar el bot: el deshacer es inmediato, mientras el mensaje exista.
_undo_store: dict[int, dict] = {}
_undo_seq = 0
_UNDO_MAX = 50  # tope de snapshots vivos; evita crecimiento ilimitado


def _push_undo(snapshot: dict) -> int:
    """Guarda un snapshot y devuelve un token único para el botón Deshacer.
    Mantiene como mucho _UNDO_MAX entradas (descarta las más antiguas)."""
    global _undo_seq
    _undo_seq += 1
    _undo_store[_undo_seq] = snapshot
    while len(_undo_store) > _UNDO_MAX:
        oldest = min(_undo_store)
        del _undo_store[oldest]
    return _undo_seq


def _pop_undo(token: int):
    """Saca (y elimina) el snapshot. None si el token ya no existe."""
    return _undo_store.pop(token, None)


# Estado de "edición de texto en curso" tras pulsar ✏️. Mapea user_id →
# {"kind": "task"|"objective", "id": int}. El siguiente mensaje de texto del
# usuario se interpreta como el nuevo título. Se pierde al reiniciar (igual
# que _history/_undo_store): la edición es inmediata.
_pending_edit: dict[int, dict] = {}


def _set_pending_edit(user_id: int, kind: str, item_id: int) -> None:
    _pending_edit[user_id] = {"kind": kind, "id": item_id}


def _peek_pending_edit(user_id: int):
    """Consulta el estado de edición sin eliminarlo. None si no hay."""
    return _pending_edit.get(user_id)


def _pop_pending_edit(user_id: int):
    """Saca (y elimina) el estado de edición. None si no hay."""
    return _pending_edit.pop(user_id, None)


def _apply_pending_edit_if_any(text: str, user_id: int) -> Optional[str]:
    """Si el usuario está en modo edición (tras pulsar ✏️), interpreta `text`
    como el nuevo título y lo aplica. Devuelve la respuesta a enviar, o None si
    no hay edición pendiente o si el texto es un comando (en cuyo caso se cancela
    el modo y se deja que el flujo normal procese el comando).

    Compartido por texto (process_incoming) y voz (process_voice_transcription)
    para que el estado no quede colgado en ninguna vía."""
    pending = _peek_pending_edit(user_id)
    if pending is None:
        return None
    stripped = text.strip()
    if stripped.lower() == "/cancelar":
        _pop_pending_edit(user_id)
        return "Edición cancelada."
    if stripped.startswith("/"):
        # Un comando: cancela el modo y deja que el flujo normal lo trate.
        _pop_pending_edit(user_id)
        return None
    if not stripped:
        return "Dame el nuevo texto, o escribe /cancelar."
    _pop_pending_edit(user_id)
    if pending["kind"] == "task":
        res = tools.update_task(pending["id"], {"text": stripped})
    else:
        res = tools.update_objective(pending["id"], {"text": stripped})
    if res.get("updated"):
        # Escapa para el parse_mode HTML del reply (el texto crudo ya se guardó).
        return f"✅ Cambiado a «{html.escape(stripped)}»."
    return "Ese item ya no existe (¿lo borraste?)."

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("bot")


# Mapa de comandos slash → frase natural que recibe el cerebro
# Comandos slash que se delegan al cerebro (Claude). Vacío: /hoy, /manana,
# /pendientes, /semana, /metricas, /nivel, /objetivos y /rachas son todos
# deterministas (handlers directos, sin Claude).
_SLASH_PROMPTS: dict[str, str] = {}

# Comandos slash que NO van al cerebro (control de bot)
_RESET_COMMANDS = ("/nueva", "/reset", "/clear")


def process_slash_command(command: str, from_user_id: int) -> Optional[str]:
    """Lógica pura: ejecuta un comando slash conocido. Devuelve None si no autorizado o desconocido."""
    if from_user_id != ALLOWED_USER_ID:
        log.warning("Slash ignorado de user_id no autorizado: %s", from_user_id)
        return None
    cmd = command.strip().lower()
    prompt = _SLASH_PROMPTS.get(cmd)
    if prompt is None:
        return None
    try:
        return markdown_to_html(brain.handle_message(prompt, user_id=from_user_id))
    except anthropic.RateLimitError:
        log.warning("Rate limit de Anthropic alcanzado en %s", cmd)
        return _RATE_LIMIT_MSG
    except Exception:
        log.exception("Error procesando comando %s", cmd)
        return (
            "Ahora mismo no puedo procesar esto. "
            "Prueba a reformularlo o vuelve a intentarlo en un momento."
        )


def process_incoming(text: str, from_user_id: int) -> Optional[str]:
    """Lógica pura: dado un mensaje de texto y user id, devuelve la respuesta (o None si no autorizado)."""
    if from_user_id != ALLOWED_USER_ID:
        log.warning("Mensaje ignorado de user_id no autorizado: %s", from_user_id)
        return None

    # Edición de texto en curso (tras pulsar ✏️): aplica el nuevo título. Si
    # devuelve None, no había edición (o era un comando) → sigue el flujo normal.
    edit_reply = _apply_pending_edit_if_any(text, from_user_id)
    if edit_reply is not None:
        return edit_reply

    cleaned = text.strip().lower()

    if cleaned in _RESET_COMMANDS:
        brain.reset_history(from_user_id)
        return "Conversación reiniciada. Empezamos de cero."

    if cleaned in _SLASH_PROMPTS:
        return process_slash_command(cleaned, from_user_id)

    try:
        return markdown_to_html(brain.handle_message(text, user_id=from_user_id))
    except anthropic.RateLimitError:
        log.warning("Rate limit de Anthropic alcanzado en mensaje libre")
        return _RATE_LIMIT_MSG
    except Exception:
        log.exception("Error procesando mensaje")
        return (
            "Ahora mismo no puedo procesar esto. "
            "Prueba a reformularlo o vuelve a intentarlo en un momento."
        )


def process_voice_transcription(transcription: str, from_user_id: int) -> Optional[str]:
    """Lógica pura: dada una transcripción y user id, devuelve la respuesta del cerebro."""
    if from_user_id != ALLOWED_USER_ID:
        log.warning("Voz ignorada de user_id no autorizado: %s", from_user_id)
        return None

    cleaned = transcription.strip()
    if not cleaned:
        return "No he entendido nada del audio. ¿Puedes repetirlo o escribirme?"

    # Edición de texto en curso (tras pulsar ✏️): un audio aplica la
    # transcripción como nuevo título, igual que un mensaje de texto.
    edit_reply = _apply_pending_edit_if_any(cleaned, from_user_id)
    if edit_reply is not None:
        return edit_reply

    try:
        return markdown_to_html(brain.handle_message(cleaned, user_id=from_user_id))
    except anthropic.RateLimitError:
        log.warning("Rate limit de Anthropic alcanzado en voz")
        return _RATE_LIMIT_MSG
    except Exception:
        log.exception("Error procesando transcripción de voz")
        return (
            "Ahora mismo no puedo procesar esto. "
            "Prueba a reformularlo o vuelve a intentarlo en un momento."
        )


def _normalize_query(text: str) -> str:
    """Minúsculas, sin tildes, sin signos en los extremos, espacios colapsados."""
    import unicodedata
    t = text.strip().lower()
    t = "".join(
        c for c in unicodedata.normalize("NFD", t)
        if unicodedata.category(c) != "Mn"
    )
    t = t.strip(" ¿?¡!.,;:")
    return " ".join(t.split())


# Verbos/locuciones que indican una ORDEN de crear o accionar, no una consulta.
_ACTION_WORDS = {
    "apunta", "apuntame", "anota", "anade", "agrega", "pon", "ponme", "mete",
    "meteme", "crea", "creame", "recuerda", "recuerdame", "avisa", "avisame",
    "marca", "completa", "hice", "termine", "acabe", "borra", "elimina", "quita",
    "cambia", "edita", "mueve", "sincroniza", "conecta",
}
# Palabras que confirman que la pregunta es sobre la AGENDA (no otra cosa).
_AGENDA_WORDS = {
    "tengo", "hay", "toca", "agenda", "dia", "plan", "planes", "eventos",
    "cita", "citas",
}
# Frases-clave temporales que, tal cual, son una consulta de cada vista.
_EXACT_HOY = {"hoy", "mi dia", "agenda de hoy", "agenda", "mi agenda", "que tengo"}
_EXACT_MANANA = {"manana", "mi manana", "agenda de manana"}
_EXACT_SEMANA = {"esta semana", "semana", "mi semana"}


def match_summary_view(text: str) -> Optional[str]:
    """Detecta si `text` es una consulta de resumen en lenguaje natural y, si lo
    es, devuelve la vista a servir ('hoy'|'manana'|'semana'|'pendientes'|
    'objetivos'). None si no lo es (irá a la IA).

    Reglas:
    - Excluye órdenes de crear/accionar (apunta/añade/marca/…).
    - Tareas/objetivos: bastan si hay pregunta, posesivo "mi(s)", o la frase
      empieza por el tipo ("objetivos de la semana").
    - Temporales (hoy/mañana/semana): exige que sea una pregunta de AGENDA
      (empieza por "qué" + palabra de agenda como tengo/hay/toca) o una
      frase-clave exacta. Así "qué compro hoy" o "ver si puedo mañana" NO entran.
    """
    n = _normalize_query(text)
    if not n:
        return None

    words = set(n.split())
    if words & _ACTION_WORDS:
        return None

    pregunta = n.startswith("que ")
    posesivo = "mi" in words or "mis" in words
    agenda = bool(words & _AGENDA_WORDS)
    short_start = ":" not in n and len(words) <= 5

    has_pend = bool(words & {"pendiente", "pendientes", "tarea", "tareas"})
    has_obj = bool(words & {"objetivo", "objetivos", "meta", "metas"})

    # Tareas / pendientes
    if has_pend and (
        pregunta or posesivo or (short_start and n.startswith(("pendientes", "tareas")))
    ):
        return "pendientes"
    # Objetivos
    if has_obj and (
        pregunta or posesivo or (short_start and n.startswith(("objetivos", "metas")))
    ):
        return "objetivos"

    # Temporales: pregunta de agenda, o frase-clave exacta.
    need = pregunta and agenda
    if "semana" in words and (need or n in _EXACT_SEMANA):
        return "semana"
    if "manana" in words and (need or n in _EXACT_MANANA):
        return "manana"
    if "hoy" in words and (need or n in _EXACT_HOY):
        return "hoy"
    # Genéricas sin marcador temporal ("mi agenda", "qué tengo").
    if n in _EXACT_HOY:
        return "hoy"
    return None


def _render_summary_view(view_key: str, conn, today):
    """Mapea una clave de vista a su render determinista de views.py. Devuelve
    (texto_html, teclado). Reutiliza las mismas vistas que los comandos /hoy etc."""
    from datetime import timedelta
    if view_key == "hoy":
        return views.render_today_view(today, conn)
    if view_key == "manana":
        return views.render_tomorrow_view(today + timedelta(days=1), conn)
    if view_key == "semana":
        return views.render_week_view(today, conn)
    if view_key == "pendientes":
        return views.render_pending_view(conn)
    if view_key == "objetivos":
        return views.render_objectives_view(today, conn)
    raise ValueError(f"vista desconocida: {view_key}")


def _calendar_button_keyboard(user_id: int):
    """Si brain dejó un event_id pendiente, devuelve un teclado con el botón.
    Si no, None.
    """
    event_id = brain.pop_pending_calendar_button(user_id)
    if event_id is None:
        return None
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("📅 Mandar a Calendar", callback_data=f"gc:{event_id}"),
    ]])


async def _on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text or not update.effective_user:
        return
    user_id = update.effective_user.id

    # Consulta de resumen en lenguaje natural ("qué tengo hoy", "mis objetivos"…):
    # servir la MISMA vista determinista del comando, con sus botones, sin IA.
    # Solo si no hay una edición de texto en curso (esa tiene prioridad).
    if user_id == ALLOWED_USER_ID and _peek_pending_edit(user_id) is None:
        view_key = match_summary_view(update.message.text)
        if view_key is not None:
            try:
                today = date_utils.today_madrid()
                with db.connect() as conn:
                    text, keyboard = _render_summary_view(view_key, conn, today)
                await update.message.reply_text(
                    text, parse_mode=ParseMode.HTML, reply_markup=keyboard
                )
                return
            except Exception:
                log.exception("Error sirviendo vista de resumen NL (%s); caigo a IA", view_key)

    reply = process_incoming(text=update.message.text, from_user_id=user_id)
    if reply is None:
        return
    keyboard = _calendar_button_keyboard(user_id)
    await update.message.reply_text(reply, parse_mode=ParseMode.HTML, reply_markup=keyboard)

    # Si Claude disparó una subida de nivel, mandar mensaje aparte
    level_change = brain.pop_level_up(user_id)
    if level_change:
        level_before, level_after = level_change
        try:
            await context.bot.send_message(
                chat_id=ALLOWED_USER_ID,
                text=_render_level_up_message(level_before, level_after),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            log.exception("Error enviando mensaje de subida de nivel post-brain")

    # Recordatorios custom inmediatos disparados por la respuesta de Claude
    for rem in brain.pop_immediate_reminders(user_id):
        try:
            await context.bot.send_message(
                chat_id=ALLOWED_USER_ID,
                text=_render_reminder_message(
                    rem["offset_minutes"], rem["title"]
                ),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            log.exception(
                "Error enviando recordatorio inmediato del evento %s",
                rem["event_id"],
            )


async def _on_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.voice:
        return

    from_user_id = update.effective_user.id
    if from_user_id != ALLOWED_USER_ID:
        log.warning("Voz ignorada de user_id no autorizado: %s", from_user_id)
        return

    try:
        tg_file = await context.bot.get_file(update.message.voice.file_id)
        audio_bytes = bytes(await tg_file.download_as_bytearray())
    except Exception:
        log.exception("Error descargando audio de Telegram")
        await update.message.reply_text(
            "No he podido descargar el audio. Inténtalo de nuevo."
        )
        return

    try:
        transcription = await asyncio.to_thread(transcriber.transcribe, audio_bytes)
    except transcriber.TranscriptionUnavailable:
        await update.message.reply_text(
            "Aún no he configurado la transcripción de voz. Mándame texto por ahora."
        )
        return
    except Exception:
        log.exception("Error en la transcripción")
        await update.message.reply_text(
            "Ahora mismo no puedo transcribir audios. "
            "Prueba a escribirme o vuelve a intentarlo en un minuto."
        )
        return

    reply = process_voice_transcription(transcription, from_user_id=from_user_id)
    if reply is None:
        return
    keyboard = _calendar_button_keyboard(from_user_id)
    await update.message.reply_text(reply, parse_mode=ParseMode.HTML, reply_markup=keyboard)

    # Si Claude disparó una subida de nivel, mandar mensaje aparte
    level_change = brain.pop_level_up(from_user_id)
    if level_change:
        level_before, level_after = level_change
        try:
            await context.bot.send_message(
                chat_id=ALLOWED_USER_ID,
                text=_render_level_up_message(level_before, level_after),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            log.exception("Error enviando mensaje de subida de nivel post-brain (voz)")

    # Recordatorios custom inmediatos disparados por la respuesta de Claude
    for rem in brain.pop_immediate_reminders(from_user_id):
        try:
            await context.bot.send_message(
                chat_id=ALLOWED_USER_ID,
                text=_render_reminder_message(
                    rem["offset_minutes"], rem["title"]
                ),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            log.exception(
                "Error enviando recordatorio inmediato del evento %s",
                rem["event_id"],
            )


_WELCOME_TEXT = (
    "👋 ¡Hola {name}! Soy tu secretaria personal. Te ayudo a organizar "
    "<b>eventos</b>, <b>tareas</b>, <b>objetivos de la semana</b> y <b>rutinas</b>.\n\n"
    "Háblame con naturalidad, por ejemplo:\n"
    "• «mañana a las 5 tengo dentista, avísame 30 min antes»\n"
    "• «apúntame comprar pan para hoy»\n"
    "• «ya hice la reunión»\n"
    "• «¿qué tengo hoy?»\n\n"
    "También puedes mandarme un <b>audio</b> y lo entiendo.\n\n"
    "Comandos rápidos:\n"
    "📅 /hoy · /manana · /semana\n"
    "📝 /pendientes · 🎯 /objetivos\n"
    "🔥 /rachas · 🏆 /nivel · 📊 /metricas\n"
    "🔍 /duplicados · 🔄 /nueva (reinicia la conversación)\n\n"
    "Escribe /ayuda para volver a ver esto cuando quieras."
)


async def _on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Error handler global: loguea cualquier excepción no capturada en handlers
    para tener visibilidad (antes quedaban en el logger de asyncio sin contexto)."""
    log.exception("Excepción no capturada en un handler", exc_info=context.error)


async def _cancel_edit_on_command(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler de grupo -1: si llega un comando REGISTRADO (/hoy, /pendientes…)
    estando en modo edición (✏️), cancela el modo. No consume el update — el
    CommandHandler de grupo 0 lo procesa después.

    Excepción: /cancelar NO se toca aquí; llega a process_incoming, que da el
    mensaje 'Edición cancelada'. Si lo limpiáramos aquí, process_incoming vería
    el estado ya vacío y mandaría '/cancelar' a la IA."""
    msg = getattr(update, "message", None)
    text = (getattr(msg, "text", "") or "") if msg else ""
    if text.strip().lower() == "/cancelar":
        return
    user = getattr(update, "effective_user", None)
    if user is not None:
        _pop_pending_edit(user.id)


async def _on_start(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    """/start y /ayuda: mensaje de bienvenida con qué puede hacer el bot."""
    if not update.message or not update.effective_user:
        return
    if update.effective_user.id != ALLOWED_USER_ID:
        log.warning("/start ignorado de user_id no autorizado: %s", update.effective_user.id)
        return
    await update.message.reply_text(
        _WELCOME_TEXT.format(name=USER_NAME),
        parse_mode=ParseMode.HTML,
    )


async def _on_hoy(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    """/hoy: vista generada por views.render_today_view (sin Claude)."""
    if not update.message or not update.effective_user:
        return
    if update.effective_user.id != ALLOWED_USER_ID:
        log.warning("/hoy ignorado de user_id no autorizado: %s", update.effective_user.id)
        return

    today = date_utils.today_madrid()
    with db.connect() as conn:
        text, keyboard = views.render_today_view(today, conn)

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


async def _on_manana(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    """/manana: vista de lo que toca mañana (solo lectura)."""
    if not update.message or not update.effective_user:
        return
    if update.effective_user.id != ALLOWED_USER_ID:
        log.warning("/manana ignorado de user_id no autorizado: %s", update.effective_user.id)
        return

    from datetime import timedelta
    tomorrow = date_utils.today_madrid() + timedelta(days=1)
    with db.connect() as conn:
        text, keyboard = views.render_tomorrow_view(tomorrow, conn)

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


async def _on_pendientes(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    """/pendientes: lista de tareas pendientes con botón por tarea."""
    if not update.message or not update.effective_user:
        return
    if update.effective_user.id != ALLOWED_USER_ID:
        log.warning("/pendientes ignorado de user_id no autorizado: %s", update.effective_user.id)
        return

    with db.connect() as conn:
        text, keyboard = views.render_pending_view(conn)

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


async def _on_objetivos(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    """/objetivos: objetivos de la semana con botón por ítem (sin Claude)."""
    if not update.message or not update.effective_user:
        return
    if update.effective_user.id != ALLOWED_USER_ID:
        log.warning("/objetivos ignorado de user_id no autorizado: %s", update.effective_user.id)
        return

    today = date_utils.today_madrid()
    with db.connect() as conn:
        text, keyboard = views.render_objectives_view(today, conn)

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


async def _on_duplicados(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    """/duplicados: posibles tareas/eventos repetidos con botón para borrar."""
    if not update.message or not update.effective_user:
        return
    if update.effective_user.id != ALLOWED_USER_ID:
        log.warning("/duplicados ignorado de user_id no autorizado: %s", update.effective_user.id)
        return

    with db.connect() as conn:
        text, keyboard = views.render_duplicados_view(conn)

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


async def _on_rachas(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    """/rachas: estado de rachas de rutinas (sin Claude)."""
    if not update.message or not update.effective_user:
        return
    if update.effective_user.id != ALLOWED_USER_ID:
        log.warning("/rachas ignorado de user_id no autorizado: %s", update.effective_user.id)
        return

    today = date_utils.today_madrid()
    with db.connect() as conn:
        text, keyboard = views.render_rachas_view(today, conn)

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


async def _on_semana(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    """/semana: resumen de la semana con botones solo en objetivos."""
    if not update.message or not update.effective_user:
        return
    if update.effective_user.id != ALLOWED_USER_ID:
        log.warning("/semana ignorado de user_id no autorizado: %s", update.effective_user.id)
        return

    today = date_utils.today_madrid()
    with db.connect() as conn:
        text, keyboard = views.render_week_view(today, conn)

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


async def _on_metricas(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    """/metricas: panel de últimos 30 días, vista determinística."""
    if not update.message or not update.effective_user:
        return
    if update.effective_user.id != ALLOWED_USER_ID:
        log.warning("/metricas ignorado de user_id no autorizado: %s", update.effective_user.id)
        return

    today = date_utils.today_madrid()
    with db.connect() as conn:
        text, keyboard = views.render_metrics_view(today, conn)

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


async def _on_nivel(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    """/nivel: panel del sistema XP."""
    if not update.message or not update.effective_user:
        return
    if update.effective_user.id != ALLOWED_USER_ID:
        log.warning("/nivel ignorado de user_id no autorizado: %s", update.effective_user.id)
        return

    today = date_utils.today_madrid()
    with db.connect() as conn:
        text, keyboard = views.render_nivel_view(today, conn)

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


def _render_level_up_message(level_before: int, level_after: int) -> str:
    """Devuelve el texto HTML del mensaje de subida de nivel.

    Incluye transición de medalla si hay cambio de tramo.
    """
    medal_before = tools.medal_for_level(level_before)
    medal_after = tools.medal_for_level(level_after)
    if medal_before != medal_after and medal_after:
        transition = f" {medal_before or '⬜'} → {medal_after}"
    else:
        transition = f" {medal_after}" if medal_after else ""
    return (
        f"🎉 ¡Nivel {level_after} desbloqueado!{transition}\n"
        f"¡Sigue así!"
    )


def _render_reminder_message(offset_minutes: int, title: str) -> str:
    """Texto HTML del recordatorio inmediato (mismo formato que el scheduler)."""
    from scheduler import _format_offset
    pretty = _format_offset(offset_minutes)
    return f"⏰ En {pretty} tienes: <b>{title}</b>"


_CALLBACK_ACTIONS = {
    "mE": lambda i: tools.mark_event_done(i),
    "uE": lambda i: tools.unmark_event_done(i),
    "mR": lambda i: tools.mark_event_done(i),
    "uR": lambda i: tools.uncomplete_routine_today(i),
    "mT": lambda i: tools.complete_task(i),
    "uT": lambda i: tools.uncomplete_task(i),
    "mO": lambda i: tools.mark_objective_done(i),
    "uO": lambda i: tools.unmark_objective_done(i),
    "xT": lambda i: tools.delete_task(i),
    "xE": lambda i: tools.delete_event(i),
    "tg": lambda i: None,  # toggle de visibilidad: no muta, solo re-renderiza
    "gc": lambda i: tools.push_event_to_calendar(i),
    "rE": lambda i: tools.recreate_event(i),
    "rT": lambda i: tools.recreate_task(i),
    "rO": lambda i: tools.recreate_objective(i),
    "dE": lambda i: tools.discard_event(i),
    "dT": lambda i: tools.discard_task(i),
    "dO": lambda i: tools.discard_objective(i),
}

_PROACTIVE_CONFIRM_TEXTS = {
    "rE": "✅ Pasado a hoy.",
    "rT": "✅ Pasada a hoy.",
    "rO": "✅ Pasado a esta semana.",
    "dE": "🗑️ Descartado.",
    "dT": "🗑️ Descartada.",
    "dO": "🗑️ Descartado.",
}


async def _on_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Procesa taps en botones inline de /hoy y saludo matutino."""
    query = update.callback_query
    if query is None:
        return
    if query.from_user.id != ALLOWED_USER_ID:
        log.warning("Callback ignorado de user_id no autorizado: %s", query.from_user.id)
        await query.answer("No autorizado")
        return

    data = query.data or ""
    if len(data) < 4 or ":" not in data:
        log.warning("callback_data malformado: %r", data)
        await query.answer("Acción no reconocida")
        return

    action_type = data[:2]
    parts = data[3:].split(":", 1)
    try:
        item_id = int(parts[0])
    except ValueError:
        log.warning("callback_data sin id válido: %r", data)
        await query.answer("Acción no reconocida")
        return

    view_letter = parts[1] if len(parts) > 1 else "H"

    # Deshacer borrado de /duplicados: restaura el item desde el store en memoria.
    if action_type == "zD":
        snapshot = _pop_undo(item_id)
        if snapshot is None:
            await query.answer("Ya no se puede deshacer")
            try:
                await query.edit_message_text(
                    "↩️ El deshacer ya ha caducado.", reply_markup=None
                )
            except BadRequest:
                pass
            return
        try:
            tools.restore_from_snapshot(snapshot)
            label = snapshot["data"].get("text") or snapshot["data"].get("title") or ""
            await query.edit_message_text(
                f"↩️ Restaurado: <b>{html.escape(label)}</b>",
                parse_mode=ParseMode.HTML,
                reply_markup=None,
            )
        except Exception:
            log.exception("Error restaurando snapshot de undo")
            await query.answer("No pude restaurar")
            return
        await query.answer("Restaurado")
        return

    # Botón ✏️: entra en modo edición de texto para esa tarea/objetivo.
    if action_type in ("eT", "eO"):
        kind = "task" if action_type == "eT" else "objective"
        table = "tasks" if kind == "task" else "objectives"
        with db.connect() as conn:
            row = conn.execute(
                f"SELECT text FROM {table} WHERE id = ?", (item_id,)
            ).fetchone()
        if row is None:
            await query.answer("Ese item ya no existe")
            return
        _set_pending_edit(query.from_user.id, kind, item_id)
        try:
            await context.bot.send_message(
                chat_id=ALLOWED_USER_ID,
                text=(
                    f"✏️ Escríbeme el nuevo texto para "
                    f"«{html.escape(row['text'])}» (o /cancelar)."
                ),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            log.exception("Error pidiendo nuevo texto de edición")
        await query.answer("Escríbeme el nuevo texto")
        return

    # Captura el snapshot ANTES de borrar, solo para borrados desde /duplicados,
    # para poder ofrecer el botón Deshacer.
    undo_snapshot = None
    if action_type in ("xT", "xE") and view_letter == "D":
        kind = "task" if action_type == "xT" else "event"
        undo_snapshot = tools.snapshot_for_undo(kind, item_id)

    handler = _CALLBACK_ACTIONS.get(action_type)
    if handler is None:
        log.warning("Acción de callback desconocida: %r", action_type)
        await query.answer("Acción no reconocida")
        return

    try:
        result = handler(item_id)
    except Exception:
        log.exception("Error aplicando mutación de callback %s", data)
        result = None

    if isinstance(result, dict):
        level_before = result.get("level_before")
        level_after = result.get("level_after")
        if (
            level_before is not None
            and level_after is not None
            and level_after > level_before
        ):
            try:
                await context.bot.send_message(
                    chat_id=ALLOWED_USER_ID,
                    text=_render_level_up_message(level_before, level_after),
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                log.exception("Error enviando mensaje de subida de nivel")

    if action_type == "gc":
        try:
            # Quitamos el teclado y mantenemos el texto original con un sufijo.
            original = query.message.text_html if query.message else ""
            await query.edit_message_text(
                f"{original}\n\n✅ Enviado a Calendar",
                parse_mode=ParseMode.HTML,
                reply_markup=None,
            )
        except BadRequest:
            log.warning("No pude editar el mensaje del botón Calendar")
        await query.answer("Enviado a Calendar")
        return

    if action_type in _PROACTIVE_CONFIRM_TEXTS:
        try:
            original = query.message.text_html if query.message else ""
        except AttributeError:
            original = ""
        confirm = _PROACTIVE_CONFIRM_TEXTS[action_type]
        item_type_map = {"r": "recreate", "d": "discard"}
        item_kind_map = {"E": "event", "T": "task", "O": "objective"}
        action = item_type_map[action_type[0]]
        item_kind = item_kind_map[action_type[1]]
        try:
            with db.connect() as conn:
                conn.execute(
                    "UPDATE missed_notifications "
                    "SET decision = ?, decided_at = ? "
                    "WHERE item_type = ? AND item_id = ?",
                    (action, date_utils.now_iso(), item_kind, item_id),
                )
        except Exception:
            log.exception("No pude actualizar missed_notifications para %s", data)
        try:
            await query.edit_message_text(
                f"{original}\n\n{confirm}",
                parse_mode=ParseMode.HTML,
                reply_markup=None,
            )
        except BadRequest:
            log.warning("No pude editar mensaje proactivo %s", data)
        await query.answer(confirm)
        return

    today = date_utils.today_madrid()
    with db.connect() as conn:
        if view_letter == "P":
            text, keyboard = views.render_pending_view(conn)
        elif view_letter == "Wc":
            text, keyboard = views.render_week_view(today, conn, show_completed=True)
        elif view_letter == "W":
            text, keyboard = views.render_week_view(today, conn, show_completed=False)
        elif view_letter == "O":
            text, keyboard = views.render_objectives_view(today, conn)
        elif view_letter == "D":
            text, keyboard = views.render_duplicados_view(conn)
        elif view_letter == "Hc":
            text, keyboard = views.render_today_view(today, conn, show_completed=True)
        else:
            text, keyboard = views.render_today_view(today, conn, show_completed=False)

    try:
        await query.edit_message_text(
            text, parse_mode=ParseMode.HTML, reply_markup=keyboard,
        )
    except BadRequest:
        log.warning("Mensaje no editable (probablemente >48h), enviando nuevo")
        await context.bot.send_message(
            chat_id=ALLOWED_USER_ID,
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )

    # Si se borró un item desde /duplicados, ofrece deshacer en un mensaje aparte
    # (la lista de duplicados ya se ha repintado arriba).
    if undo_snapshot is not None:
        token = _push_undo(undo_snapshot)
        label = undo_snapshot["data"].get("text") or undo_snapshot["data"].get("title") or ""
        undo_kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("↩️ Deshacer", callback_data=f"zD:{token}"),
        ]])
        try:
            await context.bot.send_message(
                chat_id=ALLOWED_USER_ID,
                text=f"🗑️ Borrado: <s>{html.escape(label)}</s>",
                parse_mode=ParseMode.HTML,
                reply_markup=undo_kb,
            )
        except Exception:
            log.exception("Error enviando mensaje de deshacer")

    await query.answer()


async def _set_bot_commands(application: Application) -> None:
    """Registra el menú de comandos visible al escribir '/' en Telegram.

    Se llama DESPUÉS de que la app esté arrancada (no en post_init) porque
    ahí teníamos un fallo silencioso intermitente. Loguea éxito o fallo.
    """
    commands = [
        BotCommand("hoy", "Resumen de hoy"),
        BotCommand("manana", "Resumen de mañana"),
        BotCommand("semana", "Resumen de la semana"),
        BotCommand("pendientes", "Tareas pendientes"),
        BotCommand("objetivos", "Objetivos de la semana"),
        BotCommand("rachas", "Mis rachas"),
        BotCommand("duplicados", "Revisar duplicados"),
        BotCommand("metricas", "Métricas de cumplimiento"),
        BotCommand("nivel", "Tu nivel y XP"),
        BotCommand("ayuda", "Qué puedo hacer"),
        BotCommand("nueva", "Reiniciar conversación"),
    ]
    try:
        await application.bot.set_my_commands(commands)
        log.info(
            "Menú de comandos actualizado en Telegram (%d comandos)",
            len(commands),
        )
    except Exception:
        log.exception("Error registrando el menú de comandos en Telegram")


async def _async_main() -> None:
    from datetime import time as dtime

    import pytz
    from aiohttp import web

    import scheduler
    import siri_server
    from config import SIRI_TOKEN

    db.init_schema()
    log.info("Base de datos lista en %s", db.DB_PATH)

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", _on_start))
    app.add_handler(CommandHandler("ayuda", _on_start))
    app.add_handler(CommandHandler("hoy", _on_hoy))
    app.add_handler(CommandHandler("manana", _on_manana))
    app.add_handler(CommandHandler("pendientes", _on_pendientes))
    app.add_handler(CommandHandler("semana", _on_semana))
    app.add_handler(CommandHandler("metricas", _on_metricas))
    app.add_handler(CommandHandler("nivel", _on_nivel))
    app.add_handler(CommandHandler("objetivos", _on_objetivos))
    app.add_handler(CommandHandler("rachas", _on_rachas))
    app.add_handler(CommandHandler("duplicados", _on_duplicados))

    # Grupo -1: cancela el modo edición (✏️) ante cualquier comando, sin
    # consumir el update (los CommandHandler de grupo 0 lo procesan igual).
    app.add_handler(MessageHandler(filters.COMMAND, _cancel_edit_on_command), group=-1)

    app.add_handler(MessageHandler(filters.TEXT, _on_message))
    app.add_handler(MessageHandler(filters.VOICE, _on_voice))
    app.add_handler(CallbackQueryHandler(_on_callback_query))
    app.add_error_handler(_on_error)

    madrid = pytz.timezone("Europe/Madrid")
    app.job_queue.run_daily(
        scheduler.morning_summary,
        time=dtime(hour=9, minute=0, tzinfo=madrid),
        name="morning_summary",
    )
    app.job_queue.run_repeating(
        scheduler.check_reminders,
        interval=300,
        first=30,
        name="check_reminders",
    )
    app.job_queue.run_daily(
        scheduler.weekly_objectives_reminder,
        time=dtime(hour=13, minute=0, tzinfo=madrid),
        days=(0,),
        name="weekly_objectives_reminder",
    )
    app.job_queue.run_daily(
        scheduler.detect_missed_items,
        time=dtime(hour=0, minute=5, tzinfo=madrid),
        name="detect_missed_items",
    )

    await app.initialize()
    await app.start()
    await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)

    # Registrar el menú DESPUÉS de que el bot esté arrancado.
    await _set_bot_commands(app)

    siri_app = siri_server.build_app(
        telegram_bot=app.bot,
        brain_fn=brain.handle_message,
        siri_token=SIRI_TOKEN,
        allowed_user_id=ALLOWED_USER_ID,
    )
    import gcal_sync
    gcal_sync.register_oauth_routes(
        siri_app,
        telegram_bot=app.bot,
        allowed_user_id=ALLOWED_USER_ID,
    )
    runner = web.AppRunner(siri_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8080)
    await site.start()

    log.info("Bot arrancando (polling + HTTP en :8080)…")

    try:
        await asyncio.Event().wait()
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
        await runner.cleanup()


def main() -> None:
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()

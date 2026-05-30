"""Listener de Telegram. Filtra por usuario autorizado y delega en el cerebro."""
import asyncio
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

import brain
import date_utils
import db
import tools
import transcriber
import views
from config import ALLOWED_USER_ID, TELEGRAM_TOKEN
from formatting import markdown_to_html

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("bot")


# Mapa de comandos slash → frase natural que recibe el cerebro
_SLASH_PROMPTS = {
    "/objetivos": (
        "Muéstrame el estado de mis objetivos de esta semana. "
        "Llama a query_objectives(week_start=lunes de esta semana). "
        "Lista cada uno con ✅ si está done=1 o 🔲 si no. "
        "Una frase de cierre con ánimo. Sin preámbulos."
    ),
    "/rachas": (
        "Muestra el estado de las rachas de mis rutinas. SIGUE ESTOS PASOS:\n"
        "1. Llama a routine_summary(date_from=hoy en YYYY-MM-DD, date_to=hoy en YYYY-MM-DD). Los streaks son globales, el rango no importa.\n"
        "2. Empieza la respuesta con un título de sección en negrita: 🔥 <b>RACHAS</b>\n"
        "3. Para cada rutina del paso 1, una línea con formato:\n"
        "   • {title} — actual: {current_streak} · mejor: {best_streak}\n"
        "   Si current_streak == best_streak Y best_streak > 0, añade ' 🏆' al final.\n"
        "4. Cierre motivador opcional de UNA frase si encaja.\n"
        "5. Si no hay ninguna rutina (lista vacía del paso 1), responde solo: «Aún no tienes rutinas registradas.»\n"
        "NADA de preámbulos ni preguntas."
    ),
}

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

    cleaned = text.strip().lower()

    if cleaned in _RESET_COMMANDS:
        brain.reset_history(from_user_id)
        return "Conversación reiniciada. Empezamos de cero."

    if cleaned in _SLASH_PROMPTS:
        return process_slash_command(cleaned, from_user_id)

    try:
        return markdown_to_html(brain.handle_message(text, user_id=from_user_id))
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

    try:
        return markdown_to_html(brain.handle_message(cleaned, user_id=from_user_id))
    except Exception:
        log.exception("Error procesando transcripción de voz")
        return (
            "Ahora mismo no puedo procesar esto. "
            "Prueba a reformularlo o vuelve a intentarlo en un momento."
        )


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


async def _on_message(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return
    user_id = update.effective_user.id
    reply = process_incoming(text=update.message.text, from_user_id=user_id)
    if reply is None:
        return
    keyboard = _calendar_button_keyboard(user_id)
    await update.message.reply_text(reply, parse_mode=ParseMode.HTML, reply_markup=keyboard)


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


_CALLBACK_ACTIONS = {
    "mE": lambda i: tools.mark_event_done(i),
    "uE": lambda i: tools.unmark_event_done(i),
    "mR": lambda i: tools.mark_event_done(i),
    "uR": lambda i: tools.uncomplete_routine_today(i),
    "mT": lambda i: tools.complete_task(i),
    "uT": lambda i: tools.uncomplete_task(i),
    "mO": lambda i: tools.mark_objective_done(i),
    "uO": lambda i: tools.unmark_objective_done(i),
    "tg": lambda i: None,  # toggle de visibilidad: no muta, solo re-renderiza
    "gc": lambda i: tools.push_event_to_calendar(i),
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

    handler = _CALLBACK_ACTIONS.get(action_type)
    if handler is None:
        log.warning("Acción de callback desconocida: %r", action_type)
        await query.answer("Acción no reconocida")
        return

    try:
        handler(item_id)
    except Exception:
        log.exception("Error aplicando mutación de callback %s", data)

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

    today = date_utils.today_madrid()
    with db.connect() as conn:
        if view_letter == "P":
            text, keyboard = views.render_pending_view(conn)
        elif view_letter == "W":
            text, keyboard = views.render_week_view(today, conn)
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

    await query.answer()


def _make_slash_handler(command: str):
    """Factory: crea un handler async para un comando slash conocido."""
    async def handler(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message or not update.effective_user:
            return
        reply = process_slash_command(command, from_user_id=update.effective_user.id)
        if reply is not None:
            await update.message.reply_text(reply, parse_mode=ParseMode.HTML)
    return handler


async def _set_bot_commands(application: Application) -> None:
    """Registra el menú de comandos visible al escribir '/' en Telegram."""
    await application.bot.set_my_commands([
        BotCommand("hoy", "Resumen de hoy"),
        BotCommand("manana", "Resumen de mañana"),
        BotCommand("semana", "Resumen de la semana"),
        BotCommand("pendientes", "Tareas pendientes"),
        BotCommand("objetivos", "Objetivos de la semana"),
        BotCommand("rachas", "Mis rachas"),
        BotCommand("metricas", "Métricas de cumplimiento"),
        BotCommand("nueva", "Reiniciar conversación"),
    ])


async def _async_main() -> None:
    from datetime import time as dtime

    import pytz
    from aiohttp import web

    import scheduler
    import siri_server
    from config import SIRI_TOKEN

    db.init_schema()
    log.info("Base de datos lista en %s", db.DB_PATH)

    app = Application.builder().token(TELEGRAM_TOKEN).post_init(_set_bot_commands).build()

    app.add_handler(CommandHandler("hoy", _on_hoy))
    app.add_handler(CommandHandler("manana", _on_manana))
    app.add_handler(CommandHandler("pendientes", _on_pendientes))
    app.add_handler(CommandHandler("semana", _on_semana))
    app.add_handler(CommandHandler("metricas", _on_metricas))
    for cmd in ("objetivos", "rachas"):
        app.add_handler(CommandHandler(cmd, _make_slash_handler(f"/{cmd}")))

    app.add_handler(MessageHandler(filters.TEXT, _on_message))
    app.add_handler(MessageHandler(filters.VOICE, _on_voice))
    app.add_handler(CallbackQueryHandler(_on_callback_query))

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

    await app.initialize()
    await app.start()
    await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)

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

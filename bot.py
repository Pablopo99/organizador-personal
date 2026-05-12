"""Listener de Telegram. Filtra por usuario autorizado y delega en el cerebro."""
import asyncio
import logging
import re
from typing import Optional

from telegram import BotCommand, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import brain
import db
import transcriber
from config import ALLOWED_USER_ID, TELEGRAM_TOKEN

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("bot")


_BOLD_MD_RE = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)


def _markdown_to_html(text: str) -> str:
    """Convierte Markdown bold (**texto**) a HTML (<b>texto</b>).

    Defensa por si Claude se le escapa el formato Markdown a pesar del system prompt.
    """
    return _BOLD_MD_RE.sub(r"<b>\1</b>", text)


# Mapa de comandos slash → frase natural que recibe el cerebro
_SLASH_PROMPTS = {
    "/hoy": (
        "Hazme el resumen de hoy con TRES secciones (no más, no menos): "
        "📅 HOY (eventos del día con done=0), "
        "📝 PENDIENTES (tareas pendientes con list_tasks), "
        "y ✅ COMPLETADO HOY (eventos de hoy con done=1 que obtengas con query_events include_done=true filtrando los hechos, MÁS tareas con done_at de hoy obtenidas con list_tasks include_done=true). "
        "Si alguna sección está vacía, omítela. Termina con un cierre breve motivador, especialmente si he completado cosas."
    ),
    "/semana": (
        "Hazme el resumen de esta semana con TRES secciones: "
        "📅 ESTA SEMANA (eventos pendientes próximos), "
        "🎯 OBJETIVOS (objetivos de la semana — marca cuáles están hechos), "
        "y ✅ COMPLETADO (eventos de la semana con done=1 + tareas completadas esta semana). "
        "Si alguna sección está vacía, omítela. Cierra con un comentario motivador."
    ),
    "/pendientes": "Lista mis tareas pendientes con formato HTML, una por bullet.",
    "/objetivos": "¿Cómo van mis objetivos de esta semana? Muéstrame cuáles he cumplido y cuáles me quedan, con motivación.",
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
        return _markdown_to_html(brain.handle_message(prompt, user_id=from_user_id))
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
        return _markdown_to_html(brain.handle_message(text, user_id=from_user_id))
    except Exception:
        log.exception("Error procesando mensaje")
        return (
            "Ahora mismo no puedo procesar esto. "
            "Prueba a reformularlo o vuelve a intentarlo en un momento."
        )


def process_voice_transcription(transcription: str, from_user_id: int) -> Optional[str]:
    """Lógica pura: dada una transcripción y user id, devuelve la respuesta completa con prefijo."""
    if from_user_id != ALLOWED_USER_ID:
        log.warning("Voz ignorada de user_id no autorizado: %s", from_user_id)
        return None

    cleaned = transcription.strip()
    if not cleaned:
        return "No he entendido nada del audio. ¿Puedes repetirlo o escribirme?"

    try:
        brain_reply = _markdown_to_html(brain.handle_message(cleaned, user_id=from_user_id))
    except Exception:
        log.exception("Error procesando transcripción de voz")
        return (
            "Ahora mismo no puedo procesar esto. "
            "Prueba a reformularlo o vuelve a intentarlo en un momento."
        )

    return f"📝 He entendido: «{cleaned}»\n\n{brain_reply}"


async def _on_message(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return
    reply = process_incoming(
        text=update.message.text,
        from_user_id=update.effective_user.id,
    )
    if reply is not None:
        await update.message.reply_text(reply, parse_mode=ParseMode.HTML)


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
    if reply is not None:
        await update.message.reply_text(reply, parse_mode=ParseMode.HTML)


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
        BotCommand("semana", "Resumen de la semana"),
        BotCommand("pendientes", "Tareas pendientes"),
        BotCommand("objetivos", "Objetivos de la semana"),
        BotCommand("nueva", "Reiniciar conversación"),
    ])


def main() -> None:
    db.init_schema()
    log.info("Base de datos lista en %s", db.DB_PATH)

    app = Application.builder().token(TELEGRAM_TOKEN).post_init(_set_bot_commands).build()

    # Slash commands
    for cmd in ("hoy", "semana", "pendientes", "objetivos"):
        app.add_handler(CommandHandler(cmd, _make_slash_handler(f"/{cmd}")))

    # Mensajes de texto (incluye /nueva, /reset, /clear que no están registrados como CommandHandler)
    app.add_handler(MessageHandler(filters.TEXT, _on_message))
    app.add_handler(MessageHandler(filters.VOICE, _on_voice))

    log.info("Bot arrancando (polling)…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

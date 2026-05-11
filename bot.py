"""Listener de Telegram. Filtra por usuario autorizado y delega en el cerebro."""
import logging
from typing import Optional

from telegram import Update
from telegram.ext import (
    Application,
    ContextTypes,
    MessageHandler,
    filters,
)

import brain
import db
from config import ALLOWED_USER_ID, TELEGRAM_TOKEN

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("bot")


def process_incoming(text: str, from_user_id: int) -> Optional[str]:
    """Lógica pura: dado un mensaje y user id, devuelve la respuesta (o None si no autorizado)."""
    if from_user_id != ALLOWED_USER_ID:
        log.warning("Mensaje ignorado de user_id no autorizado: %s", from_user_id)
        return None
    try:
        return brain.handle_message(text)
    except Exception:
        log.exception("Error procesando mensaje")
        return (
            "Ahora mismo no puedo procesar esto. "
            "Prueba a reformularlo o vuelve a intentarlo en un momento."
        )


async def _on_message(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return
    reply = process_incoming(
        text=update.message.text,
        from_user_id=update.effective_user.id,
    )
    if reply is not None:
        await update.message.reply_text(reply)


def main() -> None:
    db.init_schema()
    log.info("Base de datos lista en %s", db.DB_PATH)

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _on_message))

    log.info("Bot arrancando (polling)…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

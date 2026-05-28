"""Servidor aiohttp con endpoint /ingest para que Siri pueda hablar al bot."""
import logging
import re
from typing import Callable

from aiohttp import web

log = logging.getLogger("siri_server")

_TAG_RE = re.compile(r"<[^>]+>")

_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FFFF"   # símbolos y pictogramas, emoticonos, transporte, etc.
    "\U00002600-\U000027BF"   # misc symbols + dingbats (✅, ⏰, ☀, etc.)
    "\U00002580-\U000025FF"   # geometric shapes (▼, ▲, 🔲 partial)
    "\U0001F1E6-\U0001F1FF"   # banderas
    "]"
    "[\U0000FE00-\U0000FE0F]?",  # selectores de variación opcionales
    flags=re.UNICODE,
)


def html_to_plain(text: str) -> str:
    """Quita tags HTML simples y desescapa entidades básicas. Para que Siri pueda leer la respuesta."""
    plain = _TAG_RE.sub("", text)
    plain = plain.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    return plain


def strip_emojis(text: str) -> str:
    """Elimina emojis del texto. Siri los lee como descripciones (ej. 'carita sonriente') que distraen."""
    return _EMOJI_RE.sub("", text)


def build_app(
    *,
    telegram_bot,
    brain_fn: Callable[..., str],
    siri_token: str,
    allowed_user_id: int,
) -> web.Application:
    """Crea la aiohttp Application con el endpoint /ingest."""
    async def _on_ingest(request: web.Request) -> web.Response:
        auth = request.headers.get("Authorization", "")
        if auth != f"Bearer {siri_token}":
            return web.json_response({"reply": "No autorizado"}, status=401)

        try:
            body = await request.json()
        except Exception:
            return web.json_response({"reply": "Petición inválida"}, status=400)

        text = body.get("text") if isinstance(body, dict) else None
        if not text or not isinstance(text, str) or not text.strip():
            return web.json_response({"reply": "Falta el texto"}, status=400)

        try:
            html_reply = brain_fn(text, user_id=allowed_user_id)
        except Exception:
            log.exception("Error procesando ingest")
            return web.json_response(
                {"reply": "Algo ha fallado, vuelve a intentarlo en un momento."},
                status=500,
            )

        try:
            await telegram_bot.send_message(
                chat_id=allowed_user_id,
                text=html_reply,
                parse_mode="HTML",
            )
        except Exception:
            log.exception("Error mandando eco a Telegram (Siri ya recibió respuesta)")

        siri_text = strip_emojis(html_to_plain(html_reply))
        return web.json_response({"reply": siri_text}, status=200)

    app = web.Application()
    app.router.add_post("/ingest", _on_ingest)
    return app

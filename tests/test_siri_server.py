import siri_server


def test_html_to_plain_strips_bold_tags():
    assert siri_server.html_to_plain("Hola <b>mundo</b>") == "Hola mundo"


def test_html_to_plain_strips_italic_strike_spoiler():
    assert siri_server.html_to_plain("<i>uno</i> <s>dos</s> <tg-spoiler>tres</tg-spoiler>") == "uno dos tres"


def test_html_to_plain_handles_html_entities():
    assert siri_server.html_to_plain("a &lt; b &amp; c &gt; d") == "a < b & c > d"


def test_html_to_plain_leaves_plain_text_alone():
    assert siri_server.html_to_plain("texto sin formato") == "texto sin formato"


from unittest.mock import AsyncMock, MagicMock

import pytest


VALID_TOKEN = "test-token-secret"


def _build_test_app(brain_reply="Listo, hecho", brain_side_effect=None, send_side_effect=None):
    """Crea una app de test con brain y telegram_bot mockeados."""
    if brain_side_effect is not None:
        brain_fn = MagicMock(side_effect=brain_side_effect)
    else:
        brain_fn = MagicMock(return_value=brain_reply)

    telegram_bot = MagicMock()
    telegram_bot.send_message = AsyncMock(side_effect=send_side_effect)

    app = siri_server.build_app(
        telegram_bot=telegram_bot,
        brain_fn=brain_fn,
        siri_token=VALID_TOKEN,
        allowed_user_id=42,
    )
    app["brain_fn"] = brain_fn
    app["telegram_bot"] = telegram_bot
    return app


@pytest.mark.asyncio
async def test_ingest_happy_path_returns_reply_and_calls_brain_and_telegram(aiohttp_client):
    app = _build_test_app(brain_reply="Listo, <b>Dentista</b> apuntado")
    client = await aiohttp_client(app)

    resp = await client.post(
        "/ingest",
        json={"text": "apunta dentista mañana 10"},
        headers={"Authorization": f"Bearer {VALID_TOKEN}"},
    )

    assert resp.status == 200
    body = await resp.json()
    assert body["reply"] == "Listo, Dentista apuntado"

    app["brain_fn"].assert_called_once_with("apunta dentista mañana 10", user_id=42)

    app["telegram_bot"].send_message.assert_awaited_once()
    call = app["telegram_bot"].send_message.await_args
    assert call.kwargs["chat_id"] == 42
    assert call.kwargs["text"] == "Listo, <b>Dentista</b> apuntado"
    assert call.kwargs["parse_mode"] == "HTML"

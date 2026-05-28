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


@pytest.mark.asyncio
async def test_ingest_missing_auth_returns_401(aiohttp_client):
    app = _build_test_app()
    client = await aiohttp_client(app)

    resp = await client.post("/ingest", json={"text": "hola"})

    assert resp.status == 401
    body = await resp.json()
    assert body["reply"] == "No autorizado"
    app["brain_fn"].assert_not_called()


@pytest.mark.asyncio
async def test_ingest_wrong_token_returns_401(aiohttp_client):
    app = _build_test_app()
    client = await aiohttp_client(app)

    resp = await client.post(
        "/ingest",
        json={"text": "hola"},
        headers={"Authorization": "Bearer wrong"},
    )

    assert resp.status == 401
    app["brain_fn"].assert_not_called()


@pytest.mark.asyncio
async def test_ingest_malformed_json_returns_400(aiohttp_client):
    app = _build_test_app()
    client = await aiohttp_client(app)

    resp = await client.post(
        "/ingest",
        data="not json",
        headers={
            "Authorization": f"Bearer {VALID_TOKEN}",
            "Content-Type": "application/json",
        },
    )

    assert resp.status == 400
    body = await resp.json()
    assert "inválida" in body["reply"].lower() or "falta" in body["reply"].lower()


@pytest.mark.asyncio
async def test_ingest_missing_text_field_returns_400(aiohttp_client):
    app = _build_test_app()
    client = await aiohttp_client(app)

    resp = await client.post(
        "/ingest",
        json={"otra_clave": "valor"},
        headers={"Authorization": f"Bearer {VALID_TOKEN}"},
    )

    assert resp.status == 400
    body = await resp.json()
    assert "falta" in body["reply"].lower()


@pytest.mark.asyncio
async def test_ingest_empty_text_returns_400(aiohttp_client):
    app = _build_test_app()
    client = await aiohttp_client(app)

    resp = await client.post(
        "/ingest",
        json={"text": "   "},
        headers={"Authorization": f"Bearer {VALID_TOKEN}"},
    )

    assert resp.status == 400


@pytest.mark.asyncio
async def test_ingest_brain_exception_returns_500_and_no_telegram(aiohttp_client):
    def boom(text, user_id=0):
        raise RuntimeError("boom")

    app = _build_test_app(brain_side_effect=boom)
    client = await aiohttp_client(app)

    resp = await client.post(
        "/ingest",
        json={"text": "hola"},
        headers={"Authorization": f"Bearer {VALID_TOKEN}"},
    )

    assert resp.status == 500
    body = await resp.json()
    assert "fallado" in body["reply"].lower()
    app["telegram_bot"].send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_ingest_telegram_failure_still_returns_200(aiohttp_client):
    """Si el eco a Telegram falla, Siri sigue recibiendo su 200 con el reply."""
    app = _build_test_app(
        brain_reply="ok",
        send_side_effect=RuntimeError("telegram down"),
    )
    client = await aiohttp_client(app)

    resp = await client.post(
        "/ingest",
        json={"text": "hola"},
        headers={"Authorization": f"Bearer {VALID_TOKEN}"},
    )

    assert resp.status == 200
    body = await resp.json()
    assert body["reply"] == "ok"

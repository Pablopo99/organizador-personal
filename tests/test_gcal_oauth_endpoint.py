import os
import tempfile
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from aiohttp import web

import db
import gcal_sync


@pytest.fixture(autouse=True)
def temp_db(monkeypatch):
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init_schema()
    yield path
    os.unlink(path)


def _make_app(telegram_bot, allowed_user_id):
    app = web.Application()
    gcal_sync.register_oauth_routes(app, telegram_bot=telegram_bot, allowed_user_id=allowed_user_id)
    return app


@pytest.mark.asyncio
async def test_callback_with_valid_code_saves_tokens_and_pings_telegram(aiohttp_client):
    tg_bot = AsyncMock()
    client = await aiohttp_client(_make_app(tg_bot, 42))

    with patch("gcal_sync.exchange_code") as ex:
        resp = await client.get("/oauth/callback?code=THE-CODE")

    assert resp.status == 200
    body = await resp.text()
    assert "Calendar conectado" in body
    ex.assert_called_once_with("THE-CODE")
    tg_bot.send_message.assert_awaited_once()
    args = tg_bot.send_message.await_args.kwargs
    assert args["chat_id"] == 42
    assert "Calendar conectado" in args["text"]


@pytest.mark.asyncio
async def test_callback_without_code_returns_400(aiohttp_client):
    client = await aiohttp_client(_make_app(AsyncMock(), 42))
    resp = await client.get("/oauth/callback")
    assert resp.status == 400


@pytest.mark.asyncio
async def test_callback_with_error_query_returns_400(aiohttp_client):
    client = await aiohttp_client(_make_app(AsyncMock(), 42))
    resp = await client.get("/oauth/callback?error=access_denied")
    assert resp.status == 400
    body = await resp.text()
    assert "denegada" in body.lower() or "error" in body.lower()


@pytest.mark.asyncio
async def test_callback_exchange_fails_returns_500(aiohttp_client):
    tg_bot = AsyncMock()
    client = await aiohttp_client(_make_app(tg_bot, 42))
    with patch("gcal_sync.exchange_code", side_effect=RuntimeError("boom")):
        resp = await client.get("/oauth/callback?code=BAD")
    assert resp.status == 500

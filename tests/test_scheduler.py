import os
import tempfile
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import db
import scheduler


@pytest.fixture(autouse=True)
def temp_db(monkeypatch):
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init_schema()
    yield path
    os.unlink(path)


def _fake_context(send_message_mock=None):
    """Crea un fake context de python-telegram-bot."""
    ctx = SimpleNamespace()
    ctx.bot = SimpleNamespace()
    ctx.bot.send_message = send_message_mock or AsyncMock()
    return ctx


@pytest.mark.asyncio
async def test_morning_summary_sends_to_allowed_user(monkeypatch):
    monkeypatch.setattr(scheduler, "ALLOWED_USER_ID", 42)
    monkeypatch.setattr(
        scheduler.brain, "handle_message",
        lambda text, user_id=0: "🌅 Buenos días Pablo. Hoy no tienes nada."
    )

    send_mock = AsyncMock()
    await scheduler.morning_summary(_fake_context(send_mock))

    send_mock.assert_called_once()
    call = send_mock.call_args
    assert call.kwargs["chat_id"] == 42
    assert "Buenos días" in call.kwargs["text"]
    assert call.kwargs["parse_mode"] == "HTML"


@pytest.mark.asyncio
async def test_morning_summary_converts_markdown_to_html(monkeypatch):
    monkeypatch.setattr(scheduler, "ALLOWED_USER_ID", 42)
    monkeypatch.setattr(
        scheduler.brain, "handle_message",
        lambda text, user_id=0: "Hola **Pablo**"
    )

    send_mock = AsyncMock()
    await scheduler.morning_summary(_fake_context(send_mock))

    text = send_mock.call_args.kwargs["text"]
    assert "<b>Pablo</b>" in text
    assert "**" not in text


@pytest.mark.asyncio
async def test_morning_summary_handles_brain_exception(monkeypatch):
    monkeypatch.setattr(scheduler, "ALLOWED_USER_ID", 42)

    def explode(text, user_id=0):
        raise RuntimeError("boom")

    monkeypatch.setattr(scheduler.brain, "handle_message", explode)

    send_mock = AsyncMock()
    await scheduler.morning_summary(_fake_context(send_mock))
    send_mock.assert_not_called()

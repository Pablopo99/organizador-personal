"""Tests del job detect_missed_items."""
import os
import tempfile
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import date_utils
import db
import scheduler
import tools


@pytest.fixture(autouse=True)
def temp_db(monkeypatch):
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init_schema()
    yield path
    os.unlink(path)


def _ctx(send_mock=None):
    ctx = SimpleNamespace()
    ctx.bot = SimpleNamespace()
    ctx.bot.send_message = send_mock or AsyncMock()
    return ctx


@pytest.mark.asyncio
async def test_detect_missed_task_notifies_with_buttons(monkeypatch):
    monkeypatch.setattr(scheduler, "ALLOWED_USER_ID", 42)
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 30))

    t = tools.add_task("Llamar dentista", due_date="2026-05-27")

    send = AsyncMock()
    await scheduler.detect_missed_items(_ctx(send))

    send.assert_called_once()
    kwargs = send.call_args.kwargs
    assert "Llamar dentista" in kwargs["text"]
    markup = kwargs["reply_markup"]
    callbacks = [
        btn.callback_data for row in markup.inline_keyboard for btn in row
    ]
    assert f"rT:{t['id']}" in callbacks
    assert f"dT:{t['id']}" in callbacks

    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM missed_notifications WHERE item_type='task' AND item_id=?",
            (t["id"],),
        ).fetchone()
    assert row is not None


@pytest.mark.asyncio
async def test_detect_missed_idempotent_second_run(monkeypatch):
    monkeypatch.setattr(scheduler, "ALLOWED_USER_ID", 42)
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 30))

    tools.add_task("X", due_date="2026-05-27")

    send = AsyncMock()
    await scheduler.detect_missed_items(_ctx(send))
    assert send.call_count == 1

    await scheduler.detect_missed_items(_ctx(send))
    assert send.call_count == 1


@pytest.mark.asyncio
async def test_detect_missed_routine_notifies_streak_broken(monkeypatch):
    monkeypatch.setattr(scheduler, "ALLOWED_USER_ID", 42)
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 30))

    r = tools.add_event(
        "Meditar", "2026-05-25T08:00:00", "personal", recurring_rule="DAILY"
    )
    with db.connect() as conn:
        for d in ["2026-05-25", "2026-05-26", "2026-05-27"]:
            conn.execute(
                "INSERT INTO routine_completions (event_id, completion_date, created_at, status) "
                "VALUES (?, ?, ?, 'on_time')",
                (r["id"], d, "2026-05-30T08:00:00"),
            )

    send = AsyncMock()
    await scheduler.detect_missed_items(_ctx(send))

    send.assert_called()
    texts = [c.kwargs["text"] for c in send.call_args_list]
    assert any("Meditar" in t and "racha" in t.lower() for t in texts)


@pytest.mark.asyncio
async def test_detect_missed_routine_without_prior_streak_silent(monkeypatch):
    monkeypatch.setattr(scheduler, "ALLOWED_USER_ID", 42)
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 30))

    tools.add_event(
        "Lectura", "2026-05-01T08:00:00", "personal", recurring_rule="DAILY"
    )

    send = AsyncMock()
    await scheduler.detect_missed_items(_ctx(send))

    send.assert_not_called()

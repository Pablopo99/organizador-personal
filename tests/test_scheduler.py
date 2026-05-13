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
async def test_morning_summary_uses_isolated_history(monkeypatch):
    """El scheduler usa un user_id propio, no el del usuario real."""
    monkeypatch.setattr(scheduler, "ALLOWED_USER_ID", 42)
    captured = {}

    def fake_brain(text, user_id=0):
        captured["user_id"] = user_id
        return "🌅 Buenos días"

    monkeypatch.setattr(scheduler.brain, "handle_message", fake_brain)

    # Llenamos la memoria del usuario real con basura — el scheduler no debe usarla
    scheduler.brain._history[42] = [{"role": "user", "content": "chorro de turnos previos"}]

    await scheduler.morning_summary(_fake_context())

    assert captured["user_id"] != 42  # No usa el del usuario real
    assert captured["user_id"] == scheduler._SCHEDULER_USER_ID


@pytest.mark.asyncio
async def test_morning_summary_resets_history_each_run(monkeypatch):
    """Cada matutino empieza con historial limpio para el user_id del scheduler."""
    monkeypatch.setattr(scheduler, "ALLOWED_USER_ID", 42)
    monkeypatch.setattr(
        scheduler.brain, "handle_message",
        lambda text, user_id=0: "ok"
    )

    # Simulamos basura del run anterior
    sid = scheduler._SCHEDULER_USER_ID
    scheduler.brain._history[sid] = [{"role": "user", "content": "basura previa"}]

    await scheduler.morning_summary(_fake_context())

    # Después del reset y la llamada mockeada (que no añade nada), el historial
    # del scheduler debe NO contener la basura previa.
    history = scheduler.brain._history.get(sid, [])
    contents = [m.get("content") for m in history if isinstance(m.get("content"), str)]
    assert "basura previa" not in contents


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


def _add_event_at_offset(hours: float, title: str = "Evento", category: str = "work", done: int = 0):
    """Helper: añade un evento que ocurre en `hours` horas desde ahora."""
    dt = datetime.now() + timedelta(hours=hours)
    with db.connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO events (title, datetime, category, created_at, done,
                                reminder_1d_sent, reminder_1h_sent)
            VALUES (?, ?, ?, ?, ?, 0, 0)
            """,
            (title, dt.isoformat(timespec="seconds"), category,
             datetime.now().isoformat(timespec="seconds"), done),
        )
        return cur.lastrowid


@pytest.mark.asyncio
async def test_check_reminders_sends_1h_reminder(monkeypatch):
    monkeypatch.setattr(scheduler, "ALLOWED_USER_ID", 42)
    event_id = _add_event_at_offset(hours=1.0, title="Cita médico")

    send_mock = AsyncMock()
    await scheduler.check_reminders(_fake_context(send_mock))

    send_mock.assert_called_once()
    text = send_mock.call_args.kwargs["text"].lower()
    assert "1h" in text or "una hora" in text
    assert "Cita médico" in send_mock.call_args.kwargs["text"]

    with db.connect() as conn:
        row = conn.execute(
            "SELECT reminder_1h_sent FROM events WHERE id = ?", (event_id,)
        ).fetchone()
    assert row[0] == 1


@pytest.mark.asyncio
async def test_check_reminders_sends_1d_reminder(monkeypatch):
    monkeypatch.setattr(scheduler, "ALLOWED_USER_ID", 42)
    event_id = _add_event_at_offset(hours=24.0, title="Dentista")

    send_mock = AsyncMock()
    await scheduler.check_reminders(_fake_context(send_mock))

    send_mock.assert_called_once()
    text = send_mock.call_args.kwargs["text"].lower()
    assert "mañana" in text
    assert "Dentista" in send_mock.call_args.kwargs["text"]

    with db.connect() as conn:
        row = conn.execute(
            "SELECT reminder_1d_sent FROM events WHERE id = ?", (event_id,)
        ).fetchone()
    assert row[0] == 1


@pytest.mark.asyncio
async def test_check_reminders_skips_already_sent(monkeypatch):
    monkeypatch.setattr(scheduler, "ALLOWED_USER_ID", 42)
    event_id = _add_event_at_offset(hours=1.0, title="Ya avisado")
    with db.connect() as conn:
        conn.execute(
            "UPDATE events SET reminder_1h_sent = 1 WHERE id = ?", (event_id,)
        )

    send_mock = AsyncMock()
    await scheduler.check_reminders(_fake_context(send_mock))

    send_mock.assert_not_called()


@pytest.mark.asyncio
async def test_check_reminders_skips_done_events(monkeypatch):
    monkeypatch.setattr(scheduler, "ALLOWED_USER_ID", 42)
    _add_event_at_offset(hours=1.0, title="Hecho", done=1)

    send_mock = AsyncMock()
    await scheduler.check_reminders(_fake_context(send_mock))

    send_mock.assert_not_called()


@pytest.mark.asyncio
async def test_check_reminders_skips_recurring_events(monkeypatch):
    monkeypatch.setattr(scheduler, "ALLOWED_USER_ID", 42)
    dt = datetime.now() + timedelta(hours=1.0)
    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO events (title, datetime, category, recurring_rule, created_at, done,
                                reminder_1d_sent, reminder_1h_sent)
            VALUES (?, ?, 'personal', 'WEEKLY:MON', ?, 0, 0, 0)
            """,
            ("Gimnasio", dt.isoformat(timespec="seconds"),
             datetime.now().isoformat(timespec="seconds")),
        )

    send_mock = AsyncMock()
    await scheduler.check_reminders(_fake_context(send_mock))

    send_mock.assert_not_called()


@pytest.mark.asyncio
async def test_check_reminders_no_events_no_messages(monkeypatch):
    monkeypatch.setattr(scheduler, "ALLOWED_USER_ID", 42)

    send_mock = AsyncMock()
    await scheduler.check_reminders(_fake_context(send_mock))

    send_mock.assert_not_called()


@pytest.mark.asyncio
async def test_check_reminders_event_outside_window(monkeypatch):
    """Eventos muy lejos en el tiempo no disparan recordatorios."""
    monkeypatch.setattr(scheduler, "ALLOWED_USER_ID", 42)
    _add_event_at_offset(hours=48.0, title="Lejos")

    send_mock = AsyncMock()
    await scheduler.check_reminders(_fake_context(send_mock))

    send_mock.assert_not_called()

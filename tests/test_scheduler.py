import os
import tempfile
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import db
import scheduler
import date_utils as _date_utils
from datetime import date as _date


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
async def test_morning_summary_sends_greeting_with_view(monkeypatch):
    monkeypatch.setattr(scheduler, "ALLOWED_USER_ID", 42)

    send_mock = AsyncMock()
    await scheduler.morning_summary(_fake_context(send_mock))

    send_mock.assert_called_once()
    call = send_mock.call_args
    assert call.kwargs["chat_id"] == 42
    assert "Buenos días Pablo" in call.kwargs["text"]
    assert call.kwargs["parse_mode"] == "HTML"


@pytest.mark.asyncio
async def test_morning_summary_empty_db_says_day_libre(monkeypatch):
    monkeypatch.setattr(scheduler, "ALLOWED_USER_ID", 42)

    send_mock = AsyncMock()
    await scheduler.morning_summary(_fake_context(send_mock))

    text = send_mock.call_args.kwargs["text"]
    assert "Día libre" in text


@pytest.mark.asyncio
async def test_morning_summary_with_pending_item_includes_keyboard(monkeypatch):
    import date_utils
    import tools
    from datetime import date
    fixed_today = date(2026, 5, 19)
    monkeypatch.setattr(date_utils, "today_madrid", lambda: fixed_today)
    monkeypatch.setattr(scheduler, "ALLOWED_USER_ID", 42)
    tools.add_task("comprar pan", due_date=fixed_today.isoformat())

    send_mock = AsyncMock()
    await scheduler.morning_summary(_fake_context(send_mock))

    keyboard = send_mock.call_args.kwargs["reply_markup"]
    assert keyboard is not None
    assert len(keyboard.inline_keyboard) == 1


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


@pytest.mark.asyncio
async def test_morning_summary_lunes_incluye_bloque_semanal(monkeypatch):
    monkeypatch.setattr(scheduler, "ALLOWED_USER_ID", 42)
    # 2026-05-25 es lunes
    monkeypatch.setattr(_date_utils, "today_madrid", lambda: _date(2026, 5, 25))

    import tools
    # Crear datos de la semana pasada: una tarea hecha on_time el martes 20-may.
    t = tools.add_task("X", due_date="2026-05-20")
    monkeypatch.setattr(_date_utils, "today_madrid", lambda: _date(2026, 5, 20))
    tools.complete_task(t["id"])
    monkeypatch.setattr(_date_utils, "today_madrid", lambda: _date(2026, 5, 25))

    send_mock = AsyncMock()
    await scheduler.morning_summary(_fake_context(send_mock))

    send_mock.assert_called_once()
    text = send_mock.call_args.kwargs["text"]
    assert "Tu semana pasada" in text


@pytest.mark.asyncio
async def test_morning_summary_martes_no_incluye_bloque_semanal(monkeypatch):
    monkeypatch.setattr(scheduler, "ALLOWED_USER_ID", 42)
    monkeypatch.setattr(_date_utils, "today_madrid", lambda: _date(2026, 5, 26))

    send_mock = AsyncMock()
    await scheduler.morning_summary(_fake_context(send_mock))

    send_mock.assert_called_once()
    text = send_mock.call_args.kwargs["text"]
    assert "Tu semana pasada" not in text


@pytest.mark.asyncio
async def test_morning_summary_lunes_perfect_week_bonus(monkeypatch):
    monkeypatch.setattr(scheduler, "ALLOWED_USER_ID", 42)
    # Lunes 2026-06-01; semana pasada empieza 2026-05-25
    monkeypatch.setattr(_date_utils, "today_madrid", lambda: _date(2026, 5, 25))
    import tools
    o = tools.add_objective("A", "2026-05-25")
    monkeypatch.setattr(_date_utils, "today_madrid", lambda: _date(2026, 5, 28))
    tools.mark_objective_done(o["id"])
    monkeypatch.setattr(_date_utils, "today_madrid", lambda: _date(2026, 6, 1))

    send_mock = AsyncMock()
    await scheduler.morning_summary(_fake_context(send_mock))

    text = send_mock.call_args.kwargs["text"]
    assert "Semana perfecta" in text
    assert "+100 XP" in text


def test_ptb_days_convention_zero_is_sunday():
    """Sanity check: en python-telegram-bot v21 days=(0,) es domingo.

    Si esto cambia (PTB v22+ podría revertir la convención), nuestro
    weekly_objectives_reminder se dispararía el día equivocado.
    """
    from telegram.ext._jobqueue import JobQueue
    assert JobQueue._CRON_MAPPING[0] == "sun"
    assert JobQueue._CRON_MAPPING[6] == "sat"


@pytest.mark.asyncio
async def test_weekly_objectives_reminder_sends_message(monkeypatch):
    """Domingo a las 13:00 Madrid: recordatorio para pensar los 3 objetivos."""
    monkeypatch.setattr(scheduler, "ALLOWED_USER_ID", 42)

    send_mock = AsyncMock()
    await scheduler.weekly_objectives_reminder(_fake_context(send_mock))

    send_mock.assert_called_once()
    call = send_mock.call_args
    assert call.kwargs["chat_id"] == 42
    text = call.kwargs["text"]
    assert "objetivos" in text.lower()
    assert "🎯" in text
    assert call.kwargs["parse_mode"] == "HTML"


@pytest.mark.asyncio
async def test_check_reminders_skips_defaults_when_event_has_customs(monkeypatch):
    """Un evento con cualquier event_reminders NO recibe los defaults
    aunque caigan dentro de la ventana."""
    monkeypatch.setattr(scheduler, "ALLOWED_USER_ID", 42)
    import tools
    # Evento dentro de la ventana de 1h (entre 50 y 70 min)
    when = (datetime.now() + timedelta(minutes=60)).replace(microsecond=0)
    ev = tools.add_event("Cita", when.isoformat(), "personal")
    # Añadir un recordatorio custom de 30 min antes (queda sent=0)
    tools.add_event_reminder(ev["id"], 30)

    send_mock = AsyncMock()
    await scheduler.check_reminders(_fake_context(send_mock))

    # NO debió haberse mandado el default 1h (ni 1d, fuera de ventana)
    assert send_mock.call_count == 0
    with db.connect() as conn:
        row = conn.execute(
            "SELECT reminder_1h_sent FROM events WHERE id = ?",
            (ev["id"],),
        ).fetchone()
    assert row["reminder_1h_sent"] == 0


@pytest.mark.asyncio
async def test_check_reminders_sends_custom_within_window(monkeypatch):
    """Un custom cuyo fire_time cae dentro de la ventana ±5 min se manda
    y se marca sent=1."""
    monkeypatch.setattr(scheduler, "ALLOWED_USER_ID", 42)
    import tools
    # Evento dentro de 35 min; custom 30 min antes → fire_time = en 5 min,
    # dentro de la ventana ±5 min.
    when = (datetime.now() + timedelta(minutes=35)).replace(microsecond=0)
    ev = tools.add_event("Dentista", when.isoformat(), "personal")
    tools.add_event_reminder(ev["id"], 30)

    send_mock = AsyncMock()
    await scheduler.check_reminders(_fake_context(send_mock))

    send_mock.assert_called_once()
    text = send_mock.call_args.kwargs["text"]
    assert "Dentista" in text
    assert "30 min" in text
    with db.connect() as conn:
        row = conn.execute(
            "SELECT sent FROM event_reminders WHERE event_id = ?",
            (ev["id"],),
        ).fetchone()
    assert row["sent"] == 1


@pytest.mark.asyncio
async def test_check_reminders_groups_same_time_into_one_message(monkeypatch):
    """Tres eventos a la misma hora con la misma antelación → UN solo mensaje
    con los tres títulos, no tres mensajes."""
    monkeypatch.setattr(scheduler, "ALLOWED_USER_ID", 42)
    import tools
    when = (datetime.now() + timedelta(minutes=35)).replace(microsecond=0)
    ids = []
    for title in ("Dentista", "Llamar banco", "Recoger paquete"):
        ev = tools.add_event(title, when.isoformat(), "personal")
        tools.add_event_reminder(ev["id"], 30)
        ids.append(ev["id"])

    send_mock = AsyncMock()
    await scheduler.check_reminders(_fake_context(send_mock))

    send_mock.assert_called_once()  # un único mensaje
    text = send_mock.call_args.kwargs["text"]
    assert "Dentista" in text
    assert "Llamar banco" in text
    assert "Recoger paquete" in text
    assert "30 min" in text
    # los tres marcados como enviados
    with db.connect() as conn:
        sent = conn.execute(
            "SELECT COUNT(*) FROM event_reminders WHERE sent = 1"
        ).fetchone()[0]
    assert sent == 3


@pytest.mark.asyncio
async def test_check_reminders_does_not_resend_sent_custom(monkeypatch):
    monkeypatch.setattr(scheduler, "ALLOWED_USER_ID", 42)
    import tools
    when = (datetime.now() + timedelta(minutes=35)).replace(microsecond=0)
    ev = tools.add_event("Dentista", when.isoformat(), "personal")
    tools.add_event_reminder(ev["id"], 30)
    # Forzar sent=1
    with db.connect() as conn:
        conn.execute(
            "UPDATE event_reminders SET sent = 1 WHERE event_id = ?",
            (ev["id"],),
        )

    send_mock = AsyncMock()
    await scheduler.check_reminders(_fake_context(send_mock))

    assert send_mock.call_count == 0


@pytest.mark.asyncio
async def test_check_reminders_ignores_custom_outside_window(monkeypatch):
    """Custom cuyo fire_time está fuera de la ventana ±5 min no se manda."""
    monkeypatch.setattr(scheduler, "ALLOWED_USER_ID", 42)
    import tools
    # Evento dentro de 24h; custom 30 min antes → fire_time aún lejos
    when = (datetime.now() + timedelta(hours=24)).replace(microsecond=0)
    ev = tools.add_event("Cita", when.isoformat(), "personal")
    tools.add_event_reminder(ev["id"], 30)

    send_mock = AsyncMock()
    await scheduler.check_reminders(_fake_context(send_mock))

    assert send_mock.call_count == 0


@pytest.mark.asyncio
async def test_check_reminders_ignores_custom_for_done_event(monkeypatch):
    monkeypatch.setattr(scheduler, "ALLOWED_USER_ID", 42)
    import tools
    when = (datetime.now() + timedelta(minutes=35)).replace(microsecond=0)
    ev = tools.add_event("Cita", when.isoformat(), "personal")
    tools.add_event_reminder(ev["id"], 30)
    with db.connect() as conn:
        conn.execute("UPDATE events SET done = 1 WHERE id = ?", (ev["id"],))

    send_mock = AsyncMock()
    await scheduler.check_reminders(_fake_context(send_mock))

    assert send_mock.call_count == 0



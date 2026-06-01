"""Tests de la tool add_event_reminder y add_event con reminders."""
import os
import tempfile
from datetime import date, datetime, timedelta

import pytest

import date_utils
import db
import tools


@pytest.fixture(autouse=True)
def temp_db(monkeypatch):
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init_schema()
    yield path
    os.unlink(path)


def _seed_future_event(title="Cita", offset_hours=24):
    """Crea un evento que ocurre `offset_hours` horas en el futuro real."""
    when = (datetime.now() + timedelta(hours=offset_hours)).replace(microsecond=0)
    return tools.add_event(title, when.isoformat(), "personal")


def test_add_event_reminder_not_found():
    res = tools.add_event_reminder(99999, 30)
    assert res.get("error") == "not_found"


def test_add_event_reminder_invalid_offset_zero():
    ev = _seed_future_event()
    res = tools.add_event_reminder(ev["id"], 0)
    assert res.get("error") == "invalid_offset"


def test_add_event_reminder_invalid_offset_negative():
    ev = _seed_future_event()
    res = tools.add_event_reminder(ev["id"], -10)
    assert res.get("error") == "invalid_offset"


def test_add_event_reminder_recurring_event_rejected():
    ev = tools.add_event(
        "Meditar",
        (datetime.now() + timedelta(hours=24)).replace(microsecond=0).isoformat(),
        "personal",
        recurring_rule="DAILY",
    )
    res = tools.add_event_reminder(ev["id"], 30)
    assert res.get("error") == "event_is_recurring"


def test_add_event_reminder_done_event_rejected():
    ev = _seed_future_event()
    with db.connect() as conn:
        conn.execute("UPDATE events SET done = 1 WHERE id = ?", (ev["id"],))
    res = tools.add_event_reminder(ev["id"], 30)
    assert res.get("error") == "event_already_done"


def test_add_event_reminder_future_inserts_pending():
    """Evento dentro de 24h, recordatorio 30 min antes → fila sent=0,
    fires_immediately=False."""
    ev = _seed_future_event(offset_hours=24)
    res = tools.add_event_reminder(ev["id"], 30)
    assert res.get("event_id") == ev["id"]
    assert res.get("offset_minutes") == 30
    assert res.get("fires_immediately") is False
    with db.connect() as conn:
        row = conn.execute(
            "SELECT sent, offset_minutes FROM event_reminders "
            "WHERE event_id = ?",
            (ev["id"],),
        ).fetchone()
    assert row["sent"] == 0
    assert row["offset_minutes"] == 30


def test_add_event_reminder_past_window_fires_immediately():
    """Evento dentro de 10 min, offset 30 min → fire_time ya pasó →
    sent=1 y fires_immediately=True."""
    ev = _seed_future_event(offset_hours=0.16)  # ~10 min en el futuro
    res = tools.add_event_reminder(ev["id"], 30)
    assert res["fires_immediately"] is True
    with db.connect() as conn:
        row = conn.execute(
            "SELECT sent FROM event_reminders WHERE event_id = ?",
            (ev["id"],),
        ).fetchone()
    assert row["sent"] == 1


def test_add_event_reminder_idempotent_same_offset():
    """Llamar dos veces con (event_id, offset) iguales no duplica."""
    ev = _seed_future_event(offset_hours=24)
    r1 = tools.add_event_reminder(ev["id"], 30)
    assert "already_exists" not in r1
    r2 = tools.add_event_reminder(ev["id"], 30)
    assert r2.get("already_exists") is True
    with db.connect() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM event_reminders WHERE event_id = ?",
            (ev["id"],),
        ).fetchone()[0]
    assert count == 1


def test_add_event_reminder_different_offsets_coexist():
    """Dos offsets distintos en el mismo evento son dos filas independientes."""
    ev = _seed_future_event(offset_hours=24)
    tools.add_event_reminder(ev["id"], 30)
    tools.add_event_reminder(ev["id"], 180)
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT offset_minutes FROM event_reminders "
            "WHERE event_id = ? ORDER BY offset_minutes",
            (ev["id"],),
        ).fetchall()
    assert [r["offset_minutes"] for r in rows] == [30, 180]

import os
import tempfile

import pytest

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


def test_add_event_returns_id():
    result = tools.add_event(
        title="Cita médico",
        datetime_iso="2026-05-22T17:00:00",
        category="medical",
    )
    assert result["id"] >= 1
    assert result["title"] == "Cita médico"


def test_query_events_in_range_returns_event():
    tools.add_event("Reunión", "2026-05-15T10:00:00", "work")
    tools.add_event("Lejos", "2026-06-01T10:00:00", "work")

    rows = tools.query_events("2026-05-14T00:00:00", "2026-05-16T00:00:00")

    assert len(rows) == 1
    assert rows[0]["title"] == "Reunión"


def test_query_events_filters_by_category():
    tools.add_event("Médico", "2026-05-15T10:00:00", "medical")
    tools.add_event("Trabajo", "2026-05-15T11:00:00", "work")

    rows = tools.query_events(
        "2026-05-15T00:00:00", "2026-05-15T23:59:59", category="medical"
    )

    assert len(rows) == 1
    assert rows[0]["title"] == "Médico"


def test_query_events_expands_weekly_recurring():
    tools.add_event(
        title="Gimnasio",
        datetime_iso="2026-05-04T08:00:00",  # un lunes
        category="personal",
        recurring_rule="WEEKLY:MON",
    )
    rows = tools.query_events("2026-05-11T00:00:00", "2026-05-25T23:59:59")
    titles = [r["title"] for r in rows]
    assert titles.count("Gimnasio") == 3  # lunes 11, 18 y 25 de mayo


def test_update_event_changes_title():
    created = tools.add_event("Viejo", "2026-05-15T10:00:00", "work")
    tools.update_event(created["id"], {"title": "Nuevo"})
    rows = tools.query_events("2026-05-15T00:00:00", "2026-05-15T23:59:59")
    assert rows[0]["title"] == "Nuevo"


def test_delete_event_removes_it():
    created = tools.add_event("Borrable", "2026-05-15T10:00:00", "other")
    tools.delete_event(created["id"])
    rows = tools.query_events("2026-05-15T00:00:00", "2026-05-15T23:59:59")
    assert rows == []


def test_add_event_rejects_invalid_category():
    with pytest.raises(ValueError, match="categoría"):
        tools.add_event("X", "2026-05-15T10:00:00", "invalid_cat")


def test_mark_event_done_updates_flag():
    created = tools.add_event("Dentista", "2026-05-15T10:00:00", "medical")
    res = tools.mark_event_done(created["id"])
    assert res["updated"] == 1


def test_query_events_hides_done_by_default():
    a = tools.add_event("Pasado", "2026-05-15T10:00:00", "medical")
    tools.add_event("Vigente", "2026-05-15T11:00:00", "work")
    tools.mark_event_done(a["id"])

    rows = tools.query_events("2026-05-15T00:00:00", "2026-05-15T23:59:59")
    titles = [r["title"] for r in rows]
    assert titles == ["Vigente"]


def test_query_events_includes_done_when_flag_true():
    a = tools.add_event("Pasado", "2026-05-15T10:00:00", "medical")
    tools.add_event("Vigente", "2026-05-15T11:00:00", "work")
    tools.mark_event_done(a["id"])

    rows = tools.query_events(
        "2026-05-15T00:00:00", "2026-05-15T23:59:59", include_done=True
    )
    titles = [r["title"] for r in rows]
    assert sorted(titles) == ["Pasado", "Vigente"]


def test_update_event_with_datetime_resets_reminder_flags():
    created = tools.add_event("X", "2026-06-01T10:00:00", "work")
    with db.connect() as conn:
        conn.execute(
            "UPDATE events SET reminder_1d_sent = 1, reminder_1h_sent = 1 WHERE id = ?",
            (created["id"],),
        )

    tools.update_event(created["id"], {"datetime": "2026-06-02T10:00:00"})

    with db.connect() as conn:
        row = conn.execute(
            "SELECT reminder_1d_sent, reminder_1h_sent FROM events WHERE id = ?",
            (created["id"],),
        ).fetchone()
    assert row[0] == 0
    assert row[1] == 0


def test_update_event_with_title_keeps_reminder_flags():
    """Si solo cambia el título, los flags se preservan."""
    created = tools.add_event("X", "2026-06-01T10:00:00", "work")
    with db.connect() as conn:
        conn.execute(
            "UPDATE events SET reminder_1d_sent = 1 WHERE id = ?",
            (created["id"],),
        )

    tools.update_event(created["id"], {"title": "Y"})

    with db.connect() as conn:
        row = conn.execute(
            "SELECT reminder_1d_sent FROM events WHERE id = ?",
            (created["id"],),
        ).fetchone()
    assert row[0] == 1


def test_mark_event_done_on_non_recurring_sets_done_flag():
    """Comportamiento original intacto: evento puntual -> done=1."""
    created = tools.add_event("Médico", "2026-05-20T10:00:00", "medical")

    result = tools.mark_event_done(created["id"])

    assert result["updated"] == 1
    assert result.get("already_done_today") is not True
    with db.connect() as conn:
        row = conn.execute(
            "SELECT done FROM events WHERE id = ?", (created["id"],)
        ).fetchone()
    assert row[0] == 1


def test_mark_event_done_on_recurring_inserts_completion(monkeypatch):
    """Rutina -> no toca done; inserta en routine_completions con fecha de hoy Madrid."""
    from datetime import date
    import date_utils
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 19))

    created = tools.add_event(
        "Flexiones", "2026-05-19T08:00:00", "personal",
        recurring_rule="DAILY",
    )

    result = tools.mark_event_done(created["id"])

    assert result["event_id"] == created["id"]
    assert result["completion_date"] == "2026-05-19"
    assert result.get("already_done_today") is not True

    with db.connect() as conn:
        row = conn.execute(
            "SELECT done FROM events WHERE id = ?", (created["id"],)
        ).fetchone()
        assert row[0] == 0
        rc = conn.execute(
            "SELECT completion_date FROM routine_completions WHERE event_id = ?",
            (created["id"],),
        ).fetchone()
        assert rc[0] == "2026-05-19"


def test_mark_event_done_on_recurring_twice_same_day_idempotent(monkeypatch):
    """Marcar la misma rutina dos veces el mismo día devuelve already_done_today=True."""
    from datetime import date
    import date_utils
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 19))

    created = tools.add_event(
        "Flexiones", "2026-05-19T08:00:00", "personal",
        recurring_rule="DAILY",
    )

    first = tools.mark_event_done(created["id"])
    second = tools.mark_event_done(created["id"])

    assert first.get("already_done_today") is not True
    assert second["already_done_today"] is True

    with db.connect() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM routine_completions WHERE event_id = ?",
            (created["id"],),
        ).fetchone()[0]
    assert count == 1


def test_mark_event_done_recurring_different_days(monkeypatch):
    """Marcar la misma rutina dos días distintos sí inserta dos filas."""
    from datetime import date
    import date_utils
    created = tools.add_event(
        "Flexiones", "2026-05-19T08:00:00", "personal",
        recurring_rule="DAILY",
    )

    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 19))
    tools.mark_event_done(created["id"])

    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 20))
    tools.mark_event_done(created["id"])

    with db.connect() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM routine_completions WHERE event_id = ?",
            (created["id"],),
        ).fetchone()[0]
    assert count == 2

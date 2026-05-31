import os
import tempfile
from datetime import date
from unittest.mock import patch

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


def test_mark_event_done_updates_flag(monkeypatch):
    from datetime import date
    import date_utils
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 15))
    created = tools.add_event("Dentista", "2026-05-15T10:00:00", "medical")
    res = tools.mark_event_done(created["id"])
    assert res["updated"] == 1


def test_query_events_hides_done_by_default(monkeypatch):
    from datetime import date
    import date_utils
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 15))
    a = tools.add_event("Pasado", "2026-05-15T10:00:00", "medical")
    tools.add_event("Vigente", "2026-05-15T11:00:00", "work")
    tools.mark_event_done(a["id"])

    rows = tools.query_events("2026-05-15T00:00:00", "2026-05-15T23:59:59")
    titles = [r["title"] for r in rows]
    assert titles == ["Vigente"]


def test_query_events_includes_done_when_flag_true(monkeypatch):
    from datetime import date
    import date_utils
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 15))
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


def test_mark_event_done_on_non_recurring_sets_done_flag(monkeypatch):
    """Comportamiento original intacto: evento puntual -> done=1."""
    from datetime import date
    import date_utils
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 20))
    created = tools.add_event("Médico", "2026-05-20T10:00:00", "medical")

    result = tools.mark_event_done(created["id"])

    assert result["updated"] == 1
    assert result.get("already_done") is not True
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
    assert result.get("already_done") is not True

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
    """Marcar la misma rutina dos veces el mismo día devuelve already_done=True."""
    from datetime import date
    import date_utils
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 19))

    created = tools.add_event(
        "Flexiones", "2026-05-19T08:00:00", "personal",
        recurring_rule="DAILY",
    )

    first = tools.mark_event_done(created["id"])
    second = tools.mark_event_done(created["id"])

    assert first.get("already_done") is not True
    assert second["already_done"] is True

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


def test_query_events_recurring_instance_done_today_reflects_completion():
    """Una rutina DAILY marcada hoy aparece con done=1 en query_events para hoy."""
    created = tools.add_event(
        "Flexiones", "2026-05-19T08:00:00", "personal",
        recurring_rule="DAILY",
    )
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO routine_completions (event_id, completion_date, created_at) VALUES (?, '2026-05-19', '2026-05-19T08:00:00')",
            (created["id"],),
        )

    rows = tools.query_events(
        "2026-05-19T00:00:00", "2026-05-19T23:59:59", include_done=True
    )

    flex_rows = [r for r in rows if r["title"] == "Flexiones"]
    assert len(flex_rows) == 1
    assert flex_rows[0]["done"] == 1


def test_query_events_recurring_instance_pending_when_no_completion():
    """Una rutina DAILY sin completar hoy aparece con done=0."""
    tools.add_event(
        "Flexiones", "2026-05-19T08:00:00", "personal",
        recurring_rule="DAILY",
    )

    rows = tools.query_events(
        "2026-05-19T00:00:00", "2026-05-19T23:59:59", include_done=True
    )

    flex_rows = [r for r in rows if r["title"] == "Flexiones"]
    assert len(flex_rows) == 1
    assert flex_rows[0]["done"] == 0


def test_query_events_recurring_each_instance_independent():
    """Marcar el 19 no afecta a la instancia del 20."""
    created = tools.add_event(
        "Flexiones", "2026-05-19T08:00:00", "personal",
        recurring_rule="DAILY",
    )
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO routine_completions (event_id, completion_date, created_at) VALUES (?, '2026-05-19', '2026-05-19T08:00:00')",
            (created["id"],),
        )

    rows = tools.query_events(
        "2026-05-19T00:00:00", "2026-05-21T23:59:59", include_done=True
    )

    flex_rows = sorted(
        [r for r in rows if r["title"] == "Flexiones"],
        key=lambda r: r["datetime"],
    )
    assert len(flex_rows) == 3
    assert flex_rows[0]["done"] == 1
    assert flex_rows[1]["done"] == 0
    assert flex_rows[2]["done"] == 0


def test_query_events_non_recurring_done_unchanged(monkeypatch):
    """Eventos puntuales mantienen su .done original."""
    from datetime import date
    import date_utils
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 19))
    created = tools.add_event("Médico", "2026-05-19T10:00:00", "medical")
    tools.mark_event_done(created["id"])

    rows = tools.query_events(
        "2026-05-19T00:00:00", "2026-05-19T23:59:59", include_done=True
    )

    med = [r for r in rows if r["title"] == "Médico"][0]
    assert med["done"] == 1


def test_routine_summary_counts_completions_in_range():
    """Marca 3 días de la semana → completed_days=3, scheduled_days=7."""
    created = tools.add_event(
        "Flexiones", "2026-05-18T08:00:00", "personal",
        recurring_rule="DAILY",
    )
    with db.connect() as conn:
        for d in ("2026-05-18", "2026-05-19", "2026-05-20"):
            conn.execute(
                "INSERT INTO routine_completions (event_id, completion_date, created_at) VALUES (?, ?, ?)",
                (created["id"], d, "2026-05-19T08:00:00"),
            )

    summary = tools.routine_summary("2026-05-18", "2026-05-24")

    flex = [r for r in summary if r["title"] == "Flexiones"][0]
    assert flex["scheduled_days"] == 7
    assert flex["completed_days"] == 3
    assert flex["event_id"] == created["id"]
    assert flex["recurring_rule"] == "DAILY"


def test_routine_summary_weekly_routine_scheduled_once():
    """WEEKLY:MON entre lunes 18 y domingo 24 → scheduled_days=1."""
    tools.add_event(
        "Gimnasio", "2026-05-18T19:00:00", "personal",
        recurring_rule="WEEKLY:MON",
    )

    summary = tools.routine_summary("2026-05-18", "2026-05-24")

    gym = [r for r in summary if r["title"] == "Gimnasio"][0]
    assert gym["scheduled_days"] == 1
    assert gym["completed_days"] == 0


def test_routine_summary_ignores_non_recurring():
    """Eventos puntuales no aparecen en el summary."""
    tools.add_event("Médico", "2026-05-20T10:00:00", "medical")

    summary = tools.routine_summary("2026-05-18", "2026-05-24")

    titles = [r["title"] for r in summary]
    assert "Médico" not in titles


def test_routine_summary_empty_when_no_routines():
    summary = tools.routine_summary("2026-05-18", "2026-05-24")
    assert summary == []


def test_routine_summary_weekly_routine_not_in_range_excluded():
    """WEEKLY:TUE en una semana que no contiene martes → no aparece."""
    tools.add_event(
        "Yoga", "2026-05-19T07:00:00", "personal",
        recurring_rule="WEEKLY:TUE",
    )

    # Rango Wed-Tue: contiene un martes
    summary = tools.routine_summary("2026-05-20", "2026-05-26")
    yoga = [r for r in summary if r["title"] == "Yoga"]
    assert len(yoga) == 1
    assert yoga[0]["scheduled_days"] == 1

    # Rango sin martes
    summary = tools.routine_summary("2026-05-21", "2026-05-25")
    yoga = [r for r in summary if r["title"] == "Yoga"]
    assert yoga == []


def _insert_completion(event_id: int, completion_date: str) -> None:
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO routine_completions (event_id, completion_date, created_at) VALUES (?, ?, ?)",
            (event_id, completion_date, "2026-05-19T08:00:00"),
        )


def test_current_streak_daily_three_days_through_today():
    """Hoy hecho + ayer + anteayer -> 3."""
    from datetime import date
    e = tools.add_event("F", "2026-05-17T08:00:00", "personal", recurring_rule="DAILY")
    for d in ("2026-05-17", "2026-05-18", "2026-05-19"):
        _insert_completion(e["id"], d)

    with db.connect() as conn:
        streak = tools._current_streak(e["id"], "DAILY", date(2026, 5, 19), conn)
    assert streak == 3


def test_current_streak_daily_alive_when_today_pending():
    """Ayer y anteayer hechos, hoy pendiente -> 2 (vivo)."""
    from datetime import date
    e = tools.add_event("F", "2026-05-17T08:00:00", "personal", recurring_rule="DAILY")
    for d in ("2026-05-17", "2026-05-18"):
        _insert_completion(e["id"], d)

    with db.connect() as conn:
        streak = tools._current_streak(e["id"], "DAILY", date(2026, 5, 19), conn)
    assert streak == 2


def test_current_streak_daily_broken_when_yesterday_missing():
    """Anteayer hecho pero ayer no -> 0 (roto)."""
    from datetime import date
    e = tools.add_event("F", "2026-05-17T08:00:00", "personal", recurring_rule="DAILY")
    _insert_completion(e["id"], "2026-05-17")  # anteayer

    with db.connect() as conn:
        streak = tools._current_streak(e["id"], "DAILY", date(2026, 5, 19), conn)
    assert streak == 0


def test_current_streak_daily_only_today_done():
    """Solo hoy hecho, sin historia -> 1."""
    from datetime import date
    e = tools.add_event("F", "2026-05-19T08:00:00", "personal", recurring_rule="DAILY")
    _insert_completion(e["id"], "2026-05-19")

    with db.connect() as conn:
        streak = tools._current_streak(e["id"], "DAILY", date(2026, 5, 19), conn)
    assert streak == 1


def test_current_streak_weekly_two_consecutive_mondays_today_wednesday():
    """WEEKLY:MON, 2 lunes seguidos hechos, hoy es miércoles -> 2."""
    from datetime import date
    e = tools.add_event("G", "2026-05-11T19:00:00", "personal", recurring_rule="WEEKLY:MON")
    _insert_completion(e["id"], "2026-05-11")
    _insert_completion(e["id"], "2026-05-18")

    with db.connect() as conn:
        streak = tools._current_streak(e["id"], "WEEKLY:MON", date(2026, 5, 20), conn)
    assert streak == 2


def test_current_streak_weekly_broken_last_monday_missed():
    """WEEKLY:MON, último lunes no hecho -> 0."""
    from datetime import date
    e = tools.add_event("G", "2026-05-11T19:00:00", "personal", recurring_rule="WEEKLY:MON")
    _insert_completion(e["id"], "2026-05-11")

    with db.connect() as conn:
        streak = tools._current_streak(e["id"], "WEEKLY:MON", date(2026, 5, 20), conn)
    assert streak == 0


def test_current_streak_weekly_today_is_target_weekday_pending():
    """WEEKLY:MON, hoy es lunes y aún no hecho, los 2 lunes anteriores hechos -> 2 (vivo)."""
    from datetime import date
    e = tools.add_event("G", "2026-05-04T19:00:00", "personal", recurring_rule="WEEKLY:MON")
    _insert_completion(e["id"], "2026-05-04")
    _insert_completion(e["id"], "2026-05-11")

    with db.connect() as conn:
        streak = tools._current_streak(e["id"], "WEEKLY:MON", date(2026, 5, 18), conn)
    assert streak == 2


def test_current_streak_no_completions_returns_zero():
    from datetime import date
    e = tools.add_event("F", "2026-05-19T08:00:00", "personal", recurring_rule="DAILY")

    with db.connect() as conn:
        streak = tools._current_streak(e["id"], "DAILY", date(2026, 5, 19), conn)
    assert streak == 0


def test_best_streak_daily_max_run():
    """Histórico DAILY: 5 seguidos, salto, 3 seguidos -> 5."""
    e = tools.add_event("F", "2026-05-01T08:00:00", "personal", recurring_rule="DAILY")
    for d in ("2026-05-01", "2026-05-02", "2026-05-03", "2026-05-04", "2026-05-05"):
        _insert_completion(e["id"], d)
    for d in ("2026-05-08", "2026-05-09", "2026-05-10"):
        _insert_completion(e["id"], d)

    with db.connect() as conn:
        best = tools._best_streak(e["id"], "DAILY", conn)
    assert best == 5


def test_best_streak_weekly_consecutive_mondays():
    """WEEKLY:MON: 3 lunes seguidos, salto, 2 lunes seguidos -> 3."""
    e = tools.add_event("G", "2026-05-04T19:00:00", "personal", recurring_rule="WEEKLY:MON")
    for d in ("2026-05-04", "2026-05-11", "2026-05-18"):
        _insert_completion(e["id"], d)
    for d in ("2026-06-01", "2026-06-08"):
        _insert_completion(e["id"], d)

    with db.connect() as conn:
        best = tools._best_streak(e["id"], "WEEKLY:MON", conn)
    assert best == 3


def test_best_streak_no_completions_returns_zero():
    e = tools.add_event("F", "2026-05-19T08:00:00", "personal", recurring_rule="DAILY")

    with db.connect() as conn:
        best = tools._best_streak(e["id"], "DAILY", conn)
    assert best == 0


def test_best_streak_single_completion_returns_one():
    e = tools.add_event("F", "2026-05-19T08:00:00", "personal", recurring_rule="DAILY")
    _insert_completion(e["id"], "2026-05-19")

    with db.connect() as conn:
        best = tools._best_streak(e["id"], "DAILY", conn)
    assert best == 1


def test_unmark_event_done_sets_done_zero(monkeypatch):
    from datetime import date
    import date_utils
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 20))
    e = tools.add_event("Médico", "2026-05-20T10:00:00", "medical")
    tools.mark_event_done(e["id"])

    tools.unmark_event_done(e["id"])

    with db.connect() as conn:
        row = conn.execute("SELECT done FROM events WHERE id = ?", (e["id"],)).fetchone()
    assert row[0] == 0


def test_unmark_event_done_idempotent_on_unmarked():
    e = tools.add_event("Médico", "2026-05-20T10:00:00", "medical")
    tools.unmark_event_done(e["id"])

    with db.connect() as conn:
        row = conn.execute("SELECT done FROM events WHERE id = ?", (e["id"],)).fetchone()
    assert row[0] == 0


def test_uncomplete_routine_today_removes_today_completion(monkeypatch):
    from datetime import date
    import date_utils
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 19))

    e = tools.add_event("Flexiones", "2026-05-19T08:00:00", "personal", recurring_rule="DAILY")
    tools.mark_event_done(e["id"])

    tools.uncomplete_routine_today(e["id"])

    with db.connect() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM routine_completions WHERE event_id = ? AND completion_date = ?",
            (e["id"], "2026-05-19"),
        ).fetchone()[0]
    assert count == 0


def test_uncomplete_routine_today_preserves_other_days(monkeypatch):
    from datetime import date
    import date_utils
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 19))

    e = tools.add_event("Flexiones", "2026-05-17T08:00:00", "personal", recurring_rule="DAILY")
    with db.connect() as conn:
        for d in ("2026-05-17", "2026-05-18", "2026-05-19"):
            conn.execute(
                "INSERT INTO routine_completions (event_id, completion_date, created_at) VALUES (?, ?, ?)",
                (e["id"], d, "2026-05-19T08:00:00"),
            )

    tools.uncomplete_routine_today(e["id"])

    with db.connect() as conn:
        dates = [r[0] for r in conn.execute(
            "SELECT completion_date FROM routine_completions WHERE event_id = ? ORDER BY completion_date",
            (e["id"],),
        ).fetchall()]
    assert dates == ["2026-05-17", "2026-05-18"]


def test_uncomplete_routine_today_idempotent_when_not_completed(monkeypatch):
    from datetime import date
    import date_utils
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 19))

    e = tools.add_event("Flexiones", "2026-05-19T08:00:00", "personal", recurring_rule="DAILY")
    tools.uncomplete_routine_today(e["id"])  # no debería fallar


def test_routine_summary_includes_current_streak(monkeypatch):
    from datetime import date
    import date_utils
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 19))

    e = tools.add_event("F", "2026-05-17T08:00:00", "personal", recurring_rule="DAILY")
    for d in ("2026-05-17", "2026-05-18", "2026-05-19"):
        _insert_completion(e["id"], d)

    summary = tools.routine_summary("2026-05-18", "2026-05-24")
    flex = [r for r in summary if r["title"] == "F"][0]
    assert flex["current_streak"] == 3


def test_routine_summary_includes_best_streak(monkeypatch):
    from datetime import date
    import date_utils
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 19))

    e = tools.add_event("F", "2026-05-01T08:00:00", "personal", recurring_rule="DAILY")
    for d in ("2026-05-01", "2026-05-02", "2026-05-03", "2026-05-04", "2026-05-05"):
        _insert_completion(e["id"], d)

    summary = tools.routine_summary("2026-05-19", "2026-05-19")
    flex = [r for r in summary if r["title"] == "F"][0]
    assert flex["best_streak"] == 5


def test_routine_summary_streak_alive_when_today_pending(monkeypatch):
    from datetime import date
    import date_utils
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 19))

    e = tools.add_event("F", "2026-05-17T08:00:00", "personal", recurring_rule="DAILY")
    for d in ("2026-05-17", "2026-05-18"):
        _insert_completion(e["id"], d)

    summary = tools.routine_summary("2026-05-19", "2026-05-19")
    flex = [r for r in summary if r["title"] == "F"][0]
    assert flex["current_streak"] == 2


def test_routine_summary_no_completions_zero_streaks(monkeypatch):
    from datetime import date
    import date_utils
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 19))

    tools.add_event("F", "2026-05-19T08:00:00", "personal", recurring_rule="DAILY")
    summary = tools.routine_summary("2026-05-19", "2026-05-19")
    flex = [r for r in summary if r["title"] == "F"][0]
    assert flex["current_streak"] == 0
    assert flex["best_streak"] == 0


def test_update_event_propagates_to_calendar_when_synced():
    created = tools.add_event("Reu", "2026-05-29T10:00:00", "work")
    # Marcar la fila como sincronizada (simula que pasó por push_event_to_calendar)
    with db.connect() as conn:
        conn.execute(
            "UPDATE events SET gcal_event_id = ? WHERE id = ?",
            ("gcal-1", created["id"]),
        )

    with patch("tools.gcal_sync.update_event") as upd:
        tools.update_event(created["id"], {"title": "Reu nueva"})

    upd.assert_called_once_with("gcal-1", {"title": "Reu nueva"})


def test_update_event_does_not_call_gcal_when_not_synced():
    created = tools.add_event("Sin sync", "2026-05-29T10:00:00", "work")
    with patch("tools.gcal_sync.update_event") as upd:
        tools.update_event(created["id"], {"title": "Otro"})
    upd.assert_not_called()


def test_update_event_swallows_gcal_errors():
    created = tools.add_event("Reu", "2026-05-29T10:00:00", "work")
    with db.connect() as conn:
        conn.execute(
            "UPDATE events SET gcal_event_id = ? WHERE id = ?",
            ("gcal-x", created["id"]),
        )
    with patch("tools.gcal_sync.update_event", side_effect=RuntimeError("boom")):
        result = tools.update_event(created["id"], {"title": "Reu2"})
    assert result["updated"] == 1  # update local sí funcionó


def test_delete_event_propagates_to_calendar_when_synced():
    created = tools.add_event("Borrar", "2026-05-29T10:00:00", "work")
    with db.connect() as conn:
        conn.execute(
            "UPDATE events SET gcal_event_id = ? WHERE id = ?",
            ("gcal-d", created["id"]),
        )
    with patch("tools.gcal_sync.delete_event") as dl:
        tools.delete_event(created["id"])
    dl.assert_called_once_with("gcal-d")


def test_delete_event_does_not_call_gcal_when_not_synced():
    created = tools.add_event("X", "2026-05-29T10:00:00", "work")
    with patch("tools.gcal_sync.delete_event") as dl:
        tools.delete_event(created["id"])
    dl.assert_not_called()


def test_add_event_with_sync_to_calendar_true_pushes_and_stores_gcal_id():
    with patch("tools.gcal_sync.push_event", return_value="gcal-sync-1") as p:
        result = tools.add_event(
            "Reu", "2026-05-29T10:00:00", "work", sync_to_calendar=True
        )
    p.assert_called_once()
    assert result["gcal_event_id"] == "gcal-sync-1"
    with db.connect() as conn:
        row = conn.execute(
            "SELECT gcal_event_id FROM events WHERE id = ?", (result["id"],)
        ).fetchone()
    assert row["gcal_event_id"] == "gcal-sync-1"


def test_add_event_default_does_not_call_calendar():
    with patch("tools.gcal_sync.push_event") as p:
        tools.add_event("Reu", "2026-05-29T10:00:00", "work")
    p.assert_not_called()


def test_add_event_with_sync_not_connected_returns_unsynced_but_keeps_event():
    import gcal_sync
    with patch("tools.gcal_sync.push_event", side_effect=gcal_sync.NotConnected()):
        result = tools.add_event(
            "Reu", "2026-05-29T10:00:00", "work", sync_to_calendar=True
        )
    assert "id" in result
    assert result.get("sync_error") == "not_connected"


def test_push_event_to_calendar_writes_gcal_id_and_returns_ok():
    created = tools.add_event("Cena", "2026-05-29T21:00:00", "personal")

    with patch("tools.gcal_sync.push_event", return_value="gcal-cena-1"):
        result = tools.push_event_to_calendar(created["id"])

    assert result == {"event_id": created["id"], "gcal_event_id": "gcal-cena-1", "synced": True}
    with db.connect() as conn:
        row = conn.execute(
            "SELECT gcal_event_id FROM events WHERE id = ?", (created["id"],)
        ).fetchone()
    assert row["gcal_event_id"] == "gcal-cena-1"


def test_push_event_to_calendar_is_idempotent_when_already_synced():
    created = tools.add_event("Cita", "2026-05-29T10:00:00", "medical")
    with db.connect() as conn:
        conn.execute(
            "UPDATE events SET gcal_event_id = ? WHERE id = ?",
            ("gcal-already", created["id"]),
        )

    with patch("tools.gcal_sync.push_event") as p:
        result = tools.push_event_to_calendar(created["id"])

    p.assert_not_called()
    assert result["already_synced"] is True
    assert result["gcal_event_id"] == "gcal-already"


def test_push_event_to_calendar_raises_friendly_when_not_connected():
    created = tools.add_event("Cita", "2026-05-29T10:00:00", "medical")
    import gcal_sync
    with patch("tools.gcal_sync.push_event", side_effect=gcal_sync.NotConnected()):
        result = tools.push_event_to_calendar(created["id"])
    assert result == {"event_id": created["id"], "synced": False, "error": "not_connected"}


def test_push_event_to_calendar_unknown_event_id():
    result = tools.push_event_to_calendar(99999)
    assert result == {"event_id": 99999, "synced": False, "error": "not_found"}


def test_connect_calendar_returns_auth_url():
    with patch("tools.gcal_sync.oauth_start_url", return_value="https://example/auth?x=1"):
        result = tools.connect_calendar()
    assert result == {"auth_url": "https://example/auth?x=1"}


def test_mark_event_done_on_time_sets_outcome(monkeypatch):
    from datetime import date
    import date_utils
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 30))
    res = tools.add_event("Dentista", "2026-05-30T10:00:00", "personal")
    tools.mark_event_done(res["id"])
    with db.connect() as conn:
        row = conn.execute(
            "SELECT done, outcome FROM events WHERE id = ?", (res["id"],)
        ).fetchone()
    assert row["done"] == 1
    assert row["outcome"] == "on_time"


def test_mark_event_done_grace_when_one_day_late(monkeypatch):
    from datetime import date
    import date_utils
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 31))
    res = tools.add_event("Dentista", "2026-05-30T10:00:00", "personal")
    tools.mark_event_done(res["id"])
    with db.connect() as conn:
        row = conn.execute(
            "SELECT done, outcome FROM events WHERE id = ?", (res["id"],)
        ).fetchone()
    assert row["done"] == 1
    assert row["outcome"] == "grace"


def test_mark_event_done_rejected_out_of_window(monkeypatch):
    from datetime import date
    import date_utils
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 6, 1))
    res = tools.add_event("Dentista", "2026-05-30T10:00:00", "personal")
    out = tools.mark_event_done(res["id"])
    assert out.get("error") == "out_of_window"
    with db.connect() as conn:
        row = conn.execute(
            "SELECT done, outcome FROM events WHERE id = ?", (res["id"],)
        ).fetchone()
    assert row["done"] == 0
    assert row["outcome"] is None


def test_mark_routine_done_today_on_time(monkeypatch):
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 30))
    res = tools.add_event(
        "Meditar", "2026-05-01T08:00:00", "personal", recurring_rule="DAILY"
    )
    tools.mark_event_done(res["id"])
    with db.connect() as conn:
        row = conn.execute(
            "SELECT completion_date, status FROM routine_completions "
            "WHERE event_id = ?",
            (res["id"],),
        ).fetchone()
    assert row["completion_date"] == "2026-05-30"
    assert row["status"] == "on_time"


def test_mark_weekly_sat_routine_done_one_day_late_uses_expected_day_with_grace(monkeypatch):
    """WEEKLY:SAT: si hoy es domingo 31 y no se hizo el sábado 30, se registra el 30 con grace."""
    # 2026-05-30 = sábado, 2026-05-31 = domingo.
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 31))
    res = tools.add_event(
        "Meditar", "2026-05-01T08:00:00", "personal", recurring_rule="WEEKLY:SAT"
    )
    tools.mark_event_done(res["id"])
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT completion_date, status FROM routine_completions "
            "WHERE event_id = ? ORDER BY completion_date",
            (res["id"],),
        ).fetchall()
    assert len(rows) == 1
    assert rows[0]["completion_date"] == "2026-05-30"
    assert rows[0]["status"] == "grace"


def test_mark_weekly_routine_done_in_grace_records_expected_day(monkeypatch):
    """WEEKLY:MON: si hoy es martes y no se hizo el lunes, grabar el lunes."""
    # 2026-05-25 lunes, 2026-05-26 martes.
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 26))
    res = tools.add_event(
        "Reunión semanal", "2026-05-04T09:00:00", "work",
        recurring_rule="WEEKLY:MON",
    )
    tools.mark_event_done(res["id"])
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT completion_date, status FROM routine_completions "
            "WHERE event_id = ?",
            (res["id"],),
        ).fetchall()
    assert len(rows) == 1
    assert rows[0]["completion_date"] == "2026-05-25"
    assert rows[0]["status"] == "grace"


def test_mark_daily_routine_for_today_is_on_time(monkeypatch):
    """DAILY: hoy SIEMPRE es fecha esperada, así que cualquier mark es on_time."""
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 6, 1))
    res = tools.add_event(
        "Meditar", "2026-05-01T08:00:00", "personal", recurring_rule="DAILY"
    )
    out = tools.mark_event_done(res["id"])
    assert out.get("status") == "on_time"


def test_mark_weekly_routine_done_in_wrong_day_rejected(monkeypatch):
    """WEEKLY:MON: si hoy es jueves (no lunes ni martes), rechazar."""
    # 2026-05-28 jueves.
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 28))
    res = tools.add_event(
        "Reunión semanal", "2026-05-04T09:00:00", "work",
        recurring_rule="WEEKLY:MON",
    )
    out = tools.mark_event_done(res["id"])
    assert out.get("error") == "out_of_window"
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM routine_completions WHERE event_id = ?",
            (res["id"],),
        ).fetchall()
    assert len(rows) == 0


def test_routine_summary_scheduled_days_clamps_to_routine_start(monkeypatch):
    """Una rutina creada a mitad del rango no cuenta días anteriores a su inicio."""
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 30))
    res = tools.add_event(
        "Nueva rutina", "2026-05-28T08:00:00", "personal", recurring_rule="DAILY"
    )
    summary = tools.routine_summary("2026-05-25", "2026-05-30")
    target = next(r for r in summary if r["event_id"] == res["id"])
    # Solo 3 días esperados: 28, 29, 30 (no 25-27 cuando la rutina no existía).
    assert target["scheduled_days"] == 3


def test_routine_summary_breaks_down_on_time_and_grace(monkeypatch):
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 30))
    res = tools.add_event(
        "Meditar", "2026-05-25T08:00:00", "personal", recurring_rule="DAILY"
    )
    # Insertamos manualmente 2 on_time + 1 grace en el rango.
    with db.connect() as conn:
        for d, status in [
            ("2026-05-25", "on_time"),
            ("2026-05-26", "grace"),
            ("2026-05-27", "on_time"),
        ]:
            conn.execute(
                "INSERT INTO routine_completions (event_id, completion_date, created_at, status) "
                "VALUES (?, ?, ?, ?)",
                (res["id"], d, "2026-05-30T08:00:00", status),
            )

    summary = tools.routine_summary("2026-05-25", "2026-05-30")
    target = next(r for r in summary if r["event_id"] == res["id"])
    assert target["on_time_count"] == 2
    assert target["grace_count"] == 1
    assert target["completed_days"] == 3
    assert target["scheduled_days"] == 6


def test_query_events_include_grace_returns_yesterday_pending():
    tools.add_event("Cita perdida", "2026-05-29T10:00:00", "personal")
    rows = tools.query_events(
        date_from="2026-05-30T00:00:00",
        date_to="2026-05-30T23:59:59",
        include_grace=True,
    )
    titles = [r["title"] for r in rows]
    assert "Cita perdida" in titles


def test_query_events_default_does_not_return_yesterday():
    tools.add_event("Cita perdida", "2026-05-29T10:00:00", "personal")
    rows = tools.query_events(
        date_from="2026-05-30T00:00:00",
        date_to="2026-05-30T23:59:59",
    )
    titles = [r["title"] for r in rows]
    assert "Cita perdida" not in titles


def test_query_events_include_grace_excludes_already_missed():
    res = tools.add_event("Cita descartada", "2026-05-29T10:00:00", "personal")
    with db.connect() as conn:
        conn.execute(
            "UPDATE events SET outcome = 'missed' WHERE id = ?", (res["id"],)
        )
    rows = tools.query_events(
        date_from="2026-05-30T00:00:00",
        date_to="2026-05-30T23:59:59",
        include_grace=True,
    )
    titles = [r["title"] for r in rows]
    assert "Cita descartada" not in titles

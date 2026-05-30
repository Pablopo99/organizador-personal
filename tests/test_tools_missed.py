"""Tests de recreate_* y discard_* helpers."""
import os
import tempfile
from datetime import date

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


def test_recreate_task_creates_new_with_today_due_date(monkeypatch):
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 30))
    orig = tools.add_task("Llamar dentista", due_date="2026-05-20")

    res = tools.recreate_task(orig["id"])

    assert res["new_id"] != orig["id"]
    with db.connect() as conn:
        new_row = conn.execute(
            "SELECT text, due_date, outcome, done FROM tasks WHERE id = ?",
            (res["new_id"],),
        ).fetchone()
        old_row = conn.execute(
            "SELECT outcome FROM tasks WHERE id = ?", (orig["id"],)
        ).fetchone()
    assert new_row["text"] == "Llamar dentista"
    assert new_row["due_date"] == "2026-05-30"
    assert new_row["outcome"] is None
    assert new_row["done"] == 0
    assert old_row["outcome"] == "missed"


def test_recreate_event_creates_new_with_today_date_keeping_time(monkeypatch):
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 30))
    orig = tools.add_event("Dentista", "2026-05-20T10:00:00", "personal")

    res = tools.recreate_event(orig["id"])

    assert res["new_id"] != orig["id"]
    with db.connect() as conn:
        new_row = conn.execute(
            "SELECT title, datetime, outcome, done, gcal_event_id FROM events WHERE id = ?",
            (res["new_id"],),
        ).fetchone()
        old_row = conn.execute(
            "SELECT outcome FROM events WHERE id = ?", (orig["id"],)
        ).fetchone()
    assert new_row["title"] == "Dentista"
    assert new_row["datetime"] == "2026-05-30T10:00:00"
    assert new_row["outcome"] is None
    assert new_row["done"] == 0
    # El nuevo evento NO hereda gcal_event_id (Pablo decide sincronizarlo).
    assert new_row["gcal_event_id"] is None
    assert old_row["outcome"] == "missed"


def test_recreate_objective_creates_new_in_current_week(monkeypatch):
    # 2026-05-30 es sábado; lunes de su semana es 2026-05-25.
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 30))
    orig = tools.add_objective("Leer 100 páginas", "2026-05-11")

    res = tools.recreate_objective(orig["id"])

    assert res["new_id"] != orig["id"]
    with db.connect() as conn:
        new_row = conn.execute(
            "SELECT text, week_start, outcome, done FROM objectives WHERE id = ?",
            (res["new_id"],),
        ).fetchone()
        old_row = conn.execute(
            "SELECT outcome FROM objectives WHERE id = ?", (orig["id"],)
        ).fetchone()
    assert new_row["text"] == "Leer 100 páginas"
    assert new_row["week_start"] == "2026-05-25"
    assert new_row["outcome"] is None
    assert new_row["done"] == 0
    assert old_row["outcome"] == "missed"


def test_discard_task_marks_missed():
    orig = tools.add_task("X", due_date="2026-05-20")
    res = tools.discard_task(orig["id"])
    assert res["updated"] == 1
    with db.connect() as conn:
        row = conn.execute(
            "SELECT outcome, done FROM tasks WHERE id = ?", (orig["id"],)
        ).fetchone()
    assert row["outcome"] == "missed"
    assert row["done"] == 0


def test_discard_event_marks_missed():
    orig = tools.add_event("Cita", "2026-05-20T10:00:00", "personal")
    tools.discard_event(orig["id"])
    with db.connect() as conn:
        row = conn.execute(
            "SELECT outcome, done FROM events WHERE id = ?", (orig["id"],)
        ).fetchone()
    assert row["outcome"] == "missed"
    assert row["done"] == 0


def test_discard_objective_marks_missed():
    orig = tools.add_objective("Meta vieja", "2026-05-11")
    tools.discard_objective(orig["id"])
    with db.connect() as conn:
        row = conn.execute(
            "SELECT outcome, done FROM objectives WHERE id = ?", (orig["id"],)
        ).fetchone()
    assert row["outcome"] == "missed"
    assert row["done"] == 0

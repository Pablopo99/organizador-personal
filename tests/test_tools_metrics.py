"""Tests de tools.metrics_summary."""
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


def test_empty_db_returns_zero_counts():
    m = tools.metrics_summary("2026-05-01", "2026-05-31")
    assert m["events"] == {"on_time": 0, "grace": 0, "missed": 0}
    assert m["tasks"] == {"on_time": 0, "grace": 0, "missed": 0}
    assert m["objectives"] == {"on_time": 0, "grace": 0, "missed": 0}
    assert m["routines"]["totals"] == {"on_time": 0, "grace": 0, "missed": 0}
    assert m["routines"]["per_event"] == []


def test_counts_tasks_by_outcome(monkeypatch):
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 30))
    a = tools.add_task("a", due_date="2026-05-30")
    b = tools.add_task("b", due_date="2026-05-30")
    c = tools.add_task("c", due_date="2026-05-29")  # ayer
    tools.complete_task(a["id"])  # on_time
    tools.complete_task(b["id"])  # on_time
    tools.complete_task(c["id"])  # grace
    # Tarea perdida manualmente:
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO tasks (text, done, created_at, due_date, outcome) "
            "VALUES ('d', 0, '2026-05-20T10:00:00', '2026-05-20', 'missed')"
        )

    m = tools.metrics_summary("2026-05-01", "2026-05-31")
    assert m["tasks"] == {"on_time": 2, "grace": 1, "missed": 1}


def test_counts_routines_per_event(monkeypatch):
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 30))
    r = tools.add_event(
        "Meditar", "2026-05-25T08:00:00", "personal", recurring_rule="DAILY"
    )
    with db.connect() as conn:
        for d, status in [
            ("2026-05-25", "on_time"),
            ("2026-05-26", "on_time"),
            ("2026-05-27", "grace"),
        ]:
            conn.execute(
                "INSERT INTO routine_completions (event_id, completion_date, created_at, status) "
                "VALUES (?, ?, ?, ?)",
                (r["id"], d, "2026-05-30T08:00:00", status),
            )

    m = tools.metrics_summary("2026-05-25", "2026-05-30")
    per_event = m["routines"]["per_event"]
    assert len(per_event) == 1
    item = per_event[0]
    assert item["title"] == "Meditar"
    assert item["on_time"] == 2
    assert item["grace"] == 1
    # 6 días scheduled - 3 completados = 3 missed
    assert item["missed"] == 3
    assert m["routines"]["totals"] == {"on_time": 2, "grace": 1, "missed": 3}

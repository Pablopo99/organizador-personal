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


def test_add_and_list_tasks_pending_only():
    a = tools.add_task("Comprar pan")
    b = tools.add_task("Llamar fontanero")
    tools.complete_task(a["id"])

    rows = tools.list_tasks(include_done=False)
    texts = [r["text"] for r in rows]
    assert texts == ["Llamar fontanero"]


def test_list_tasks_with_done():
    a = tools.add_task("X")
    tools.complete_task(a["id"])
    rows = tools.list_tasks(include_done=True)
    assert len(rows) == 1
    assert rows[0]["done"] == 1


def test_complete_task_returns_updated_count():
    a = tools.add_task("Y")
    res = tools.complete_task(a["id"])
    assert res["updated"] == 1


def test_complete_task_sets_done_at():
    a = tools.add_task("Z")
    tools.complete_task(a["id"])
    rows = tools.list_tasks(include_done=True)
    target = next(r for r in rows if r["id"] == a["id"])
    assert target["done"] == 1
    assert target["done_at"] is not None
    # Comprobamos que es un ISO date razonable (no vacío y se puede parsear)
    from datetime import datetime
    datetime.fromisoformat(target["done_at"])


def test_pending_task_has_no_done_at():
    a = tools.add_task("Pendiente")
    rows = tools.list_tasks()
    target = next(r for r in rows if r["id"] == a["id"])
    assert target["done"] == 0
    assert target["done_at"] is None


def test_uncomplete_task_resets_done_and_done_at():
    t = tools.add_task("comprar pan")
    tools.complete_task(t["id"])

    tools.uncomplete_task(t["id"])

    with db.connect() as conn:
        row = conn.execute(
            "SELECT done, done_at FROM tasks WHERE id = ?", (t["id"],)
        ).fetchone()
    assert row[0] == 0
    assert row[1] is None


def test_uncomplete_task_idempotent_when_pending():
    t = tools.add_task("comprar pan")
    tools.uncomplete_task(t["id"])

    with db.connect() as conn:
        row = conn.execute(
            "SELECT done FROM tasks WHERE id = ?", (t["id"],)
        ).fetchone()
    assert row[0] == 0


def test_add_task_with_due_date_persists_it():
    res = tools.add_task("Comprar pan", due_date="2026-06-05")
    with db.connect() as conn:
        row = conn.execute(
            "SELECT due_date FROM tasks WHERE id = ?", (res["id"],)
        ).fetchone()
    assert row["due_date"] == "2026-06-05"


def test_add_task_without_due_date_leaves_null():
    res = tools.add_task("Tarea flotante")
    with db.connect() as conn:
        row = conn.execute(
            "SELECT due_date FROM tasks WHERE id = ?", (res["id"],)
        ).fetchone()
    assert row["due_date"] is None


def test_complete_task_on_time_sets_outcome_on_time(monkeypatch):
    import date_utils
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 30))
    t = tools.add_task("X", due_date="2026-05-30")
    tools.complete_task(t["id"])
    with db.connect() as conn:
        row = conn.execute(
            "SELECT outcome FROM tasks WHERE id = ?", (t["id"],)
        ).fetchone()
    assert row["outcome"] == "on_time"


def test_complete_task_grace_when_one_day_late(monkeypatch):
    import date_utils
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 31))
    t = tools.add_task("Y", due_date="2026-05-30")
    tools.complete_task(t["id"])
    with db.connect() as conn:
        row = conn.execute(
            "SELECT outcome FROM tasks WHERE id = ?", (t["id"],)
        ).fetchone()
    assert row["outcome"] == "grace"


def test_complete_task_rejected_when_two_days_late(monkeypatch):
    import date_utils
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 6, 1))
    t = tools.add_task("Z", due_date="2026-05-30")
    res = tools.complete_task(t["id"])
    assert res.get("error") == "out_of_window"
    assert res.get("updated") == 0
    with db.connect() as conn:
        row = conn.execute(
            "SELECT done, outcome FROM tasks WHERE id = ?", (t["id"],)
        ).fetchone()
    assert row["done"] == 0
    assert row["outcome"] is None


def test_complete_task_floating_leaves_outcome_null(monkeypatch):
    import date_utils
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 30))
    t = tools.add_task("Flotante")
    tools.complete_task(t["id"])
    with db.connect() as conn:
        row = conn.execute(
            "SELECT done, outcome FROM tasks WHERE id = ?", (t["id"],)
        ).fetchone()
    assert row["done"] == 1
    assert row["outcome"] is None


def test_complete_task_inserts_xp_log(monkeypatch):
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 30))
    t = tools.add_task("A", due_date="2026-05-30")
    res = tools.complete_task(t["id"])
    assert res["xp_awarded"] == 10
    assert res["level_before"] == 0
    assert res["level_after"] == 0  # 10 XP < 30 → still level 0
    with db.connect() as conn:
        row = conn.execute(
            "SELECT xp_amount, item_type, outcome FROM xp_log "
            "WHERE item_id = ?",
            (t["id"],),
        ).fetchone()
    assert row["xp_amount"] == 10
    assert row["item_type"] == "task"
    assert row["outcome"] == "on_time"


def test_complete_task_grace_inserts_five_xp(monkeypatch):
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 31))
    t = tools.add_task("B", due_date="2026-05-30")
    res = tools.complete_task(t["id"])
    assert res["xp_awarded"] == 5


def test_complete_task_floating_no_xp(monkeypatch):
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 30))
    t = tools.add_task("Flotante")  # sin due_date
    res = tools.complete_task(t["id"])
    assert res["xp_awarded"] == 0
    assert tools._get_xp_total() == 0


def test_complete_task_out_of_window_no_xp(monkeypatch):
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 6, 5))
    t = tools.add_task("Tarde", due_date="2026-05-30")
    res = tools.complete_task(t["id"])
    assert res.get("error") == "out_of_window"
    assert tools._get_xp_total() == 0


def test_complete_task_level_up(monkeypatch):
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 30))
    # 3 tareas on_time = 30 XP = nivel 1
    for i in range(2):
        t = tools.add_task(f"T{i}", due_date="2026-05-30")
        tools.complete_task(t["id"])
    # Al completar la tercera, sube a nivel 1
    t = tools.add_task("T2", due_date="2026-05-30")
    res = tools.complete_task(t["id"])
    assert res["level_before"] == 0
    assert res["level_after"] == 1


def test_uncomplete_task_reverses_xp(monkeypatch):
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 30))
    t = tools.add_task("X", due_date="2026-05-30")
    tools.complete_task(t["id"])
    assert tools._get_xp_total() == 10
    tools.uncomplete_task(t["id"])
    assert tools._get_xp_total() == 0
    with db.connect() as conn:
        reversals = conn.execute(
            "SELECT COUNT(*) FROM xp_log WHERE outcome = 'reversal'"
        ).fetchone()[0]
    assert reversals == 1

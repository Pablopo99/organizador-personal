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

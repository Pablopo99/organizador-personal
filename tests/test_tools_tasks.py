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

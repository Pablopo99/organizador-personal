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


def test_add_objective_uses_monday_of_given_week():
    res = tools.add_objective("Terminar informe", week_start="2026-05-13")
    # 2026-05-13 es miércoles → debe normalizar a lunes 11
    assert res["week_start"] == "2026-05-11"


def test_query_objectives_by_week():
    tools.add_objective("Obj A", "2026-05-11")
    tools.add_objective("Obj B", "2026-05-11")
    tools.add_objective("Obj C", "2026-05-18")

    rows = tools.query_objectives("2026-05-11")
    assert len(rows) == 2
    titles = [r["text"] for r in rows]
    assert "Obj A" in titles
    assert "Obj B" in titles


def test_query_objectives_all_when_no_week():
    tools.add_objective("X", "2026-05-11")
    tools.add_objective("Y", "2026-05-18")
    rows = tools.query_objectives(None)
    assert len(rows) == 2


def test_mark_objective_done():
    res = tools.add_objective("Hacer X", "2026-05-11")
    tools.mark_objective_done(res["id"])
    rows = tools.query_objectives("2026-05-11")
    assert rows[0]["done"] == 1


def test_unmark_objective_done_sets_done_zero():
    o = tools.add_objective("Terminar pres", "2026-05-18")
    tools.mark_objective_done(o["id"])

    tools.unmark_objective_done(o["id"])

    with db.connect() as conn:
        row = conn.execute(
            "SELECT done FROM objectives WHERE id = ?", (o["id"],)
        ).fetchone()
    assert row[0] == 0


def test_unmark_objective_done_idempotent():
    o = tools.add_objective("Terminar pres", "2026-05-18")
    tools.unmark_objective_done(o["id"])

    with db.connect() as conn:
        row = conn.execute(
            "SELECT done FROM objectives WHERE id = ?", (o["id"],)
        ).fetchone()
    assert row[0] == 0

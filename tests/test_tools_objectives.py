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


def test_mark_objective_done(monkeypatch):
    # Monkeypatch today to be within the week of 2026-05-11 (lunes).
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 15))
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


def test_mark_objective_on_time(monkeypatch):
    # 2026-05-25 es lunes; semana actual.
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 28))
    o = tools.add_objective("Leer 100 páginas", "2026-05-25")
    tools.mark_objective_done(o["id"])
    with db.connect() as conn:
        row = conn.execute(
            "SELECT done, outcome FROM objectives WHERE id = ?", (o["id"],)
        ).fetchone()
    assert row["done"] == 1
    assert row["outcome"] == "on_time"


def test_mark_objective_grace_next_week(monkeypatch):
    # Objetivo de la semana del 18-may; hoy es 28-may (jueves de la semana siguiente).
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 28))
    o = tools.add_objective("Leer 100 páginas", "2026-05-18")
    tools.mark_objective_done(o["id"])
    with db.connect() as conn:
        row = conn.execute(
            "SELECT done, outcome FROM objectives WHERE id = ?", (o["id"],)
        ).fetchone()
    assert row["done"] == 1
    assert row["outcome"] == "grace"


def test_mark_objective_rejected_two_weeks_late(monkeypatch):
    # Objetivo de la semana del 11-may; hoy 28-may (2 semanas más tarde).
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 28))
    o = tools.add_objective("Leer", "2026-05-11")
    out = tools.mark_objective_done(o["id"])
    assert out.get("error") == "out_of_window"
    with db.connect() as conn:
        row = conn.execute(
            "SELECT done, outcome FROM objectives WHERE id = ?", (o["id"],)
        ).fetchone()
    assert row["done"] == 0
    assert row["outcome"] is None


def test_mark_objective_done_inserts_xp_on_time(monkeypatch):
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 28))
    o = tools.add_objective("Meta", "2026-05-25")
    out = tools.mark_objective_done(o["id"])
    assert out["xp_awarded"] == 50
    assert out["outcome"] == "on_time"


def test_mark_objective_done_inserts_xp_grace(monkeypatch):
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 28))
    o = tools.add_objective("Meta", "2026-05-18")
    out = tools.mark_objective_done(o["id"])
    assert out["xp_awarded"] == 25
    assert out["outcome"] == "grace"


def test_mark_objective_done_out_of_window_no_xp(monkeypatch):
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 28))
    o = tools.add_objective("Meta", "2026-05-11")
    out = tools.mark_objective_done(o["id"])
    assert out.get("error") == "out_of_window"
    assert tools._get_xp_total() == 0


def test_unmark_objective_done_reverses_xp(monkeypatch):
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 28))
    o = tools.add_objective("Meta", "2026-05-25")
    tools.mark_objective_done(o["id"])
    assert tools._get_xp_total() == 50
    tools.unmark_objective_done(o["id"])
    assert tools._get_xp_total() == 0


def test_delete_objective_existing():
    o = tools.add_objective("Leer 2 libros", "2026-06-08")
    result = tools.delete_objective(o["id"])
    assert result["deleted"] == 1
    assert tools.query_objectives(None) == []


def test_delete_objective_not_found():
    result = tools.delete_objective(99999)
    assert result["deleted"] == 0

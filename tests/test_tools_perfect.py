"""Tests de día perfecto y semana perfecta."""
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


def test_perfect_day_no_items_no_bonus(monkeypatch):
    """Sin nada programado: no es perfecto."""
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 30))
    # Sin rutinas, tareas ni eventos. Forzamos la comprobación llamando
    # complete_task sobre una tarea flotante (no afecta).
    t = tools.add_task("Flotante")
    tools.complete_task(t["id"])
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT COUNT(*) FROM xp_log WHERE item_type='perfect_day'"
        ).fetchone()[0]
    assert rows == 0


def test_perfect_day_awarded_when_task_today_completed(monkeypatch):
    """Una sola tarea con due_date=hoy, completada → día perfecto."""
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 30))
    t = tools.add_task("Hoy", due_date="2026-05-30")
    res = tools.complete_task(t["id"])
    assert res.get("perfect_day_bonus") == 20
    with db.connect() as conn:
        row = conn.execute(
            "SELECT xp_amount FROM xp_log WHERE item_type='perfect_day'"
        ).fetchone()
    assert row["xp_amount"] == 20


def test_perfect_day_not_awarded_with_pending_task(monkeypatch):
    """Si queda una tarea de hoy sin hacer, NO es perfecto."""
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 30))
    t1 = tools.add_task("A", due_date="2026-05-30")
    tools.add_task("B", due_date="2026-05-30")  # queda pendiente
    res = tools.complete_task(t1["id"])
    assert res.get("perfect_day_bonus") == 0


def test_perfect_day_idempotent(monkeypatch):
    """No se otorga dos veces el mismo día."""
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 30))
    t1 = tools.add_task("A", due_date="2026-05-30")
    t2 = tools.add_task("B", due_date="2026-05-30")
    tools.complete_task(t1["id"])
    tools.complete_task(t2["id"])
    with db.connect() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM xp_log WHERE item_type='perfect_day'"
        ).fetchone()[0]
    assert count == 1


def test_perfect_day_requires_all_routines_done(monkeypatch):
    """Rutinas esperadas hoy también cuentan."""
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 30))
    r = tools.add_event(
        "Meditar", "2026-05-25T08:00:00", "personal", recurring_rule="DAILY"
    )
    t = tools.add_task("Hoy", due_date="2026-05-30")
    # Solo completamos la tarea, la rutina queda pendiente
    tools.complete_task(t["id"])
    with db.connect() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM xp_log WHERE item_type='perfect_day'"
        ).fetchone()[0]
    assert count == 0
    # Ahora marcamos la rutina
    tools.mark_event_done(r["id"])
    with db.connect() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM xp_log WHERE item_type='perfect_day'"
        ).fetchone()[0]
    assert count == 1


def test_perfect_week_all_objectives_done(monkeypatch):
    """Lunes con los 3 objetivos de la semana pasada done=1 on_time → +100 XP."""
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 6, 1))
    # 2026-06-01 es lunes; la semana pasada empezó el 2026-05-25 (lunes)
    o1 = tools.add_objective("A", "2026-05-25")
    o2 = tools.add_objective("B", "2026-05-25")
    o3 = tools.add_objective("C", "2026-05-25")
    # Marcamos los 3 como on_time (forzando fecha previa)
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 28))
    tools.mark_objective_done(o1["id"])
    tools.mark_objective_done(o2["id"])
    tools.mark_objective_done(o3["id"])
    # Ahora es lunes 1 jun y evaluamos
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 6, 1))
    with db.connect() as conn:
        bonus = tools._check_and_award_perfect_week(conn, date(2026, 6, 1))
    assert bonus == 100
    with db.connect() as conn:
        row = conn.execute(
            "SELECT xp_amount FROM xp_log WHERE item_type='perfect_week'"
        ).fetchone()
    assert row["xp_amount"] == 100


def test_perfect_week_incomplete_no_bonus(monkeypatch):
    """Si falta algún objetivo, no se otorga."""
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 28))
    o1 = tools.add_objective("A", "2026-05-25")
    tools.add_objective("B", "2026-05-25")  # queda sin marcar
    tools.mark_objective_done(o1["id"])
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 6, 1))
    with db.connect() as conn:
        bonus = tools._check_and_award_perfect_week(conn, date(2026, 6, 1))
    assert bonus == 0


def test_perfect_week_no_objectives_no_bonus(monkeypatch):
    """Si la semana pasada no tenía objetivos, no aplica."""
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 6, 1))
    with db.connect() as conn:
        bonus = tools._check_and_award_perfect_week(conn, date(2026, 6, 1))
    assert bonus == 0


def test_perfect_week_idempotent(monkeypatch):
    """Dos llamadas el mismo lunes → solo una fila."""
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 28))
    o = tools.add_objective("A", "2026-05-25")
    tools.mark_objective_done(o["id"])
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 6, 1))
    with db.connect() as conn:
        tools._check_and_award_perfect_week(conn, date(2026, 6, 1))
        tools._check_and_award_perfect_week(conn, date(2026, 6, 1))
        count = conn.execute(
            "SELECT COUNT(*) FROM xp_log WHERE item_type='perfect_week'"
        ).fetchone()[0]
    assert count == 1

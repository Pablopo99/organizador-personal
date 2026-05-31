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

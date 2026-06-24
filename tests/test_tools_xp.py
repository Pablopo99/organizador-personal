"""Tests de helpers puros del sistema XP/niveles."""
import os
import tempfile

import pytest

import db
import tools


# _calculate_xp(item_type, outcome, streak_after=0) -> (xp_amount, streak_bonus)

def test_calculate_xp_task_on_time():
    xp, bonus = tools._calculate_xp("task", "on_time")
    assert xp == 10
    assert bonus == 0


def test_calculate_xp_task_grace():
    xp, bonus = tools._calculate_xp("task", "grace")
    assert xp == 5
    assert bonus == 0


def test_calculate_xp_event_on_time():
    xp, bonus = tools._calculate_xp("event", "on_time")
    assert xp == 10
    assert bonus == 0


def test_calculate_xp_event_grace():
    xp, bonus = tools._calculate_xp("event", "grace")
    assert xp == 5
    assert bonus == 0


def test_calculate_xp_routine_on_time_no_streak():
    xp, bonus = tools._calculate_xp("routine", "on_time", streak_after=0)
    assert xp == 5
    assert bonus == 0


def test_calculate_xp_routine_on_time_streak_one():
    xp, bonus = tools._calculate_xp("routine", "on_time", streak_after=1)
    assert xp == 6
    assert bonus == 1


def test_calculate_xp_routine_on_time_streak_seven():
    xp, bonus = tools._calculate_xp("routine", "on_time", streak_after=7)
    assert xp == 12
    assert bonus == 7


def test_calculate_xp_routine_on_time_streak_capped():
    xp, bonus = tools._calculate_xp("routine", "on_time", streak_after=14)
    assert xp == 12
    assert bonus == 7


def test_calculate_xp_routine_grace_with_streak():
    xp, bonus = tools._calculate_xp("routine", "grace", streak_after=3)
    assert xp == 5
    assert bonus == 3


def test_calculate_xp_objective_on_time():
    xp, bonus = tools._calculate_xp("objective", "on_time")
    assert xp == 50
    assert bonus == 0


def test_calculate_xp_objective_grace():
    xp, bonus = tools._calculate_xp("objective", "grace")
    assert xp == 25
    assert bonus == 0


# compute_level(xp_total) -> int

def test_compute_level_zero():
    assert tools.compute_level(0) == 0


def test_compute_level_below_first():
    assert tools.compute_level(29) == 0


def test_compute_level_exactly_first():
    assert tools.compute_level(30) == 1


def test_compute_level_just_below_second():
    assert tools.compute_level(79) == 1


def test_compute_level_exactly_second():
    assert tools.compute_level(80) == 2


def test_compute_level_ten():
    assert tools.compute_level(1200) == 10


def test_compute_level_below_ten():
    # nivel 10 = 1200; nivel 9 = 990
    assert tools.compute_level(1199) == 9


# medal_for_level(level) -> str

def test_medal_level_zero_no_medal():
    assert tools.medal_for_level(0) == ""


def test_medal_bronze():
    for lv in (1, 3, 5):
        assert tools.medal_for_level(lv) == "🥉"


def test_medal_silver():
    for lv in (6, 10, 15):
        assert tools.medal_for_level(lv) == "🥈"


def test_medal_gold():
    for lv in (16, 25, 30):
        assert tools.medal_for_level(lv) == "🥇"


def test_medal_diamond():
    for lv in (31, 50, 60):
        assert tools.medal_for_level(lv) == "💎"


def test_medal_crown():
    for lv in (61, 100, 999):
        assert tools.medal_for_level(lv) == "👑"


# _insert_xp_log / _get_xp_total — persistence helpers

@pytest.fixture
def temp_db(monkeypatch):
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init_schema()
    yield path
    os.unlink(path)


def test_get_xp_total_empty_db(temp_db):
    assert tools._get_xp_total() == 0


def test_insert_xp_log_and_get_total(temp_db):
    with db.connect() as conn:
        tools._insert_xp_log(
            conn, "task", 1, "on_time",
            xp_amount=10, streak_bonus=0,
        )
    assert tools._get_xp_total() == 10


def test_insert_xp_log_negative_for_reversal(temp_db):
    with db.connect() as conn:
        tools._insert_xp_log(
            conn, "task", 1, "on_time", xp_amount=10, streak_bonus=0,
        )
        tools._insert_xp_log(
            conn, "task", 1, "reversal", xp_amount=-10, streak_bonus=0,
        )
    assert tools._get_xp_total() == 0


def test_insert_xp_log_stores_streak_bonus(temp_db):
    with db.connect() as conn:
        tools._insert_xp_log(
            conn, "routine", 1, "on_time",
            xp_amount=12, streak_bonus=7,
        )
        row = conn.execute(
            "SELECT streak_bonus FROM xp_log WHERE item_id = 1"
        ).fetchone()
    assert row["streak_bonus"] == 7


def test_e2e_completar_y_subir_nivel(monkeypatch, temp_db):
    """Smoke: marcar varias acciones acumula XP correctamente."""
    from datetime import date
    import date_utils
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 30))
    # Tarea bloqueadora que queda pendiente para que no se otorgue día perfecto
    tools.add_task("bloqueador", due_date="2026-05-30")
    # 3 tareas on_time = 30 XP = nivel 1
    for i in range(3):
        t = tools.add_task(f"T{i}", due_date="2026-05-30")
        tools.complete_task(t["id"])
    assert tools._get_xp_total() == 30
    assert tools.compute_level(tools._get_xp_total()) == 1
    # 1 objetivo on_time = +50 XP = 80 = nivel 2
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 28))
    o = tools.add_objective("O", "2026-05-25")
    tools.mark_objective_done(o["id"])
    assert tools._get_xp_total() == 80
    assert tools.compute_level(tools._get_xp_total()) == 2


def test_uncomplete_recomplete_uncomplete_no_xp_leak(monkeypatch, temp_db):
    """Una tarea marcada → desmarcada → re-marcada → desmarcada otra vez
    debe acabar con XP = 0 (cada complete inserta +10; cada uncomplete -10)."""
    from datetime import date
    import date_utils
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 30))
    # Tarea bloqueadora para evitar día perfecto
    tools.add_task("bloqueador", due_date="2026-05-30")
    t = tools.add_task("ciclo", due_date="2026-05-30")

    tools.complete_task(t["id"])
    assert tools._get_xp_total() == 10
    tools.uncomplete_task(t["id"])
    assert tools._get_xp_total() == 0
    tools.complete_task(t["id"])
    assert tools._get_xp_total() == 10
    tools.uncomplete_task(t["id"])
    assert tools._get_xp_total() == 0

    # Sanidad: dos ganancias y dos reversiones, nada más
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT outcome, xp_amount FROM xp_log "
            "WHERE item_type = 'task' AND item_id = ? "
            "ORDER BY id",
            (t["id"],),
        ).fetchall()
    assert [r["xp_amount"] for r in rows] == [10, -10, 10, -10]
    assert [r["outcome"] for r in rows] == [
        "on_time", "reversal", "on_time", "reversal"
    ]


# ---- Fix #2: la reversión de XP es idempotente (doble desmarcado) ----

def test_uncomplete_task_twice_reverts_once(monkeypatch, temp_db):
    import date_utils
    from datetime import date
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 30))
    t = tools.add_task("A", due_date="2026-05-30")
    tools.complete_task(t["id"])
    total_after_complete = tools._get_xp_total()
    tools.uncomplete_task(t["id"])
    total_after_uncomplete = tools._get_xp_total()
    # segundo desmarcado NO debe volver a restar
    tools.uncomplete_task(t["id"])
    assert tools._get_xp_total() == total_after_uncomplete
    assert total_after_uncomplete < total_after_complete


def test_unmark_objective_twice_reverts_once(monkeypatch, temp_db):
    import date_utils
    from datetime import date
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 28))
    o = tools.add_objective("Meta", "2026-05-25")
    tools.mark_objective_done(o["id"])
    assert tools._get_xp_total() == 50
    tools.unmark_objective_done(o["id"])
    tools.unmark_objective_done(o["id"])
    assert tools._get_xp_total() == 0


# ---- Fix #1: el bonus de día perfecto se revierte si el día deja de serlo ----

def test_perfect_day_bonus_reverted_on_uncomplete(monkeypatch, temp_db):
    import date_utils
    from datetime import date
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 30))
    # Único item del día: una tarea. Completarla = día perfecto (+10 +20).
    t = tools.add_task("Única", due_date="2026-05-30")
    res = tools.complete_task(t["id"])
    assert res["perfect_day_bonus"] == 20
    assert tools._get_xp_total() == 30
    # Al desmarcar, el día ya no es perfecto → se revierte tarea (-10) Y bonus (-20)
    tools.uncomplete_task(t["id"])
    assert tools._get_xp_total() == 0


def test_perfect_day_rewarded_again_after_revert(monkeypatch, temp_db):
    """Tras revertir el día perfecto, volver a completar lo re-otorga."""
    import date_utils
    from datetime import date
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 30))
    t = tools.add_task("Única", due_date="2026-05-30")
    tools.complete_task(t["id"])
    tools.uncomplete_task(t["id"])
    assert tools._get_xp_total() == 0
    res = tools.complete_task(t["id"])
    assert res["perfect_day_bonus"] == 20
    assert tools._get_xp_total() == 30


def test_perfect_day_not_reverted_if_still_perfect(monkeypatch, temp_db):
    """Si tras desmarcar un ítem el día SIGUE siendo perfecto (quedan otros
    completados y nada pendiente), el bonus no debe revertirse indebidamente."""
    import date_utils
    from datetime import date
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 30))
    # Dos tareas hoy; completar ambas = día perfecto.
    a = tools.add_task("A", due_date="2026-05-30")
    b = tools.add_task("B", due_date="2026-05-30")
    tools.complete_task(a["id"])
    tools.complete_task(b["id"])  # aquí se otorga el día perfecto
    # desmarcar B deja B pendiente → el día deja de ser perfecto → revierte bonus
    tools.uncomplete_task(b["id"])
    # queda: A=+10 (sin bonus). Total 10.
    assert tools._get_xp_total() == 10

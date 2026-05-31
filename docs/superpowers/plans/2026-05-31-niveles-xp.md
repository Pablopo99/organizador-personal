# Niveles y XP — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implementar una capa de progresión irreversible (XP + niveles + medallas) encima del juego de gracia/missed ya existente.

**Architecture:** Una sola tabla nueva `xp_log` append-only. Helpers puros para cálculo de XP y nivel. Hooks dentro de cada `complete_*` / `mark_*_done` / `uncomplete_*` para insertar/revertir XP. Bonus de día perfecto disparado tras cada marcado; bonus de semana perfecta evaluado en `morning_summary` del lunes. Línea de cabecera en todas las vistas determinísticas. Comando `/nivel` con vista dedicada. Notificación aparte al subir nivel.

**Tech Stack:** Python 3, SQLite, python-telegram-bot 21, pytest + pytest-asyncio. Spec completa en `docs/superpowers/specs/2026-05-31-niveles-xp-design.md`.

---

## File structure

**Modificados:**
- `db.py` — añadir migración para tabla `xp_log` + índice.
- `tools.py` — helpers puros (`_calculate_xp`, `compute_level`, `medal_for_level`, `_insert_xp_log`, `_get_xp_total`, `_check_and_award_perfect_day`); modificar `complete_task`, `mark_event_done`, `mark_objective_done`, `uncomplete_task`, `unmark_event_done`, `uncomplete_routine_today`, `unmark_objective_done`.
- `scheduler.py` — `morning_summary` evalúa semana perfecta los lunes (`_check_and_award_perfect_week`).
- `views.py` — helper `_render_level_header` prependeado en `render_today_view`, `render_tomorrow_view`, `render_pending_view`, `render_week_view`, `render_metrics_view`; nuevo `render_nivel_view`.
- `bot.py` — handler `_on_nivel`; `BotCommand("nivel", ...)` en `_set_bot_commands`; lógica de detectar subida de nivel y enviar mensaje aparte en `_on_callback_query` y `_on_message`.
- `brain.py` — registrar `level_before/level_after` cuando una tool devuelve esos campos, vía `record_level_up`.

**Nuevos tests:**
- `tests/test_tools_xp.py` — tests de helpers puros (`_calculate_xp`, `compute_level`, `medal_for_level`).
- `tests/test_tools_perfect.py` — tests de día perfecto y semana perfecta.

**Tests modificados:**
- `tests/test_db.py` — verificar tabla `xp_log`.
- `tests/test_tools_tasks.py` — `complete_task` retorna `xp_awarded`, reversión.
- `tests/test_tools_events.py` — `mark_event_done` puntual y rutina con xp y bonus de racha; reversión.
- `tests/test_tools_objectives.py` — `mark_objective_done` retorna xp; reversión.
- `tests/test_views.py` — cabecera de nivel en cada vista; render de `/nivel`.
- `tests/test_bot.py` — `/nivel` handler; subida de nivel envía mensaje aparte.
- `tests/test_scheduler.py` — semana perfecta en `morning_summary` del lunes.

**Comando para correr la suite:**

```bash
./.venv/bin/python -m pytest
```

Para tests específicos:

```bash
./.venv/bin/python -m pytest tests/test_tools_xp.py -v
./.venv/bin/python -m pytest -k "xp or level or perfect"
```

**Convención de fechas en tests**: patchear `date_utils.today_madrid` (no `tools.now_iso` porque está importado por nombre). Si un test necesita controlar `now_iso`, patchear `date_utils.now_iso` (las funciones nuevas lo usan via `date_utils.now_iso()`).

---

## Task 1: Migración de esquema `xp_log`

**Files:**
- Modify: `db.py:70-160` (función `_migrate`) y `db.py:8-90` (`_SCHEMA`)
- Test: `tests/test_db.py`

- [ ] **Step 1: Escribir tests fallidos**

Añadir al final de `tests/test_db.py`:

```python
def test_xp_log_table_exists(fresh_db):
    with db.connect() as conn:
        cols = [r[1] for r in conn.execute(
            "PRAGMA table_info(xp_log)"
        ).fetchall()]
    assert "item_type" in cols
    assert "item_id" in cols
    assert "outcome" in cols
    assert "xp_amount" in cols
    assert "streak_bonus" in cols
    assert "awarded_at" in cols


def test_xp_log_default_item_id_is_zero(fresh_db):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO xp_log (item_type, outcome, xp_amount, awarded_at) "
            "VALUES ('perfect_day', 'bonus', 20, '2026-05-31T22:00:00')"
        )
        row = conn.execute(
            "SELECT item_id FROM xp_log WHERE item_type='perfect_day'"
        ).fetchone()
    assert row["item_id"] == 0
```

- [ ] **Step 2: Verificar que fallan**

```
./.venv/bin/python -m pytest tests/test_db.py -v -k "xp_log"
```

Esperado: FAIL con `no such table: xp_log`.

- [ ] **Step 3: Añadir la migración en `db.py`**

En la función `_migrate(conn)`, antes de la línea final, añadir:

```python
    if "xp_log" not in tables:
        conn.execute("""
            CREATE TABLE xp_log (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                item_type     TEXT    NOT NULL,
                item_id       INTEGER NOT NULL DEFAULT 0,
                outcome       TEXT    NOT NULL,
                xp_amount     INTEGER NOT NULL,
                streak_bonus  INTEGER NOT NULL DEFAULT 0,
                awarded_at    TEXT    NOT NULL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_xp_log_awarded_at
                ON xp_log(awarded_at)
        """)
```

Y en `_SCHEMA` (el string al inicio de `db.py`), añadir antes del cierre triple-comilla:

```sql

CREATE TABLE IF NOT EXISTS xp_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    item_type     TEXT    NOT NULL,
    item_id       INTEGER NOT NULL DEFAULT 0,
    outcome       TEXT    NOT NULL,
    xp_amount     INTEGER NOT NULL,
    streak_bonus  INTEGER NOT NULL DEFAULT 0,
    awarded_at    TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_xp_log_awarded_at
    ON xp_log(awarded_at);
```

- [ ] **Step 4: Verificar que pasan**

```
./.venv/bin/python -m pytest tests/test_db.py -v
```

Esperado: PASS en todos.

- [ ] **Step 5: Correr suite**

```
./.venv/bin/python -m pytest
```

- [ ] **Step 6: Commit**

```
git add db.py tests/test_db.py
git commit -m "$(cat <<'EOF'
feat(db): migración para tabla xp_log

Tabla append-only para registrar todas las ganancias y reversiones
de XP. Base para el sistema de niveles. Migración idempotente.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Helpers puros `_calculate_xp`, `compute_level`, `medal_for_level`

**Files:**
- Modify: `tools.py` (añadir helpers antes de la sección `# ---- events ----`)
- Create: `tests/test_tools_xp.py`

- [ ] **Step 1: Crear `tests/test_tools_xp.py`**

```python
"""Tests de helpers puros del sistema XP/niveles."""
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
```

- [ ] **Step 2: Verificar que fallan**

```
./.venv/bin/python -m pytest tests/test_tools_xp.py -v
```

Esperado: FAIL con `AttributeError: module 'tools' has no attribute '_calculate_xp'`.

- [ ] **Step 3: Añadir helpers en `tools.py`**

Justo antes del comentario `# ---- events ----` (que está alrededor de la línea 37 después de `_calculate_outcome`), añadir:

```python
# ----------------------------------------------------------------- xp ----

_XP_BASE = {
    "task":      {"on_time": 10, "grace":  5},
    "event":     {"on_time": 10, "grace":  5},
    "routine":   {"on_time":  5, "grace":  2},
    "objective": {"on_time": 50, "grace": 25},
}

_STREAK_BONUS_CAP = 7


def _calculate_xp(
    item_type: str,
    outcome: str,
    streak_after: int = 0,
) -> tuple[int, int]:
    """Devuelve (xp_amount, streak_bonus_component).

    Para rutinas, el bonus de racha = min(streak_after, 7).
    Para otros tipos, bonus = 0.
    """
    base = _XP_BASE[item_type][outcome]
    streak_bonus = 0
    if item_type == "routine":
        streak_bonus = min(max(streak_after, 0), _STREAK_BONUS_CAP)
    return base + streak_bonus, streak_bonus


def compute_level(xp_total: int) -> int:
    """Devuelve el nivel actual para un total de XP.

    Fórmula: XP_total_para_nivel_N = 10 * N * (N + 2).
    Nivel 0 = < 30 XP.
    """
    if xp_total < 30:
        return 0
    n = 1
    while 10 * (n + 1) * (n + 3) <= xp_total:
        n += 1
    return n


_MEDAL_RANGES = [
    (1, 5, "🥉"),
    (6, 15, "🥈"),
    (16, 30, "🥇"),
    (31, 60, "💎"),
]


def medal_for_level(level: int) -> str:
    """Devuelve el emoji de medalla para el nivel (vacío si nivel 0)."""
    if level <= 0:
        return ""
    for lo, hi, medal in _MEDAL_RANGES:
        if lo <= level <= hi:
            return medal
    return "👑"
```

- [ ] **Step 4: Verificar que pasan**

```
./.venv/bin/python -m pytest tests/test_tools_xp.py -v
```

Esperado: PASS en todos (24 tests).

- [ ] **Step 5: Suite**

```
./.venv/bin/python -m pytest
```

- [ ] **Step 6: Commit**

```
git add tools.py tests/test_tools_xp.py
git commit -m "$(cat <<'EOF'
feat(tools): helpers puros _calculate_xp, compute_level, medal_for_level

Tres funciones puras que encapsulan toda la lógica de cálculo del
sistema XP/niveles: cuánto XP da cada acción según outcome, qué
nivel corresponde a un total y qué medalla por tramo.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Helpers de persistencia `_insert_xp_log` y `_get_xp_total`

**Files:**
- Modify: `tools.py` (añadir tras los helpers de Task 2)
- Modify: `tests/test_tools_xp.py`

- [ ] **Step 1: Añadir tests al final de `tests/test_tools_xp.py`**

```python
import os
import tempfile

import pytest

import db


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
```

- [ ] **Step 2: Verificar que fallan**

```
./.venv/bin/python -m pytest tests/test_tools_xp.py -v -k "insert or get_total"
```

- [ ] **Step 3: Añadir helpers en `tools.py`**

Tras los helpers de Task 2 (después de `medal_for_level`):

```python
def _insert_xp_log(
    conn,
    item_type: str,
    item_id: int,
    outcome: str,
    xp_amount: int,
    streak_bonus: int = 0,
) -> None:
    """Inserta una fila en xp_log. Usar la misma `conn` que la operación
    principal para que todo esté en la misma transacción."""
    import date_utils
    conn.execute(
        """
        INSERT INTO xp_log
            (item_type, item_id, outcome, xp_amount, streak_bonus, awarded_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (item_type, item_id, outcome, xp_amount, streak_bonus, date_utils.now_iso()),
    )


def _get_xp_total() -> int:
    """Suma todos los xp_amount registrados (incluye reversiones)."""
    with db.connect() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(xp_amount), 0) AS total FROM xp_log"
        ).fetchone()
    return row["total"] or 0
```

- [ ] **Step 4: Verificar pass**

```
./.venv/bin/python -m pytest tests/test_tools_xp.py -v
```

- [ ] **Step 5: Suite**

```
./.venv/bin/python -m pytest
```

- [ ] **Step 6: Commit**

```
git add tools.py tests/test_tools_xp.py
git commit -m "$(cat <<'EOF'
feat(tools): helpers _insert_xp_log y _get_xp_total

Persistencia básica del sistema XP. _insert_xp_log opera sobre una
conn existente para coordinar con la transacción principal. _get_xp_total
suma todas las filas incluyendo reversiones.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `complete_task` y `uncomplete_task` con XP

**Files:**
- Modify: `tools.py` — `complete_task` y `uncomplete_task`
- Modify: `tests/test_tools_tasks.py`

- [ ] **Step 1: Añadir tests al final de `tests/test_tools_tasks.py`**

```python
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
```

- [ ] **Step 2: Verificar que fallan**

```
./.venv/bin/python -m pytest tests/test_tools_tasks.py -v -k "xp or level_up or reverses"
```

- [ ] **Step 3: Modificar `complete_task` en `tools.py`**

Reemplazar la función `complete_task` (alrededor de la línea ~575) por:

```python
def complete_task(task_id: int) -> dict:
    import date_utils

    today = date_utils.today_madrid()
    with db.connect() as conn:
        row = conn.execute(
            "SELECT due_date FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if row is None:
            return {"id": task_id, "updated": 0, "error": "not_found"}

        assigned = None
        if row["due_date"]:
            assigned = date.fromisoformat(row["due_date"])
            outcome = _calculate_outcome(assigned, today)
            if outcome is None:
                return {"id": task_id, "updated": 0, "error": "out_of_window"}
        else:
            outcome = None

        cur = conn.execute(
            "UPDATE tasks SET done = 1, done_at = ?, outcome = ? WHERE id = ?",
            (now_iso(), outcome, task_id),
        )

        # XP: solo si hay outcome (tareas flotantes no entran al juego)
        xp_awarded = 0
        level_before = compute_level(_get_xp_total_with_conn(conn))
        if outcome in ("on_time", "grace"):
            xp_awarded, _ = _calculate_xp("task", outcome)
            _insert_xp_log(conn, "task", task_id, outcome, xp_awarded)
        level_after = compute_level(_get_xp_total_with_conn(conn))

    return {
        "id": task_id,
        "updated": cur.rowcount,
        "outcome": outcome,
        "xp_awarded": xp_awarded,
        "level_before": level_before,
        "level_after": level_after,
    }
```

Y añadir un nuevo helper `_get_xp_total_with_conn` justo después de `_get_xp_total`:

```python
def _get_xp_total_with_conn(conn) -> int:
    """Versión de _get_xp_total que usa una conn existente (para
    operaciones dentro de la misma transacción)."""
    row = conn.execute(
        "SELECT COALESCE(SUM(xp_amount), 0) AS total FROM xp_log"
    ).fetchone()
    return row["total"] or 0
```

Reemplazar `uncomplete_task` (alrededor de la línea ~597) por:

```python
def uncomplete_task(task_id: int) -> dict:
    """Desmarca una tarea: done=0, done_at=NULL, outcome=NULL.
    Inserta una reversión en xp_log si había una ganancia previa."""
    with db.connect() as conn:
        cur = conn.execute(
            "UPDATE tasks SET done = 0, done_at = NULL, outcome = NULL "
            "WHERE id = ?",
            (task_id,),
        )
        # Buscar última fila xp_log para esta tarea no reversada
        original = conn.execute(
            "SELECT xp_amount FROM xp_log "
            "WHERE item_type = 'task' AND item_id = ? AND outcome != 'reversal' "
            "ORDER BY id DESC LIMIT 1",
            (task_id,),
        ).fetchone()
        if original and original["xp_amount"] > 0:
            _insert_xp_log(
                conn, "task", task_id, "reversal",
                xp_amount=-original["xp_amount"], streak_bonus=0,
            )
    return {"id": task_id, "updated": cur.rowcount}
```

- [ ] **Step 4: Verificar pass**

```
./.venv/bin/python -m pytest tests/test_tools_tasks.py -v
```

Si algún test antiguo falla porque no esperaba `xp_awarded` / `level_before` / `level_after` en el dict de retorno, actualizar para ignorar esos campos extra (el test pasa si comprueba lo que comprueba).

- [ ] **Step 5: Suite**

```
./.venv/bin/python -m pytest
```

- [ ] **Step 6: Commit**

```
git add tools.py tests/test_tools_tasks.py
git commit -m "$(cat <<'EOF'
feat(tools): complete_task otorga XP y uncomplete_task lo revierte

Las tareas con due_date dan 10 XP on_time / 5 XP grace; flotantes
y out_of_window no dan. Al desmarcar, se inserta una fila negativa
en xp_log para compensar. El retorno de complete_task incluye
xp_awarded, level_before y level_after.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `mark_event_done` con XP (puntuales y rutinas) y reversiones

**Files:**
- Modify: `tools.py` — `mark_event_done`, `unmark_event_done`, `uncomplete_routine_today`
- Modify: `tests/test_tools_events.py`

- [ ] **Step 1: Añadir tests al final de `tests/test_tools_events.py`**

```python
def test_mark_event_done_puntual_inserts_xp(monkeypatch):
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 30))
    res = tools.add_event("Cita", "2026-05-30T10:00:00", "personal")
    out = tools.mark_event_done(res["id"])
    assert out["xp_awarded"] == 10
    with db.connect() as conn:
        row = conn.execute(
            "SELECT xp_amount FROM xp_log WHERE item_type='event' AND item_id=?",
            (res["id"],),
        ).fetchone()
    assert row["xp_amount"] == 10


def test_mark_event_done_routine_with_streak_bonus(monkeypatch):
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 30))
    res = tools.add_event(
        "Meditar", "2026-05-25T08:00:00", "personal", recurring_rule="DAILY"
    )
    # Insertamos completions previas para construir racha
    with db.connect() as conn:
        for d in ["2026-05-25", "2026-05-26", "2026-05-27",
                  "2026-05-28", "2026-05-29"]:
            conn.execute(
                "INSERT INTO routine_completions "
                "(event_id, completion_date, created_at, status) "
                "VALUES (?, ?, ?, 'on_time')",
                (res["id"], d, "2026-05-30T08:00:00"),
            )
    # Hoy es día 6 de racha; tras marcar será día 6 → bonus +6
    out = tools.mark_event_done(res["id"])
    # XP base 5 + bonus 6 = 11
    assert out["xp_awarded"] == 11
    assert out["streak_bonus"] == 6


def test_mark_event_done_routine_streak_cap(monkeypatch):
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 30))
    res = tools.add_event(
        "Meditar", "2026-05-20T08:00:00", "personal", recurring_rule="DAILY"
    )
    with db.connect() as conn:
        # 9 completions previas (20-28); hoy 30. La 29 falta pero por ahora
        # forzamos 9 días seguidos terminando en 29.
        for d in ["2026-05-20", "2026-05-21", "2026-05-22", "2026-05-23",
                  "2026-05-24", "2026-05-25", "2026-05-26", "2026-05-27",
                  "2026-05-28", "2026-05-29"]:
            conn.execute(
                "INSERT INTO routine_completions "
                "(event_id, completion_date, created_at, status) "
                "VALUES (?, ?, ?, 'on_time')",
                (res["id"], d, "2026-05-30T08:00:00"),
            )
    out = tools.mark_event_done(res["id"])
    # 11 días seguidos = bonus capado en 7
    assert out["streak_bonus"] == 7
    assert out["xp_awarded"] == 12


def test_unmark_event_done_reverses_xp(monkeypatch):
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 30))
    res = tools.add_event("Cita", "2026-05-30T10:00:00", "personal")
    tools.mark_event_done(res["id"])
    assert tools._get_xp_total() == 10
    tools.unmark_event_done(res["id"])
    assert tools._get_xp_total() == 0


def test_uncomplete_routine_today_reverses_xp(monkeypatch):
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 30))
    res = tools.add_event(
        "Meditar", "2026-05-30T08:00:00", "personal", recurring_rule="DAILY"
    )
    out = tools.mark_event_done(res["id"])
    assert tools._get_xp_total() == out["xp_awarded"]
    tools.uncomplete_routine_today(res["id"])
    assert tools._get_xp_total() == 0
```

- [ ] **Step 2: Verificar que fallan**

```
./.venv/bin/python -m pytest tests/test_tools_events.py -v -k "xp or streak_cap or reverses_xp or routine_today_reverses"
```

- [ ] **Step 3: Modificar `mark_event_done` en `tools.py`**

Localizar `mark_event_done` (alrededor de la línea ~270 tras los cambios previos). Reemplazar por:

```python
def mark_event_done(event_id: int) -> dict:
    """Marca un evento como hecho con XP.

    Eventos puntuales -> done=1 + outcome + xp.
    Eventos recurrentes -> inserta routine_completions con status + xp.
    """
    import sqlite3
    import date_utils

    today = date_utils.today_madrid()

    with db.connect() as conn:
        row = conn.execute(
            "SELECT recurring_rule, datetime FROM events WHERE id = ?", (event_id,)
        ).fetchone()
        if row is None:
            return {"id": event_id, "updated": 0, "error": "not_found"}

        level_before = compute_level(_get_xp_total_with_conn(conn))

        if row["recurring_rule"]:
            rule = row["recurring_rule"]
            most_recent_expected = _most_recent_expected_date(rule, today)
            previous_expected = _previous_expected_date(rule, today)

            target_date = None
            status = None
            if most_recent_expected == today:
                target_date = today
                status = "on_time"
            elif (
                previous_expected is not None
                and (today - previous_expected).days == 1
            ):
                target_date = previous_expected
                status = "grace"
            else:
                return {"id": event_id, "updated": 0, "error": "out_of_window"}

            target_iso = target_date.isoformat()
            try:
                conn.execute(
                    """
                    INSERT INTO routine_completions (event_id, completion_date, created_at, status)
                    VALUES (?, ?, ?, ?)
                    """,
                    (event_id, target_iso, date_utils.now_iso(), status),
                )
            except sqlite3.IntegrityError:
                return {
                    "event_id": event_id,
                    "completion_date": target_iso,
                    "already_done": True,
                    "updated": 0,
                }

            # Calcular racha tras insertar (incluye la actual)
            streak_after = _current_streak(event_id, rule, today, conn)
            xp_amount, streak_bonus = _calculate_xp(
                "routine", status, streak_after=streak_after
            )
            _insert_xp_log(
                conn, "routine", event_id, status,
                xp_amount=xp_amount, streak_bonus=streak_bonus,
            )
            level_after = compute_level(_get_xp_total_with_conn(conn))

            return {
                "event_id": event_id,
                "completion_date": target_iso,
                "status": status,
                "updated": 1,
                "xp_awarded": xp_amount,
                "streak_bonus": streak_bonus,
                "level_before": level_before,
                "level_after": level_after,
            }

        # Evento puntual
        try:
            assigned = date.fromisoformat(row["datetime"][:10])
        except ValueError:
            return {"id": event_id, "updated": 0, "error": "bad_datetime"}

        outcome = _calculate_outcome(assigned, today)
        if outcome is None:
            return {"id": event_id, "updated": 0, "error": "out_of_window"}

        cur = conn.execute(
            "UPDATE events SET done = 1, outcome = ? WHERE id = ?",
            (outcome, event_id),
        )

        xp_amount, _ = _calculate_xp("event", outcome)
        _insert_xp_log(conn, "event", event_id, outcome, xp_amount)
        level_after = compute_level(_get_xp_total_with_conn(conn))

        return {
            "id": event_id,
            "updated": cur.rowcount,
            "outcome": outcome,
            "xp_awarded": xp_amount,
            "level_before": level_before,
            "level_after": level_after,
        }
```

Reemplazar `unmark_event_done`:

```python
def unmark_event_done(event_id: int) -> dict:
    """Quita el done=1 + outcome=NULL de un evento puntual. Revierte XP."""
    with db.connect() as conn:
        cur = conn.execute(
            "UPDATE events SET done = 0, outcome = NULL WHERE id = ?",
            (event_id,),
        )
        original = conn.execute(
            "SELECT xp_amount FROM xp_log "
            "WHERE item_type = 'event' AND item_id = ? AND outcome != 'reversal' "
            "ORDER BY id DESC LIMIT 1",
            (event_id,),
        ).fetchone()
        if original and original["xp_amount"] > 0:
            _insert_xp_log(
                conn, "event", event_id, "reversal",
                xp_amount=-original["xp_amount"], streak_bonus=0,
            )
    return {"id": event_id, "updated": cur.rowcount}
```

Reemplazar `uncomplete_routine_today`:

```python
def uncomplete_routine_today(event_id: int) -> dict:
    """Borra la completion de hoy (Madrid) para una rutina y revierte XP."""
    import date_utils
    today = date_utils.today_madrid().isoformat()
    with db.connect() as conn:
        cur = conn.execute(
            "DELETE FROM routine_completions "
            "WHERE event_id = ? AND completion_date = ?",
            (event_id, today),
        )
        if cur.rowcount > 0:
            # Revertir el XP de la última fila xp_log de esta rutina
            original = conn.execute(
                "SELECT xp_amount FROM xp_log "
                "WHERE item_type = 'routine' AND item_id = ? "
                "AND outcome != 'reversal' "
                "ORDER BY id DESC LIMIT 1",
                (event_id,),
            ).fetchone()
            if original and original["xp_amount"] > 0:
                _insert_xp_log(
                    conn, "routine", event_id, "reversal",
                    xp_amount=-original["xp_amount"], streak_bonus=0,
                )
    return {"event_id": event_id, "completion_date": today, "deleted": cur.rowcount}
```

- [ ] **Step 4: Verificar pass**

```
./.venv/bin/python -m pytest tests/test_tools_events.py -v
```

- [ ] **Step 5: Suite**

```
./.venv/bin/python -m pytest
```

Si algún test viejo de rutinas falla por el cambio de retorno (xp_awarded, level_*), actualizar para que no sean estrictos en el comparado de dict (`assert res.get("status") == "on_time"` en vez de comparar igualdad completa).

- [ ] **Step 6: Commit**

```
git add tools.py tests/test_tools_events.py
git commit -m "$(cat <<'EOF'
feat(tools): mark_event_done otorga XP con bonus de racha; reversiones

Eventos puntuales: 10 XP on_time / 5 XP grace. Rutinas: 5/2 XP +
min(racha, 7) de bonus. unmark_event_done y uncomplete_routine_today
insertan reversiones en xp_log.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: `mark_objective_done` y `unmark_objective_done` con XP

**Files:**
- Modify: `tools.py` — `mark_objective_done`, `unmark_objective_done`
- Modify: `tests/test_tools_objectives.py`

- [ ] **Step 1: Añadir tests al final de `tests/test_tools_objectives.py`**

```python
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
```

- [ ] **Step 2: Verificar que fallan**

```
./.venv/bin/python -m pytest tests/test_tools_objectives.py -v -k "xp or reverses"
```

- [ ] **Step 3: Modificar `mark_objective_done` y `unmark_objective_done` en `tools.py`**

Reemplazar `mark_objective_done` por:

```python
def mark_objective_done(objective_id: int) -> dict:
    from date_utils import monday_of_week
    import date_utils

    today = date_utils.today_madrid()
    today_monday = monday_of_week(today)

    with db.connect() as conn:
        row = conn.execute(
            "SELECT week_start FROM objectives WHERE id = ?", (objective_id,)
        ).fetchone()
        if row is None:
            return {"id": objective_id, "updated": 0, "error": "not_found"}

        week_start = date.fromisoformat(row["week_start"])
        weeks_diff = (today_monday - week_start).days // 7

        if weeks_diff <= 0:
            outcome = "on_time"
        elif weeks_diff == 1:
            outcome = "grace"
        else:
            return {"id": objective_id, "updated": 0, "error": "out_of_window"}

        level_before = compute_level(_get_xp_total_with_conn(conn))

        cur = conn.execute(
            "UPDATE objectives SET done = 1, outcome = ? WHERE id = ?",
            (outcome, objective_id),
        )

        xp_amount, _ = _calculate_xp("objective", outcome)
        _insert_xp_log(conn, "objective", objective_id, outcome, xp_amount)
        level_after = compute_level(_get_xp_total_with_conn(conn))

    return {
        "id": objective_id,
        "updated": cur.rowcount,
        "outcome": outcome,
        "xp_awarded": xp_amount,
        "level_before": level_before,
        "level_after": level_after,
    }
```

Reemplazar `unmark_objective_done`:

```python
def unmark_objective_done(objective_id: int) -> dict:
    """Desmarca un objetivo y revierte XP."""
    with db.connect() as conn:
        cur = conn.execute(
            "UPDATE objectives SET done = 0, outcome = NULL WHERE id = ?",
            (objective_id,),
        )
        original = conn.execute(
            "SELECT xp_amount FROM xp_log "
            "WHERE item_type = 'objective' AND item_id = ? "
            "AND outcome != 'reversal' "
            "ORDER BY id DESC LIMIT 1",
            (objective_id,),
        ).fetchone()
        if original and original["xp_amount"] > 0:
            _insert_xp_log(
                conn, "objective", objective_id, "reversal",
                xp_amount=-original["xp_amount"], streak_bonus=0,
            )
    return {"id": objective_id, "updated": cur.rowcount}
```

- [ ] **Step 4: Verificar pass**

```
./.venv/bin/python -m pytest tests/test_tools_objectives.py -v
```

- [ ] **Step 5: Suite**

```
./.venv/bin/python -m pytest
```

- [ ] **Step 6: Commit**

```
git add tools.py tests/test_tools_objectives.py
git commit -m "$(cat <<'EOF'
feat(tools): mark_objective_done otorga XP (50/25), unmark revierte

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Día perfecto (`_check_and_award_perfect_day`)

**Files:**
- Modify: `tools.py` — añadir helper + integrar en `complete_task` y `mark_event_done`
- Create: `tests/test_tools_perfect.py`

- [ ] **Step 1: Crear `tests/test_tools_perfect.py`**

```python
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
    # Solo el segundo dispara el perfect day. Si se intentara desmarcar y volver
    # a marcar, no debe duplicarse.
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
```

- [ ] **Step 2: Verificar que fallan**

```
./.venv/bin/python -m pytest tests/test_tools_perfect.py -v -k "perfect_day"
```

- [ ] **Step 3: Añadir helper en `tools.py`**

Después de los helpers de XP (y antes de `# ---- events ----` o donde tenga sentido), añadir:

```python
def _check_and_award_perfect_day(conn, today: date) -> int:
    """Comprueba si hoy es perfecto y, si lo es y aún no se ha otorgado,
    inserta la fila perfect_day y devuelve 20. Si no aplica, devuelve 0."""
    import date_utils
    today_iso = today.isoformat()

    # ¿Ya otorgado hoy?
    existing = conn.execute(
        "SELECT 1 FROM xp_log "
        "WHERE item_type = 'perfect_day' "
        "AND substr(awarded_at, 1, 10) = ?",
        (today_iso,),
    ).fetchone()
    if existing:
        return 0

    # Rutinas esperadas hoy
    routines = conn.execute(
        "SELECT id, recurring_rule FROM events WHERE recurring_rule IS NOT NULL"
    ).fetchall()
    expected_routine_ids = set()
    for r in routines:
        expected = _most_recent_expected_date(r["recurring_rule"], today)
        if expected == today:
            expected_routine_ids.add(r["id"])
    if expected_routine_ids:
        placeholders = ",".join(["?"] * len(expected_routine_ids))
        completed = conn.execute(
            f"SELECT event_id FROM routine_completions "
            f"WHERE completion_date = ? "
            f"AND event_id IN ({placeholders})",
            [today_iso, *expected_routine_ids],
        ).fetchall()
        completed_ids = {c["event_id"] for c in completed}
        if completed_ids != expected_routine_ids:
            return 0

    # Tareas con due_date=hoy pendientes
    pending_tasks = conn.execute(
        "SELECT COUNT(*) FROM tasks "
        "WHERE due_date = ? AND done = 0 "
        "AND (outcome IS NULL OR outcome != 'missed')",
        (today_iso,),
    ).fetchone()[0]
    if pending_tasks > 0:
        return 0

    # Eventos puntuales de hoy pendientes
    pending_events = conn.execute(
        "SELECT COUNT(*) FROM events "
        "WHERE recurring_rule IS NULL "
        "AND substr(datetime, 1, 10) = ? "
        "AND done = 0 "
        "AND (outcome IS NULL OR outcome != 'missed')",
        (today_iso,),
    ).fetchone()[0]
    if pending_events > 0:
        return 0

    # ¿Había algo evaluable hoy?
    total_today_tasks = conn.execute(
        "SELECT COUNT(*) FROM tasks WHERE due_date = ?",
        (today_iso,),
    ).fetchone()[0]
    total_today_events = conn.execute(
        "SELECT COUNT(*) FROM events "
        "WHERE recurring_rule IS NULL "
        "AND substr(datetime, 1, 10) = ?",
        (today_iso,),
    ).fetchone()[0]
    total_today = (
        len(expected_routine_ids) + total_today_tasks + total_today_events
    )
    if total_today == 0:
        return 0

    # Otorgar
    conn.execute(
        "INSERT INTO xp_log "
        "(item_type, item_id, outcome, xp_amount, streak_bonus, awarded_at) "
        "VALUES ('perfect_day', 0, 'bonus', 20, 0, ?)",
        (date_utils.now_iso(),),
    )
    return 20
```

- [ ] **Step 4: Integrar en `complete_task` y `mark_event_done`**

En `complete_task`, tras el `_insert_xp_log` y antes de calcular `level_after`, añadir:

```python
        # Comprobar día perfecto SOLO si esta marca dio XP (no flotante, no error)
        perfect_day_bonus = 0
        if xp_awarded > 0:
            perfect_day_bonus = _check_and_award_perfect_day(conn, today)
```

Y añadir al dict de retorno:
```python
        "perfect_day_bonus": perfect_day_bonus,
```

(El level_after debe recalcularse DESPUÉS de la posible inserción de perfect_day.)

En `mark_event_done`, hacer la misma integración. En la rama de evento puntual:

```python
        _insert_xp_log(conn, "event", event_id, outcome, xp_amount)
        perfect_day_bonus = _check_and_award_perfect_day(conn, today)
        level_after = compute_level(_get_xp_total_with_conn(conn))

        return {
            "id": event_id,
            "updated": cur.rowcount,
            "outcome": outcome,
            "xp_awarded": xp_amount,
            "level_before": level_before,
            "level_after": level_after,
            "perfect_day_bonus": perfect_day_bonus,
        }
```

En la rama de rutina (tras el `_insert_xp_log` para routine):

```python
            _insert_xp_log(
                conn, "routine", event_id, status,
                xp_amount=xp_amount, streak_bonus=streak_bonus,
            )
            perfect_day_bonus = _check_and_award_perfect_day(conn, today)
            level_after = compute_level(_get_xp_total_with_conn(conn))

            return {
                "event_id": event_id,
                "completion_date": target_iso,
                "status": status,
                "updated": 1,
                "xp_awarded": xp_amount,
                "streak_bonus": streak_bonus,
                "level_before": level_before,
                "level_after": level_after,
                "perfect_day_bonus": perfect_day_bonus,
            }
```

(NO integrar en `mark_objective_done` — los objetivos no influyen al día perfecto.)

- [ ] **Step 5: Verificar tests perfect_day**

```
./.venv/bin/python -m pytest tests/test_tools_perfect.py -v -k "perfect_day"
```

- [ ] **Step 6: Suite**

```
./.venv/bin/python -m pytest
```

- [ ] **Step 7: Commit**

```
git add tools.py tests/test_tools_perfect.py
git commit -m "$(cat <<'EOF'
feat(tools): bonus de día perfecto (+20 XP)

Cuando todas las rutinas esperadas, tareas con due_date=hoy y
eventos puntuales de hoy están en estado completado, se otorga
+20 XP. Idempotente por día. Integrado en complete_task y
mark_event_done; mark_objective_done NO lo evalúa.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Semana perfecta (`_check_and_award_perfect_week`) en `morning_summary`

**Files:**
- Modify: `scheduler.py` — `morning_summary` evalúa semana perfecta los lunes
- Modify: `tools.py` — añadir helper `_check_and_award_perfect_week`
- Modify: `tests/test_tools_perfect.py`

- [ ] **Step 1: Añadir tests al final de `tests/test_tools_perfect.py`**

```python
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
```

- [ ] **Step 2: Verificar que fallan**

```
./.venv/bin/python -m pytest tests/test_tools_perfect.py -v -k "perfect_week"
```

- [ ] **Step 3: Añadir `_check_and_award_perfect_week` en `tools.py`**

Tras `_check_and_award_perfect_day`:

```python
def _check_and_award_perfect_week(conn, today: date) -> int:
    """Evalúa la semana pasada (lunes-domingo) y otorga +100 XP si todos
    los objetivos fueron done con outcome on_time/grace. Llamar solo en lunes."""
    from datetime import timedelta
    from date_utils import monday_of_week
    import date_utils

    last_monday = monday_of_week(today) - timedelta(days=7)
    last_monday_iso = last_monday.isoformat()

    # Ya otorgado hoy
    existing = conn.execute(
        "SELECT 1 FROM xp_log "
        "WHERE item_type = 'perfect_week' "
        "AND substr(awarded_at, 1, 10) = ?",
        (today.isoformat(),),
    ).fetchone()
    if existing:
        return 0

    objs = conn.execute(
        "SELECT done, outcome FROM objectives WHERE week_start = ?",
        (last_monday_iso,),
    ).fetchall()
    if not objs:
        return 0
    all_done = all(
        o["done"] == 1 and o["outcome"] in ("on_time", "grace")
        for o in objs
    )
    if not all_done:
        return 0

    conn.execute(
        "INSERT INTO xp_log "
        "(item_type, item_id, outcome, xp_amount, streak_bonus, awarded_at) "
        "VALUES ('perfect_week', 0, 'bonus', 100, 0, ?)",
        (date_utils.now_iso(),),
    )
    return 100
```

- [ ] **Step 4: Integrar en `morning_summary` de `scheduler.py`**

Modificar `morning_summary` para que, antes de generar el bloque semanal (que ya existe del feature anterior), evalúe perfect_week:

```python
    # Bloque semanal solo los lunes
    weekly_block = ""
    perfect_week_awarded = 0
    if today.weekday() == 0:
        last_monday = today - _td(days=7)
        last_sunday = today - _td(days=1)
        try:
            with db.connect() as conn:
                perfect_week_awarded = _tools._check_and_award_perfect_week(
                    conn, today
                )
            m = _tools.metrics_summary(
                last_monday.isoformat(), last_sunday.isoformat()
            )
            weekly_block = _format_weekly_block(m)
            if perfect_week_awarded > 0:
                weekly_block += (
                    "   🏆 ¡Semana perfecta! +100 XP\n\n"
                )
        except Exception:
            log.exception("Error generando bloque semanal del lunes")
            weekly_block = ""
```

(`_tools` ya está importado al inicio del archivo en otras funciones; comprobar y añadir si no.)

- [ ] **Step 5: Añadir test integración en `tests/test_scheduler.py`**

```python
@pytest.mark.asyncio
async def test_morning_summary_lunes_perfect_week_bonus(monkeypatch):
    monkeypatch.setattr(scheduler, "ALLOWED_USER_ID", 42)
    # Lunes 2026-06-01; semana pasada empieza 2026-05-25
    monkeypatch.setattr(_date_utils, "today_madrid", lambda: _date(2026, 5, 25))
    import tools
    o = tools.add_objective("A", "2026-05-25")
    monkeypatch.setattr(_date_utils, "today_madrid", lambda: _date(2026, 5, 28))
    tools.mark_objective_done(o["id"])
    monkeypatch.setattr(_date_utils, "today_madrid", lambda: _date(2026, 6, 1))

    send_mock = AsyncMock()
    await scheduler.morning_summary(_fake_context(send_mock))

    text = send_mock.call_args.kwargs["text"]
    assert "Semana perfecta" in text
    assert "+100 XP" in text
```

- [ ] **Step 6: Verificar pass**

```
./.venv/bin/python -m pytest tests/test_tools_perfect.py tests/test_scheduler.py -v
```

- [ ] **Step 7: Suite**

```
./.venv/bin/python -m pytest
```

- [ ] **Step 8: Commit**

```
git add tools.py scheduler.py tests/test_tools_perfect.py tests/test_scheduler.py
git commit -m "$(cat <<'EOF'
feat(scheduler): bonus de semana perfecta (+100 XP) en morning_summary lunes

Evalúa al inicio del saludo del lunes si los objetivos de la
semana pasada están todos done (on_time o grace). Si sí, otorga
+100 XP y añade línea "🏆 ¡Semana perfecta! +100 XP" al bloque.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Cabecera de nivel en todas las vistas (`_render_level_header`)

**Files:**
- Modify: `views.py` — añadir helper + prependear en `render_today_view`, `render_tomorrow_view`, `render_pending_view`, `render_week_view`, `render_metrics_view`
- Modify: `tests/test_views.py`

- [ ] **Step 1: Añadir tests al final de `tests/test_views.py`**

```python
def test_render_today_view_includes_level_header_zero():
    """Sin XP, la cabecera dice Nivel 0 sin medalla."""
    with db.connect() as conn:
        text, _ = views.render_today_view(date(2026, 5, 19), conn)
    assert "Nivel 0" in text


def test_render_today_view_includes_medal_when_level_up(monkeypatch):
    """Con XP suficiente, la cabecera muestra medalla y nivel."""
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 19))
    # Forzar XP para nivel 1: 30 XP
    with db.connect() as conn:
        for _ in range(3):
            conn.execute(
                "INSERT INTO xp_log "
                "(item_type, item_id, outcome, xp_amount, awarded_at) "
                "VALUES ('task', 1, 'on_time', 10, '2026-05-19T10:00:00')"
            )
    with db.connect() as conn:
        text, _ = views.render_today_view(date(2026, 5, 19), conn)
    assert "🥉" in text
    assert "Nivel 1" in text


def test_render_metrics_view_includes_level_header(monkeypatch):
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 30))
    with db.connect() as conn:
        text, _ = views.render_metrics_view(date(2026, 5, 30), conn)
    # Aunque esté vacío, la cabecera siempre se incluye
    assert "Nivel" in text


def test_render_pending_view_includes_level_header(monkeypatch):
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 19))
    tools.add_task("X", due_date="2026-05-19")
    with db.connect() as conn:
        text, _ = views.render_pending_view(conn)
    assert "Nivel" in text


def test_render_week_view_includes_level_header():
    with db.connect() as conn:
        text, _ = views.render_week_view(date(2026, 5, 19), conn)
    assert "Nivel" in text


def test_render_tomorrow_view_includes_level_header():
    with db.connect() as conn:
        text, _ = views.render_tomorrow_view(date(2026, 5, 20), conn)
    assert "Nivel" in text
```

- [ ] **Step 2: Verificar que fallan**

```
./.venv/bin/python -m pytest tests/test_views.py -v -k "level_header or includes_medal"
```

- [ ] **Step 3: Añadir helper `_render_level_header` en `views.py`**

Al inicio de `views.py`, tras los imports, añadir:

```python
def _render_level_header(conn) -> str:
    """Devuelve la línea de cabecera del nivel actual con doble salto."""
    import tools
    total = conn.execute(
        "SELECT COALESCE(SUM(xp_amount), 0) AS t FROM xp_log"
    ).fetchone()["t"] or 0
    level = tools.compute_level(total)
    if level == 0:
        return "<b>Nivel 0</b>\n\n"
    medal = tools.medal_for_level(level)
    return f"{medal} <b>Nivel {level}</b>\n\n"
```

- [ ] **Step 4: Prependear en cada render que aplica**

En `render_today_view`, justo antes del `return text, keyboard` final (en ambas ramas: la del día libre y la normal), añadir el header.

Buscar el patrón:
```python
    if not sections:
        return "Día libre, disfrútalo 💪", None
```

Cambiar a:
```python
    header = _render_level_header(conn)
    if not sections:
        return header + "Día libre, disfrútalo 💪", None
```

Y para la rama principal, buscar el `text = "\n\n".join(sections)` y poco después el `return text, keyboard`. Cambiar la línea de text a:
```python
    text = header + "\n\n".join(sections)
```

(El `header` definido arriba.)

Repetir el patrón en:
- `render_tomorrow_view`
- `render_pending_view`
- `render_week_view`
- `render_metrics_view`

Asegurarse de que el header se genera UNA vez antes de cualquier return.

- [ ] **Step 5: Verificar pass**

```
./.venv/bin/python -m pytest tests/test_views.py -v
```

Si tests previos fallan porque comprobaban texto exacto al inicio, ajustarlos para usar `in` en vez de igualdad. Por ejemplo, un test que ahora asegura `text == "Día libre, disfrútalo 💪"` debe pasar a `assert "Día libre" in text` (porque ahora hay un prefijo de nivel).

- [ ] **Step 6: Suite**

```
./.venv/bin/python -m pytest
```

- [ ] **Step 7: Commit**

```
git add views.py tests/test_views.py
git commit -m "$(cat <<'EOF'
feat(views): cabecera de nivel en todas las vistas determinísticas

Prepende una línea "🥉 Nivel N" al inicio de /hoy, /manana,
/pendientes, /semana y /metricas. Nivel 0 se muestra sin medalla.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Comando `/nivel` y vista `render_nivel_view`

**Files:**
- Modify: `views.py` — añadir `render_nivel_view`
- Modify: `bot.py` — añadir `_on_nivel`, registrar `CommandHandler` y `BotCommand`
- Modify: `tests/test_views.py`, `tests/test_bot.py`

- [ ] **Step 1: Añadir tests para `render_nivel_view` al final de `tests/test_views.py`**

```python
def test_render_nivel_view_zero(monkeypatch):
    """Sin XP, muestra info de nivel 0."""
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 30))
    with db.connect() as conn:
        text, kb = views.render_nivel_view(date(2026, 5, 30), conn)
    assert "Nivel 0" in text
    assert "30 XP" in text  # XP necesario para nivel 1


def test_render_nivel_view_with_xp(monkeypatch):
    """Con XP intermedio, muestra progreso, faltan y breakdown."""
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 30))
    with db.connect() as conn:
        # 50 XP totales: nivel 1 (30) → 20/50 hacia nivel 2 (80)
        conn.execute(
            "INSERT INTO xp_log "
            "(item_type, item_id, outcome, xp_amount, awarded_at) "
            "VALUES ('task', 1, 'on_time', 50, '2026-05-30T10:00:00')"
        )
    with db.connect() as conn:
        text, kb = views.render_nivel_view(date(2026, 5, 30), conn)
    assert "Nivel 1" in text
    assert "50 XP" in text
    assert "Para nivel 2" in text  # falta info
    assert "30 XP" in text  # faltan 80-50=30


def test_render_nivel_view_30_day_breakdown(monkeypatch):
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 30))
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO xp_log "
            "(item_type, item_id, outcome, xp_amount, awarded_at) "
            "VALUES ('task', 1, 'on_time', 10, '2026-05-29T10:00:00')"
        )
        conn.execute(
            "INSERT INTO xp_log "
            "(item_type, item_id, outcome, xp_amount, awarded_at) "
            "VALUES ('routine', 2, 'on_time', 6, '2026-05-28T10:00:00')"
        )
    with db.connect() as conn:
        text, kb = views.render_nivel_view(date(2026, 5, 30), conn)
    # Breakdown debe aparecer
    assert "Últimos 30 días" in text
    assert "Rutinas" in text
    assert "Tareas" in text
```

- [ ] **Step 2: Añadir tests en `tests/test_bot.py`**

```python
@pytest.mark.asyncio
async def test_on_nivel_sends_text(monkeypatch):
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    reply_mock = AsyncMock()
    update = MagicMock()
    update.message.reply_text = reply_mock
    update.effective_user.id = 42

    await bot._on_nivel(update, MagicMock())

    reply_mock.assert_called_once()
    args, kwargs = reply_mock.call_args
    text = args[0] if args else kwargs.get("text")
    assert "Nivel" in text


@pytest.mark.asyncio
async def test_on_nivel_unauthorized_ignored(monkeypatch):
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    reply_mock = AsyncMock()
    update = MagicMock()
    update.message.reply_text = reply_mock
    update.effective_user.id = 999

    await bot._on_nivel(update, MagicMock())

    reply_mock.assert_not_called()
```

- [ ] **Step 3: Verificar que fallan**

```
./.venv/bin/python -m pytest tests/test_views.py tests/test_bot.py -v -k "nivel_view or on_nivel"
```

- [ ] **Step 4: Añadir `render_nivel_view` en `views.py`**

Al final del archivo:

```python
def render_nivel_view(
    today: date, conn
) -> tuple[str, Optional[InlineKeyboardMarkup]]:
    """Panel de nivel con XP total, progreso, faltan y breakdown 30d."""
    from datetime import timedelta
    import tools

    total = conn.execute(
        "SELECT COALESCE(SUM(xp_amount), 0) AS t FROM xp_log"
    ).fetchone()["t"] or 0
    level = tools.compute_level(total)
    medal = tools.medal_for_level(level)
    medal_prefix = f"{medal} " if medal else ""

    # XP del nivel actual y del siguiente
    xp_for_current = 0 if level == 0 else 10 * level * (level + 2)
    xp_for_next = 10 * (level + 1) * (level + 3)
    needed = xp_for_next - total
    progress_in_level = total - xp_for_current
    range_in_level = xp_for_next - xp_for_current
    pct = int(100 * progress_in_level / range_in_level) if range_in_level else 0

    # Barra de 10 bloques
    blocks_filled = int(pct / 10)
    blocks_empty = 10 - blocks_filled
    bar = "▓" * blocks_filled + "▒" * blocks_empty

    sections = [
        f"{medal_prefix}<b>Nivel {level}</b> — {total} XP",
        f"Para nivel {level + 1} faltan: <b>{needed} XP</b>\n"
        f"Progreso: {bar} {pct}%",
    ]

    # Breakdown últimos 30 días
    cutoff = (today - timedelta(days=29)).isoformat()
    rows = conn.execute(
        "SELECT item_type, COALESCE(SUM(xp_amount), 0) AS sum_xp "
        "FROM xp_log "
        "WHERE substr(awarded_at, 1, 10) >= ? "
        "GROUP BY item_type",
        (cutoff,),
    ).fetchall()
    breakdown = {r["item_type"]: r["sum_xp"] for r in rows}
    total_30d = sum(breakdown.values())

    if total_30d > 0:
        breakdown_lines = [
            f"📊 <b>Últimos 30 días</b>: {total_30d} XP ganados"
        ]
        labels = [
            ("routine", "Rutinas"),
            ("task", "Tareas"),
            ("event", "Eventos"),
            ("objective", "Objetivos"),
            ("perfect_day", "Días perfectos"),
            ("perfect_week", "Semanas perfectas"),
        ]
        for key, label in labels:
            value = breakdown.get(key, 0)
            if value:
                breakdown_lines.append(f"  {label}: {value} XP")
        sections.append("\n".join(breakdown_lines))

    return "\n\n".join(sections), None
```

- [ ] **Step 5: Añadir handler `_on_nivel` y registrar en `bot.py`**

Cerca de `_on_metricas` (alrededor de la línea ~270 tras el feature anterior):

```python
async def _on_nivel(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    """/nivel: panel del sistema XP."""
    if not update.message or not update.effective_user:
        return
    if update.effective_user.id != ALLOWED_USER_ID:
        log.warning("/nivel ignorado de user_id no autorizado: %s", update.effective_user.id)
        return

    today = date_utils.today_madrid()
    with db.connect() as conn:
        text, keyboard = views.render_nivel_view(today, conn)

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )
```

Registrar en `_async_main` (junto a los otros `CommandHandler`):

```python
    app.add_handler(CommandHandler("nivel", _on_nivel))
```

Y añadir a `_set_bot_commands`:

```python
        BotCommand("nivel", "Tu nivel y XP"),
```

- [ ] **Step 6: Verificar pass**

```
./.venv/bin/python -m pytest tests/test_views.py tests/test_bot.py -v
```

- [ ] **Step 7: Suite**

```
./.venv/bin/python -m pytest
```

- [ ] **Step 8: Commit**

```
git add views.py bot.py tests/test_views.py tests/test_bot.py
git commit -m "$(cat <<'EOF'
feat(bot): comando /nivel con panel dedicado de XP y progreso

Nueva vista determinística que muestra nivel actual, XP total,
faltan para el siguiente, barra de progreso (10 bloques) y
breakdown por tipo en los últimos 30 días.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: Notificación de subida de nivel en callbacks (`_on_callback_query`)

**Files:**
- Modify: `bot.py` — añadir `_render_level_up_message` + lógica en `_on_callback_query`
- Modify: `tests/test_bot.py`

- [ ] **Step 1: Añadir test al final de `tests/test_bot.py`**

```python
@pytest.mark.asyncio
async def test_callback_marks_task_and_sends_level_up(monkeypatch, temp_db):
    """Cuando una acción sube de nivel, se manda mensaje aparte."""
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    from datetime import date
    import date_utils
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 19))

    import tools
    # Preparar: 20 XP previos
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO xp_log "
            "(item_type, item_id, outcome, xp_amount, awarded_at) "
            "VALUES ('task', 999, 'on_time', 20, '2026-05-19T10:00:00')"
        )
    # Crear tarea de hoy y simular su id
    t = tools.add_task("Hoy", due_date="2026-05-19")

    query = MagicMock()
    query.from_user.id = 42
    query.data = f"mT:{t['id']}:P"
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    query.message = MagicMock()
    update = MagicMock()
    update.callback_query = query
    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock()

    await bot._on_callback_query(update, ctx)

    # XP total ahora 30 = nivel 1. Antes 20 = nivel 0. Debió mandar level-up.
    ctx.bot.send_message.assert_called()
    # Mensaje contiene "Nivel 1 desbloqueado"
    sent_text = ctx.bot.send_message.call_args.kwargs["text"]
    assert "Nivel 1" in sent_text
```

- [ ] **Step 2: Verificar que falla**

```
./.venv/bin/python -m pytest tests/test_bot.py -v -k "sends_level_up"
```

- [ ] **Step 3: Añadir `_render_level_up_message` y lógica en `bot.py`**

Cerca del inicio de `bot.py` tras `_PROACTIVE_CONFIRM_TEXTS`:

```python
def _render_level_up_message(level_before: int, level_after: int) -> str:
    """Devuelve el texto HTML del mensaje de subida de nivel.

    Incluye transición de medalla si hay cambio de tramo.
    """
    import tools
    medal_before = tools.medal_for_level(level_before)
    medal_after = tools.medal_for_level(level_after)
    if medal_before != medal_after and medal_after:
        transition = f" {medal_before or '⬜'} → {medal_after}"
    else:
        transition = f" {medal_after}" if medal_after else ""
    return (
        f"🎉 ¡Nivel {level_after} desbloqueado!{transition}\n"
        f"¡Sigue así!"
    )
```

En `_on_callback_query`, justo después del `handler(item_id)` y antes del bloque de re-renderizado/proactivos, añadir:

```python
    # Detectar subida de nivel y notificar
    level_before = None
    level_after = None
    try:
        result = _CALLBACK_RESULT.pop(query.id, None) if hasattr(query, "id") else None
    except Exception:
        result = None
```

Hmm — el handler actual ya hace `handler(item_id)` y descarta el return. Para capturar el dict, hay que cambiar la llamada a:

```python
    try:
        result = handler(item_id)
    except Exception:
        log.exception("Error aplicando mutación de callback %s", data)
        result = None
    if isinstance(result, dict):
        level_before = result.get("level_before")
        level_after = result.get("level_after")
        if (
            level_before is not None
            and level_after is not None
            and level_after > level_before
        ):
            try:
                await context.bot.send_message(
                    chat_id=ALLOWED_USER_ID,
                    text=_render_level_up_message(level_before, level_after),
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                log.exception("Error enviando mensaje de subida de nivel")
```

(Sustituir la llamada existente `handler(item_id)` por el bloque `try`/result.)

- [ ] **Step 4: Verificar pass**

```
./.venv/bin/python -m pytest tests/test_bot.py -v
```

- [ ] **Step 5: Suite**

```
./.venv/bin/python -m pytest
```

- [ ] **Step 6: Commit**

```
git add bot.py tests/test_bot.py
git commit -m "$(cat <<'EOF'
feat(bot): mensaje de subida de nivel tras callbacks que mutan XP

Cuando un tap en un botón inline marca algo y eso sube de nivel,
envía un mensaje aparte "🎉 ¡Nivel N desbloqueado!" con transición
de medalla si cambia de tramo.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: Notificación de subida desde brain (`record_level_up` / `pop_level_up`)

**Files:**
- Modify: `brain.py` — añadir `_pending_level_up`, `record_level_up`, `pop_level_up`, llamada en dispatch
- Modify: `bot.py` — en `_on_message` y `_on_voice`, pop y enviar
- Modify: `tests/test_brain.py`, `tests/test_bot.py`

- [ ] **Step 1: Añadir tests en `tests/test_brain.py`**

```python
def test_record_and_pop_level_up():
    """record_level_up persiste hasta pop."""
    import brain
    brain.record_level_up(42, 4, 5)
    res = brain.pop_level_up(42)
    assert res == (4, 5)
    # Segunda llamada → None
    assert brain.pop_level_up(42) is None
```

- [ ] **Step 2: Modificar `brain.py`**

Tras `_pending_calendar_button` (alrededor de la línea ~20), añadir:

```python
_pending_level_up: dict[int, tuple[int, int]] = {}


def record_level_up(user_id: int, level_before: int, level_after: int) -> None:
    _pending_level_up[user_id] = (level_before, level_after)


def pop_level_up(user_id: int) -> Optional[tuple[int, int]]:
    return _pending_level_up.pop(user_id, None)
```

Asegúrate de que `from typing import Optional` está en los imports (debería estarlo; si no, añade).

Dentro de `handle_message`, en el bloque de tool_use que procesa los results, añadir tras `result = tools.dispatch(...)`:

```python
                    if isinstance(result, dict):
                        lb = result.get("level_before")
                        la = result.get("level_after")
                        if (
                            lb is not None and la is not None and la > lb
                        ):
                            record_level_up(user_id, lb, la)
```

- [ ] **Step 3: Modificar `bot.py` para enviar mensaje tras respuesta de brain**

En `_on_message`, tras el `reply_text` final:

```python
    # Si Claude disparó una subida de nivel, mandar mensaje aparte
    level_change = brain.pop_level_up(user_id)
    if level_change:
        level_before, level_after = level_change
        try:
            await context.bot.send_message(
                chat_id=ALLOWED_USER_ID,
                text=_render_level_up_message(level_before, level_after),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            log.exception("Error enviando mensaje de subida de nivel post-brain")
```

Pero `_on_message` no recibe `context`; recibe `_` (un placeholder). Hay que cambiar la firma:

Buscar:
```python
async def _on_message(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
```

Cambiar a:
```python
async def _on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
```

Y donde se usa `update.message.reply_text(reply, ...)`, mantener. Tras esa llamada añadir el bloque arriba.

Repetir en `_on_voice` (que sí recibe `context: ContextTypes.DEFAULT_TYPE` ya).

- [ ] **Step 4: Añadir test integración (opcional)**

En `tests/test_bot.py`:

```python
@pytest.mark.asyncio
async def test_brain_level_up_triggers_message(monkeypatch):
    """Si brain registra subida, _on_message la envía aparte."""
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    import brain
    brain.record_level_up(42, 0, 1)

    msg_mock = AsyncMock()
    update = MagicMock()
    update.message.text = "hola"
    update.message.reply_text = AsyncMock()
    update.effective_user.id = 42

    ctx = MagicMock()
    ctx.bot.send_message = msg_mock

    # process_incoming en _on_message hace bypass de Claude si no hay TOKEN
    # válido; simulamos con un monkeypatch directo
    monkeypatch.setattr(
        bot, "process_incoming", lambda text, from_user_id: "ok"
    )

    await bot._on_message(update, ctx)

    msg_mock.assert_called_once()
    assert "Nivel 1" in msg_mock.call_args.kwargs["text"]
```

- [ ] **Step 5: Verificar pass**

```
./.venv/bin/python -m pytest tests/test_brain.py tests/test_bot.py -v
```

- [ ] **Step 6: Suite**

```
./.venv/bin/python -m pytest
```

- [ ] **Step 7: Commit**

```
git add brain.py bot.py tests/test_brain.py tests/test_bot.py
git commit -m "$(cat <<'EOF'
feat(brain): notificación de subida de nivel desde tools de Claude

brain registra los cambios de nivel detectados durante tool_use
en _pending_level_up. bot.py los recoge en _on_message y _on_voice
y manda el mensaje 🎉 aparte tras la respuesta normal.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 13: Registrar comando `/nivel` y limpieza final

**Files:**
- Verificar: `bot.py` ya tiene el `CommandHandler("nivel", _on_nivel)` y `BotCommand("nivel", ...)` (Task 10).

Esta tarea solo cubre la suite completa final + un test smoke que confirma que todo el sistema funciona end-to-end.

- [ ] **Step 1: Test end-to-end en `tests/test_tools_xp.py`**

```python
def test_e2e_completar_y_subir_nivel(monkeypatch, temp_db):
    """Smoke: marcar varias acciones acumula XP correctamente."""
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 30))
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
```

Asegúrate de que `import date_utils` y `from datetime import date` están al inicio del archivo.

- [ ] **Step 2: Verificar pass**

```
./.venv/bin/python -m pytest tests/test_tools_xp.py -v -k "e2e"
```

- [ ] **Step 3: Suite completa**

```
./.venv/bin/python -m pytest -v 2>&1 | tail -5
```

Esperado: ALL PASSED.

- [ ] **Step 4: Verificación local del bot**

```
./.venv/bin/python -c "import bot; print('OK')"
```

Esperado: `OK` sin tracebacks.

- [ ] **Step 5: Commit final**

```
git add tests/test_tools_xp.py
git commit -m "$(cat <<'EOF'
test: smoke e2e del sistema XP/niveles

Acumula XP de tareas + objetivos y verifica que el nivel sube
correctamente atravesando los thresholds 30 y 80.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Verificación final (manual, post-merge)

- [ ] Suite verde local:
```
./.venv/bin/python -m pytest
```

- [ ] Arranque local sin errores:
```
./start.sh
```

- [ ] Probar manualmente en Telegram:
   - `/nivel` → muestra Nivel 0, faltan 30 XP.
   - Marcar una rutina del día → debería responder marcado + (si toca) mensaje aparte de subida.
   - `/hoy` → cabecera con nivel.
   - `/metricas` → cabecera con nivel.

- [ ] Deploy a Fly:
```
flyctl deploy --app mi-secretaria-pablo
```

- [ ] Verificar en logs:
```
flyctl logs --app mi-secretaria-pablo --no-tail
```
Buscar `Menú de comandos actualizado en Telegram (9 comandos)` (subió de 8 a 9 porque añadimos `/nivel`).

- [ ] Tras el primer lunes después del deploy: comprobar que el saludo matutino muestra el bloque semanal + posible `🏆 ¡Semana perfecta! +100 XP` si aplica.

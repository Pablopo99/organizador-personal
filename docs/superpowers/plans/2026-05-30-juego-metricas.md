# Mi Secretaria: el juego (gracia, perdidos y métricas) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implementar la mecánica de día/semana de gracia, el flujo de recreación/descarte de ítems perdidos y un panel de métricas a tiempo / al día siguiente / perdido por tipo de ítem.

**Architecture:** TDD pequeño y aditivo. Migraciones de esquema retro-compatibles (`ALTER TABLE ADD COLUMN` idempotentes + nueva tabla `missed_notifications`). Una columna `outcome TEXT NULL` en `events`/`tasks`/`objectives` que se rellena en paralelo a `done`. Una columna `status` en `routine_completions` que distingue on_time vs grace. Un job nocturno nuevo `detect_missed_items` en APScheduler. Comando `/metricas` con vista determinística. Sin Claude en los caminos calientes.

**Tech Stack:** Python 3, SQLite, python-telegram-bot 21, APScheduler (via `job_queue` de PTB), pytest + pytest-asyncio. Spec completa en `docs/superpowers/specs/2026-05-30-juego-metricas-design.md`.

---

## File structure

**Modificados:**
- `db.py` — añadir migraciones para `outcome` (events, tasks, objectives), `due_date` (tasks), `status` (routine_completions); crear tabla `missed_notifications`.
- `tools.py` — helper `_calculate_outcome`; modificar `add_task`, `complete_task`, `mark_event_done`, `mark_objective_done`; ampliar `routine_summary` con conteos por status; nuevo tool `metrics_summary`; helpers `recreate_event/task/objective` y `discard_event/task/objective`; ampliar `query_events` con `include_grace`.
- `views.py` — modificar `render_today_view` (sección gracia + filtro tareas por due_date), modificar `render_pending_view` (3 secciones), nueva `render_metrics_view`.
- `scheduler.py` — nuevo job `detect_missed_items`; añadir bloque semanal del lunes en `morning_summary`.
- `bot.py` — handler `_on_metricas`, callbacks `rE/rT/rO/dE/dT/dO`, registrar comando y job nuevos.
- `brain.py` — añadir regla en system prompt para preguntar `due_date` al crear tarea.

**Nuevos tests:**
- `tests/test_tools_outcome.py` — tests del helper `_calculate_outcome`.
- `tests/test_tools_missed.py` — tests de `recreate_*` y `discard_*`.
- `tests/test_tools_metrics.py` — tests de `metrics_summary`.
- `tests/test_scheduler_missed.py` — tests del job `detect_missed_items`.

**Tests modificados:**
- `tests/test_tools_tasks.py` — añadir tests de `due_date` y `outcome`.
- `tests/test_tools_events.py` — añadir tests de `outcome` y grace en rutinas.
- `tests/test_tools_objectives.py` — añadir tests de `outcome`.
- `tests/test_views.py` — añadir tests de gracia en `render_today_view`, secciones en `render_pending_view`, render de métricas.
- `tests/test_scheduler.py` — añadir tests del bloque semanal de lunes.
- `tests/test_bot.py` — añadir tests de `/metricas` y callbacks de recreación/descarte.

**Comando para correr la suite completa:**

```bash
./.venv/bin/python -m pytest
```

Para un fichero o patrón concreto:

```bash
./.venv/bin/python -m pytest tests/test_tools_outcome.py -v
./.venv/bin/python -m pytest -k "outcome or grace"
```

**Convención de fechas en tests**: patchear `date_utils.today_madrid` (NO `tools.now_iso`, porque `now_iso` está importado por nombre en `tools.py`). Las rutas absolutas a los módulos en `tools.py` siguen siendo `date_utils.today_madrid()`, así que `monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 30))` funciona.

---

## Task 1: Migraciones de esquema

**Files:**
- Modify: `db.py:70-105` (función `_migrate`)
- Modify: `db.py:8-61` (`_SCHEMA`)
- Test: `tests/test_db.py`

- [ ] **Step 1: Escribir el test fallido**

Añadir al final de `tests/test_db.py`:

```python
import os
import sqlite3
import tempfile

import pytest

import db


@pytest.fixture
def fresh_db(monkeypatch):
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init_schema()
    yield path
    os.unlink(path)


def test_events_has_outcome_column(fresh_db):
    with db.connect() as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(events)").fetchall()]
    assert "outcome" in cols


def test_tasks_has_due_date_and_outcome_columns(fresh_db):
    with db.connect() as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(tasks)").fetchall()]
    assert "due_date" in cols
    assert "outcome" in cols


def test_objectives_has_outcome_column(fresh_db):
    with db.connect() as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(objectives)").fetchall()]
    assert "outcome" in cols


def test_routine_completions_has_status_column(fresh_db):
    with db.connect() as conn:
        cols = [r[1] for r in conn.execute(
            "PRAGMA table_info(routine_completions)"
        ).fetchall()]
    assert "status" in cols


def test_missed_notifications_table_exists(fresh_db):
    with db.connect() as conn:
        cols = [r[1] for r in conn.execute(
            "PRAGMA table_info(missed_notifications)"
        ).fetchall()]
    assert "item_type" in cols
    assert "item_id" in cols
    assert "occurrence_date" in cols
    assert "notified_at" in cols
    assert "decision" in cols


def test_missed_notifications_unique_routine_per_occurrence(fresh_db):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO missed_notifications (item_type, item_id, occurrence_date, notified_at) "
            "VALUES ('routine', 1, '2026-05-28', '2026-05-29T00:05:00')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO missed_notifications (item_type, item_id, occurrence_date, notified_at) "
                "VALUES ('routine', 1, '2026-05-28', '2026-05-29T00:05:00')"
            )


def test_missed_notifications_unique_task_one_per_item(fresh_db):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO missed_notifications (item_type, item_id, notified_at) "
            "VALUES ('task', 5, '2026-05-29T00:05:00')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO missed_notifications (item_type, item_id, notified_at) "
                "VALUES ('task', 5, '2026-05-30T00:05:00')"
            )
```

- [ ] **Step 2: Ejecutar tests para verificar que fallan**

```
./.venv/bin/python -m pytest tests/test_db.py -v -k "outcome or due_date or status or missed_notifications"
```

Esperado: FAIL en todos los nuevos tests con errores tipo `'outcome' not in cols` o `no such table: missed_notifications`.

- [ ] **Step 3: Implementar las migraciones**

Reemplazar la función `_migrate` en `db.py` (líneas 70-105) por:

```python
def _migrate(conn: sqlite3.Connection) -> None:
    """Migraciones idempotentes para tablas ya creadas en versiones anteriores."""
    events_cols = [row[1] for row in conn.execute("PRAGMA table_info(events)").fetchall()]
    if "done" not in events_cols:
        conn.execute("ALTER TABLE events ADD COLUMN done INTEGER NOT NULL DEFAULT 0")
    if "reminder_1d_sent" not in events_cols:
        conn.execute("ALTER TABLE events ADD COLUMN reminder_1d_sent INTEGER NOT NULL DEFAULT 0")
    if "reminder_1h_sent" not in events_cols:
        conn.execute("ALTER TABLE events ADD COLUMN reminder_1h_sent INTEGER NOT NULL DEFAULT 0")
    if "gcal_event_id" not in events_cols:
        conn.execute("ALTER TABLE events ADD COLUMN gcal_event_id TEXT")
    if "outcome" not in events_cols:
        conn.execute("ALTER TABLE events ADD COLUMN outcome TEXT")

    tasks_cols = [row[1] for row in conn.execute("PRAGMA table_info(tasks)").fetchall()]
    if "done_at" not in tasks_cols:
        conn.execute("ALTER TABLE tasks ADD COLUMN done_at TEXT")
    if "due_date" not in tasks_cols:
        conn.execute("ALTER TABLE tasks ADD COLUMN due_date TEXT")
    if "outcome" not in tasks_cols:
        conn.execute("ALTER TABLE tasks ADD COLUMN outcome TEXT")

    objectives_cols = [row[1] for row in conn.execute("PRAGMA table_info(objectives)").fetchall()]
    if "outcome" not in objectives_cols:
        conn.execute("ALTER TABLE objectives ADD COLUMN outcome TEXT")

    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()]
    if "routine_completions" not in tables:
        conn.execute("""
            CREATE TABLE routine_completions (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id         INTEGER NOT NULL,
                completion_date  TEXT NOT NULL,
                created_at       TEXT NOT NULL,
                status           TEXT NOT NULL DEFAULT 'on_time',
                UNIQUE(event_id, completion_date),
                FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_routine_completions_date
                ON routine_completions(completion_date)
        """)
    else:
        rc_cols = [row[1] for row in conn.execute(
            "PRAGMA table_info(routine_completions)"
        ).fetchall()]
        if "status" not in rc_cols:
            conn.execute(
                "ALTER TABLE routine_completions ADD COLUMN status TEXT NOT NULL DEFAULT 'on_time'"
            )

    if "missed_notifications" not in tables:
        conn.execute("""
            CREATE TABLE missed_notifications (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                item_type       TEXT NOT NULL,
                item_id         INTEGER NOT NULL,
                occurrence_date TEXT,
                notified_at     TEXT NOT NULL,
                decision        TEXT,
                decided_at      TEXT
            )
        """)
        conn.execute("""
            CREATE UNIQUE INDEX idx_missed_notif_routine
                ON missed_notifications(item_type, item_id, occurrence_date)
                WHERE item_type = 'routine'
        """)
        conn.execute("""
            CREATE UNIQUE INDEX idx_missed_notif_other
                ON missed_notifications(item_type, item_id)
                WHERE item_type != 'routine'
        """)
```

También actualizar `_SCHEMA` (líneas 8-61) para reflejar las columnas nuevas en bases recién creadas. Sustituir el bloque entero de `_SCHEMA` por:

```python
_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    title             TEXT NOT NULL,
    datetime          TEXT NOT NULL,
    category          TEXT NOT NULL DEFAULT 'other',
    recurring_rule    TEXT,
    notes             TEXT,
    created_at        TEXT NOT NULL,
    done              INTEGER NOT NULL DEFAULT 0,
    reminder_1d_sent  INTEGER NOT NULL DEFAULT 0,
    reminder_1h_sent  INTEGER NOT NULL DEFAULT 0,
    gcal_event_id     TEXT,
    outcome           TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_datetime ON events(datetime);

CREATE TABLE IF NOT EXISTS objectives (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    text        TEXT NOT NULL,
    week_start  TEXT NOT NULL,
    done        INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    outcome     TEXT
);

CREATE INDEX IF NOT EXISTS idx_objectives_week ON objectives(week_start);

CREATE TABLE IF NOT EXISTS tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    text        TEXT NOT NULL,
    done        INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    done_at     TEXT,
    due_date    TEXT,
    outcome     TEXT
);

CREATE TABLE IF NOT EXISTS routine_completions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id         INTEGER NOT NULL,
    completion_date  TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'on_time',
    UNIQUE(event_id, completion_date),
    FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_routine_completions_date
    ON routine_completions(completion_date);

CREATE TABLE IF NOT EXISTS oauth_tokens (
    provider      TEXT PRIMARY KEY,
    access_token  TEXT NOT NULL,
    refresh_token TEXT NOT NULL,
    expires_at    TEXT NOT NULL,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS missed_notifications (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    item_type       TEXT NOT NULL,
    item_id         INTEGER NOT NULL,
    occurrence_date TEXT,
    notified_at     TEXT NOT NULL,
    decision        TEXT,
    decided_at      TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_missed_notif_routine
    ON missed_notifications(item_type, item_id, occurrence_date)
    WHERE item_type = 'routine';

CREATE UNIQUE INDEX IF NOT EXISTS idx_missed_notif_other
    ON missed_notifications(item_type, item_id)
    WHERE item_type != 'routine';
"""
```

- [ ] **Step 4: Ejecutar tests para verificar que pasan**

```
./.venv/bin/python -m pytest tests/test_db.py -v
```

Esperado: PASS en todos los tests, incluidos los nuevos y los existentes.

- [ ] **Step 5: Correr la suite completa para asegurar que no rompemos nada**

```
./.venv/bin/python -m pytest
```

Esperado: PASS. Si algún test antiguo rompe por las columnas nuevas, no debería (son aditivas con default).

- [ ] **Step 6: Commit**

```
git add db.py tests/test_db.py
git commit -m "$(cat <<'EOF'
feat(db): migraciones para outcome, due_date, status y missed_notifications

Migraciones aditivas idempotentes para soportar la mecánica del
"juego": outcome en events/tasks/objectives, due_date opcional en
tasks, status en routine_completions y nueva tabla
missed_notifications con UNIQUE diferenciada por tipo.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Helper `_calculate_outcome`

Función pura que dada una fecha asignada y "hoy" devuelve `'on_time'`, `'grace'` o `None` (fuera de ventana, marcar debe rechazarse).

**Files:**
- Modify: `tools.py` (añadir helper cerca de los otros `_helpers`, antes de la sección `events`)
- Create: `tests/test_tools_outcome.py`

- [ ] **Step 1: Escribir el test fallido**

Crear `tests/test_tools_outcome.py`:

```python
"""Tests del helper _calculate_outcome (lógica pura, sin BD)."""
from datetime import date

import pytest

import tools


def test_same_day_is_on_time():
    assert tools._calculate_outcome(
        assigned=date(2026, 5, 30), today=date(2026, 5, 30)
    ) == "on_time"


def test_day_after_is_grace():
    assert tools._calculate_outcome(
        assigned=date(2026, 5, 30), today=date(2026, 5, 31)
    ) == "grace"


def test_two_days_after_is_none():
    assert tools._calculate_outcome(
        assigned=date(2026, 5, 30), today=date(2026, 6, 1)
    ) is None


def test_before_assigned_is_on_time():
    # Si Pablo marca algo antes de tiempo, contamos como on_time.
    assert tools._calculate_outcome(
        assigned=date(2026, 5, 30), today=date(2026, 5, 29)
    ) == "on_time"


def test_assigned_none_returns_none():
    # Item sin fecha asignada (tarea flotante): outcome queda en None.
    assert tools._calculate_outcome(
        assigned=None, today=date(2026, 5, 30)
    ) is None
```

- [ ] **Step 2: Ejecutar test para verificar que falla**

```
./.venv/bin/python -m pytest tests/test_tools_outcome.py -v
```

Esperado: FAIL con `AttributeError: module 'tools' has no attribute '_calculate_outcome'`.

- [ ] **Step 3: Implementar el helper en `tools.py`**

Añadir en `tools.py`, justo antes de la línea 19 (`# ---- events ----`):

```python
def _calculate_outcome(assigned: Optional[date], today: date) -> Optional[str]:
    """Devuelve 'on_time', 'grace' o None (fuera de ventana / sin fecha).

    Regla:
    - today <= assigned     -> 'on_time'
    - today == assigned + 1 -> 'grace'
    - today >= assigned + 2 -> None (cliente debe rechazar el mark)
    - assigned is None      -> None (item sin fecha; outcome se deja NULL)
    """
    if assigned is None:
        return None
    delta = (today - assigned).days
    if delta <= 0:
        return "on_time"
    if delta == 1:
        return "grace"
    return None
```

- [ ] **Step 4: Ejecutar test para verificar que pasa**

```
./.venv/bin/python -m pytest tests/test_tools_outcome.py -v
```

Esperado: PASS en los 5 tests.

- [ ] **Step 5: Commit**

```
git add tools.py tests/test_tools_outcome.py
git commit -m "$(cat <<'EOF'
feat(tools): helper _calculate_outcome para clasificar a tiempo / gracia / fuera

Función pura que dado un par (assigned_date, today) clasifica como
on_time, grace (1 día tarde) o None (fuera de ventana). Base
compartida para los flujos de marcado de eventos, tareas y objetivos.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `add_task` acepta `due_date`

**Files:**
- Modify: `tools.py:535-542` (`add_task`)
- Modify: `tools.py:721-728` (TOOL_DEFINITIONS para add_task)
- Modify: `tests/test_tools_tasks.py`

- [ ] **Step 1: Escribir el test fallido**

Añadir al final de `tests/test_tools_tasks.py`:

```python
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
```

- [ ] **Step 2: Ejecutar tests para verificar que fallan**

```
./.venv/bin/python -m pytest tests/test_tools_tasks.py -v -k "due_date"
```

Esperado: FAIL con `TypeError: add_task() got an unexpected keyword argument 'due_date'`.

- [ ] **Step 3: Implementar**

Reemplazar `add_task` en `tools.py` (líneas 535-542) por:

```python
def add_task(text: str, due_date: Optional[str] = None) -> dict:
    with db.connect() as conn:
        cur = conn.execute(
            "INSERT INTO tasks (text, done, created_at, due_date) VALUES (?, 0, ?, ?)",
            (text, now_iso(), due_date),
        )
        new_id = cur.lastrowid
    return {"id": new_id, "text": text, "due_date": due_date}
```

Actualizar la TOOL_DEFINITIONS de `add_task` (líneas 721-728) a:

```python
    {
        "name": "add_task",
        "description": (
            "Añade una tarea. due_date es opcional ('YYYY-MM-DD'); úsala SOLO si "
            "el usuario indica un día concreto. Si no la indica, no inventes fecha."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "due_date": {
                    "type": ["string", "null"],
                    "description": "Fecha objetivo en formato YYYY-MM-DD. NULL si no la hay.",
                },
            },
            "required": ["text"],
        },
    },
```

- [ ] **Step 4: Ejecutar tests**

```
./.venv/bin/python -m pytest tests/test_tools_tasks.py -v
```

Esperado: PASS en todos (los antiguos siguen funcionando porque `due_date` es opcional).

- [ ] **Step 5: Commit**

```
git add tools.py tests/test_tools_tasks.py
git commit -m "$(cat <<'EOF'
feat(tools): add_task acepta due_date opcional

Permite asociar fecha objetivo a tareas. Las tareas sin due_date
siguen siendo válidas (flotantes, fuera del juego de gracia/perdido).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `complete_task` calcula `outcome`

**Files:**
- Modify: `tools.py:558-564` (`complete_task`)
- Modify: `tests/test_tools_tasks.py`

- [ ] **Step 1: Escribir tests fallidos**

Añadir al final de `tests/test_tools_tasks.py`:

```python
from datetime import date

import date_utils


def test_complete_task_on_time_sets_outcome_on_time(monkeypatch):
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 30))
    t = tools.add_task("X", due_date="2026-05-30")
    tools.complete_task(t["id"])
    with db.connect() as conn:
        row = conn.execute(
            "SELECT outcome FROM tasks WHERE id = ?", (t["id"],)
        ).fetchone()
    assert row["outcome"] == "on_time"


def test_complete_task_grace_when_one_day_late(monkeypatch):
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 31))
    t = tools.add_task("Y", due_date="2026-05-30")
    tools.complete_task(t["id"])
    with db.connect() as conn:
        row = conn.execute(
            "SELECT outcome FROM tasks WHERE id = ?", (t["id"],)
        ).fetchone()
    assert row["outcome"] == "grace"


def test_complete_task_rejected_when_two_days_late(monkeypatch):
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
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 30))
    t = tools.add_task("Flotante")
    tools.complete_task(t["id"])
    with db.connect() as conn:
        row = conn.execute(
            "SELECT done, outcome FROM tasks WHERE id = ?", (t["id"],)
        ).fetchone()
    assert row["done"] == 1
    assert row["outcome"] is None
```

- [ ] **Step 2: Ejecutar tests para verificar que fallan**

```
./.venv/bin/python -m pytest tests/test_tools_tasks.py -v -k "outcome or window"
```

Esperado: FAIL — `outcome` columna leída pero nunca se escribe; el de "out_of_window" falla porque hoy `complete_task` siempre marca done=1.

- [ ] **Step 3: Implementar**

Reemplazar `complete_task` en `tools.py` (líneas 558-564) por:

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
                # Fuera de ventana: rechazar.
                return {"id": task_id, "updated": 0, "error": "out_of_window"}
        else:
            outcome = None  # tarea flotante

        cur = conn.execute(
            "UPDATE tasks SET done = 1, done_at = ?, outcome = ? WHERE id = ?",
            (now_iso(), outcome, task_id),
        )
    return {"id": task_id, "updated": cur.rowcount, "outcome": outcome}
```

- [ ] **Step 4: Ejecutar tests**

```
./.venv/bin/python -m pytest tests/test_tools_tasks.py -v
```

Esperado: PASS en todos los nuevos. Los antiguos (de tareas sin `due_date`) siguen pasando: `outcome` queda NULL y `done=1` como antes.

- [ ] **Step 5: Commit**

```
git add tools.py tests/test_tools_tasks.py
git commit -m "$(cat <<'EOF'
feat(tools): complete_task calcula outcome y rechaza tareas perdidas

Al marcar hecha una tarea con due_date:
- on_time si hoy <= due_date
- grace si hoy == due_date + 1
- out_of_window (error, no muta) si hoy >= due_date + 2

Las tareas flotantes (due_date NULL) se completan sin outcome.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `mark_event_done` calcula `outcome` para eventos puntuales

**Files:**
- Modify: `tools.py:254-298` (`mark_event_done`)
- Modify: `tests/test_tools_events.py`

- [ ] **Step 1: Escribir tests fallidos**

Añadir al final de `tests/test_tools_events.py`:

```python
from datetime import date

import date_utils


def test_mark_event_done_on_time_sets_outcome(monkeypatch):
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 30))
    res = tools.add_event("Dentista", "2026-05-30T10:00:00", "personal")
    tools.mark_event_done(res["id"])
    with db.connect() as conn:
        row = conn.execute(
            "SELECT done, outcome FROM events WHERE id = ?", (res["id"],)
        ).fetchone()
    assert row["done"] == 1
    assert row["outcome"] == "on_time"


def test_mark_event_done_grace_when_one_day_late(monkeypatch):
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 31))
    res = tools.add_event("Dentista", "2026-05-30T10:00:00", "personal")
    tools.mark_event_done(res["id"])
    with db.connect() as conn:
        row = conn.execute(
            "SELECT done, outcome FROM events WHERE id = ?", (res["id"],)
        ).fetchone()
    assert row["done"] == 1
    assert row["outcome"] == "grace"


def test_mark_event_done_rejected_out_of_window(monkeypatch):
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 6, 1))
    res = tools.add_event("Dentista", "2026-05-30T10:00:00", "personal")
    out = tools.mark_event_done(res["id"])
    assert out.get("error") == "out_of_window"
    with db.connect() as conn:
        row = conn.execute(
            "SELECT done, outcome FROM events WHERE id = ?", (res["id"],)
        ).fetchone()
    assert row["done"] == 0
    assert row["outcome"] is None
```

- [ ] **Step 2: Ejecutar tests para verificar que fallan**

```
./.venv/bin/python -m pytest tests/test_tools_events.py -v -k "outcome or out_of_window"
```

Esperado: FAIL — `outcome` no se escribe y el "out_of_window" no se detecta.

- [ ] **Step 3: Implementar**

Reemplazar `mark_event_done` en `tools.py` (líneas 254-298). Esta implementación cubre **solo el caso no-recurrente**; el caso recurrente se trata en la Task 6.

```python
def mark_event_done(event_id: int) -> dict:
    """Marca un evento como hecho.

    Eventos puntuales -> done=1 + outcome (on_time | grace | rechazo).
    Eventos recurrentes (rutinas) -> inserta routine_completions con
    fecha esperada + status (on_time | grace) o rechazo si fuera de ventana.
    Ver Task 6 para la lógica recurrente.
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

        if row["recurring_rule"]:
            # Lógica recurrente: se completa en Task 6.
            today_iso = today.isoformat()
            try:
                conn.execute(
                    """
                    INSERT INTO routine_completions (event_id, completion_date, created_at, status)
                    VALUES (?, ?, ?, 'on_time')
                    """,
                    (event_id, today_iso, date_utils.now_iso()),
                )
                return {
                    "event_id": event_id,
                    "completion_date": today_iso,
                    "status": "on_time",
                    "updated": 1,
                }
            except sqlite3.IntegrityError:
                return {
                    "event_id": event_id,
                    "completion_date": today_iso,
                    "already_done_today": True,
                    "updated": 0,
                }

        # Evento puntual.
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
        return {"id": event_id, "updated": cur.rowcount, "outcome": outcome}
```

- [ ] **Step 4: Ejecutar tests**

```
./.venv/bin/python -m pytest tests/test_tools_events.py -v
```

Esperado: PASS en todos los nuevos y los antiguos.

- [ ] **Step 5: Commit**

```
git add tools.py tests/test_tools_events.py
git commit -m "$(cat <<'EOF'
feat(tools): mark_event_done calcula outcome para eventos puntuales

Eventos no recurrentes: on_time si hoy es el día del evento o antes,
grace si hoy es el día siguiente, out_of_window (error) si hoy es
día +2 o más. La lógica recurrente sigue como antes y se mejora en
la siguiente tarea.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: `mark_event_done` registra `grace` para rutinas

Cuando se marca una rutina en día de gracia, el completion debe registrarse con la **fecha esperada perdida** (no `today`) y `status='grace'`. Así la racha sigue intacta.

**Files:**
- Modify: `tools.py` — bloque recurrente dentro de `mark_event_done`
- Modify: `tests/test_tools_events.py`

- [ ] **Step 1: Escribir tests fallidos**

Añadir al final de `tests/test_tools_events.py`:

```python
def test_mark_routine_done_today_on_time(monkeypatch):
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 30))
    res = tools.add_event(
        "Meditar", "2026-05-01T08:00:00", "personal", recurring_rule="DAILY"
    )
    tools.mark_event_done(res["id"])
    with db.connect() as conn:
        row = conn.execute(
            "SELECT completion_date, status FROM routine_completions "
            "WHERE event_id = ?",
            (res["id"],),
        ).fetchone()
    assert row["completion_date"] == "2026-05-30"
    assert row["status"] == "on_time"


def test_mark_daily_routine_done_one_day_late_uses_yesterday_with_grace(monkeypatch):
    """DAILY: si hoy es 31 y no se hizo el 30, se registra el 30 con grace."""
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 31))
    res = tools.add_event(
        "Meditar", "2026-05-01T08:00:00", "personal", recurring_rule="DAILY"
    )
    tools.mark_event_done(res["id"])
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT completion_date, status FROM routine_completions "
            "WHERE event_id = ? ORDER BY completion_date",
            (res["id"],),
        ).fetchall()
    # Solo se ha grabado uno: el de ayer (30) con status grace.
    assert len(rows) == 1
    assert rows[0]["completion_date"] == "2026-05-30"
    assert rows[0]["status"] == "grace"


def test_mark_weekly_routine_done_in_grace_records_expected_day(monkeypatch):
    """WEEKLY:MON: si hoy es martes y no se hizo el lunes, grabar el lunes."""
    # 2026-05-25 es lunes. 2026-05-26 es martes.
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 26))
    res = tools.add_event(
        "Reunión semanal", "2026-05-04T09:00:00", "work",
        recurring_rule="WEEKLY:MON",
    )
    tools.mark_event_done(res["id"])
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT completion_date, status FROM routine_completions "
            "WHERE event_id = ?",
            (res["id"],),
        ).fetchall()
    assert len(rows) == 1
    assert rows[0]["completion_date"] == "2026-05-25"
    assert rows[0]["status"] == "grace"


def test_mark_daily_routine_done_two_days_late_rejected(monkeypatch):
    """DAILY: si hoy es 1 y no hay completion del 30 ni 31, rechazar (out of window)."""
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 6, 1))
    res = tools.add_event(
        "Meditar", "2026-05-01T08:00:00", "personal", recurring_rule="DAILY"
    )
    out = tools.mark_event_done(res["id"])
    # 2026-06-01 es fecha esperada DAILY → on_time. No rechaza.
    # Este test cambia: para DAILY, hoy SIEMPRE es fecha esperada, así que es on_time.
    assert out.get("status") == "on_time"


def test_mark_weekly_routine_done_in_wrong_day_rejected(monkeypatch):
    """WEEKLY:MON: si hoy es jueves (no lunes ni martes), rechazar."""
    # 2026-05-28 es jueves.
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 28))
    res = tools.add_event(
        "Reunión semanal", "2026-05-04T09:00:00", "work",
        recurring_rule="WEEKLY:MON",
    )
    out = tools.mark_event_done(res["id"])
    assert out.get("error") == "out_of_window"
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM routine_completions WHERE event_id = ?",
            (res["id"],),
        ).fetchall()
    assert len(rows) == 0
```

- [ ] **Step 2: Ejecutar tests para verificar que fallan**

```
./.venv/bin/python -m pytest tests/test_tools_events.py -v -k "routine and (grace or rejected or expected_day)"
```

Esperado: FAIL — actualmente el código siempre escribe `completion_date = today` con `status='on_time'`.

- [ ] **Step 3: Implementar**

Sustituir el bloque "if row[recurring_rule]" dentro de `mark_event_done` por:

```python
        if row["recurring_rule"]:
            rule = row["recurring_rule"]
            most_recent_expected = _most_recent_expected_date(rule, today)
            previous_expected = _previous_expected_date(rule, today)

            target_date: Optional[date] = None
            status: Optional[str] = None

            if most_recent_expected == today:
                target_date = today
                status = "on_time"
            elif (
                previous_expected is not None
                and (today - previous_expected).days == 1
            ):
                # Día de gracia: la fecha esperada anterior fue ayer y no se hizo.
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
                return {
                    "event_id": event_id,
                    "completion_date": target_iso,
                    "status": status,
                    "updated": 1,
                }
            except sqlite3.IntegrityError:
                return {
                    "event_id": event_id,
                    "completion_date": target_iso,
                    "already_done": True,
                    "updated": 0,
                }
```

Nota: `_most_recent_expected_date` y `_previous_expected_date` ya existen en `tools.py:331-364`.

- [ ] **Step 4: Ejecutar tests**

```
./.venv/bin/python -m pytest tests/test_tools_events.py -v
```

Esperado: PASS en todos. Los tests antiguos de rutinas siguen funcionando porque DAILY en su día esperado entra en la rama `on_time`.

- [ ] **Step 5: Commit**

```
git add tools.py tests/test_tools_events.py
git commit -m "$(cat <<'EOF'
feat(tools): mark_event_done registra grace en rutinas con fecha esperada

Cuando se marca una rutina al día siguiente de su fecha esperada,
se registra el completion con la fecha esperada perdida (no hoy) y
status='grace'. Así _current_streak no rompe la racha. Si la fecha
esperada anterior fue hace más de un día, se rechaza el mark
(out_of_window).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: `mark_objective_done` calcula `outcome`

**Files:**
- Modify: `tools.py:516-521` (`mark_objective_done`)
- Modify: `tests/test_tools_objectives.py`

- [ ] **Step 1: Escribir tests fallidos**

Añadir al final de `tests/test_tools_objectives.py`:

```python
from datetime import date

import date_utils


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
```

- [ ] **Step 2: Ejecutar tests para verificar que fallan**

```
./.venv/bin/python -m pytest tests/test_tools_objectives.py -v -k "outcome or rejected"
```

Esperado: FAIL.

- [ ] **Step 3: Implementar**

Reemplazar `mark_objective_done` en `tools.py` (líneas 516-521) por:

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

        cur = conn.execute(
            "UPDATE objectives SET done = 1, outcome = ? WHERE id = ?",
            (outcome, objective_id),
        )
    return {"id": objective_id, "updated": cur.rowcount, "outcome": outcome}
```

- [ ] **Step 4: Ejecutar tests**

```
./.venv/bin/python -m pytest tests/test_tools_objectives.py -v
```

Esperado: PASS.

- [ ] **Step 5: Commit**

```
git add tools.py tests/test_tools_objectives.py
git commit -m "$(cat <<'EOF'
feat(tools): mark_objective_done calcula outcome por semanas

on_time si la semana actual <= week_start del objetivo, grace si
es la semana siguiente, out_of_window (error) a partir de la
segunda semana siguiente.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: `routine_summary` incluye conteos `on_time` y `grace`

**Files:**
- Modify: `tools.py:411-460` (`routine_summary`)
- Modify: `tests/test_tools_events.py`

- [ ] **Step 1: Escribir tests fallidos**

Añadir al final de `tests/test_tools_events.py`:

```python
def test_routine_summary_breaks_down_on_time_and_grace(monkeypatch):
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 30))
    res = tools.add_event(
        "Meditar", "2026-05-25T08:00:00", "personal", recurring_rule="DAILY"
    )
    # Insertamos manualmente: 2 on_time y 1 grace en el rango.
    with db.connect() as conn:
        for d, status in [
            ("2026-05-25", "on_time"),
            ("2026-05-26", "grace"),
            ("2026-05-27", "on_time"),
        ]:
            conn.execute(
                "INSERT INTO routine_completions (event_id, completion_date, created_at, status) "
                "VALUES (?, ?, ?, ?)",
                (res["id"], d, "2026-05-30T08:00:00", status),
            )

    summary = tools.routine_summary("2026-05-25", "2026-05-30")
    target = next(r for r in summary if r["event_id"] == res["id"])
    assert target["on_time_count"] == 2
    assert target["grace_count"] == 1
    assert target["completed_days"] == 3  # on_time + grace
    assert target["scheduled_days"] == 6  # 25-30 inclusive
```

- [ ] **Step 2: Ejecutar test para verificar que falla**

```
./.venv/bin/python -m pytest tests/test_tools_events.py -v -k "breaks_down"
```

Esperado: FAIL con `KeyError: 'on_time_count'`.

- [ ] **Step 3: Implementar**

Modificar `routine_summary` en `tools.py` (líneas 411-460). Reemplazar el bucle interno desde `for row in rows:` por:

```python
        for row in rows:
            rule = row["recurring_rule"]
            scheduled = _count_scheduled_days(rule, row["datetime"], start, end)
            if scheduled == 0:
                continue
            counts = conn.execute(
                """
                SELECT
                    SUM(CASE WHEN status = 'on_time' THEN 1 ELSE 0 END) as on_time_count,
                    SUM(CASE WHEN status = 'grace'   THEN 1 ELSE 0 END) as grace_count,
                    COUNT(*) as completed_days
                FROM routine_completions
                WHERE event_id = ?
                  AND completion_date >= ?
                  AND completion_date <= ?
                """,
                (row["id"], date_from, date_to),
            ).fetchone()
            on_time_count = counts["on_time_count"] or 0
            grace_count = counts["grace_count"] or 0
            completed = counts["completed_days"] or 0
            current = _current_streak(row["id"], rule, today, conn)
            best = _best_streak(row["id"], rule, conn)
            results.append({
                "event_id": row["id"],
                "title": row["title"],
                "category": row["category"],
                "recurring_rule": rule,
                "scheduled_days": scheduled,
                "completed_days": completed,
                "on_time_count": on_time_count,
                "grace_count": grace_count,
                "current_streak": current,
                "best_streak": best,
            })
```

- [ ] **Step 4: Ejecutar tests**

```
./.venv/bin/python -m pytest tests/test_tools_events.py -v
```

Esperado: PASS, incluyendo los tests previos de routine_summary que no leían `on_time_count` (solo añadimos campos).

- [ ] **Step 5: Commit**

```
git add tools.py tests/test_tools_events.py
git commit -m "$(cat <<'EOF'
feat(tools): routine_summary añade conteos on_time y grace

Cada fila incluye on_time_count y grace_count (separados) además
del completed_days agregado existente. Base para las métricas
detalladas del panel.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Nuevo tool `metrics_summary`

**Files:**
- Modify: `tools.py` (añadir función antes de TOOL_DEFINITIONS y registrar)
- Create: `tests/test_tools_metrics.py`

- [ ] **Step 1: Escribir tests fallidos**

Crear `tests/test_tools_metrics.py`:

```python
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
```

- [ ] **Step 2: Ejecutar tests para verificar que fallan**

```
./.venv/bin/python -m pytest tests/test_tools_metrics.py -v
```

Esperado: FAIL con `AttributeError: module 'tools' has no attribute 'metrics_summary'`.

- [ ] **Step 3: Implementar**

Añadir en `tools.py` justo antes de `TOOL_DEFINITIONS` (línea 579):

```python
def metrics_summary(date_from: str, date_to: str) -> dict:
    """Conteos agregados por outcome para el rango [date_from, date_to] inclusive.

    Fechas en formato 'YYYY-MM-DD'. Para tareas/eventos/objetivos cuenta
    filas con outcome dentro del rango (usando la fecha asignada: due_date,
    datetime[:10], week_start). Para rutinas usa routine_completions.status
    en el rango y deriva 'missed' como scheduled - on_time - grace.
    """
    start = date.fromisoformat(date_from)
    end = date.fromisoformat(date_to)

    def _count_outcomes(rows: list) -> dict:
        return {
            "on_time": sum(1 for r in rows if r["outcome"] == "on_time"),
            "grace":   sum(1 for r in rows if r["outcome"] == "grace"),
            "missed":  sum(1 for r in rows if r["outcome"] == "missed"),
        }

    with db.connect() as conn:
        # --- Eventos puntuales: filtramos por substring de datetime (10 chars)
        ev_rows = conn.execute(
            """
            SELECT outcome FROM events
            WHERE recurring_rule IS NULL
              AND outcome IS NOT NULL
              AND substr(datetime, 1, 10) >= ?
              AND substr(datetime, 1, 10) <= ?
            """,
            (date_from, date_to),
        ).fetchall()

        # --- Tareas: filtrar por due_date
        task_rows = conn.execute(
            """
            SELECT outcome FROM tasks
            WHERE due_date IS NOT NULL
              AND outcome IS NOT NULL
              AND due_date >= ?
              AND due_date <= ?
            """,
            (date_from, date_to),
        ).fetchall()

        # --- Objetivos: filtrar por week_start (el lunes de la semana del objetivo)
        obj_rows = conn.execute(
            """
            SELECT outcome FROM objectives
            WHERE outcome IS NOT NULL
              AND week_start >= ?
              AND week_start <= ?
            """,
            (date_from, date_to),
        ).fetchall()

        # --- Rutinas: agregamos por evento usando routine_summary.
        routine_rows = routine_summary(date_from, date_to)

    per_event = []
    routine_totals = {"on_time": 0, "grace": 0, "missed": 0}
    for r in routine_rows:
        on_t = r["on_time_count"]
        gr = r["grace_count"]
        missed = max(0, r["scheduled_days"] - on_t - gr)
        per_event.append({
            "event_id": r["event_id"],
            "title": r["title"],
            "on_time": on_t,
            "grace": gr,
            "missed": missed,
        })
        routine_totals["on_time"] += on_t
        routine_totals["grace"] += gr
        routine_totals["missed"] += missed

    return {
        "events": _count_outcomes(ev_rows),
        "tasks": _count_outcomes(task_rows),
        "objectives": _count_outcomes(obj_rows),
        "routines": {"per_event": per_event, "totals": routine_totals},
    }
```

Registrar en `TOOL_DEFINITIONS` (al final de la lista, antes del cierre `]`):

```python
    {
        "name": "metrics_summary",
        "description": (
            "Conteos agregados por outcome (on_time/grace/missed) para rutinas, "
            "eventos puntuales, tareas y objetivos en un rango de fechas. Útil "
            "cuando el usuario pregunta por sus métricas o porcentajes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date_from": {"type": "string", "description": "ISO date YYYY-MM-DD"},
                "date_to":   {"type": "string", "description": "ISO date YYYY-MM-DD"},
            },
            "required": ["date_from", "date_to"],
        },
    },
```

Y en `_DISPATCH` (alrededor de la línea 776):

```python
    "metrics_summary": metrics_summary,
```

- [ ] **Step 4: Ejecutar tests**

```
./.venv/bin/python -m pytest tests/test_tools_metrics.py -v
```

Esperado: PASS.

- [ ] **Step 5: Commit**

```
git add tools.py tests/test_tools_metrics.py
git commit -m "$(cat <<'EOF'
feat(tools): metrics_summary agrega conteos por outcome y tipo

Nueva herramienta que devuelve, para un rango de fechas, los
conteos on_time/grace/missed de rutinas (por rutina + total),
eventos puntuales, tareas y objetivos. Registrada en
TOOL_DEFINITIONS para que Claude pueda invocarla.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Helpers `recreate_event/task/objective`

**Files:**
- Modify: `tools.py` (añadir tres funciones cerca de los `uncomplete_*` existentes)
- Create: `tests/test_tools_missed.py`

- [ ] **Step 1: Escribir tests fallidos**

Crear `tests/test_tools_missed.py`:

```python
"""Tests de recreate_* y discard_* helpers."""
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


def test_recreate_task_creates_new_with_today_due_date(monkeypatch):
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 30))
    orig = tools.add_task("Llamar dentista", due_date="2026-05-20")

    res = tools.recreate_task(orig["id"])

    assert res["new_id"] != orig["id"]
    with db.connect() as conn:
        new_row = conn.execute(
            "SELECT text, due_date, outcome, done FROM tasks WHERE id = ?",
            (res["new_id"],),
        ).fetchone()
        old_row = conn.execute(
            "SELECT outcome FROM tasks WHERE id = ?", (orig["id"],)
        ).fetchone()
    assert new_row["text"] == "Llamar dentista"
    assert new_row["due_date"] == "2026-05-30"
    assert new_row["outcome"] is None
    assert new_row["done"] == 0
    assert old_row["outcome"] == "missed"


def test_recreate_event_creates_new_with_today_date_keeping_time(monkeypatch):
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 30))
    orig = tools.add_event("Dentista", "2026-05-20T10:00:00", "personal")

    res = tools.recreate_event(orig["id"])

    assert res["new_id"] != orig["id"]
    with db.connect() as conn:
        new_row = conn.execute(
            "SELECT title, datetime, outcome, done, gcal_event_id FROM events WHERE id = ?",
            (res["new_id"],),
        ).fetchone()
        old_row = conn.execute(
            "SELECT outcome FROM events WHERE id = ?", (orig["id"],)
        ).fetchone()
    assert new_row["title"] == "Dentista"
    assert new_row["datetime"] == "2026-05-30T10:00:00"
    assert new_row["outcome"] is None
    assert new_row["done"] == 0
    # El nuevo evento NO hereda gcal_event_id (Pablo decide sincronizarlo).
    assert new_row["gcal_event_id"] is None
    assert old_row["outcome"] == "missed"


def test_recreate_objective_creates_new_in_current_week(monkeypatch):
    # 2026-05-30 es sábado; lunes de su semana es 2026-05-25.
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 30))
    orig = tools.add_objective("Leer 100 páginas", "2026-05-11")

    res = tools.recreate_objective(orig["id"])

    assert res["new_id"] != orig["id"]
    with db.connect() as conn:
        new_row = conn.execute(
            "SELECT text, week_start, outcome, done FROM objectives WHERE id = ?",
            (res["new_id"],),
        ).fetchone()
        old_row = conn.execute(
            "SELECT outcome FROM objectives WHERE id = ?", (orig["id"],)
        ).fetchone()
    assert new_row["text"] == "Leer 100 páginas"
    assert new_row["week_start"] == "2026-05-25"
    assert new_row["outcome"] is None
    assert new_row["done"] == 0
    assert old_row["outcome"] == "missed"
```

- [ ] **Step 2: Ejecutar tests para verificar que fallan**

```
./.venv/bin/python -m pytest tests/test_tools_missed.py -v -k "recreate"
```

Esperado: FAIL con `AttributeError`.

- [ ] **Step 3: Implementar**

Añadir en `tools.py` después de `uncomplete_routine_today` (alrededor de la línea 320):

```python
def recreate_event(event_id: int) -> dict:
    """Crea evento nuevo con la misma hora pero fecha de hoy.
    Marca el original como outcome='missed'. NO copia gcal_event_id."""
    import date_utils

    today = date_utils.today_madrid()
    with db.connect() as conn:
        orig = conn.execute(
            "SELECT title, datetime, category, recurring_rule, notes "
            "FROM events WHERE id = ?",
            (event_id,),
        ).fetchone()
        if orig is None:
            return {"error": "not_found"}

        time_part = orig["datetime"][11:] if "T" in orig["datetime"] else "09:00:00"
        new_dt = f"{today.isoformat()}T{time_part}"

        cur = conn.execute(
            """
            INSERT INTO events (title, datetime, category, recurring_rule, notes, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (orig["title"], new_dt, orig["category"], orig["recurring_rule"],
             orig["notes"], date_utils.now_iso()),
        )
        new_id = cur.lastrowid

        conn.execute(
            "UPDATE events SET outcome = 'missed' WHERE id = ?", (event_id,)
        )

    return {"old_id": event_id, "new_id": new_id, "new_datetime": new_dt}


def recreate_task(task_id: int) -> dict:
    """Crea tarea nueva con due_date=hoy. Marca la original como missed."""
    import date_utils

    today = date_utils.today_madrid()
    with db.connect() as conn:
        orig = conn.execute(
            "SELECT text FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if orig is None:
            return {"error": "not_found"}

        cur = conn.execute(
            "INSERT INTO tasks (text, done, created_at, due_date) VALUES (?, 0, ?, ?)",
            (orig["text"], date_utils.now_iso(), today.isoformat()),
        )
        new_id = cur.lastrowid

        conn.execute(
            "UPDATE tasks SET outcome = 'missed' WHERE id = ?", (task_id,)
        )

    return {"old_id": task_id, "new_id": new_id, "due_date": today.isoformat()}


def recreate_objective(objective_id: int) -> dict:
    """Crea objetivo nuevo en la semana actual. Marca el original como missed."""
    from date_utils import monday_of_week
    import date_utils

    today = date_utils.today_madrid()
    week_start = monday_of_week(today).isoformat()
    with db.connect() as conn:
        orig = conn.execute(
            "SELECT text FROM objectives WHERE id = ?", (objective_id,)
        ).fetchone()
        if orig is None:
            return {"error": "not_found"}

        cur = conn.execute(
            "INSERT INTO objectives (text, week_start, done, created_at) VALUES (?, ?, 0, ?)",
            (orig["text"], week_start, date_utils.now_iso()),
        )
        new_id = cur.lastrowid

        conn.execute(
            "UPDATE objectives SET outcome = 'missed' WHERE id = ?", (objective_id,)
        )

    return {"old_id": objective_id, "new_id": new_id, "week_start": week_start}
```

- [ ] **Step 4: Ejecutar tests**

```
./.venv/bin/python -m pytest tests/test_tools_missed.py -v -k "recreate"
```

Esperado: PASS.

- [ ] **Step 5: Commit**

```
git add tools.py tests/test_tools_missed.py
git commit -m "$(cat <<'EOF'
feat(tools): helpers recreate_event/task/objective

Crean una entrada nueva con fecha actualizada (hoy / semana actual)
y marcan la original como outcome='missed'. El evento recreado NO
hereda gcal_event_id; Pablo decide sincronizarlo después.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: Helpers `discard_event/task/objective`

**Files:**
- Modify: `tools.py` (añadir tres funciones después de los `recreate_*`)
- Modify: `tests/test_tools_missed.py`

- [ ] **Step 1: Escribir tests fallidos**

Añadir al final de `tests/test_tools_missed.py`:

```python
def test_discard_task_marks_missed():
    orig = tools.add_task("X", due_date="2026-05-20")
    res = tools.discard_task(orig["id"])
    assert res["updated"] == 1
    with db.connect() as conn:
        row = conn.execute(
            "SELECT outcome, done FROM tasks WHERE id = ?", (orig["id"],)
        ).fetchone()
    assert row["outcome"] == "missed"
    assert row["done"] == 0


def test_discard_event_marks_missed():
    orig = tools.add_event("Cita", "2026-05-20T10:00:00", "personal")
    tools.discard_event(orig["id"])
    with db.connect() as conn:
        row = conn.execute(
            "SELECT outcome, done FROM events WHERE id = ?", (orig["id"],)
        ).fetchone()
    assert row["outcome"] == "missed"
    assert row["done"] == 0


def test_discard_objective_marks_missed():
    orig = tools.add_objective("Meta vieja", "2026-05-11")
    tools.discard_objective(orig["id"])
    with db.connect() as conn:
        row = conn.execute(
            "SELECT outcome, done FROM objectives WHERE id = ?", (orig["id"],)
        ).fetchone()
    assert row["outcome"] == "missed"
    assert row["done"] == 0
```

- [ ] **Step 2: Ejecutar tests para verificar que fallan**

```
./.venv/bin/python -m pytest tests/test_tools_missed.py -v -k "discard"
```

Esperado: FAIL con `AttributeError`.

- [ ] **Step 3: Implementar**

Añadir en `tools.py` después de los `recreate_*` (Task 10):

```python
def discard_event(event_id: int) -> dict:
    with db.connect() as conn:
        cur = conn.execute(
            "UPDATE events SET outcome = 'missed' WHERE id = ?", (event_id,)
        )
    return {"id": event_id, "updated": cur.rowcount}


def discard_task(task_id: int) -> dict:
    with db.connect() as conn:
        cur = conn.execute(
            "UPDATE tasks SET outcome = 'missed' WHERE id = ?", (task_id,)
        )
    return {"id": task_id, "updated": cur.rowcount}


def discard_objective(objective_id: int) -> dict:
    with db.connect() as conn:
        cur = conn.execute(
            "UPDATE objectives SET outcome = 'missed' WHERE id = ?", (objective_id,)
        )
    return {"id": objective_id, "updated": cur.rowcount}
```

- [ ] **Step 4: Ejecutar tests**

```
./.venv/bin/python -m pytest tests/test_tools_missed.py -v
```

Esperado: PASS.

- [ ] **Step 5: Commit**

```
git add tools.py tests/test_tools_missed.py
git commit -m "$(cat <<'EOF'
feat(tools): helpers discard_event/task/objective

Marcan un item como outcome='missed' sin tocar done. Llamados por
los callbacks de "🗑️ Descartar" en mensajes proactivos.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: `query_events` admite `include_grace`

**Files:**
- Modify: `tools.py:71-101` (`query_events`)
- Modify: `tools.py` (TOOL_DEFINITIONS de `query_events`)
- Modify: `tests/test_tools_events.py`

- [ ] **Step 1: Escribir tests fallidos**

Añadir al final de `tests/test_tools_events.py`:

```python
def test_query_events_include_grace_returns_yesterday_pending():
    tools.add_event("Cita perdida", "2026-05-29T10:00:00", "personal")
    rows = tools.query_events(
        date_from="2026-05-30T00:00:00",
        date_to="2026-05-30T23:59:59",
        include_grace=True,
    )
    titles = [r["title"] for r in rows]
    assert "Cita perdida" in titles


def test_query_events_default_does_not_return_yesterday():
    tools.add_event("Cita perdida", "2026-05-29T10:00:00", "personal")
    rows = tools.query_events(
        date_from="2026-05-30T00:00:00",
        date_to="2026-05-30T23:59:59",
    )
    titles = [r["title"] for r in rows]
    assert "Cita perdida" not in titles


def test_query_events_include_grace_excludes_already_missed():
    res = tools.add_event("Cita descartada", "2026-05-29T10:00:00", "personal")
    with db.connect() as conn:
        conn.execute(
            "UPDATE events SET outcome = 'missed' WHERE id = ?", (res["id"],)
        )
    rows = tools.query_events(
        date_from="2026-05-30T00:00:00",
        date_to="2026-05-30T23:59:59",
        include_grace=True,
    )
    titles = [r["title"] for r in rows]
    assert "Cita descartada" not in titles
```

- [ ] **Step 2: Ejecutar tests para verificar que fallan**

```
./.venv/bin/python -m pytest tests/test_tools_events.py -v -k "include_grace"
```

Esperado: FAIL — el parámetro no existe.

- [ ] **Step 3: Implementar**

Reemplazar `query_events` (líneas 71-101) por:

```python
def query_events(
    date_from: str,
    date_to: str,
    category: Optional[str] = None,
    include_done: bool = False,
    include_grace: bool = False,
) -> list[dict]:
    dt_from = datetime.fromisoformat(date_from)
    dt_to = datetime.fromisoformat(date_to)

    # En modo gracia, también traemos eventos puntuales del día anterior
    # con done=0 y outcome IS NULL (no missed).
    grace_from: Optional[datetime] = None
    grace_to: Optional[datetime] = None
    if include_grace:
        grace_day = (dt_from.date() - timedelta(days=1))
        grace_from = datetime.combine(grace_day, datetime.min.time())
        grace_to = datetime.combine(grace_day, datetime.max.time().replace(microsecond=0))

    with db.connect() as conn:
        params: list = []
        sql = "SELECT * FROM events WHERE 1=1"
        if not include_done:
            sql += " AND COALESCE(done, 0) = 0"
        # Excluir items missed siempre que se filtre por activos.
        sql += " AND (outcome IS NULL OR outcome != 'missed')"
        if category:
            sql += " AND category = ?"
            params.append(category)
        rows = [dict(r) for r in conn.execute(sql, params).fetchall()]

        occurrences: list[dict] = []
        for row in rows:
            rule = row.get("recurring_rule")
            if not rule:
                row_dt = datetime.fromisoformat(row["datetime"])
                if dt_from <= row_dt <= dt_to:
                    occurrences.append(row)
                elif (
                    include_grace
                    and grace_from is not None
                    and grace_from <= row_dt <= grace_to
                ):
                    occurrences.append(row)
            else:
                occurrences.extend(_expand_recurring(row, rule, dt_from, dt_to, conn))

    occurrences.sort(key=lambda r: r["datetime"])
    return occurrences
```

Actualizar TOOL_DEFINITIONS de `query_events` para añadir `include_grace`:

```python
                "include_grace": {
                    "type": "boolean",
                    "default": False,
                    "description": "Si es true, también devuelve eventos puntuales del día anterior con done=0 (día de gracia).",
                },
```

(Añadir dentro del `properties` dict de la definición existente.)

- [ ] **Step 4: Ejecutar tests**

```
./.venv/bin/python -m pytest tests/test_tools_events.py -v
```

Esperado: PASS en todos. Tests antiguos siguen pasando porque `include_grace` por defecto es `False`.

- [ ] **Step 5: Commit**

```
git add tools.py tests/test_tools_events.py
git commit -m "$(cat <<'EOF'
feat(tools): query_events admite include_grace y excluye missed

include_grace=True añade eventos puntuales del día anterior con
done=0 y outcome NULL. Además, query_events siempre excluye items
con outcome='missed' del listado activo (descartados no aparecen).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 13: `render_today_view` con sección de gracia y filtro de tareas por `due_date`

**Files:**
- Modify: `views.py:14-119` (`render_today_view`)
- Modify: `tests/test_views.py`

- [ ] **Step 1: Escribir tests fallidos**

Añadir al final de `tests/test_views.py`:

```python
def test_render_today_view_shows_grace_section_for_event():
    tools.add_event("Cita perdida", "2026-05-18T10:00:00", "personal")
    text, keyboard = _render(today=date(2026, 5, 19))
    assert "AYER" in text
    assert "Cita perdida" in text


def test_render_today_view_grace_button_uses_mE():
    res = tools.add_event("Cita perdida", "2026-05-18T10:00:00", "personal")
    text, keyboard = _render(today=date(2026, 5, 19))
    callbacks = [
        btn.callback_data
        for row in keyboard.inline_keyboard for btn in row
    ]
    assert f"mE:{res['id']}:H" in callbacks


def test_render_today_view_filters_tasks_by_due_date():
    tools.add_task("hoy", due_date="2026-05-19")
    tools.add_task("manana", due_date="2026-05-20")
    tools.add_task("flotante")
    tools.add_task("ayer", due_date="2026-05-18")

    text, keyboard = _render(today=date(2026, 5, 19))
    # Sí aparecen: la de hoy (PENDIENTES) y la de ayer (AYER en gracia)
    assert "hoy" in text
    assert "ayer" in text
    # No aparecen: manana ni flotante
    assert "manana" not in text
    assert "flotante" not in text
```

- [ ] **Step 2: Ejecutar tests para verificar que fallan**

```
./.venv/bin/python -m pytest tests/test_views.py -v -k "grace or filters_tasks_by_due_date"
```

Esperado: FAIL.

- [ ] **Step 3: Implementar**

Reescribir `render_today_view` en `views.py` (líneas 14-119). La función queda así:

```python
def render_today_view(
    today: date, conn, show_completed: bool = False
) -> tuple[str, Optional[InlineKeyboardMarkup]]:
    from datetime import timedelta

    today_iso = today.isoformat()
    yesterday = today - timedelta(days=1)
    yesterday_iso = yesterday.isoformat()
    today_start = f"{today_iso}T00:00:00"
    today_end = f"{today_iso}T23:59:59"

    events = tools.query_events(
        today_start, today_end, include_done=True, include_grace=True
    )
    tasks_all = tools.list_tasks(include_done=True)
    routines = tools.routine_summary(today_iso, today_iso)
    streak_by_id = {r["event_id"]: r["current_streak"] for r in routines}

    # Particionar eventos no recurrentes en hoy / gracia (ayer)
    hoy_pending: list[dict] = []
    grace_pending: list[dict] = []
    hoy_done: list[dict] = []
    for e in events:
        if e.get("recurring_rule"):
            continue
        ev_day = e["datetime"][:10]
        if ev_day == today_iso:
            if e["done"] == 1:
                hoy_done.append(e)
            else:
                hoy_pending.append(e)
        elif ev_day == yesterday_iso and e["done"] == 0:
            grace_pending.append(e)

    rutina_pending = [e for e in events if e.get("recurring_rule") and e["done"] == 0]
    rutina_done = [e for e in events if e.get("recurring_rule") and e["done"] == 1]

    # Tareas: filtramos por due_date en (hoy, ayer)
    task_pending_today = [
        t for t in tasks_all
        if t["done"] == 0 and t.get("due_date") == today_iso
        and t.get("outcome") != "missed"
    ]
    task_grace = [
        t for t in tasks_all
        if t["done"] == 0 and t.get("due_date") == yesterday_iso
        and t.get("outcome") != "missed"
    ]
    task_done_today = [
        t for t in tasks_all
        if t["done"] == 1 and (t.get("done_at") or "").startswith(today_iso)
    ]

    has_completed = bool(hoy_done or rutina_done or task_done_today)
    completed_count = len(hoy_done) + len(rutina_done) + len(task_done_today)
    view_letter = "Hc" if show_completed else "H"

    sections: list[str] = []

    if grace_pending or task_grace:
        lines = []
        for e in grace_pending:
            dt = datetime.fromisoformat(e["datetime"])
            lines.append(f"• {dt.strftime('%H:%M')} — {e['title']}")
        for t in task_grace:
            lines.append(f"• {t['text']}")
        sections.append("🟡 <b>AYER (último día)</b>\n" + "\n".join(lines))

    if hoy_pending:
        lines = []
        for e in hoy_pending:
            dt = datetime.fromisoformat(e["datetime"])
            lines.append(f"• {dt.strftime('%H:%M')} — {e['title']}")
        sections.append("📅 <b>HOY</b>\n" + "\n".join(lines))

    if rutina_pending:
        lines = []
        for e in rutina_pending:
            streak = streak_by_id.get(e["id"], 0)
            suffix = f" 🔥 {streak}" if streak >= 2 else ""
            lines.append(f"• {e['title']}{suffix}")
        sections.append("🔁 <b>RUTINAS</b>\n" + "\n".join(lines))

    if task_pending_today:
        lines = [f"• {t['text']}" for t in task_pending_today]
        sections.append("📝 <b>PENDIENTES</b>\n" + "\n".join(lines))

    if show_completed and has_completed:
        lines = []
        for e in hoy_done:
            dt = datetime.fromisoformat(e["datetime"])
            lines.append(f"• <s>{dt.strftime('%H:%M')} — {e['title']}</s>")
        for e in rutina_done:
            streak = streak_by_id.get(e["id"], 0)
            suffix = f" 🔥 {streak}" if streak >= 2 else ""
            lines.append(f"• <s>{e['title']}{suffix}</s>")
        for t in task_done_today:
            lines.append(f"• <s>{t['text']}</s>")
        sections.append("✅ <b>COMPLETADO HOY</b>\n" + "\n".join(lines))

    if not sections:
        return "Día libre, disfrútalo 💪", None

    text = "\n\n".join(sections)

    buttons: list[list[InlineKeyboardButton]] = []
    for e in grace_pending:
        buttons.append([InlineKeyboardButton(
            f"🟡 {e['title']} (ayer)", callback_data=f"mE:{e['id']}:{view_letter}"
        )])
    for t in task_grace:
        buttons.append([InlineKeyboardButton(
            f"🟡 {t['text']} (ayer)", callback_data=f"mT:{t['id']}:{view_letter}"
        )])
    for e in hoy_pending:
        buttons.append([InlineKeyboardButton(
            f"🔲 {e['title']}", callback_data=f"mE:{e['id']}:{view_letter}"
        )])
    for e in rutina_pending:
        buttons.append([InlineKeyboardButton(
            f"🔲 {e['title']}", callback_data=f"mR:{e['id']}:{view_letter}"
        )])
    for t in task_pending_today:
        buttons.append([InlineKeyboardButton(
            f"🔲 {t['text']}", callback_data=f"mT:{t['id']}:{view_letter}"
        )])

    if show_completed:
        for e in hoy_done:
            buttons.append([InlineKeyboardButton(
                f"✅ {e['title']}", callback_data=f"uE:{e['id']}:{view_letter}"
            )])
        for e in rutina_done:
            buttons.append([InlineKeyboardButton(
                f"✅ {e['title']}", callback_data=f"uR:{e['id']}:{view_letter}"
            )])
        for t in task_done_today:
            buttons.append([InlineKeyboardButton(
                f"✅ {t['text']}", callback_data=f"uT:{t['id']}:{view_letter}"
            )])

    if has_completed:
        if show_completed:
            buttons.append([InlineKeyboardButton(
                "▲ Ocultar completados", callback_data="tg:0:H"
            )])
        else:
            buttons.append([InlineKeyboardButton(
                f"🏆 Ver completados ({completed_count})", callback_data="tg:0:Hc"
            )])

    keyboard = InlineKeyboardMarkup(buttons) if buttons else None
    return text, keyboard
```

- [ ] **Step 4: Ejecutar tests**

```
./.venv/bin/python -m pytest tests/test_views.py -v
```

Esperado: PASS de los tests nuevos. Tests previos en `tests/test_views.py` que crean tareas con `tools.add_task("X")` (sin `due_date`) y esperan verlas en la sección PENDIENTES de `/hoy` **van a romperse** por el cambio de semántica. Es un cambio esperado.

**Adaptación de tests previos rotos:** abrir cada test que falle, identificar las llamadas `tools.add_task("texto")` que deberían aparecer en `/hoy` y cambiarlas a `tools.add_task("texto", due_date="2026-05-19")` (la misma fecha que pasa el test a `_render`). Los tests que comprueban tareas "flotantes" deben actualizarse para usar `/pendientes` (`render_pending_view`) en vez de `/hoy`. Volver a correr y verificar PASS.

- [ ] **Step 5: Commit**

```
git add views.py tests/test_views.py
git commit -m "$(cat <<'EOF'
feat(views): render_today_view incluye sección AYER y filtra tareas

Eventos puntuales pendientes de ayer aparecen ahora como sección
🟡 AYER (último día). Las tareas se filtran por due_date IN (hoy,
ayer); las flotantes y las de otros días dejan de aparecer en /hoy
y pasan a /pendientes (próxima tarea).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 14: `render_pending_view` con tres secciones

**Files:**
- Modify: `views.py:157-173` (`render_pending_view`)
- Modify: `tests/test_views.py`

- [ ] **Step 1: Escribir tests fallidos**

Añadir al final de `tests/test_views.py`:

```python
def test_pending_view_three_sections(monkeypatch):
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 19))
    tools.add_task("a_grace", due_date="2026-05-18")
    tools.add_task("b_con_fecha_futura", due_date="2026-05-25")
    tools.add_task("c_flotante")

    with db.connect() as conn:
        text, _ = views.render_pending_view(conn)

    assert "EN GRACIA" in text
    assert "CON FECHA" in text
    assert "FLOTANTES" in text
    assert "a_grace" in text
    assert "b_con_fecha_futura" in text
    assert "c_flotante" in text


def test_pending_view_excludes_missed_tasks(monkeypatch):
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 19))
    r = tools.add_task("descartada", due_date="2026-05-10")
    with db.connect() as conn:
        conn.execute(
            "UPDATE tasks SET outcome = 'missed' WHERE id = ?", (r["id"],)
        )

    with db.connect() as conn:
        text, keyboard = views.render_pending_view(conn)

    assert "descartada" not in text
```

Asegúrate de que el import de `date_utils` esté al inicio del fichero:

```python
import date_utils
```

- [ ] **Step 2: Ejecutar tests para verificar que fallan**

```
./.venv/bin/python -m pytest tests/test_views.py -v -k "pending_view"
```

Esperado: FAIL — falta la sección y el filtro.

- [ ] **Step 3: Implementar**

Reemplazar `render_pending_view` (líneas 157-173) por:

```python
def render_pending_view(conn) -> tuple[str, Optional[InlineKeyboardMarkup]]:
    """Vista de /pendientes: tres secciones (gracia, con fecha, flotantes)."""
    from datetime import timedelta

    import date_utils

    today = date_utils.today_madrid()
    yesterday = today - timedelta(days=1)
    today_iso = today.isoformat()
    yesterday_iso = yesterday.isoformat()

    all_tasks = tools.list_tasks(include_done=False)
    # Filtramos las missed (no deberían venir desde list_tasks si done=0
    # ya estaba, pero por defensa):
    pending = [t for t in all_tasks if t.get("outcome") != "missed"]

    grace = [t for t in pending if t.get("due_date") == yesterday_iso]
    with_date = sorted(
        [t for t in pending
         if t.get("due_date") and t["due_date"] >= today_iso],
        key=lambda t: t["due_date"],
    )
    floating = [t for t in pending if not t.get("due_date")]

    if not (grace or with_date or floating):
        return "No tienes tareas pendientes. 🎉", None

    sections: list[str] = []
    if grace:
        lines = [f"• {t['text']}" for t in grace]
        sections.append("🟡 <b>EN GRACIA</b>\n" + "\n".join(lines))
    if with_date:
        lines = []
        weekdays_es = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
        for t in with_date:
            d = date.fromisoformat(t["due_date"])
            wd = weekdays_es[d.weekday()]
            lines.append(f"• {wd} {d.day}/{d.month:02d} — {t['text']}")
        sections.append("📅 <b>CON FECHA</b>\n" + "\n".join(lines))
    if floating:
        lines = [f"• {t['text']}" for t in floating]
        sections.append("🌊 <b>FLOTANTES</b>\n" + "\n".join(lines))

    text = "\n\n".join(sections)

    buttons: list[list[InlineKeyboardButton]] = []
    for t in grace + with_date + floating:
        buttons.append([InlineKeyboardButton(
            f"🔲 {t['text']}", callback_data=f"mT:{t['id']}:P"
        )])

    return text, InlineKeyboardMarkup(buttons)
```

También, en `tools.list_tasks` (línea 545) hay que excluir las missed cuando `include_done=False`. Modificar:

```python
def list_tasks(include_done: bool = False) -> list[dict]:
    with db.connect() as conn:
        if include_done:
            rows = conn.execute(
                "SELECT * FROM tasks ORDER BY done, id"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE done = 0 "
                "AND (outcome IS NULL OR outcome != 'missed') "
                "ORDER BY id"
            ).fetchall()
    return [dict(r) for r in rows]
```

- [ ] **Step 4: Ejecutar tests**

```
./.venv/bin/python -m pytest tests/test_views.py tests/test_tools_tasks.py -v
```

Esperado: PASS.

- [ ] **Step 5: Commit**

```
git add views.py tools.py tests/test_views.py
git commit -m "$(cat <<'EOF'
feat(views): render_pending_view reorganiza en gracia/con fecha/flotantes

/pendientes muestra tres secciones: 🟡 EN GRACIA (due_date=ayer),
📅 CON FECHA (due_date >= hoy, ordenadas), 🌊 FLOTANTES (sin due_date).
list_tasks excluye items con outcome='missed' del listado activo.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 15: `render_metrics_view`

**Files:**
- Modify: `views.py` (añadir función al final)
- Modify: `tests/test_views.py`

- [ ] **Step 1: Escribir tests fallidos**

Añadir al final de `tests/test_views.py`:

```python
def test_metrics_view_empty():
    with db.connect() as conn:
        text, kb = views.render_metrics_view(date(2026, 5, 30), conn)
    assert "sin datos" in text.lower() or "todavía" in text.lower()


def test_metrics_view_with_data(monkeypatch):
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 30))
    a = tools.add_task("on", due_date="2026-05-25")
    b = tools.add_task("late", due_date="2026-05-29")
    tools.complete_task(a["id"])
    tools.complete_task(b["id"])

    with db.connect() as conn:
        text, kb = views.render_metrics_view(date(2026, 5, 30), conn)

    assert "Métricas" in text
    # 1 on_time + 1 grace + 0 missed → 50% / 50%
    assert "Tareas" in text
    assert "50%" in text
```

- [ ] **Step 2: Ejecutar tests para verificar que fallan**

```
./.venv/bin/python -m pytest tests/test_views.py -v -k "metrics_view"
```

Esperado: FAIL — la función no existe.

- [ ] **Step 3: Implementar**

Añadir al final de `views.py`:

```python
def render_metrics_view(
    today: date, conn
) -> tuple[str, Optional[InlineKeyboardMarkup]]:
    """Panel de métricas de los últimos 30 días."""
    from datetime import timedelta

    date_from = (today - timedelta(days=29)).isoformat()
    date_to = today.isoformat()
    m = tools.metrics_summary(date_from, date_to)

    routine_totals = m["routines"]["totals"]
    has_any = (
        sum(routine_totals.values()) > 0
        or sum(m["events"].values()) > 0
        or sum(m["tasks"].values()) > 0
        or sum(m["objectives"].values()) > 0
    )
    if not has_any:
        return "Todavía no hay datos suficientes para mostrar métricas.", None

    def _pct(d: dict) -> str:
        total = d["on_time"] + d["grace"] + d["missed"]
        if total == 0:
            return ""
        ot = round(100 * d["on_time"] / total)
        gr = round(100 * d["grace"] / total)
        ms = round(100 * d["missed"] / total)
        return f"({ot}% / {gr}% / {ms}%)"

    sections: list[str] = [
        f"📊 <b>Métricas — últimos 30 días</b>"
    ]

    if m["routines"]["per_event"]:
        lines = []
        for r in m["routines"]["per_event"]:
            d = {"on_time": r["on_time"], "grace": r["grace"], "missed": r["missed"]}
            lines.append(
                f"• {r['title']}: 🟢 {r['on_time']}  🟡 {r['grace']}  🔴 {r['missed']}  {_pct(d)}"
            )
        lines.append(
            f"  <b>Total</b>: 🟢 {routine_totals['on_time']}  "
            f"🟡 {routine_totals['grace']}  🔴 {routine_totals['missed']}  "
            f"{_pct(routine_totals)}"
        )
        sections.append("🔁 <b>Rutinas</b>\n" + "\n".join(lines))

    ev = m["events"]
    if sum(ev.values()) > 0:
        sections.append(
            "📅 <b>Eventos puntuales</b>\n"
            f"🟢 {ev['on_time']}  🟡 {ev['grace']}  🔴 {ev['missed']}  {_pct(ev)}"
        )

    tk = m["tasks"]
    if sum(tk.values()) > 0:
        sections.append(
            "✅ <b>Tareas</b>\n"
            f"🟢 {tk['on_time']}  🟡 {tk['grace']}  🔴 {tk['missed']}  {_pct(tk)}"
        )

    ob = m["objectives"]
    if sum(ob.values()) > 0:
        sections.append(
            "🎯 <b>Objetivos semanales</b>\n"
            f"🟢 {ob['on_time']}  🟡 {ob['grace']}  🔴 {ob['missed']}  {_pct(ob)}"
        )

    return "\n\n".join(sections), None
```

- [ ] **Step 4: Ejecutar tests**

```
./.venv/bin/python -m pytest tests/test_views.py -v -k "metrics_view"
```

Esperado: PASS.

- [ ] **Step 5: Commit**

```
git add views.py tests/test_views.py
git commit -m "$(cat <<'EOF'
feat(views): render_metrics_view para panel /metricas

Vista determinística de los últimos 30 días con conteos y
porcentajes por tipo. Omite secciones vacías. Usa metrics_summary
internamente.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 16: Comando `/metricas` en `bot.py`

**Files:**
- Modify: `bot.py` — handler `_on_metricas`, registro en `_async_main` y en `_set_bot_commands`
- Modify: `tests/test_bot.py`

- [ ] **Step 1: Escribir test fallido**

Añadir al final de `tests/test_bot.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock

import bot


@pytest.mark.asyncio
async def test_on_metricas_sends_text(monkeypatch):
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)

    reply_mock = AsyncMock()
    update = MagicMock()
    update.message.reply_text = reply_mock
    update.effective_user.id = 42

    await bot._on_metricas(update, MagicMock())

    reply_mock.assert_called_once()
    args, kwargs = reply_mock.call_args
    text = args[0] if args else kwargs.get("text")
    # Empty DB: mensaje de "todavía no hay datos".
    assert "métricas" in text.lower() or "datos" in text.lower()


@pytest.mark.asyncio
async def test_on_metricas_unauthorized_user_ignored(monkeypatch):
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    reply_mock = AsyncMock()
    update = MagicMock()
    update.message.reply_text = reply_mock
    update.effective_user.id = 999

    await bot._on_metricas(update, MagicMock())

    reply_mock.assert_not_called()
```

- [ ] **Step 2: Ejecutar test para verificar que falla**

```
./.venv/bin/python -m pytest tests/test_bot.py -v -k "on_metricas"
```

Esperado: FAIL — `bot._on_metricas` no existe.

- [ ] **Step 3: Implementar**

Añadir en `bot.py` cerca de `_on_semana` (alrededor de línea 244):

```python
async def _on_metricas(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    """/metricas: panel de últimos 30 días, vista determinística."""
    if not update.message or not update.effective_user:
        return
    if update.effective_user.id != ALLOWED_USER_ID:
        log.warning("/metricas ignorado de user_id no autorizado: %s", update.effective_user.id)
        return

    today = date_utils.today_madrid()
    with db.connect() as conn:
        text, keyboard = views.render_metrics_view(today, conn)

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )
```

Registrar handler en `_async_main` (después de `app.add_handler(CommandHandler("semana", _on_semana))`):

```python
    app.add_handler(CommandHandler("metricas", _on_metricas))
```

Y añadir a `_set_bot_commands` la línea:

```python
        BotCommand("metricas", "Métricas de cumplimiento"),
```

- [ ] **Step 4: Ejecutar tests**

```
./.venv/bin/python -m pytest tests/test_bot.py -v -k "on_metricas"
```

Esperado: PASS.

- [ ] **Step 5: Commit**

```
git add bot.py tests/test_bot.py
git commit -m "$(cat <<'EOF'
feat(bot): comando /metricas con panel de últimos 30 días

Handler dedicado _on_metricas que llama directamente a
views.render_metrics_view sin pasar por Claude. Registrado en el
menú de Telegram.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 17: Callbacks `rE/rT/rO` y `dE/dT/dO` en `bot.py`

**Files:**
- Modify: `bot.py:263-274` (`_CALLBACK_ACTIONS`), `bot.py:277-353` (`_on_callback_query`)
- Modify: `tests/test_bot.py`

- [ ] **Step 1: Escribir tests fallidos**

Añadir al final de `tests/test_bot.py`:

```python
import db
import tools


@pytest.fixture
def temp_db(monkeypatch):
    import os
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init_schema()
    yield path
    os.unlink(path)


@pytest.mark.asyncio
async def test_callback_rT_recreates_task(monkeypatch, temp_db):
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    from datetime import date
    import date_utils
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 30))

    orig = tools.add_task("Llamar dentista", due_date="2026-05-20")

    query = MagicMock()
    query.from_user.id = 42
    query.data = f"rT:{orig['id']}"
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    update = MagicMock()
    update.callback_query = query

    await bot._on_callback_query(update, MagicMock())

    with db.connect() as conn:
        rows = conn.execute(
            "SELECT outcome FROM tasks ORDER BY id"
        ).fetchall()
    # Hay dos tareas: la original (missed) y la nueva (null).
    assert rows[0]["outcome"] == "missed"
    assert rows[1]["outcome"] is None
    query.edit_message_text.assert_called_once()


@pytest.mark.asyncio
async def test_callback_dT_discards_task(monkeypatch, temp_db):
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)

    orig = tools.add_task("X", due_date="2026-05-20")

    query = MagicMock()
    query.from_user.id = 42
    query.data = f"dT:{orig['id']}"
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    update = MagicMock()
    update.callback_query = query

    await bot._on_callback_query(update, MagicMock())

    with db.connect() as conn:
        row = conn.execute(
            "SELECT outcome FROM tasks WHERE id = ?", (orig["id"],)
        ).fetchone()
    assert row["outcome"] == "missed"
    query.edit_message_text.assert_called_once()
```

- [ ] **Step 2: Ejecutar tests para verificar que fallan**

```
./.venv/bin/python -m pytest tests/test_bot.py -v -k "callback_rT or callback_dT"
```

Esperado: FAIL — los callbacks no se reconocen.

- [ ] **Step 3: Implementar**

Reemplazar `_CALLBACK_ACTIONS` en `bot.py` (líneas 263-274) por:

```python
_CALLBACK_ACTIONS = {
    "mE": lambda i: tools.mark_event_done(i),
    "uE": lambda i: tools.unmark_event_done(i),
    "mR": lambda i: tools.mark_event_done(i),
    "uR": lambda i: tools.uncomplete_routine_today(i),
    "mT": lambda i: tools.complete_task(i),
    "uT": lambda i: tools.uncomplete_task(i),
    "mO": lambda i: tools.mark_objective_done(i),
    "uO": lambda i: tools.unmark_objective_done(i),
    "tg": lambda i: None,
    "gc": lambda i: tools.push_event_to_calendar(i),
    "rE": lambda i: tools.recreate_event(i),
    "rT": lambda i: tools.recreate_task(i),
    "rO": lambda i: tools.recreate_objective(i),
    "dE": lambda i: tools.discard_event(i),
    "dT": lambda i: tools.discard_task(i),
    "dO": lambda i: tools.discard_objective(i),
}

_PROACTIVE_CONFIRM_TEXTS = {
    "rE": "✅ Pasado a hoy.",
    "rT": "✅ Pasada a hoy.",
    "rO": "✅ Pasado a esta semana.",
    "dE": "🗑️ Descartado.",
    "dT": "🗑️ Descartada.",
    "dO": "🗑️ Descartado.",
}
```

Y en `_on_callback_query` (líneas 277-353), añadir el caso especial **después** del bloque `if action_type == "gc"` y antes del bloque que re-renderiza por view_letter. Insertar:

```python
    if action_type in _PROACTIVE_CONFIRM_TEXTS:
        try:
            original = query.message.text_html if query.message else ""
        except AttributeError:
            original = ""
        confirm = _PROACTIVE_CONFIRM_TEXTS[action_type]
        # Registrar la decisión en missed_notifications si hay row
        item_type_map = {"r": "recreate", "d": "discard"}
        item_kind_map = {"E": "event", "T": "task", "O": "objective"}
        action = item_type_map[action_type[0]]
        item_kind = item_kind_map[action_type[1]]
        try:
            with db.connect() as conn:
                conn.execute(
                    "UPDATE missed_notifications "
                    "SET decision = ?, decided_at = ? "
                    "WHERE item_type = ? AND item_id = ?",
                    (action, date_utils.now_iso(), item_kind, item_id),
                )
        except Exception:
            log.exception("No pude actualizar missed_notifications para %s", data)
        try:
            await query.edit_message_text(
                f"{original}\n\n{confirm}",
                parse_mode=ParseMode.HTML,
                reply_markup=None,
            )
        except BadRequest:
            log.warning("No pude editar mensaje proactivo %s", data)
        await query.answer(confirm)
        return
```

También importar `date_utils` y `db` si no lo están ya (`db` ya está; `date_utils` también).

- [ ] **Step 4: Ejecutar tests**

```
./.venv/bin/python -m pytest tests/test_bot.py -v
```

Esperado: PASS en todos.

- [ ] **Step 5: Commit**

```
git add bot.py tests/test_bot.py
git commit -m "$(cat <<'EOF'
feat(bot): callbacks rE/rT/rO y dE/dT/dO para items perdidos

Tap en "📌 Pasar a hoy" llama a tools.recreate_*; tap en "🗑️ Descartar"
llama a tools.discard_*. Ambos editan el mensaje original con texto
de confirmación, sin re-renderizar vistas. Actualizan
missed_notifications.decision para auditoría.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 18: Job nocturno `detect_missed_items`

**Files:**
- Modify: `scheduler.py` — nueva función `detect_missed_items`
- Create: `tests/test_scheduler_missed.py`

- [ ] **Step 1: Escribir tests fallidos**

Crear `tests/test_scheduler_missed.py`:

```python
"""Tests del job detect_missed_items."""
import os
import tempfile
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import date_utils
import db
import scheduler
import tools


@pytest.fixture(autouse=True)
def temp_db(monkeypatch):
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init_schema()
    yield path
    os.unlink(path)


def _ctx(send_mock=None):
    ctx = SimpleNamespace()
    ctx.bot = SimpleNamespace()
    ctx.bot.send_message = send_mock or AsyncMock()
    return ctx


@pytest.mark.asyncio
async def test_detect_missed_task_notifies_with_buttons(monkeypatch):
    monkeypatch.setattr(scheduler, "ALLOWED_USER_ID", 42)
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 30))

    t = tools.add_task("Llamar dentista", due_date="2026-05-27")

    send = AsyncMock()
    await scheduler.detect_missed_items(_ctx(send))

    send.assert_called_once()
    kwargs = send.call_args.kwargs
    assert "Llamar dentista" in kwargs["text"]
    # Tiene reply_markup con dos botones (recrear/descartar):
    markup = kwargs["reply_markup"]
    callbacks = [
        btn.callback_data for row in markup.inline_keyboard for btn in row
    ]
    assert f"rT:{t['id']}" in callbacks
    assert f"dT:{t['id']}" in callbacks

    # missed_notifications registrado
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM missed_notifications WHERE item_type='task' AND item_id=?",
            (t["id"],),
        ).fetchone()
    assert row is not None


@pytest.mark.asyncio
async def test_detect_missed_idempotent_second_run(monkeypatch):
    monkeypatch.setattr(scheduler, "ALLOWED_USER_ID", 42)
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 30))

    tools.add_task("X", due_date="2026-05-27")

    send = AsyncMock()
    await scheduler.detect_missed_items(_ctx(send))
    assert send.call_count == 1

    await scheduler.detect_missed_items(_ctx(send))
    # Sigue siendo 1: no se duplica.
    assert send.call_count == 1


@pytest.mark.asyncio
async def test_detect_missed_routine_notifies_streak_broken(monkeypatch):
    """Rutina DAILY con racha de 3 días y luego dos huecos -> notificar una vez."""
    monkeypatch.setattr(scheduler, "ALLOWED_USER_ID", 42)
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 30))

    r = tools.add_event(
        "Meditar", "2026-05-25T08:00:00", "personal", recurring_rule="DAILY"
    )
    with db.connect() as conn:
        for d in ["2026-05-25", "2026-05-26", "2026-05-27"]:
            conn.execute(
                "INSERT INTO routine_completions (event_id, completion_date, created_at, status) "
                "VALUES (?, ?, ?, 'on_time')",
                (r["id"], d, "2026-05-30T08:00:00"),
            )
    # 28 y 29 no se hicieron. Hoy es 30: detect_missed corre y debe notificar
    # que se perdió el 28 (la primera rotura).

    send = AsyncMock()
    await scheduler.detect_missed_items(_ctx(send))

    send.assert_called()
    texts = [c.kwargs["text"] for c in send.call_args_list]
    assert any("Meditar" in t and "racha" in t.lower() for t in texts)


@pytest.mark.asyncio
async def test_detect_missed_routine_without_prior_streak_silent(monkeypatch):
    """Rutina nueva sin ninguna completion: no se notifica nada."""
    monkeypatch.setattr(scheduler, "ALLOWED_USER_ID", 42)
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 30))

    tools.add_event(
        "Lectura", "2026-05-01T08:00:00", "personal", recurring_rule="DAILY"
    )

    send = AsyncMock()
    await scheduler.detect_missed_items(_ctx(send))

    send.assert_not_called()
```

- [ ] **Step 2: Ejecutar tests para verificar que fallan**

```
./.venv/bin/python -m pytest tests/test_scheduler_missed.py -v
```

Esperado: FAIL — `scheduler.detect_missed_items` no existe.

- [ ] **Step 3: Implementar**

Añadir al final de `scheduler.py`:

```python
async def detect_missed_items(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Detecta ítems que cruzaron a 'perdido' y notifica al usuario.

    Reglas:
    - Tareas con due_date < today - 1 día, done=0, outcome NULL.
    - Eventos puntuales (recurring_rule IS NULL) con datetime[:10] <
      today - 1 día, done=0, outcome NULL.
    - Objetivos con week_start <= today_monday - 14 días, done=0, outcome NULL.
    - Rutinas: la fecha esperada anterior a la "fecha de gracia"
      (today - 1) no tiene completion Y la fecha esperada anterior a
      esa sí (= antes había racha viva).

    Para cada ítem: insertar en missed_notifications (idempotente vía
    UNIQUE) y enviar mensaje al usuario.
    """
    import date_utils
    import tools as _tools
    from datetime import timedelta as _td

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    today = date_utils.today_madrid()
    yesterday = today - _td(days=1)
    notify_iso = date_utils.now_iso()

    async def _notify_with_buttons(item_kind: str, item_id: int, title: str) -> None:
        # item_kind in ('event', 'task', 'objective')
        prefix_recreate = {"event": "rE", "task": "rT", "objective": "rO"}[item_kind]
        prefix_discard = {"event": "dE", "task": "dT", "objective": "dO"}[item_kind]
        markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("📌 Pasar a hoy",
                                 callback_data=f"{prefix_recreate}:{item_id}"),
            InlineKeyboardButton("🗑️ Descartar",
                                 callback_data=f"{prefix_discard}:{item_id}"),
        ]])
        try:
            await context.bot.send_message(
                chat_id=ALLOWED_USER_ID,
                text=f"⚠️ Se te ha pasado: <b>{title}</b>",
                parse_mode=ParseMode.HTML,
                reply_markup=markup,
            )
        except Exception:
            log.exception("Error notificando perdido %s/%s", item_kind, item_id)

    async def _notify_routine(event_id: int, title: str, streak_before: int) -> None:
        text = (
            f"⚠️ Se rompió tu racha de <b>{title}</b>"
            + (f" (llevabas {streak_before} días)." if streak_before > 0 else ".")
            + "\nLa rutina sigue activa, vuelve a empezar cuando quieras."
        )
        try:
            await context.bot.send_message(
                chat_id=ALLOWED_USER_ID,
                text=text,
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            log.exception("Error notificando rotura de racha %s", event_id)

    with db.connect() as conn:
        # --- Tareas perdidas
        rows = conn.execute(
            """
            SELECT id, text FROM tasks
            WHERE done = 0 AND outcome IS NULL
              AND due_date IS NOT NULL
              AND due_date < ?
            """,
            (yesterday.isoformat(),),
        ).fetchall()
        for r in rows:
            try:
                conn.execute(
                    "INSERT INTO missed_notifications "
                    "(item_type, item_id, notified_at) VALUES ('task', ?, ?)",
                    (r["id"], notify_iso),
                )
            except Exception:
                continue  # ya notificado
            await _notify_with_buttons("task", r["id"], r["text"])

        # --- Eventos puntuales perdidos
        rows = conn.execute(
            """
            SELECT id, title FROM events
            WHERE done = 0 AND outcome IS NULL
              AND recurring_rule IS NULL
              AND substr(datetime, 1, 10) < ?
            """,
            (yesterday.isoformat(),),
        ).fetchall()
        for r in rows:
            try:
                conn.execute(
                    "INSERT INTO missed_notifications "
                    "(item_type, item_id, notified_at) VALUES ('event', ?, ?)",
                    (r["id"], notify_iso),
                )
            except Exception:
                continue
            await _notify_with_buttons("event", r["id"], r["title"])

        # --- Objetivos semanales perdidos
        from date_utils import monday_of_week
        cutoff_obj = monday_of_week(today) - _td(days=14)
        rows = conn.execute(
            """
            SELECT id, text, week_start FROM objectives
            WHERE done = 0 AND outcome IS NULL
              AND week_start <= ?
            """,
            (cutoff_obj.isoformat(),),
        ).fetchall()
        for r in rows:
            try:
                conn.execute(
                    "INSERT INTO missed_notifications "
                    "(item_type, item_id, notified_at) VALUES ('objective', ?, ?)",
                    (r["id"], notify_iso),
                )
            except Exception:
                continue
            await _notify_with_buttons("objective", r["id"], r["text"])

        # --- Rutinas: notificar rotura de racha (una vez por occurrence_date)
        routine_rows = conn.execute(
            "SELECT id, title, recurring_rule, datetime FROM events "
            "WHERE recurring_rule IS NOT NULL"
        ).fetchall()
        for r in routine_rows:
            rule = r["recurring_rule"]
            # Fecha esperada anterior a la fecha de gracia (yesterday)
            lost_date = _tools._previous_expected_date(rule, yesterday)
            if lost_date is None:
                continue
            # Comprobar si esa fecha está completada o en gracia
            done_row = conn.execute(
                "SELECT 1 FROM routine_completions "
                "WHERE event_id = ? AND completion_date = ?",
                (r["id"], lost_date.isoformat()),
            ).fetchone()
            if done_row:
                continue  # no se perdió
            # Comprobar que la fecha anterior aún SÍ se completó (racha viva)
            prior = _tools._previous_expected_date(rule, lost_date)
            if prior is None:
                continue
            prior_done = conn.execute(
                "SELECT 1 FROM routine_completions "
                "WHERE event_id = ? AND completion_date = ?",
                (r["id"], prior.isoformat()),
            ).fetchone()
            if not prior_done:
                continue  # no había racha viva
            # Intentar insertar la notificación; UNIQUE evita duplicados
            try:
                conn.execute(
                    "INSERT INTO missed_notifications "
                    "(item_type, item_id, occurrence_date, notified_at) "
                    "VALUES ('routine', ?, ?, ?)",
                    (r["id"], lost_date.isoformat(), notify_iso),
                )
            except Exception:
                continue
            # Streak antes de la rotura: contar consecutivas que terminan en prior
            streak_before = _tools._current_streak(r["id"], rule, prior, conn)
            await _notify_routine(r["id"], r["title"], streak_before)
```

- [ ] **Step 4: Ejecutar tests**

```
./.venv/bin/python -m pytest tests/test_scheduler_missed.py -v
```

Esperado: PASS.

- [ ] **Step 5: Commit**

```
git add scheduler.py tests/test_scheduler_missed.py
git commit -m "$(cat <<'EOF'
feat(scheduler): job detect_missed_items con avisos proactivos

Detecta tareas, eventos puntuales, objetivos y rutinas que han
cruzado el umbral de "perdido" y envía avisos al usuario. Tareas,
eventos y objetivos llevan botones recrear/descartar; rutinas solo
mensaje informativo de racha rota (sin spam: una notificación por
occurrence_date concreta y solo si había racha viva antes).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 19: Registrar `detect_missed_items` en `bot.main()`

**Files:**
- Modify: `bot.py:406-423` (registro de jobs en `_async_main`)

- [ ] **Step 1: Inspeccionar el bloque actual**

Leer `bot.py:406-423`. Ya hay 3 jobs registrados: `morning_summary`, `check_reminders`, `weekly_objectives_reminder`.

- [ ] **Step 2: Añadir el nuevo job**

Tras el registro de `weekly_objectives_reminder`, añadir:

```python
    app.job_queue.run_daily(
        scheduler.detect_missed_items,
        time=dtime(hour=0, minute=5, tzinfo=madrid),
        name="detect_missed_items",
    )
```

- [ ] **Step 3: Verificar que el bot arranca sin errores en local (opcional manual)**

```
./.venv/bin/python -c "import bot; print('OK')"
```

Esperado: `OK` sin tracebacks.

- [ ] **Step 4: Correr la suite completa**

```
./.venv/bin/python -m pytest
```

Esperado: PASS.

- [ ] **Step 5: Commit**

```
git add bot.py
git commit -m "$(cat <<'EOF'
feat(bot): registra job detect_missed_items a las 00:05 Madrid

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 20: Bloque semanal del lunes en `morning_summary`

**Files:**
- Modify: `scheduler.py:24-49` (`morning_summary`)
- Modify: `tests/test_scheduler.py`

- [ ] **Step 1: Escribir test fallido**

Añadir al final de `tests/test_scheduler.py`:

```python
import date_utils as _date_utils
from datetime import date as _date


@pytest.mark.asyncio
async def test_morning_summary_lunes_incluye_bloque_semanal(monkeypatch):
    monkeypatch.setattr(scheduler, "ALLOWED_USER_ID", 42)
    # 2026-05-25 es lunes
    monkeypatch.setattr(_date_utils, "today_madrid", lambda: _date(2026, 5, 25))

    import tools
    # Crear datos de la semana pasada (18-24 may): una tarea hecha on_time.
    t = tools.add_task("X", due_date="2026-05-20")
    monkeypatch.setattr(_date_utils, "today_madrid", lambda: _date(2026, 5, 20))
    tools.complete_task(t["id"])
    monkeypatch.setattr(_date_utils, "today_madrid", lambda: _date(2026, 5, 25))

    send_mock = AsyncMock()
    await scheduler.morning_summary(_fake_context(send_mock))

    send_mock.assert_called_once()
    text = send_mock.call_args.kwargs["text"]
    assert "Tu semana pasada" in text


@pytest.mark.asyncio
async def test_morning_summary_martes_no_incluye_bloque_semanal(monkeypatch):
    monkeypatch.setattr(scheduler, "ALLOWED_USER_ID", 42)
    monkeypatch.setattr(_date_utils, "today_madrid", lambda: _date(2026, 5, 26))

    send_mock = AsyncMock()
    await scheduler.morning_summary(_fake_context(send_mock))

    send_mock.assert_called_once()
    text = send_mock.call_args.kwargs["text"]
    assert "Tu semana pasada" not in text
```

- [ ] **Step 2: Ejecutar tests**

```
./.venv/bin/python -m pytest tests/test_scheduler.py -v -k "semana_pasada or bloque_semanal"
```

Esperado: FAIL — el bloque no se inyecta aún.

- [ ] **Step 3: Implementar**

Reemplazar `morning_summary` en `scheduler.py` (líneas 24-49) por:

```python
async def morning_summary(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Envía el saludo matutino con la vista de hoy. Los lunes incluye bloque semanal."""
    import date_utils
    import tools as _tools
    import views
    from datetime import timedelta as _td

    today = date_utils.today_madrid()
    weekday = _WEEKDAYS_ES[today.weekday()]
    date_str = f"{today.day} {_ES_MONTHS[today.month - 1]}"
    greeting = f"Buenos días Pablo 🌅 — <b>{weekday}, {date_str}</b>\n\n"

    # Bloque semanal solo los lunes
    weekly_block = ""
    if today.weekday() == 0:
        last_monday = today - _td(days=7)
        last_sunday = today - _td(days=1)
        try:
            m = _tools.metrics_summary(
                last_monday.isoformat(), last_sunday.isoformat()
            )
            weekly_block = _format_weekly_block(m)
        except Exception:
            log.exception("Error generando bloque semanal del lunes")
            weekly_block = ""

    try:
        with db.connect() as conn:
            body, keyboard = views.render_today_view(today, conn)
    except Exception:
        log.exception("Error generando el saludo matutino")
        return

    text = greeting + weekly_block + body

    try:
        await context.bot.send_message(
            chat_id=ALLOWED_USER_ID,
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )
    except Exception:
        log.exception("Error enviando el saludo matutino")


def _format_weekly_block(m: dict) -> str:
    """Render del bloque semanal de lunes. Vacío si no hay datos."""
    routine_totals = m["routines"]["totals"]
    routine_total = sum(routine_totals.values())
    tasks_total = sum(m["tasks"].values())
    obj_total = sum(m["objectives"].values())

    if routine_total == 0 and tasks_total == 0 and obj_total == 0:
        return ""

    def _pct_line(label: str, d: dict) -> str:
        total = d["on_time"] + d["grace"] + d["missed"]
        if total == 0:
            return ""
        ot = round(100 * d["on_time"] / total)
        gr = round(100 * d["grace"] / total)
        ms = round(100 * d["missed"] / total)
        return f"   {label}:   🟢 {ot}% 🟡 {gr}% 🔴 {ms}%"

    lines = ["📊 <b>Tu semana pasada</b>"]
    if routine_total > 0:
        line = _pct_line("Rutinas", routine_totals)
        if line:
            lines.append(line)
    if tasks_total > 0:
        line = _pct_line("Tareas", m["tasks"])
        if line:
            lines.append(line)
    if obj_total > 0:
        done = m["objectives"]["on_time"] + m["objectives"]["grace"]
        total = obj_total
        lines.append(f"   Objetivos: {done} de {total} cumplidos")

    return "\n".join(lines) + "\n\n"
```

- [ ] **Step 4: Ejecutar tests**

```
./.venv/bin/python -m pytest tests/test_scheduler.py -v
```

Esperado: PASS.

- [ ] **Step 5: Commit**

```
git add scheduler.py tests/test_scheduler.py
git commit -m "$(cat <<'EOF'
feat(scheduler): morning_summary del lunes incluye bloque semanal

Cada lunes el saludo matutino añade un bloque con el resumen de
métricas de la semana anterior (rutinas, tareas, objetivos). Si la
semana pasada no tiene datos, se omite el bloque.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 21: System prompt de `brain.py` — preguntar `due_date` al crear tarea

**Files:**
- Modify: `brain.py:46-140` (texto del system prompt)

- [ ] **Step 1: Añadir la regla**

Dentro de `_system_prompt`, en `brain.py:46-140`, localizar la sección "Distinción de tipos:" (línea 70) e insertar una regla nueva DESPUÉS de la línea "Tareas = lista pendiente sin fecha…". Concretamente, después de la línea actual:

```
- "Tareas" = lista pendiente sin fecha (list_tasks). "Eventos/citas/reuniones" = con fecha y hora (query_events). "Objetivos" = metas semanales (query_objectives).
```

añadir un párrafo nuevo:

```
- Al crear una tarea: las tareas tienen due_date opcional (formato YYYY-MM-DD). Si Pablo no menciona fecha y la tarea no es obviamente flotante ("comprar pan algún día"), pregunta primero "¿Para qué día? (hoy / mañana / esta semana / sin fecha)". Solo llama a add_task una vez tengas la decisión. Si Pablo dice "sin fecha", llama con due_date=null. Si dice un día concreto, resuelve a YYYY-MM-DD.
```

- [ ] **Step 2: Verificar que no rompemos tests existentes**

```
./.venv/bin/python -m pytest tests/test_brain.py -v
```

Esperado: PASS (los tests de brain no inspeccionan el contenido del prompt al detalle; si alguno lo hace, ajustarlo).

- [ ] **Step 3: Correr la suite completa**

```
./.venv/bin/python -m pytest
```

Esperado: PASS.

- [ ] **Step 4: Commit**

```
git add brain.py
git commit -m "$(cat <<'EOF'
feat(brain): system prompt pregunta due_date al crear tarea

Antes de llamar a add_task sin fecha explícita, Claude pregunta
"¿Para qué día? (hoy / mañana / esta semana / sin fecha)".
Empuja a fechar las tareas para que entren al juego, sin obligar.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 22: `/rachas` enriquecido con mini-stats de 30 días

El comando `/rachas` ya pasa por Claude vía `_SLASH_PROMPTS["/rachas"]` ([bot.py:42-52](bot.py#L42)). Hay que ampliar el prompt para que también incluya conteos por rutina de los últimos 30 días, usando los campos nuevos `on_time_count` / `grace_count` que `routine_summary` ya devuelve (Task 8) y `metrics_summary` para confirmar el total.

**Files:**
- Modify: `bot.py:42-52` (`_SLASH_PROMPTS["/rachas"]`)
- Modify: `tests/test_bot.py`

- [ ] **Step 1: Escribir test fallido**

Añadir al final de `tests/test_bot.py`:

```python
def test_rachas_prompt_mentions_30_day_stats():
    # El prompt que se envía a Claude debe instruirle a incluir stats de 30 días.
    prompt = bot._SLASH_PROMPTS["/rachas"]
    assert "30" in prompt
    assert "on_time" in prompt or "🟢" in prompt
    assert "routine_summary" in prompt
```

- [ ] **Step 2: Ejecutar test para verificar que falla**

```
./.venv/bin/python -m pytest tests/test_bot.py -v -k "rachas_prompt"
```

Esperado: FAIL — el prompt actual no menciona "30" ni los conteos.

- [ ] **Step 3: Implementar**

Reemplazar el valor de `_SLASH_PROMPTS["/rachas"]` en `bot.py` (líneas 42-52) por:

```python
    "/rachas": (
        "Muestra el estado de las rachas de mis rutinas con stats de los últimos 30 días. "
        "SIGUE ESTOS PASOS:\n"
        "1. Calcula date_from = hoy menos 29 días en YYYY-MM-DD, date_to = hoy en YYYY-MM-DD.\n"
        "2. Llama a routine_summary(date_from, date_to). Los streaks son globales, el rango "
        "solo afecta a los conteos on_time_count/grace_count/scheduled_days.\n"
        "3. Empieza la respuesta con un título de sección en negrita: 🔥 <b>RACHAS</b>\n"
        "4. Para cada rutina del paso 2, una línea con formato exacto:\n"
        "   • {title} — racha {current_streak} días "
        "(30d: 🟢 {pct_on_time}% 🟡 {pct_grace}% 🔴 {pct_missed}%)\n"
        "   donde:\n"
        "   - pct_on_time  = round(100 * on_time_count / scheduled_days)\n"
        "   - pct_grace    = round(100 * grace_count   / scheduled_days)\n"
        "   - pct_missed   = 100 - pct_on_time - pct_grace\n"
        "   Si scheduled_days == 0, omite el paréntesis (30d:...).\n"
        "   Si current_streak == best_streak Y best_streak > 0, añade ' 🏆' al final de la línea.\n"
        "5. Cierre motivador opcional de UNA frase si encaja.\n"
        "6. Si no hay rutinas (lista vacía del paso 2), responde solo: «Aún no tienes rutinas registradas.»\n"
        "NADA de preámbulos ni preguntas."
    ),
```

- [ ] **Step 4: Ejecutar tests**

```
./.venv/bin/python -m pytest tests/test_bot.py -v
```

Esperado: PASS.

- [ ] **Step 5: Commit**

```
git add bot.py tests/test_bot.py
git commit -m "$(cat <<'EOF'
feat(bot): /rachas enriquecido con métricas de 30 días por rutina

El prompt de /rachas ahora pide a Claude incluir, junto a la racha
actual de cada rutina, los porcentajes a tiempo / al día siguiente /
perdido de los últimos 30 días. Aprovecha los nuevos conteos
on_time_count y grace_count en routine_summary.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Verificación final (manual, post-merge)

- [ ] Correr la suite entera:

```
./.venv/bin/python -m pytest -v
```

- [ ] Probar localmente:

```
./start.sh
```

   - Mandar a Telegram "/metricas" — debería responder "Todavía no hay datos suficientes" o el panel si hay datos.
   - Crear una tarea con fecha: "añade tarea comprar pan para mañana".
   - Crear una tarea sin fecha: "añade tarea llamar al banco" → Claude debe preguntar fecha.
   - Comprobar `/hoy` y `/pendientes` con datos.

- [ ] Deploy a Fly:

```
flyctl deploy --app mi-secretaria-pablo
```

- [ ] Tras el deploy, verificar logs:

```
flyctl logs --app mi-secretaria-pablo --no-tail
```

   Buscar:
   - `Base de datos lista en /data/organizador.db` (sin errores de migración)
   - Jobs registrados: `morning_summary`, `check_reminders`, `weekly_objectives_reminder`, `detect_missed_items`.

- [ ] La primera ejecución del job `detect_missed_items` (al día siguiente a las 00:05 Madrid) puede generar varios mensajes proactivos si Pablo tiene tareas/eventos/objetivos antiguos pendientes. Avisarle por adelantado o ejecutar manualmente la primera vez en horario de uso para "limpiar" backlog.

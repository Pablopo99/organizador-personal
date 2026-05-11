# Organizador Personal — Plan de Implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construir un bot de Telegram conversacional en Python que use la API de Claude para gestionar eventos, objetivos semanales y tareas en una base de datos SQLite local.

**Architecture:** Proceso de Python único (`bot.py`) que escucha Telegram por polling, envía cada mensaje al "cerebro" (`brain.py`), que lo pasa a Claude con un conjunto de herramientas (`tools.py`) que operan sobre SQLite (`db.py`). Modular para permitir extensión iterativa.

**Tech Stack:** Python 3.11+, `python-telegram-bot`, `anthropic` SDK, SQLite (stdlib), `python-dotenv`, `pytest` + `pytest-asyncio` para tests.

**Spec de referencia:** `docs/superpowers/specs/2026-05-11-organizador-personal-design.md`

---

## Convenciones del plan

- Cada **Task** produce un commit cerrado y funcional.
- TDD estricto: test que falla → implementación mínima → test pasa → commit.
- Comandos siempre desde la raíz del proyecto: `/Users/pablocansinos/Desktop/Proyecto Prueba/`.
- Python ya disponible en el sistema: 3.12 en `/Library/Frameworks/Python.framework/Versions/3.12/bin/python3`.
- Zona horaria del proyecto: Europe/Madrid. Fechas guardadas como ISO 8601 en hora local (sin tz suffix) — un solo usuario, una sola zona.

---

## Task 1: Esqueleto del proyecto, entorno virtual, git

**Files:**
- Create: `.gitignore`
- Create: `requirements.txt`
- Create: `.env.example`
- Create: `README.md`

- [ ] **Step 1: Inicializar git y crear estructura**

```bash
cd "/Users/pablocansinos/Desktop/Proyecto Prueba"
git init
mkdir -p tests
touch tests/__init__.py
```

- [ ] **Step 2: Crear `.gitignore`**

Contenido completo:
```
# Python
__pycache__/
*.py[cod]
*$py.class
.pytest_cache/
.venv/
venv/

# Secretos
.env

# Base de datos
organizador.db
organizador.db-journal

# macOS
.DS_Store

# IDE
.vscode/
.idea/
```

- [ ] **Step 3: Crear `requirements.txt`**

Contenido completo:
```
anthropic==0.39.0
python-telegram-bot==21.6
python-dotenv==1.0.1
pytest==8.3.3
pytest-asyncio==0.24.0
```

- [ ] **Step 4: Crear `.env.example`**

Contenido completo:
```
# Token del bot, lo da @BotFather en Telegram
TELEGRAM_TOKEN=

# Clave de API de Anthropic, sacar de console.anthropic.com
ANTHROPIC_API_KEY=

# Tu Telegram user ID (numérico). Sacarlo escribiendo a @userinfobot
ALLOWED_USER_ID=
```

- [ ] **Step 5: Crear `tests/conftest.py`**

Esto asegura que todos los tests tengan variables de entorno mínimas, para que `import config` no falle. Tests específicos pueden sobrescribir con monkeypatch.

Contenido completo:
```python
"""Fixtures globales y entorno mínimo para todos los tests."""
import os

os.environ.setdefault("TELEGRAM_TOKEN", "test-telegram-token")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-anthropic-key")
os.environ.setdefault("ALLOWED_USER_ID", "42")
```

- [ ] **Step 6: Crear `README.md` mínimo**

Contenido completo:
```markdown
# Organizador Personal

Asistente personal por Telegram para gestionar eventos, objetivos semanales y tareas.

Ver `docs/superpowers/specs/2026-05-11-organizador-personal-design.md` para el diseño.

## Setup

Pendiente — ver Task 11 del plan.
```

- [ ] **Step 7: Crear venv e instalar dependencias**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Expected: instalación sin errores.

- [ ] **Step 8: Verificar que pytest funciona**

```bash
source .venv/bin/activate
python -m pytest --version
```

Expected: imprime `pytest 8.3.3` o similar.

- [ ] **Step 9: Commit**

```bash
git add .gitignore requirements.txt .env.example README.md tests/__init__.py tests/conftest.py
git commit -m "chore: bootstrap project structure, deps, gitignore, test config"
```

---

## Task 2: Módulo de configuración (`config.py`)

**Files:**
- Create: `config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Escribir test que falle**

Crear `tests/test_config.py`:
```python
import config


def test_config_loads_env_vars():
    # conftest.py garantiza valores por defecto para tests
    assert config.TELEGRAM_TOKEN
    assert config.ANTHROPIC_API_KEY
    assert isinstance(config.ALLOWED_USER_ID, int)


def test_config_constants():
    assert config.TIMEZONE == "Europe/Madrid"
    assert config.DB_PATH.endswith("organizador.db")
    assert "medical" in config.CATEGORIES
    assert "work" in config.CATEGORIES
    assert "personal" in config.CATEGORIES
    assert "other" in config.CATEGORIES


def test_require_raises_for_missing(monkeypatch):
    monkeypatch.delenv("MISSING_VAR", raising=False)
    import pytest
    with pytest.raises(RuntimeError, match="MISSING_VAR"):
        config._require("MISSING_VAR")
```

- [ ] **Step 2: Ejecutar test, verificar que falla**

```bash
source .venv/bin/activate
python -m pytest tests/test_config.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'config'`.

- [ ] **Step 3: Implementar `config.py`**

Contenido completo:
```python
"""Carga de configuración y constantes globales."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

_PROJECT_ROOT = Path(__file__).parent.resolve()


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"Falta la variable de entorno {name}. "
            f"Revisa tu archivo .env (puedes copiar .env.example)."
        )
    return value


TELEGRAM_TOKEN = _require("TELEGRAM_TOKEN")
ANTHROPIC_API_KEY = _require("ANTHROPIC_API_KEY")
ALLOWED_USER_ID = int(_require("ALLOWED_USER_ID"))

TIMEZONE = "Europe/Madrid"
DB_PATH = str(_PROJECT_ROOT / "organizador.db")
CATEGORIES = ("medical", "work", "personal", "other")
CLAUDE_MODEL = "claude-sonnet-4-6"
```

- [ ] **Step 4: Ejecutar tests, verificar que pasan**

```bash
python -m pytest tests/test_config.py -v
```

Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add config.py tests/test_config.py
git commit -m "feat(config): load env vars and expose project constants"
```

---

## Task 3: Capa de base de datos (`db.py`)

**Files:**
- Create: `db.py`
- Test: `tests/test_db.py`

- [ ] **Step 1: Escribir test que falle**

Crear `tests/test_db.py`:
```python
import os
import sqlite3
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


def test_init_creates_tables(temp_db):
    with sqlite3.connect(temp_db) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
    names = [r[0] for r in rows]
    assert "events" in names
    assert "objectives" in names
    assert "tasks" in names


def test_init_is_idempotent(temp_db):
    db.init_schema()
    db.init_schema()
    with sqlite3.connect(temp_db) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
        ).fetchone()[0]
    assert count >= 3


def test_connection_context_manager_commits(temp_db):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO tasks (text, done, created_at) VALUES (?, 0, ?)",
            ("comprar pan", "2026-05-11T10:00:00"),
        )
    with sqlite3.connect(temp_db) as conn:
        row = conn.execute("SELECT text FROM tasks").fetchone()
    assert row[0] == "comprar pan"
```

- [ ] **Step 2: Ejecutar test, verificar que falla**

```bash
python -m pytest tests/test_db.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'db'`.

- [ ] **Step 3: Implementar `db.py`**

Contenido completo:
```python
"""Acceso a SQLite: esquema y conexiones."""
import sqlite3
from contextlib import contextmanager
from typing import Iterator

from config import DB_PATH

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT NOT NULL,
    datetime        TEXT NOT NULL,
    category        TEXT NOT NULL DEFAULT 'other',
    recurring_rule  TEXT,
    notes           TEXT,
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_datetime ON events(datetime);

CREATE TABLE IF NOT EXISTS objectives (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    text        TEXT NOT NULL,
    week_start  TEXT NOT NULL,
    done        INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_objectives_week ON objectives(week_start);

CREATE TABLE IF NOT EXISTS tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    text        TEXT NOT NULL,
    done        INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);
"""


def init_schema() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(_SCHEMA)


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
```

- [ ] **Step 4: Ejecutar tests**

```bash
python -m pytest tests/test_db.py -v
```

Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add db.py tests/test_db.py
git commit -m "feat(db): SQLite schema with events, objectives, tasks tables"
```

---

## Task 4: Utilidades de fecha (`date_utils.py`)

**Files:**
- Create: `date_utils.py`
- Test: `tests/test_date_utils.py`

- [ ] **Step 1: Escribir test que falle**

Crear `tests/test_date_utils.py`:
```python
from datetime import date, datetime

import date_utils


def test_monday_of_week_from_monday():
    assert date_utils.monday_of_week(date(2026, 5, 11)) == date(2026, 5, 11)


def test_monday_of_week_from_wednesday():
    assert date_utils.monday_of_week(date(2026, 5, 13)) == date(2026, 5, 11)


def test_monday_of_week_from_sunday():
    assert date_utils.monday_of_week(date(2026, 5, 17)) == date(2026, 5, 11)


def test_now_iso_returns_string():
    s = date_utils.now_iso()
    parsed = datetime.fromisoformat(s)
    assert isinstance(parsed, datetime)


def test_format_human_es():
    dt = datetime(2026, 5, 22, 17, 0)
    s = date_utils.format_human_es(dt)
    assert "22" in s
    assert "may" in s.lower()
    assert "17:00" in s
```

- [ ] **Step 2: Ejecutar, verificar que falla**

```bash
python -m pytest tests/test_date_utils.py -v
```

Expected: FAIL — módulo no existe.

- [ ] **Step 3: Implementar `date_utils.py`**

Contenido completo:
```python
"""Utilidades de fecha y formato para uso interno."""
from datetime import date, datetime, timedelta

_ES_MONTHS = [
    "ene", "feb", "mar", "abr", "may", "jun",
    "jul", "ago", "sep", "oct", "nov", "dic",
]


def monday_of_week(d: date) -> date:
    """Devuelve el lunes de la semana ISO a la que pertenece la fecha."""
    return d - timedelta(days=d.weekday())


def now_iso() -> str:
    """Timestamp actual en ISO 8601 sin tz (hora local)."""
    return datetime.now().replace(microsecond=0).isoformat()


def format_human_es(dt: datetime) -> str:
    """Formato 'DD mmm HH:MM' para mostrar al usuario en español."""
    return f"{dt.day} {_ES_MONTHS[dt.month - 1]} {dt:%H:%M}"
```

- [ ] **Step 4: Ejecutar tests**

```bash
python -m pytest tests/test_date_utils.py -v
```

Expected: 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add date_utils.py tests/test_date_utils.py
git commit -m "feat(date): week_start helper, iso timestamp, spanish formatter"
```

---

## Task 5: Herramientas de eventos en `tools.py`

**Files:**
- Create: `tools.py`
- Test: `tests/test_tools_events.py`

Implementamos las 4 funciones de eventos primero. El resto se añade en las tareas siguientes al mismo archivo.

- [ ] **Step 1: Escribir tests para `add_event` y `query_events`**

Crear `tests/test_tools_events.py`:
```python
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


def test_add_event_returns_id():
    result = tools.add_event(
        title="Cita médico",
        datetime_iso="2026-05-22T17:00:00",
        category="medical",
    )
    assert result["id"] >= 1
    assert result["title"] == "Cita médico"


def test_query_events_in_range_returns_event():
    tools.add_event("Reunión", "2026-05-15T10:00:00", "work")
    tools.add_event("Lejos", "2026-06-01T10:00:00", "work")

    rows = tools.query_events("2026-05-14T00:00:00", "2026-05-16T00:00:00")

    assert len(rows) == 1
    assert rows[0]["title"] == "Reunión"


def test_query_events_filters_by_category():
    tools.add_event("Médico", "2026-05-15T10:00:00", "medical")
    tools.add_event("Trabajo", "2026-05-15T11:00:00", "work")

    rows = tools.query_events(
        "2026-05-15T00:00:00", "2026-05-15T23:59:59", category="medical"
    )

    assert len(rows) == 1
    assert rows[0]["title"] == "Médico"


def test_query_events_expands_weekly_recurring():
    tools.add_event(
        title="Gimnasio",
        datetime_iso="2026-05-04T08:00:00",  # un lunes
        category="personal",
        recurring_rule="WEEKLY:MON",
    )
    rows = tools.query_events("2026-05-11T00:00:00", "2026-05-25T23:59:59")
    titles = [r["title"] for r in rows]
    assert titles.count("Gimnasio") == 2  # 11 y 18 de mayo


def test_update_event_changes_title():
    created = tools.add_event("Viejo", "2026-05-15T10:00:00", "work")
    tools.update_event(created["id"], {"title": "Nuevo"})
    rows = tools.query_events("2026-05-15T00:00:00", "2026-05-15T23:59:59")
    assert rows[0]["title"] == "Nuevo"


def test_delete_event_removes_it():
    created = tools.add_event("Borrable", "2026-05-15T10:00:00", "other")
    tools.delete_event(created["id"])
    rows = tools.query_events("2026-05-15T00:00:00", "2026-05-15T23:59:59")
    assert rows == []


def test_add_event_rejects_invalid_category():
    with pytest.raises(ValueError, match="categoría"):
        tools.add_event("X", "2026-05-15T10:00:00", "invalid_cat")
```

- [ ] **Step 2: Ejecutar, ver que fallan**

```bash
python -m pytest tests/test_tools_events.py -v
```

Expected: FAIL — `tools` no existe.

- [ ] **Step 3: Crear `tools.py` con las funciones de eventos**

Contenido inicial (se irá ampliando en Tasks 6 y 7):
```python
"""Herramientas que Claude puede invocar. Operan sobre SQLite."""
from datetime import date, datetime, timedelta
from typing import Optional

import db
from config import CATEGORIES
from date_utils import now_iso

_WEEKDAY_MAP = {
    "MON": 0, "TUE": 1, "WED": 2, "THU": 3,
    "FRI": 4, "SAT": 5, "SUN": 6,
}


# ---------------------------------------------------------------- events ----

def add_event(
    title: str,
    datetime_iso: str,
    category: str,
    recurring_rule: Optional[str] = None,
    notes: Optional[str] = None,
) -> dict:
    if category not in CATEGORIES:
        raise ValueError(
            f"categoría inválida '{category}'. Permitidas: {CATEGORIES}"
        )
    with db.connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO events (title, datetime, category, recurring_rule, notes, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (title, datetime_iso, category, recurring_rule, notes, now_iso()),
        )
        new_id = cur.lastrowid
    return {"id": new_id, "title": title, "datetime": datetime_iso}


def query_events(
    date_from: str,
    date_to: str,
    category: Optional[str] = None,
) -> list[dict]:
    dt_from = datetime.fromisoformat(date_from)
    dt_to = datetime.fromisoformat(date_to)

    with db.connect() as conn:
        params: list = []
        sql = "SELECT * FROM events WHERE 1=1"
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
        else:
            occurrences.extend(_expand_recurring(row, rule, dt_from, dt_to))

    occurrences.sort(key=lambda r: r["datetime"])
    return occurrences


def _expand_recurring(row: dict, rule: str, dt_from: datetime, dt_to: datetime) -> list[dict]:
    base_dt = datetime.fromisoformat(row["datetime"])
    results: list[dict] = []

    if rule == "DAILY":
        step = timedelta(days=1)
    elif rule.startswith("WEEKLY:"):
        weekday_code = rule.split(":", 1)[1]
        if weekday_code not in _WEEKDAY_MAP:
            return []
        target_weekday = _WEEKDAY_MAP[weekday_code]
        # Avanza base_dt al primer día con weekday correcto >= base
        while base_dt.weekday() != target_weekday:
            base_dt += timedelta(days=1)
        step = timedelta(days=7)
    else:
        return []

    cur_dt = base_dt
    while cur_dt < dt_from:
        cur_dt += step
    while cur_dt <= dt_to:
        clone = dict(row)
        clone["datetime"] = cur_dt.isoformat()
        results.append(clone)
        cur_dt += step
    return results


def update_event(event_id: int, fields: dict) -> dict:
    allowed = {"title", "datetime", "category", "recurring_rule", "notes"}
    sets = []
    params: list = []
    for key, value in fields.items():
        if key not in allowed:
            raise ValueError(f"campo no actualizable: {key}")
        if key == "category" and value not in CATEGORIES:
            raise ValueError(f"categoría inválida '{value}'")
        sets.append(f"{key} = ?")
        params.append(value)
    if not sets:
        return {"id": event_id, "updated": 0}
    params.append(event_id)
    with db.connect() as conn:
        cur = conn.execute(
            f"UPDATE events SET {', '.join(sets)} WHERE id = ?", params
        )
        return {"id": event_id, "updated": cur.rowcount}


def delete_event(event_id: int) -> dict:
    with db.connect() as conn:
        cur = conn.execute("DELETE FROM events WHERE id = ?", (event_id,))
    return {"id": event_id, "deleted": cur.rowcount}
```

- [ ] **Step 4: Ejecutar tests, todos pasan**

```bash
python -m pytest tests/test_tools_events.py -v
```

Expected: 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tools.py tests/test_tools_events.py
git commit -m "feat(tools): event CRUD with recurring expansion (DAILY, WEEKLY)"
```

---

## Task 6: Herramientas de objetivos en `tools.py`

**Files:**
- Modify: `tools.py` (append section)
- Test: `tests/test_tools_objectives.py`

- [ ] **Step 1: Escribir tests**

Crear `tests/test_tools_objectives.py`:
```python
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
```

- [ ] **Step 2: Ejecutar, ver que fallan**

```bash
python -m pytest tests/test_tools_objectives.py -v
```

Expected: FAIL — `add_objective` no existe.

- [ ] **Step 3: Añadir sección de objectives a `tools.py`**

Añadir al final de `tools.py`:
```python

# ------------------------------------------------------------ objectives ----

def add_objective(text: str, week_start: str) -> dict:
    from date_utils import monday_of_week
    parsed = date.fromisoformat(week_start)
    normalized = monday_of_week(parsed).isoformat()
    with db.connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO objectives (text, week_start, done, created_at)
            VALUES (?, ?, 0, ?)
            """,
            (text, normalized, now_iso()),
        )
        new_id = cur.lastrowid
    return {"id": new_id, "text": text, "week_start": normalized}


def query_objectives(week_start: Optional[str]) -> list[dict]:
    with db.connect() as conn:
        if week_start:
            from date_utils import monday_of_week
            normalized = monday_of_week(date.fromisoformat(week_start)).isoformat()
            rows = conn.execute(
                "SELECT * FROM objectives WHERE week_start = ? ORDER BY id",
                (normalized,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM objectives ORDER BY week_start DESC, id"
            ).fetchall()
    return [dict(r) for r in rows]


def mark_objective_done(objective_id: int) -> dict:
    with db.connect() as conn:
        cur = conn.execute(
            "UPDATE objectives SET done = 1 WHERE id = ?", (objective_id,)
        )
    return {"id": objective_id, "updated": cur.rowcount}
```

- [ ] **Step 4: Ejecutar tests**

```bash
python -m pytest tests/test_tools_objectives.py -v
```

Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tools.py tests/test_tools_objectives.py
git commit -m "feat(tools): weekly objectives with week_start normalization"
```

---

## Task 7: Herramientas de tareas en `tools.py`

**Files:**
- Modify: `tools.py` (append section)
- Test: `tests/test_tools_tasks.py`

- [ ] **Step 1: Escribir tests**

Crear `tests/test_tools_tasks.py`:
```python
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
```

- [ ] **Step 2: Ejecutar, ver que fallan**

```bash
python -m pytest tests/test_tools_tasks.py -v
```

Expected: FAIL.

- [ ] **Step 3: Añadir sección de tasks a `tools.py`**

Añadir al final:
```python

# ----------------------------------------------------------------- tasks ----

def add_task(text: str) -> dict:
    with db.connect() as conn:
        cur = conn.execute(
            "INSERT INTO tasks (text, done, created_at) VALUES (?, 0, ?)",
            (text, now_iso()),
        )
        new_id = cur.lastrowid
    return {"id": new_id, "text": text}


def list_tasks(include_done: bool = False) -> list[dict]:
    with db.connect() as conn:
        if include_done:
            rows = conn.execute(
                "SELECT * FROM tasks ORDER BY done, id"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE done = 0 ORDER BY id"
            ).fetchall()
    return [dict(r) for r in rows]


def complete_task(task_id: int) -> dict:
    with db.connect() as conn:
        cur = conn.execute(
            "UPDATE tasks SET done = 1 WHERE id = ?", (task_id,)
        )
    return {"id": task_id, "updated": cur.rowcount}
```

- [ ] **Step 4: Ejecutar tests**

```bash
python -m pytest tests/test_tools_tasks.py -v
```

Expected: 3 tests PASS.

- [ ] **Step 5: Verificar que toda la suite sigue verde**

```bash
python -m pytest -v
```

Expected: todos los tests acumulados PASS.

- [ ] **Step 6: Commit**

```bash
git add tools.py tests/test_tools_tasks.py
git commit -m "feat(tools): standalone task list with done/pending filters"
```

---

## Task 8: Registro de herramientas y dispatcher

Le damos forma al "menú" que Claude verá: una lista de definiciones JSON Schema + una función que ejecuta cualquier herramienta por nombre.

**Files:**
- Modify: `tools.py` (append registry at end)
- Test: `tests/test_tools_registry.py`

- [ ] **Step 1: Escribir test**

Crear `tests/test_tools_registry.py`:
```python
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


def test_tool_definitions_shape():
    defs = tools.TOOL_DEFINITIONS
    assert isinstance(defs, list)
    names = {d["name"] for d in defs}
    expected = {
        "add_event", "query_events", "update_event", "delete_event",
        "add_objective", "query_objectives", "mark_objective_done",
        "add_task", "list_tasks", "complete_task",
    }
    assert expected.issubset(names)
    for d in defs:
        assert "description" in d
        assert "input_schema" in d
        assert d["input_schema"]["type"] == "object"


def test_dispatch_add_task():
    result = tools.dispatch("add_task", {"text": "comprar pan"})
    assert result["text"] == "comprar pan"


def test_dispatch_unknown_tool():
    with pytest.raises(ValueError, match="desconocida"):
        tools.dispatch("nope", {})
```

- [ ] **Step 2: Ejecutar, ver que falla**

```bash
python -m pytest tests/test_tools_registry.py -v
```

Expected: FAIL — `TOOL_DEFINITIONS` no existe.

- [ ] **Step 3: Añadir registro y dispatcher a `tools.py`**

Añadir al final:
```python

# -------------------------------------------------------------- registry ----

TOOL_DEFINITIONS: list[dict] = [
    {
        "name": "add_event",
        "description": (
            "Añade un evento o cita al calendario. Para rutinas recurrentes, "
            "usar recurring_rule con formato 'DAILY' o 'WEEKLY:MON|TUE|WED|THU|FRI|SAT|SUN'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "datetime_iso": {
                    "type": "string",
                    "description": "Fecha y hora ISO 8601 sin zona, ej. 2026-05-22T17:00:00",
                },
                "category": {
                    "type": "string",
                    "enum": list(CATEGORIES),
                },
                "recurring_rule": {"type": ["string", "null"]},
                "notes": {"type": ["string", "null"]},
            },
            "required": ["title", "datetime_iso", "category"],
        },
    },
    {
        "name": "query_events",
        "description": "Lista eventos entre dos fechas. Expande recurrentes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "date_from": {"type": "string", "description": "ISO 8601, ej. 2026-05-15T00:00:00"},
                "date_to": {"type": "string"},
                "category": {"type": ["string", "null"], "enum": [*CATEGORIES, None]},
            },
            "required": ["date_from", "date_to"],
        },
    },
    {
        "name": "update_event",
        "description": "Modifica campos de un evento existente.",
        "input_schema": {
            "type": "object",
            "properties": {
                "event_id": {"type": "integer"},
                "fields": {"type": "object"},
            },
            "required": ["event_id", "fields"],
        },
    },
    {
        "name": "delete_event",
        "description": "Borra un evento por su id. Confirmar con el usuario antes.",
        "input_schema": {
            "type": "object",
            "properties": {"event_id": {"type": "integer"}},
            "required": ["event_id"],
        },
    },
    {
        "name": "add_objective",
        "description": (
            "Añade un objetivo semanal. week_start puede ser cualquier fecha de la semana; "
            "se normaliza al lunes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "week_start": {"type": "string", "description": "ISO date YYYY-MM-DD"},
            },
            "required": ["text", "week_start"],
        },
    },
    {
        "name": "query_objectives",
        "description": "Lista objetivos. Si week_start es null, devuelve todos.",
        "input_schema": {
            "type": "object",
            "properties": {
                "week_start": {"type": ["string", "null"]},
            },
            "required": ["week_start"],
        },
    },
    {
        "name": "mark_objective_done",
        "description": "Marca un objetivo como completado.",
        "input_schema": {
            "type": "object",
            "properties": {"objective_id": {"type": "integer"}},
            "required": ["objective_id"],
        },
    },
    {
        "name": "add_task",
        "description": "Añade una tarea suelta sin fecha.",
        "input_schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
    {
        "name": "list_tasks",
        "description": "Lista tareas. Por defecto solo pendientes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "include_done": {"type": "boolean", "default": False},
            },
        },
    },
    {
        "name": "complete_task",
        "description": "Marca una tarea como hecha.",
        "input_schema": {
            "type": "object",
            "properties": {"task_id": {"type": "integer"}},
            "required": ["task_id"],
        },
    },
]


_DISPATCH = {
    "add_event": add_event,
    "query_events": query_events,
    "update_event": update_event,
    "delete_event": delete_event,
    "add_objective": add_objective,
    "query_objectives": query_objectives,
    "mark_objective_done": mark_objective_done,
    "add_task": add_task,
    "list_tasks": list_tasks,
    "complete_task": complete_task,
}


def dispatch(name: str, arguments: dict):
    if name not in _DISPATCH:
        raise ValueError(f"herramienta desconocida: {name}")
    return _DISPATCH[name](**arguments)
```

- [ ] **Step 4: Ejecutar tests**

```bash
python -m pytest tests/test_tools_registry.py -v
```

Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tools.py tests/test_tools_registry.py
git commit -m "feat(tools): tool definitions schema and dispatcher for Claude"
```

---

## Task 9: Cerebro — orquestación con Claude (`brain.py`)

**Files:**
- Create: `brain.py`
- Test: `tests/test_brain.py`

- [ ] **Step 1: Escribir test con cliente de Anthropic mockeado**

Crear `tests/test_brain.py`:
```python
import os
import tempfile
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import db
import brain


@pytest.fixture(autouse=True)
def temp_db(monkeypatch):
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init_schema()
    yield path
    os.unlink(path)


def _text_response(text: str):
    return SimpleNamespace(
        stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text=text)],
    )


def _tool_use_then_text(tool_name: str, tool_input: dict, final_text: str):
    """Simula dos turnos: primero tool_use, luego end_turn con texto."""
    first = SimpleNamespace(
        stop_reason="tool_use",
        content=[
            SimpleNamespace(type="text", text=""),
            SimpleNamespace(
                type="tool_use", id="toolu_1", name=tool_name, input=tool_input
            ),
        ],
    )
    second = _text_response(final_text)
    return [first, second]


def test_handle_message_text_only(monkeypatch):
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _text_response("Hola, ¿en qué te ayudo?")
    monkeypatch.setattr(brain, "_client", mock_client)

    reply = brain.handle_message("hola")
    assert "Hola" in reply


def test_handle_message_with_tool_use(monkeypatch):
    responses = _tool_use_then_text(
        "add_task", {"text": "comprar pan"}, "Hecho, añadida."
    )
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = responses
    monkeypatch.setattr(brain, "_client", mock_client)

    reply = brain.handle_message("añade comprar pan")
    assert "Hecho" in reply

    # La tarea se persistió de verdad
    import tools
    rows = tools.list_tasks()
    assert len(rows) == 1
    assert rows[0]["text"] == "comprar pan"
```

- [ ] **Step 2: Ejecutar, ver que falla**

```bash
python -m pytest tests/test_brain.py -v
```

Expected: FAIL — `brain` no existe.

- [ ] **Step 3: Implementar `brain.py`**

Contenido completo:
```python
"""Orquestación de Claude: envía mensajes, gestiona tool use, devuelve respuesta."""
from datetime import datetime

import anthropic

import tools
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL, TIMEZONE

_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

_MAX_TOOL_TURNS = 8


def _system_prompt() -> str:
    now = datetime.now().isoformat(timespec="minutes")
    weekday = [
        "lunes", "martes", "miércoles", "jueves",
        "viernes", "sábado", "domingo",
    ][datetime.now().weekday()]
    return f"""Eres el asistente personal de organización de un usuario hispanohablante.

Contexto:
- Fecha y hora ahora: {now} ({weekday})
- Zona horaria del usuario: {TIMEZONE}
- Idioma: español de España. Tono directo, amable, sin floritura.

Reglas:
1. Cuando el usuario te pida añadir o consultar algo con fechas, resuélvelas a ISO 8601 antes de llamar herramientas.
2. Si una fecha o detalle es ambiguo, pregunta antes de actuar (no inventes).
3. Antes de borrar algo, muestra lo que vas a borrar y pide confirmación explícita.
4. Puedes llamar varias herramientas en un mismo turno si la petición lo requiere.
5. Si una herramienta devuelve error, explícalo al usuario con palabras claras y propón una alternativa.
6. Respuestas breves: confirma lo hecho en una frase, no listes datos que el usuario ya sabe.
7. Para fechas sin año cuya fecha en el año actual ya ha pasado, asume el año siguiente y pregunta para confirmar."""


def handle_message(user_text: str) -> str:
    """Procesa un mensaje del usuario, ejecutando todas las tool calls necesarias."""
    messages = [{"role": "user", "content": user_text}]
    system = _system_prompt()

    for _ in range(_MAX_TOOL_TURNS):
        response = _client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1024,
            system=system,
            tools=tools.TOOL_DEFINITIONS,
            messages=messages,
        )

        if response.stop_reason == "end_turn":
            return _extract_text(response)

        if response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for block in response.content:
                if getattr(block, "type", None) != "tool_use":
                    continue
                try:
                    result = tools.dispatch(block.name, dict(block.input))
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": str(result),
                    })
                except Exception as exc:
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": f"ERROR: {exc}",
                        "is_error": True,
                    })
            messages.append({"role": "user", "content": tool_results})
            continue

        # Cualquier otro stop_reason: salir con lo que haya
        return _extract_text(response) or "(Sin respuesta)"

    return "Demasiados pasos internos, vuelve a intentarlo más simple."


def _extract_text(response) -> str:
    chunks = [
        getattr(b, "text", "") for b in response.content
        if getattr(b, "type", None) == "text"
    ]
    return "".join(chunks).strip()
```

- [ ] **Step 4: Ejecutar tests**

```bash
python -m pytest tests/test_brain.py -v
```

Expected: 2 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add brain.py tests/test_brain.py
git commit -m "feat(brain): Claude tool-use loop with Spanish system prompt"
```

---

## Task 10: Bot de Telegram (`bot.py`)

**Files:**
- Create: `bot.py`
- Test: `tests/test_bot.py`

Para el test, en vez de simular toda la librería de Telegram, extraemos la lógica de autorización y respuesta a una función pura que sí podamos testear.

- [ ] **Step 1: Escribir test**

Crear `tests/test_bot.py`:
```python
from unittest.mock import patch

import bot


def test_handle_unauthorized_user_returns_none():
    reply = bot.process_incoming(text="hola", from_user_id=999)
    assert reply is None


def test_handle_authorized_user_calls_brain(monkeypatch):
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)

    with patch("bot.brain.handle_message", return_value="respuesta de prueba") as mock:
        reply = bot.process_incoming(text="hola", from_user_id=42)

    mock.assert_called_once_with("hola")
    assert reply == "respuesta de prueba"


def test_handle_brain_exception_returns_friendly_message(monkeypatch):
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)

    def explode(_):
        raise RuntimeError("boom")

    monkeypatch.setattr(bot.brain, "handle_message", explode)
    reply = bot.process_incoming(text="hola", from_user_id=42)
    assert "no puedo procesar" in reply.lower()
```

- [ ] **Step 2: Ejecutar, ver que falla**

```bash
python -m pytest tests/test_bot.py -v
```

Expected: FAIL — `bot` no existe.

- [ ] **Step 3: Implementar `bot.py`**

Contenido completo:
```python
"""Listener de Telegram. Filtra por usuario autorizado y delega en el cerebro."""
import logging
from typing import Optional

from telegram import Update
from telegram.ext import (
    Application,
    ContextTypes,
    MessageHandler,
    filters,
)

import brain
import db
from config import ALLOWED_USER_ID, TELEGRAM_TOKEN

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("bot")


def process_incoming(text: str, from_user_id: int) -> Optional[str]:
    """Lógica pura: dado un mensaje y user id, devuelve la respuesta (o None si no autorizado)."""
    if from_user_id != ALLOWED_USER_ID:
        log.warning("Mensaje ignorado de user_id no autorizado: %s", from_user_id)
        return None
    try:
        return brain.handle_message(text)
    except Exception as exc:
        log.exception("Error procesando mensaje")
        return (
            "Ahora mismo no puedo procesar esto. "
            "Prueba a reformularlo o vuelve a intentarlo en un momento."
        )


async def _on_message(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return
    reply = process_incoming(
        text=update.message.text,
        from_user_id=update.effective_user.id,
    )
    if reply is not None:
        await update.message.reply_text(reply)


def main() -> None:
    db.init_schema()
    log.info("Base de datos lista en %s", db.DB_PATH)

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _on_message))

    log.info("Bot arrancando (polling)…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Ejecutar tests**

```bash
python -m pytest tests/test_bot.py -v
```

Expected: 3 tests PASS.

- [ ] **Step 5: Verificar suite completa**

```bash
python -m pytest -v
```

Expected: TODO PASS.

- [ ] **Step 6: Commit**

```bash
git add bot.py tests/test_bot.py
git commit -m "feat(bot): Telegram listener with auth gate and error handling"
```

---

## Task 11: Script de arranque y guía de setup en README

**Files:**
- Create: `start.sh`
- Modify: `README.md` (reemplazar contenido)

- [ ] **Step 1: Crear `start.sh`**

Contenido completo:
```bash
#!/bin/bash
# Arranca el bot manteniendo el Mac despierto mientras corre.
# Para parar: Ctrl+C en esta terminal.

set -e

cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
    echo "No encuentro .venv. Crea el entorno con:"
    echo "  python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

source .venv/bin/activate

if [ ! -f ".env" ]; then
    echo "No encuentro .env. Cópialo desde .env.example y rellena las claves."
    exit 1
fi

echo "Arrancando bot (Ctrl+C para parar)…"
caffeinate -i python bot.py
```

- [ ] **Step 2: Hacerlo ejecutable**

```bash
chmod +x start.sh
```

- [ ] **Step 3: Reemplazar `README.md`**

Contenido completo:
```markdown
# Organizador Personal

Asistente personal por Telegram para gestionar eventos, objetivos semanales y tareas. Hablas con él en español natural y guarda todo en una base de datos local en tu Mac.

Diseño completo: `docs/superpowers/specs/2026-05-11-organizador-personal-design.md`

## Qué necesitas antes de empezar

1. **Python 3.11+** — ya viene en macOS moderno, comprueba con `python3 --version`.
2. **Un bot de Telegram** — gratis, lo creas hablando con [@BotFather](https://t.me/BotFather):
   - Abre Telegram, busca `@BotFather`, dale a Start.
   - Escribe `/newbot`.
   - Sigue las instrucciones (nombre + username terminado en `bot`).
   - Te dará un **token** tipo `1234567:ABC-DEF...`. Guárdalo.
3. **Tu Telegram user ID** — abre [@userinfobot](https://t.me/userinfobot) en Telegram y dale a Start. Te mostrará tu ID numérico.
4. **Una clave de API de Anthropic** — en [console.anthropic.com](https://console.anthropic.com):
   - Crea una cuenta o entra.
   - Ve a `API Keys` → `Create Key`.
   - Cárgale unos pocos € (con 5 € te llega para meses de uso personal normal).

## Instalación

```bash
cd "/Users/pablocansinos/Desktop/Proyecto Prueba"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Ahora edita `.env` y rellena las tres variables con lo que has recopilado.

## Arrancar

```bash
./start.sh
```

Se quedará corriendo en la terminal. El Mac no se dormirá mientras esté activo (`caffeinate`). Para pararlo: `Ctrl+C`.

## Uso

Abre Telegram, busca tu bot por el username que le pusiste y escríbele. Ejemplos:

- "Apunta cita médico el 22 a las 5 de la tarde"
- "¿Qué tengo el 15 de mayo?"
- "Esta semana mis objetivos son terminar el informe y hacer deporte 3 veces"
- "¿Qué objetivos pusimos el domingo?"
- "Añade comprar pan a la lista"
- "¿Qué tareas tengo pendientes?"

## Backup de tus datos

Tus datos viven en `organizador.db`. Para respaldarlos, copia ese archivo donde quieras (iCloud, Dropbox, USB). Para restaurarlos, simplemente vuelve a poner el archivo en su sitio.

## Tests

```bash
source .venv/bin/activate
python -m pytest -v
```

## Estructura

| Archivo | Qué hace |
|---|---|
| `bot.py` | Escucha mensajes de Telegram |
| `brain.py` | Conversa con Claude y gestiona herramientas |
| `tools.py` | Las funciones que Claude puede invocar (CRUD) |
| `db.py` | Acceso a SQLite |
| `config.py` | Carga `.env` y constantes |
| `date_utils.py` | Helpers de fechas |
| `organizador.db` | Tu base de datos (se crea sola) |
```

- [ ] **Step 4: Verificar que la suite completa pasa**

```bash
source .venv/bin/activate
python -m pytest -v
```

Expected: TODO PASS.

- [ ] **Step 5: Commit**

```bash
git add start.sh README.md
git commit -m "docs: setup guide, usage examples, start script with caffeinate"
```

---

## Task 12: Validación manual end-to-end

Esta tarea no añade código — verifica que el conjunto funciona con APIs reales antes de dar el MVP por hecho.

- [ ] **Step 1: Comprobar que `.env` está bien**

Verifica que el usuario tiene rellenas las tres variables en `.env`:
- `TELEGRAM_TOKEN`
- `ANTHROPIC_API_KEY`
- `ALLOWED_USER_ID`

Si falta alguna, parar e indicar al usuario qué hacer (ver README).

- [ ] **Step 2: Arrancar el bot**

```bash
./start.sh
```

Expected: logs de arranque sin errores, mensaje "Bot arrancando (polling)…".

- [ ] **Step 3: Smoke test desde Telegram (móvil)**

Pedir al usuario que envíe estos mensajes al bot y comprobar respuestas:

1. "Hola" → debe responder en español, saludo conciso.
2. "Apunta cita médico el 22 de mayo a las 17:00" → debe llamar `add_event` y confirmar.
3. "¿Qué tengo el 22 de mayo?" → debe listar la cita anterior.
4. "Añade comprar pan a la lista" → confirma.
5. "¿Qué tareas tengo?" → debe listar la tarea.
6. "Mi objetivo esta semana es terminar el informe" → debe guardar objetivo.
7. "¿Qué objetivos tengo esta semana?" → debe listar el objetivo.

- [ ] **Step 4: Verificar que datos se persisten**

Parar el bot (Ctrl+C), arrancar de nuevo (`./start.sh`), preguntar "¿qué tengo el 22 de mayo?" y comprobar que la cita sigue ahí.

- [ ] **Step 5: Verificar bloqueo de no autorizados**

Si es posible (otra cuenta de Telegram), enviar un mensaje al bot desde otra cuenta y comprobar que **no responde**. En los logs debe aparecer la línea "Mensaje ignorado de user_id no autorizado: …".

- [ ] **Step 6: Commit final si hay cambios**

Si durante la validación hubo que ajustar algo, commit:
```bash
git add -A
git commit -m "fix: ajustes encontrados en validación manual"
```

Si todo fue limpio, no hace falta commit.

---

## Resumen de entregables

Al terminar el plan, el proyecto tiene:

- 6 módulos Python con sus tests (`config`, `db`, `date_utils`, `tools`, `brain`, `bot`).
- 10 herramientas conectadas a Claude vía tool use.
- 3 tablas SQLite (`events`, `objectives`, `tasks`).
- Script de arranque (`start.sh`) y guía de setup (`README.md`).
- Suite de tests completa que se ejecuta con `pytest`.
- Bot funcional en Telegram que solo responde al usuario autorizado.

A partir de aquí, cada mejora futura (recordatorios proactivos, Google Calendar, etc.) será su propio mini-proyecto con su propio diseño y plan.

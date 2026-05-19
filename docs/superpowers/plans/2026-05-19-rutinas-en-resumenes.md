# Rutinas en los resúmenes — Plan de Implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Añadir sección 🔁 RUTINAS a `/hoy`, `/semana` y saludo matutino, con marcado por instancia (no permanente) y cálculo de "hoy" en zona horaria Madrid.

**Architecture:** Nueva tabla `routine_completions(event_id, completion_date)` registra qué rutina se hizo qué día. `mark_event_done` enruta: rutina → insert en tabla, evento puntual → done=1 (intacto). Nueva tool `routine_summary` agrega cuentas por rango. Helpers `today_madrid()` / `now_madrid()` arreglan el bug latente de tz en el contenedor UTC.

**Tech Stack:** Python 3.12, SQLite con `PRAGMA foreign_keys=ON`, pytz, python-telegram-bot 21.6, pytest-asyncio, Fly.io para deploy final.

**Spec de referencia:** `docs/superpowers/specs/2026-05-19-rutinas-en-resumenes-design.md`

---

## Convenciones

- TDD estricto: test que falla → implementación → test pasa → commit.
- Cada Task termina en commit.
- Comandos desde `/Users/pablocansinos/Desktop/Otros/Proyecto Prueba`.
- Activar venv: `source .venv/bin/activate`.
- ALLOWED_USER_ID en tests es `42` (definido en `tests/conftest.py`).

---

## Task 1: Helpers de zona horaria Madrid

Añadimos `today_madrid()` y `now_madrid_naive()` para que "hoy" y "ahora" se calculen siempre en hora de Madrid, independientemente de la zona del contenedor. También fijamos `TZ=Europe/Madrid` en el Dockerfile como cinturón-y-tirantes.

**Files:**
- Modify: `date_utils.py`
- Create: tests añadidos a `tests/test_date_utils.py`
- Modify: `Dockerfile`

- [ ] **Step 1: Escribir tests de los helpers**

Añadir al final de `tests/test_date_utils.py`:

```python
from datetime import datetime, date
from unittest.mock import patch

import pytz

import date_utils


def test_today_madrid_returns_madrid_date_when_utc_is_previous_day():
    """A las 23:30 UTC del 19, en Madrid son las 00:30 (verano) o 01:30 (invierno) del 20."""
    # Simulamos UTC = 2026-07-19 23:30 (verano, Madrid = UTC+2)
    fake_now = datetime(2026, 7, 19, 23, 30, tzinfo=pytz.UTC)
    with patch.object(date_utils, "_now_utc", return_value=fake_now):
        assert date_utils.today_madrid() == date(2026, 7, 20)


def test_today_madrid_returns_today_when_within_same_day():
    """A las 12:00 UTC, en Madrid son las 14:00 — mismo día."""
    fake_now = datetime(2026, 7, 19, 12, 0, tzinfo=pytz.UTC)
    with patch.object(date_utils, "_now_utc", return_value=fake_now):
        assert date_utils.today_madrid() == date(2026, 7, 19)


def test_now_madrid_naive_returns_madrid_wallclock_as_naive():
    """now_madrid_naive() debe dar el reloj de pared de Madrid como naive datetime."""
    fake_now = datetime(2026, 7, 19, 12, 0, tzinfo=pytz.UTC)
    with patch.object(date_utils, "_now_utc", return_value=fake_now):
        result = date_utils.now_madrid_naive()
        assert result.tzinfo is None
        assert result.hour == 14  # UTC 12:00 + verano = 14:00 Madrid
        assert result.day == 19
```

- [ ] **Step 2: Ejecutar tests, verificar que fallan**

```bash
source .venv/bin/activate
python -m pytest tests/test_date_utils.py -v
```

Expected: 3 tests nuevos FAIL — funciones no existen.

- [ ] **Step 3: Implementar los helpers en `date_utils.py`**

Sustituir el contenido completo de `date_utils.py` por:

```python
"""Utilidades de fecha y formato para uso interno."""
from datetime import date, datetime, timedelta

import pytz

_ES_MONTHS = [
    "ene", "feb", "mar", "abr", "may", "jun",
    "jul", "ago", "sep", "oct", "nov", "dic",
]

_MADRID = pytz.timezone("Europe/Madrid")


def _now_utc() -> datetime:
    """Indirección que tests pueden monkeypatchear."""
    return datetime.now(pytz.UTC)


def now_madrid() -> datetime:
    """Datetime tz-aware en zona horaria Europe/Madrid."""
    return _now_utc().astimezone(_MADRID)


def now_madrid_naive() -> datetime:
    """Reloj de pared de Madrid como datetime naive (para comparar con valores naive en BD)."""
    return now_madrid().replace(tzinfo=None)


def today_madrid() -> date:
    """Fecha actual en zona horaria de Madrid."""
    return now_madrid().date()


def monday_of_week(d: date) -> date:
    """Devuelve el lunes de la semana ISO a la que pertenece la fecha."""
    return d - timedelta(days=d.weekday())


def now_iso() -> str:
    """Timestamp actual en ISO 8601 sin tz (hora Madrid)."""
    return now_madrid_naive().replace(microsecond=0).isoformat()


def format_human_es(dt: datetime) -> str:
    """Formato 'DD mmm HH:MM' para mostrar al usuario en español."""
    return f"{dt.day} {_ES_MONTHS[dt.month - 1]} {dt:%H:%M}"
```

- [ ] **Step 4: Ejecutar tests, verificar que pasan**

```bash
python -m pytest tests/test_date_utils.py -v
```

Expected: TODOS los tests PASS (los antiguos + 3 nuevos).

- [ ] **Step 5: Setear TZ=Europe/Madrid en el Dockerfile**

Editar `Dockerfile` para añadir la variable de entorno y el paquete tzdata. Sustituir el bloque actual entre `WORKDIR /app` y `COPY requirements.txt .` por:

```dockerfile
WORKDIR /app

ENV TZ=Europe/Madrid

RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && ln -fs /usr/share/zoneinfo/Europe/Madrid /etc/localtime \
    && dpkg-reconfigure -f noninteractive tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
```

- [ ] **Step 6: Ejecutar suite completa para asegurarse de no romper nada**

```bash
python -m pytest -v
```

Expected: TODO PASS.

- [ ] **Step 7: Commit**

```bash
git add date_utils.py tests/test_date_utils.py Dockerfile
git commit -m "feat(date_utils): add Madrid timezone helpers and set TZ in Dockerfile

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Tabla `routine_completions` + PRAGMA foreign_keys

Creamos la tabla nueva, habilitamos foreign keys en SQLite (no es default), y verificamos que ON DELETE CASCADE funciona.

**Files:**
- Modify: `db.py`
- Modify: `tests/test_db.py`

- [ ] **Step 1: Escribir tests de migración y CASCADE**

Añadir al final de `tests/test_db.py`:

```python


def test_migration_creates_routine_completions_table(monkeypatch):
    """BD vieja sin la tabla: init_schema la crea."""
    import os
    import sqlite3
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    monkeypatch.setattr(db, "DB_PATH", path)
    # BD vieja: solo events
    with sqlite3.connect(path) as conn:
        conn.execute("""
            CREATE TABLE events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                datetime TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'other',
                recurring_rule TEXT,
                notes TEXT,
                created_at TEXT NOT NULL,
                done INTEGER NOT NULL DEFAULT 0,
                reminder_1d_sent INTEGER NOT NULL DEFAULT 0,
                reminder_1h_sent INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.commit()

    db.init_schema()

    with sqlite3.connect(path) as conn:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
    assert "routine_completions" in tables
    os.unlink(path)


def test_connect_enables_foreign_keys():
    """db.connect() debe activar PRAGMA foreign_keys=ON."""
    with db.connect() as conn:
        cur = conn.execute("PRAGMA foreign_keys")
        assert cur.fetchone()[0] == 1


def test_delete_event_cascades_to_routine_completions(monkeypatch):
    """Borrar un evento elimina sus filas de routine_completions."""
    import os
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init_schema()

    with db.connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO events (title, datetime, category, created_at, recurring_rule)
            VALUES ('Flexiones', '2026-05-19T08:00:00', 'personal', '2026-05-19T08:00:00', 'DAILY')
            """
        )
        event_id = cur.lastrowid
        conn.execute(
            """
            INSERT INTO routine_completions (event_id, completion_date, created_at)
            VALUES (?, '2026-05-19', '2026-05-19T08:00:00')
            """,
            (event_id,),
        )

    with db.connect() as conn:
        conn.execute("DELETE FROM events WHERE id = ?", (event_id,))

    with db.connect() as conn:
        rows = conn.execute(
            "SELECT COUNT(*) FROM routine_completions WHERE event_id = ?",
            (event_id,),
        ).fetchone()
    assert rows[0] == 0
    os.unlink(path)


def test_routine_completions_unique_per_event_per_date(monkeypatch):
    """No se puede insertar dos filas con el mismo event_id y completion_date."""
    import os
    import sqlite3
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init_schema()

    with db.connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO events (title, datetime, category, created_at, recurring_rule)
            VALUES ('Flexiones', '2026-05-19T08:00:00', 'personal', '2026-05-19T08:00:00', 'DAILY')
            """
        )
        event_id = cur.lastrowid
        conn.execute(
            "INSERT INTO routine_completions (event_id, completion_date, created_at) VALUES (?, '2026-05-19', '2026-05-19T08:00:00')",
            (event_id,),
        )

    with pytest.raises(sqlite3.IntegrityError):
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO routine_completions (event_id, completion_date, created_at) VALUES (?, '2026-05-19', '2026-05-19T08:30:00')",
                (event_id,),
            )
    os.unlink(path)
```

Si `pytest` no está importado al principio del archivo, añadir `import pytest` arriba.

- [ ] **Step 2: Ejecutar tests, verificar que fallan**

```bash
python -m pytest tests/test_db.py -v
```

Expected: 4 tests nuevos FAIL — tabla no existe, FK no activado, etc.

- [ ] **Step 3: Añadir tabla al esquema en `db.py`**

Editar `db.py`. Añadir al final del bloque `_SCHEMA`, justo antes del `"""` de cierre:

```sql

CREATE TABLE IF NOT EXISTS routine_completions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id         INTEGER NOT NULL,
    completion_date  TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    UNIQUE(event_id, completion_date),
    FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_routine_completions_date
    ON routine_completions(completion_date);
```

- [ ] **Step 4: Añadir migración idempotente**

Editar `db.py`, dentro de la función `_migrate`. Añadir al final de la función:

```python
    # routine_completions: idempotente. Si no existe, la creamos.
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
                UNIQUE(event_id, completion_date),
                FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_routine_completions_date
                ON routine_completions(completion_date)
        """)
```

- [ ] **Step 5: Activar PRAGMA foreign_keys=ON en `connect()`**

Editar `db.py`, modificar el contextmanager `connect`. Sustituir la función `connect` por:

```python
@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
```

- [ ] **Step 6: Ejecutar tests, verificar que pasan**

```bash
python -m pytest tests/test_db.py -v
```

Expected: TODO PASS.

- [ ] **Step 7: Ejecutar suite completa**

```bash
python -m pytest -v
```

Expected: TODO PASS.

- [ ] **Step 8: Commit**

```bash
git add db.py tests/test_db.py
git commit -m "feat(db): routine_completions table with FK cascade and unique constraint

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: `mark_event_done` con routing inteligente

Hacemos que `mark_event_done` distinga eventos puntuales (sigue marcando `done=1`) de rutinas (inserta fila en `routine_completions`).

**Files:**
- Modify: `tools.py`
- Modify: `tests/test_tools_events.py`

- [ ] **Step 1: Escribir tests del nuevo comportamiento**

Añadir al final de `tests/test_tools_events.py`:

```python


def test_mark_event_done_on_non_recurring_sets_done_flag():
    """Comportamiento original intacto: evento puntual → done=1."""
    created = tools.add_event("Médico", "2026-05-20T10:00:00", "medical")

    result = tools.mark_event_done(created["id"])

    assert result["updated"] == 1
    assert result.get("already_done_today") is not True
    with db.connect() as conn:
        row = conn.execute(
            "SELECT done FROM events WHERE id = ?", (created["id"],)
        ).fetchone()
    assert row[0] == 1


def test_mark_event_done_on_recurring_inserts_completion(monkeypatch):
    """Rutina → no toca done; inserta en routine_completions con fecha de hoy Madrid."""
    from datetime import date
    monkeypatch.setattr("date_utils.today_madrid", lambda: date(2026, 5, 19))

    created = tools.add_event(
        "Flexiones", "2026-05-19T08:00:00", "personal",
        recurring_rule="DAILY",
    )

    result = tools.mark_event_done(created["id"])

    assert result["event_id"] == created["id"]
    assert result["completion_date"] == "2026-05-19"
    assert result.get("already_done_today") is not True

    with db.connect() as conn:
        # done sigue 0
        row = conn.execute(
            "SELECT done FROM events WHERE id = ?", (created["id"],)
        ).fetchone()
        assert row[0] == 0
        # Hay fila en routine_completions
        rc = conn.execute(
            "SELECT completion_date FROM routine_completions WHERE event_id = ?",
            (created["id"],),
        ).fetchone()
        assert rc[0] == "2026-05-19"


def test_mark_event_done_on_recurring_twice_same_day_idempotent(monkeypatch):
    """Marcar la misma rutina dos veces el mismo día devuelve already_done_today=True."""
    from datetime import date
    monkeypatch.setattr("date_utils.today_madrid", lambda: date(2026, 5, 19))

    created = tools.add_event(
        "Flexiones", "2026-05-19T08:00:00", "personal",
        recurring_rule="DAILY",
    )

    first = tools.mark_event_done(created["id"])
    second = tools.mark_event_done(created["id"])

    assert first.get("already_done_today") is not True
    assert second["already_done_today"] is True

    with db.connect() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM routine_completions WHERE event_id = ?",
            (created["id"],),
        ).fetchone()[0]
    assert count == 1


def test_mark_event_done_recurring_different_days(monkeypatch):
    """Marcar la misma rutina dos días distintos sí inserta dos filas."""
    from datetime import date
    created = tools.add_event(
        "Flexiones", "2026-05-19T08:00:00", "personal",
        recurring_rule="DAILY",
    )

    monkeypatch.setattr("date_utils.today_madrid", lambda: date(2026, 5, 19))
    tools.mark_event_done(created["id"])

    monkeypatch.setattr("date_utils.today_madrid", lambda: date(2026, 5, 20))
    tools.mark_event_done(created["id"])

    with db.connect() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM routine_completions WHERE event_id = ?",
            (created["id"],),
        ).fetchone()[0]
    assert count == 2
```

- [ ] **Step 2: Ejecutar tests, verificar que fallan**

```bash
python -m pytest tests/test_tools_events.py -v -k mark_event_done
```

Expected: los 4 tests nuevos FAIL (la lógica de rutinas todavía no existe).

- [ ] **Step 3: Implementar la lógica nueva en `tools.py`**

Editar `tools.py`. Sustituir la función `mark_event_done` por:

```python
def mark_event_done(event_id: int) -> dict:
    """Marca un evento como hecho.

    Eventos puntuales → done=1 (permanente).
    Eventos recurrentes (rutinas) → inserta fila en routine_completions
    con la fecha de hoy en Madrid (no toca done).
    """
    import sqlite3

    from date_utils import now_iso, today_madrid

    with db.connect() as conn:
        row = conn.execute(
            "SELECT recurring_rule FROM events WHERE id = ?", (event_id,)
        ).fetchone()
        if row is None:
            return {"id": event_id, "updated": 0}

        if row["recurring_rule"]:
            today = today_madrid().isoformat()
            try:
                conn.execute(
                    """
                    INSERT INTO routine_completions (event_id, completion_date, created_at)
                    VALUES (?, ?, ?)
                    """,
                    (event_id, today, now_iso()),
                )
                return {
                    "event_id": event_id,
                    "completion_date": today,
                    "updated": 1,
                }
            except sqlite3.IntegrityError:
                return {
                    "event_id": event_id,
                    "completion_date": today,
                    "already_done_today": True,
                    "updated": 0,
                }

        cur = conn.execute(
            "UPDATE events SET done = 1 WHERE id = ?", (event_id,)
        )
        return {"id": event_id, "updated": cur.rowcount}
```

- [ ] **Step 4: Ejecutar tests, verificar que pasan**

```bash
python -m pytest tests/test_tools_events.py -v
```

Expected: TODO PASS (los nuevos + los antiguos).

- [ ] **Step 5: Ejecutar suite completa**

```bash
python -m pytest -v
```

Expected: TODO PASS.

- [ ] **Step 6: Commit**

```bash
git add tools.py tests/test_tools_events.py
git commit -m "feat(tools): mark_event_done routes recurring events to routine_completions

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: `query_events` marca instancias recurrentes como hechas por día

Para que `/hoy` distinga rutinas pendientes de las ya hechas hoy, las filas expandidas recurrentes devueltas por `query_events` deben llevar `done` reflejando si hay una fila en `routine_completions` para esa instancia concreta.

**Files:**
- Modify: `tools.py`
- Modify: `tests/test_tools_events.py`

- [ ] **Step 1: Escribir tests**

Añadir al final de `tests/test_tools_events.py`:

```python


def test_query_events_recurring_instance_done_today_reflects_completion():
    """Una rutina DAILY marcada hoy aparece con done=1 en query_events para hoy."""
    created = tools.add_event(
        "Flexiones", "2026-05-19T08:00:00", "personal",
        recurring_rule="DAILY",
    )

    with db.connect() as conn:
        conn.execute(
            "INSERT INTO routine_completions (event_id, completion_date, created_at) VALUES (?, '2026-05-19', '2026-05-19T08:00:00')",
            (created["id"],),
        )

    rows = tools.query_events(
        "2026-05-19T00:00:00", "2026-05-19T23:59:59", include_done=True
    )

    flex_rows = [r for r in rows if r["title"] == "Flexiones"]
    assert len(flex_rows) == 1
    assert flex_rows[0]["done"] == 1


def test_query_events_recurring_instance_pending_when_no_completion():
    """Una rutina DAILY sin completar hoy aparece con done=0."""
    tools.add_event(
        "Flexiones", "2026-05-19T08:00:00", "personal",
        recurring_rule="DAILY",
    )

    rows = tools.query_events(
        "2026-05-19T00:00:00", "2026-05-19T23:59:59", include_done=True
    )

    flex_rows = [r for r in rows if r["title"] == "Flexiones"]
    assert len(flex_rows) == 1
    assert flex_rows[0]["done"] == 0


def test_query_events_recurring_each_instance_independent():
    """Marcar el 19 no afecta a la instancia del 20."""
    created = tools.add_event(
        "Flexiones", "2026-05-19T08:00:00", "personal",
        recurring_rule="DAILY",
    )
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO routine_completions (event_id, completion_date, created_at) VALUES (?, '2026-05-19', '2026-05-19T08:00:00')",
            (created["id"],),
        )

    rows = tools.query_events(
        "2026-05-19T00:00:00", "2026-05-21T23:59:59", include_done=True
    )

    flex_rows = sorted(
        [r for r in rows if r["title"] == "Flexiones"],
        key=lambda r: r["datetime"],
    )
    assert len(flex_rows) == 3  # 19, 20, 21
    assert flex_rows[0]["done"] == 1
    assert flex_rows[1]["done"] == 0
    assert flex_rows[2]["done"] == 0


def test_query_events_non_recurring_done_unchanged():
    """Eventos puntuales mantienen su .done original."""
    created = tools.add_event("Médico", "2026-05-19T10:00:00", "medical")
    tools.mark_event_done(created["id"])

    rows = tools.query_events(
        "2026-05-19T00:00:00", "2026-05-19T23:59:59", include_done=True
    )

    med = [r for r in rows if r["title"] == "Médico"][0]
    assert med["done"] == 1
```

- [ ] **Step 2: Ejecutar tests, verificar que fallan**

```bash
python -m pytest tests/test_tools_events.py -v -k query_events
```

Expected: los tests nuevos de instancias recurrentes con `done` FAIL.

- [ ] **Step 3: Implementar enriquecimiento en `query_events`**

Editar `tools.py`. Sustituir la función `_expand_recurring` por la siguiente versión (acepta connection y rellena `done` por instancia):

```python
def _expand_recurring(
    row: dict,
    rule: str,
    dt_from: datetime,
    dt_to: datetime,
    conn,
) -> list[dict]:
    base_dt = datetime.fromisoformat(row["datetime"])
    results: list[dict] = []

    if rule == "DAILY":
        step = timedelta(days=1)
    elif rule.startswith("WEEKLY:"):
        weekday_code = rule.split(":", 1)[1]
        if weekday_code not in _WEEKDAY_MAP:
            return []
        target_weekday = _WEEKDAY_MAP[weekday_code]
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
        # done por instancia: ¿hay completion para esa fecha?
        completion = conn.execute(
            """
            SELECT 1 FROM routine_completions
            WHERE event_id = ? AND completion_date = ?
            """,
            (row["id"], cur_dt.date().isoformat()),
        ).fetchone()
        clone["done"] = 1 if completion else 0
        results.append(clone)
        cur_dt += step
    return results
```

Y modificar `query_events` para pasar la conexión al expander. Sustituir el bucle de `query_events` que llama a `_expand_recurring` por:

```python
def query_events(
    date_from: str,
    date_to: str,
    category: Optional[str] = None,
    include_done: bool = False,
) -> list[dict]:
    dt_from = datetime.fromisoformat(date_from)
    dt_to = datetime.fromisoformat(date_to)

    with db.connect() as conn:
        params: list = []
        sql = "SELECT * FROM events WHERE 1=1"
        if not include_done:
            sql += " AND COALESCE(done, 0) = 0"
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
                occurrences.extend(_expand_recurring(row, rule, dt_from, dt_to, conn))

    occurrences.sort(key=lambda r: r["datetime"])
    return occurrences
```

Nota: el SQL inicial usa `COALESCE(done,0)=0` para excluir recurrentes con done=1 (no debería pasar, pero por seguridad). En la lista de candidatos para expandir, los recurrentes pasan el filtro (su `done` permanece 0 siempre).

- [ ] **Step 4: Ejecutar tests, verificar que pasan**

```bash
python -m pytest tests/test_tools_events.py -v
```

Expected: TODO PASS.

- [ ] **Step 5: Ejecutar suite completa**

```bash
python -m pytest -v
```

Expected: TODO PASS.

- [ ] **Step 6: Commit**

```bash
git add tools.py tests/test_tools_events.py
git commit -m "feat(tools): query_events sets per-instance done for recurring rows

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Tool `routine_summary` con conteos por rango

Para `/semana` necesitamos una vista agregada: una fila por rutina con `(completed_days, scheduled_days)`. La exponemos como herramienta para que Claude la llame directamente.

**Files:**
- Modify: `tools.py`
- Modify: `tests/test_tools_events.py`
- Modify: `tests/test_tools_registry.py`

- [ ] **Step 1: Escribir tests**

Añadir al final de `tests/test_tools_events.py`:

```python


def test_routine_summary_counts_completions_in_range():
    """Marca 3 días de la semana → completed_days=3, scheduled_days=7."""
    created = tools.add_event(
        "Flexiones", "2026-05-18T08:00:00", "personal",
        recurring_rule="DAILY",
    )
    with db.connect() as conn:
        for d in ("2026-05-18", "2026-05-19", "2026-05-20"):
            conn.execute(
                "INSERT INTO routine_completions (event_id, completion_date, created_at) VALUES (?, ?, ?)",
                (created["id"], d, "2026-05-19T08:00:00"),
            )

    summary = tools.routine_summary("2026-05-18", "2026-05-24")

    flex = [r for r in summary if r["title"] == "Flexiones"][0]
    assert flex["scheduled_days"] == 7
    assert flex["completed_days"] == 3
    assert flex["event_id"] == created["id"]
    assert flex["recurring_rule"] == "DAILY"


def test_routine_summary_weekly_routine_scheduled_once():
    """WEEKLY:MON entre lunes 18 y domingo 24 → scheduled_days=1."""
    tools.add_event(
        "Gimnasio", "2026-05-18T19:00:00", "personal",
        recurring_rule="WEEKLY:MON",
    )

    summary = tools.routine_summary("2026-05-18", "2026-05-24")

    gym = [r for r in summary if r["title"] == "Gimnasio"][0]
    assert gym["scheduled_days"] == 1
    assert gym["completed_days"] == 0


def test_routine_summary_ignores_non_recurring():
    """Eventos puntuales no aparecen en el summary."""
    tools.add_event("Médico", "2026-05-20T10:00:00", "medical")

    summary = tools.routine_summary("2026-05-18", "2026-05-24")

    titles = [r["title"] for r in summary]
    assert "Médico" not in titles


def test_routine_summary_empty_when_no_routines():
    summary = tools.routine_summary("2026-05-18", "2026-05-24")
    assert summary == []


def test_routine_summary_weekly_routine_not_in_range_excluded():
    """WEEKLY:TUE en una semana que no contiene martes (rango Wed-Wed) → no aparece."""
    tools.add_event(
        "Yoga", "2026-05-19T07:00:00", "personal",
        recurring_rule="WEEKLY:TUE",
    )

    # Rango miércoles a martes siguiente — contiene un martes
    summary = tools.routine_summary("2026-05-20", "2026-05-26")
    yoga = [r for r in summary if r["title"] == "Yoga"]
    assert len(yoga) == 1
    assert yoga[0]["scheduled_days"] == 1

    # Rango sin martes
    summary = tools.routine_summary("2026-05-21", "2026-05-25")
    yoga = [r for r in summary if r["title"] == "Yoga"]
    assert yoga == []
```

Y añadir al final de `tests/test_tools_registry.py`:

```python


def test_routine_summary_is_registered():
    names = [t["name"] for t in tools.TOOL_DEFINITIONS]
    assert "routine_summary" in names
    assert "routine_summary" in tools._DISPATCH
```

- [ ] **Step 2: Ejecutar tests, verificar que fallan**

```bash
python -m pytest tests/test_tools_events.py tests/test_tools_registry.py -v -k routine_summary
```

Expected: 6 tests nuevos FAIL — función no existe.

- [ ] **Step 3: Implementar `routine_summary` en `tools.py`**

Editar `tools.py`. Añadir después de la función `mark_event_done` (justo antes del comentario `# ------------------------------------------------------------ objectives ----`):

```python


def routine_summary(date_from: str, date_to: str) -> list[dict]:
    """Resumen agregado de rutinas (eventos recurrentes) para un rango de fechas.

    Devuelve una fila por rutina con cuántos días tocaba (scheduled_days)
    y cuántos se completaron (completed_days) dentro del rango [date_from, date_to].

    Formato fechas: 'YYYY-MM-DD'. El rango es inclusivo por ambos extremos.
    """
    start = date.fromisoformat(date_from)
    end = date.fromisoformat(date_to)
    if end < start:
        return []

    results: list[dict] = []
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM events WHERE recurring_rule IS NOT NULL"
        ).fetchall()

        for row in rows:
            rule = row["recurring_rule"]
            scheduled = _count_scheduled_days(rule, row["datetime"], start, end)
            if scheduled == 0:
                continue
            completed = conn.execute(
                """
                SELECT COUNT(*) FROM routine_completions
                WHERE event_id = ?
                  AND completion_date >= ?
                  AND completion_date <= ?
                """,
                (row["id"], date_from, date_to),
            ).fetchone()[0]
            results.append({
                "event_id": row["id"],
                "title": row["title"],
                "category": row["category"],
                "recurring_rule": rule,
                "scheduled_days": scheduled,
                "completed_days": completed,
            })
    return results


def _count_scheduled_days(rule: str, base_datetime_iso: str, start: date, end: date) -> int:
    """Cuántas instancias programadas tiene una rutina en [start, end]."""
    if rule == "DAILY":
        return (end - start).days + 1
    if rule.startswith("WEEKLY:"):
        weekday_code = rule.split(":", 1)[1]
        if weekday_code not in _WEEKDAY_MAP:
            return 0
        target = _WEEKDAY_MAP[weekday_code]
        count = 0
        cur = start
        while cur <= end:
            if cur.weekday() == target:
                count += 1
            cur += timedelta(days=1)
        return count
    return 0
```

Y registrar el tool. Editar `tools.py`, añadir al final de la lista `TOOL_DEFINITIONS` (antes del corchete de cierre `]`):

```python
    {
        "name": "routine_summary",
        "description": (
            "Resumen agregado de rutinas (eventos recurrentes) para un rango de "
            "fechas. Devuelve por cada rutina cuántos días tocaba (scheduled_days) "
            "y cuántos se completaron (completed_days). Útil para /semana."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date_from": {"type": "string", "description": "ISO date YYYY-MM-DD"},
                "date_to": {"type": "string", "description": "ISO date YYYY-MM-DD"},
            },
            "required": ["date_from", "date_to"],
        },
    },
```

Y añadirla al `_DISPATCH`:

```python
_DISPATCH = {
    "add_event": add_event,
    "query_events": query_events,
    "update_event": update_event,
    "delete_event": delete_event,
    "mark_event_done": mark_event_done,
    "routine_summary": routine_summary,
    "add_objective": add_objective,
    "query_objectives": query_objectives,
    "mark_objective_done": mark_objective_done,
    "add_task": add_task,
    "list_tasks": list_tasks,
    "complete_task": complete_task,
}
```

- [ ] **Step 4: Ejecutar tests, verificar que pasan**

```bash
python -m pytest tests/test_tools_events.py tests/test_tools_registry.py -v
```

Expected: TODO PASS.

- [ ] **Step 5: Ejecutar suite completa**

```bash
python -m pytest -v
```

Expected: TODO PASS.

- [ ] **Step 6: Commit**

```bash
git add tools.py tests/test_tools_events.py tests/test_tools_registry.py
git commit -m "feat(tools): routine_summary tool with per-range completion counts

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Prompts actualizados para sección 🔁 RUTINAS

Tres archivos con prompts: `brain.py` (system prompt — formato global), `bot.py` (slash commands `/hoy` y `/semana`), `scheduler.py` (saludo matutino). Todos deben pedir la sección RUTINAS.

**Files:**
- Modify: `brain.py`
- Modify: `bot.py`
- Modify: `scheduler.py`
- Modify: `tests/test_brain.py`
- Modify: `tests/test_bot.py`
- Modify: `tests/test_scheduler.py`

- [ ] **Step 1: Escribir tests de string-match en los prompts**

Añadir al final de `tests/test_brain.py`:

```python


def test_system_prompt_includes_rutinas_section():
    prompt = brain._system_prompt()
    assert "🔁" in prompt
    assert "RUTINAS" in prompt
```

(Si `import brain` no existe arriba, añadirlo.)

Añadir al final de `tests/test_bot.py`:

```python


def test_hoy_prompt_mentions_routine_summary_and_rutinas():
    prompt = bot._SLASH_PROMPTS["/hoy"]
    assert "RUTINAS" in prompt
    # /hoy usa query_events que devuelve done por instancia, no necesita routine_summary
    assert "query_events" in prompt


def test_semana_prompt_uses_routine_summary():
    prompt = bot._SLASH_PROMPTS["/semana"]
    assert "RUTINAS" in prompt
    assert "routine_summary" in prompt
```

Añadir al final de `tests/test_scheduler.py`:

```python


def test_morning_prompt_includes_rutinas_section():
    prompt = scheduler._morning_prompt()
    assert "🔁" in prompt
    assert "RUTINAS" in prompt
```

- [ ] **Step 2: Ejecutar tests, verificar que fallan**

```bash
python -m pytest tests/test_brain.py tests/test_bot.py tests/test_scheduler.py -v -k "rutinas or routine"
```

Expected: 4 tests nuevos FAIL — las strings no aparecen aún.

- [ ] **Step 3: Actualizar plantilla y reglas en `brain.py`**

Editar `brain.py`. Localizar el bloque de "Plantilla para resúmenes" en `_system_prompt()`. Sustituir la sección de plantilla (de `Plantilla para resúmenes` hasta el cierre `]` del cierre motivador) por:

```text
Plantilla para resúmenes (úsala como guía, ajusta lo que no encaje):

📅 <b>HOY</b>

• 09:00 — Reunión equipo
• 17:00 — Cita médico

🔁 <b>RUTINAS</b>

• 50 flexiones diarias
• Leer 5 páginas
• Anotar 3 cosas buenas del día

📝 <b>PENDIENTES</b>

• Comprar pan
• Llamar fontanero

✅ <b>COMPLETADO HOY</b>

• <s>Reunión equipo (09:00)</s>
• <s>50 flexiones diarias</s>
• <s>Comprar leche</s>

💪 [Cierre motivador opcional, 1 frase. Si he completado cosas, celébralo brevemente.]
```

Y en las "REGLAS ESTRICTAS DE FORMATO para resúmenes", añadir como nueva regla al final de la numerada (después de la 6):

```text
7. RUTINAS son eventos con recurring_rule no nulo. En la sección RUTINAS NO muestres horas — solo el título. Si la instancia de hoy ya está hecha (done=1 en el resultado de query_events para esa fila), envuelve el título en <s>...</s> y añádelo también a COMPLETADO HOY. Si no hay rutinas que toquen el día/rango, OMITE la sección RUTINAS por completo.
```

Y en "CÓMO IDENTIFICAR LO COMPLETADO" añadir al final:

```text
- "Completado hoy" para RUTINAS: instancias recurrentes devueltas por query_events para hoy cuyo done=1. (Mecánica interna: hay una fila en routine_completions para esa fecha; tú solo lees done.)
```

- [ ] **Step 4: Actualizar prompts de `/hoy` y `/semana` en `bot.py`**

Editar `bot.py`. Sustituir el contenido del diccionario `_SLASH_PROMPTS` por:

```python
_SLASH_PROMPTS = {
    "/hoy": (
        "Resumen de hoy. SIGUE ESTOS PASOS EN ORDEN:\n"
        "1. Llama a query_events(date_from=hoy 00:00, date_to=hoy 23:59, include_done=true) — devuelve TODOS los eventos de hoy, incluyendo instancias de rutinas con done por instancia.\n"
        "2. Llama a list_tasks(include_done=true) — devuelve TODAS las tareas.\n"
        "3. Construye estas secciones (OMITE las vacías sin decir nada):\n"
        "   📅 HOY = eventos del paso 1 SIN recurring_rule y con done=0\n"
        "   🔁 RUTINAS = eventos del paso 1 CON recurring_rule. Si done=1 → títulos envueltos en <s>...</s>. Sin horas.\n"
        "   📝 PENDIENTES = tareas del paso 2 con done=0\n"
        "   ✅ COMPLETADO HOY = eventos del paso 1 sin recurring_rule con done=1 + eventos del paso 1 con recurring_rule y done=1 (rutinas hechas hoy, tachadas) + tareas del paso 2 cuyo done_at sea de hoy\n"
        "4. Cierre motivador opcional de UNA frase si encaja.\n"
        "NADA de preámbulos, notas o preguntas."
    ),
    "/semana": (
        "Resumen de la semana. SIGUE ESTOS PASOS EN ORDEN:\n"
        "1. Llama a query_events(date_from=lunes 00:00, date_to=domingo 23:59 de esta semana, include_done=true).\n"
        "2. Llama a query_objectives(week_start=lunes de esta semana).\n"
        "3. Llama a list_tasks(include_done=true).\n"
        "4. Llama a routine_summary(date_from=lunes, date_to=domingo) en formato YYYY-MM-DD — devuelve agregado de cada rutina con scheduled_days y completed_days.\n"
        "5. Construye estas secciones (OMITE las vacías sin decir nada):\n"
        "   📅 ESTA SEMANA = eventos del paso 1 SIN recurring_rule y con done=0\n"
        "   🎯 OBJETIVOS = objetivos del paso 2 (marca con ✅ los done=1, con 🔲 los pendientes)\n"
        "   🔁 RUTINAS = una línea por rutina del paso 4 con formato '{title} ({completed_days}/{scheduled_days} días)'\n"
        "   ✅ COMPLETADO = eventos del paso 1 sin recurring_rule con done=1 + tareas del paso 3 cuyo done_at sea de esta semana\n"
        "6. Cierre motivador opcional de UNA frase si encaja.\n"
        "NADA de preámbulos ni preguntas."
    ),
    "/pendientes": (
        "Lista mis tareas pendientes (list_tasks con include_done=false) en formato HTML, una por bullet. "
        "Sin preámbulos. Si la lista está vacía, di solo «No tienes tareas pendientes. 🎉»."
    ),
    "/objetivos": (
        "Muéstrame el estado de mis objetivos de esta semana. "
        "Llama a query_objectives(week_start=lunes de esta semana). "
        "Lista cada uno con ✅ si está done=1 o 🔲 si no. "
        "Una frase de cierre con ánimo. Sin preámbulos."
    ),
}
```

- [ ] **Step 5: Actualizar prompt de matutino en `scheduler.py`**

Editar `scheduler.py`. Sustituir la función `_morning_prompt` por:

```python
def _morning_prompt() -> str:
    today = datetime.now()
    weekday = _WEEKDAYS_ES[today.weekday()]
    date_str = today.strftime("%Y-%m-%d")
    return (
        f"Es {weekday}, {date_str}. Genera el saludo matutino para Pablo. "
        "Empieza con 'Buenos días Pablo 🌅' y a continuación aplica el formato del resumen del día "
        "siguiendo EXACTAMENTE estos pasos:\n"
        "1. Llama a query_events(date_from=hoy 00:00, date_to=hoy 23:59, include_done=true).\n"
        "2. Llama a list_tasks(include_done=true).\n"
        "3. Construye las secciones (OMITE las vacías sin decir nada):\n"
        "   📅 HOY = eventos del paso 1 SIN recurring_rule y con done=0\n"
        "   🔁 RUTINAS = eventos del paso 1 CON recurring_rule. Si done=1 → títulos en <s>...</s>. Sin horas.\n"
        "   📝 PENDIENTES = tareas del paso 2 con done=0\n"
        "   ✅ COMPLETADO HOY = eventos del paso 1 sin recurring_rule con done=1 + eventos del paso 1 con recurring_rule y done=1 + tareas del paso 2 con done_at de hoy\n"
        "4. Si no hay nada en ninguna sección, di solo que puede disfrutar del día libre.\n"
        "5. Cierra con una frase motivadora breve si encaja."
    )
```

- [ ] **Step 6: Ejecutar tests, verificar que pasan**

```bash
python -m pytest tests/test_brain.py tests/test_bot.py tests/test_scheduler.py -v
```

Expected: TODO PASS.

- [ ] **Step 7: Ejecutar suite completa**

```bash
python -m pytest -v
```

Expected: TODO PASS.

- [ ] **Step 8: Commit**

```bash
git add brain.py bot.py scheduler.py tests/test_brain.py tests/test_bot.py tests/test_scheduler.py
git commit -m "feat(prompts): add 🔁 RUTINAS section to /hoy, /semana, morning summary

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Deploy a Fly.io y validación manual end-to-end

Subimos los cambios a Fly y validamos en producción con Pablo.

**Files:**
- (ninguno — solo despliegue y prueba en Telegram)

- [ ] **Step 1: Confirmar que la suite completa pasa**

```bash
python -m pytest -v
```

Expected: TODO PASS, sin warnings nuevos.

- [ ] **Step 2: Desplegar a Fly**

```bash
flyctl deploy --app mi-secretaria-pablo
```

Expected: build OK, machine actualizada sin errores. La migración `_migrate` corre al arrancar y crea `routine_completions` sin tocar las rutinas ya existentes.

- [ ] **Step 3: Verificar arranque limpio**

```bash
flyctl logs --app mi-secretaria-pablo --no-tail | tail -30
```

Expected: ver "Base de datos lista en /data/organizador.db", ambos jobs registrados, polling activo. **NO** ver excepciones de SQLite.

- [ ] **Step 4: Verificar `/hoy` en Telegram**

Pablo envía `/hoy` por Telegram. Esperado:
- Aparece sección 🔁 RUTINAS con las 3 rutinas diarias suyas.
- Las 3 aparecen SIN tachar (porque hoy no las ha marcado todavía).

- [ ] **Step 5: Marcar una rutina y volver a pedir `/hoy`**

Pablo envía: *"ya hice las flexiones"*. El bot debe confirmar.

Pablo envía `/hoy` otra vez. Esperado:
- 50 flexiones aparecen <s>tachadas</s> en 🔁 RUTINAS.
- Aparecen también en ✅ COMPLETADO HOY.

- [ ] **Step 6: Marcar la misma rutina dos veces**

Pablo envía otra vez: *"ya hice las flexiones"*. Esperado:
- El bot le dice algo tipo "ya estaba marcado para hoy", no duplica.

- [ ] **Step 7: Verificar `/semana`**

Pablo envía `/semana`. Esperado:
- Sección 🔁 RUTINAS con líneas tipo:
  - `50 flexiones diarias (1/7 días)`
  - `Leer 5 páginas (0/7 días)`
  - `Anotar 3 cosas buenas (0/7 días)`

- [ ] **Step 8: Push de los commits a GitHub**

```bash
git push
```

Expected: push exitoso.

---

## Resumen de entregables

- `date_utils.py`: helpers `now_madrid`, `today_madrid`, `now_madrid_naive`.
- `Dockerfile`: `TZ=Europe/Madrid` configurado.
- `db.py`: tabla `routine_completions`, migración idempotente, `PRAGMA foreign_keys=ON` en `connect()`.
- `tools.py`: `mark_event_done` enrutado, `query_events` con `done` por instancia para recurrentes, nueva tool `routine_summary`.
- `brain.py`: system prompt actualizado con plantilla RUTINAS y reglas.
- `bot.py`: prompts `/hoy` y `/semana` actualizados.
- `scheduler.py`: prompt matutino actualizado.
- Tests nuevos: 3 (date_utils tz) + 4 (db: migration/FK/cascade/unique) + 4 (mark_event_done) + 4 (query_events done por instancia) + 5 (routine_summary) + 1 (routine_summary en registry) + 4 (string-match en prompts) = **+25 sobre la base actual**.
- Deploy a Fly verificado y validado end-to-end por Pablo.

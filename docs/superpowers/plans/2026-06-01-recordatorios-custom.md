# Recordatorios personalizados — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permitir a Pablo decir "avísame X antes" sobre cualquier evento puntual y recibir un aviso por Telegram con esa antelación, desactivando los defaults (1d + 1h) para ese evento.

**Architecture:** Tabla nueva `event_reminders` ligada por FK a `events`. Tool `add_event_reminder` para Claude y parámetro `reminders` opcional en `add_event`. `scheduler.check_reminders` añade dos cambios: filtro `NOT EXISTS` para no mandar defaults cuando hay customs, y bloque nuevo que dispara los customs dentro de ventana ±5 min. Patrón `fires_immediately` paralelo al de niveles para mandar el aviso al instante cuando el offset ya pasó al añadirlo.

**Tech Stack:** Python 3, SQLite, python-telegram-bot 21, pytest + pytest-asyncio. Spec completa en `docs/superpowers/specs/2026-06-01-recordatorios-custom-design.md`.

---

## File structure

**Modificados:**
- `db.py` — añadir migración `event_reminders` + índices.
- `tools.py` — nueva `add_event_reminder`, modificar `add_event` (acepta `reminders` opcional), registrar en `TOOL_DEFINITIONS` y `_DISPATCH`.
- `scheduler.py` — modificar `check_reminders` (filtro `NOT EXISTS` en query de defaults, bloque nuevo para customs). Añadir helper `_format_offset`.
- `brain.py` — añadir `_pending_immediate_reminders` dict + `record_immediate_reminder` / `pop_immediate_reminders`; integrar captura en bucle de tool_use.
- `bot.py` — en `_on_message` y `_on_voice`, consumir y enviar los inmediatos pendientes tras la respuesta normal. Añadir helper `_render_reminder_message`. Modificar el system prompt en `brain.py` (nueva regla).

**Nuevos tests:**
- `tests/test_tools_reminders.py` — tests de `add_event_reminder` (validaciones, happy path, fires_immediately, idempotencia, cascada) y de `add_event(reminders=[...])`.

**Tests modificados:**
- `tests/test_db.py` — tabla `event_reminders` existe.
- `tests/test_scheduler.py` — `check_reminders` con customs (envío, idempotencia, defaults OFF, ventana, evento done).
- `tests/test_brain.py` — `record_immediate_reminder` / `pop_immediate_reminders`.
- `tests/test_bot.py` — `_on_message` envía recordatorios inmediatos.

**Comando para correr la suite:**

```bash
./.venv/bin/python -m pytest
```

Para tests específicos:

```bash
./.venv/bin/python -m pytest tests/test_tools_reminders.py -v
./.venv/bin/python -m pytest -k "reminder"
```

**Convención de fechas en tests**: patchear `date_utils.today_madrid`. Para tests que necesiten controlar `now_iso` o el "ahora" comparado contra event.datetime, fijar valores absolutos en los datos (no usar `datetime.now()` directo en aserciones).

---

## Task 1: Migración de esquema `event_reminders`

**Files:**
- Modify: `db.py` (`_SCHEMA` + `_migrate`)
- Test: `tests/test_db.py`

- [ ] **Step 1: Escribir tests fallidos**

Añadir al final de `tests/test_db.py`:

```python
def test_event_reminders_table_exists(fresh_db):
    with db.connect() as conn:
        cols = [r[1] for r in conn.execute(
            "PRAGMA table_info(event_reminders)"
        ).fetchall()]
    assert "event_id" in cols
    assert "offset_minutes" in cols
    assert "sent" in cols
    assert "created_at" in cols


def test_event_reminders_cascades_on_event_delete(fresh_db):
    with db.connect() as conn:
        # Crear un evento mínimo
        cur = conn.execute(
            "INSERT INTO events (title, datetime, category, created_at) "
            "VALUES ('Test', '2026-06-10T10:00:00', 'personal', '2026-06-01T08:00:00')"
        )
        event_id = cur.lastrowid
        conn.execute(
            "INSERT INTO event_reminders "
            "(event_id, offset_minutes, sent, created_at) "
            "VALUES (?, 30, 0, '2026-06-01T08:00:00')",
            (event_id,),
        )
        # Borrar el evento; el recordatorio debe desaparecer (CASCADE)
        conn.execute("DELETE FROM events WHERE id = ?", (event_id,))
        count = conn.execute(
            "SELECT COUNT(*) FROM event_reminders WHERE event_id = ?",
            (event_id,),
        ).fetchone()[0]
    assert count == 0
```

- [ ] **Step 2: Verificar que fallan**

```
./.venv/bin/python -m pytest tests/test_db.py -v -k "event_reminders"
```

Esperado: FAIL con `no such table: event_reminders`.

- [ ] **Step 3: Añadir la tabla en `db.py`**

En `_migrate(conn)`, antes de la línea final, añadir:

```python
    if "event_reminders" not in tables:
        conn.execute("""
            CREATE TABLE event_reminders (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id        INTEGER NOT NULL,
                offset_minutes  INTEGER NOT NULL,
                sent            INTEGER NOT NULL DEFAULT 0,
                created_at      TEXT    NOT NULL,
                FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_event_reminders_event "
            "ON event_reminders(event_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_event_reminders_pending "
            "ON event_reminders(sent, event_id)"
        )
```

Y en `_SCHEMA` (al final, antes del cierre triple-comilla):

```sql

CREATE TABLE IF NOT EXISTS event_reminders (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id        INTEGER NOT NULL,
    offset_minutes  INTEGER NOT NULL,
    sent            INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT    NOT NULL,
    FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_event_reminders_event
    ON event_reminders(event_id);

CREATE INDEX IF NOT EXISTS idx_event_reminders_pending
    ON event_reminders(sent, event_id);
```

- [ ] **Step 4: Verificar que pasan**

```
./.venv/bin/python -m pytest tests/test_db.py -v
```

- [ ] **Step 5: Suite completa**

```
./.venv/bin/python -m pytest
```

- [ ] **Step 6: Commit**

```
git add db.py tests/test_db.py
git commit -m "$(cat <<'EOF'
feat(db): migración para tabla event_reminders

Tabla nueva con FK a events.id ON DELETE CASCADE para los
recordatorios custom. Migración idempotente aditiva.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Tool `add_event_reminder` — validaciones y happy path

**Files:**
- Modify: `tools.py` (añadir función después de `mark_event_done`)
- Create: `tests/test_tools_reminders.py`

- [ ] **Step 1: Crear `tests/test_tools_reminders.py`**

```python
"""Tests de la tool add_event_reminder y add_event con reminders."""
import os
import tempfile
from datetime import date, datetime, timedelta

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


def _seed_future_event(title="Cita", offset_hours=24):
    """Crea un evento que ocurre `offset_hours` horas en el futuro real."""
    when = (datetime.now() + timedelta(hours=offset_hours)).replace(microsecond=0)
    return tools.add_event(title, when.isoformat(), "personal")


def test_add_event_reminder_not_found():
    res = tools.add_event_reminder(99999, 30)
    assert res.get("error") == "not_found"


def test_add_event_reminder_invalid_offset_zero():
    ev = _seed_future_event()
    res = tools.add_event_reminder(ev["id"], 0)
    assert res.get("error") == "invalid_offset"


def test_add_event_reminder_invalid_offset_negative():
    ev = _seed_future_event()
    res = tools.add_event_reminder(ev["id"], -10)
    assert res.get("error") == "invalid_offset"


def test_add_event_reminder_recurring_event_rejected():
    ev = tools.add_event(
        "Meditar",
        (datetime.now() + timedelta(hours=24)).replace(microsecond=0).isoformat(),
        "personal",
        recurring_rule="DAILY",
    )
    res = tools.add_event_reminder(ev["id"], 30)
    assert res.get("error") == "event_is_recurring"


def test_add_event_reminder_done_event_rejected():
    ev = _seed_future_event()
    with db.connect() as conn:
        conn.execute("UPDATE events SET done = 1 WHERE id = ?", (ev["id"],))
    res = tools.add_event_reminder(ev["id"], 30)
    assert res.get("error") == "event_already_done"


def test_add_event_reminder_future_inserts_pending():
    """Evento dentro de 24h, recordatorio 30 min antes → fila sent=0,
    fires_immediately=False."""
    ev = _seed_future_event(offset_hours=24)
    res = tools.add_event_reminder(ev["id"], 30)
    assert res.get("event_id") == ev["id"]
    assert res.get("offset_minutes") == 30
    assert res.get("fires_immediately") is False
    with db.connect() as conn:
        row = conn.execute(
            "SELECT sent, offset_minutes FROM event_reminders "
            "WHERE event_id = ?",
            (ev["id"],),
        ).fetchone()
    assert row["sent"] == 0
    assert row["offset_minutes"] == 30
```

- [ ] **Step 2: Verificar que fallan**

```
./.venv/bin/python -m pytest tests/test_tools_reminders.py -v
```

Esperado: FAIL con `AttributeError: module 'tools' has no attribute 'add_event_reminder'`.

- [ ] **Step 3: Añadir `add_event_reminder` en `tools.py`**

Inmediatamente después de `mark_event_done` (busca el `def mark_event_done` y añade después de su `return`):

```python
def add_event_reminder(event_id: int, minutes_before: int) -> dict:
    """Añade un recordatorio custom al evento.

    Reglas:
    - Solo eventos puntuales (no recurrentes) y no marcados como hechos.
    - minutes_before debe ser > 0.
    - Si el momento del aviso ya pasó (event.datetime - now < minutes_before),
      la fila se inserta con sent=1 y se devuelve fires_immediately=True
      para que el bot lo entregue inmediatamente.
    """
    import date_utils
    if minutes_before <= 0:
        return {"error": "invalid_offset"}

    with db.connect() as conn:
        row = conn.execute(
            "SELECT id, datetime, recurring_rule, done FROM events WHERE id = ?",
            (event_id,),
        ).fetchone()
        if row is None:
            return {"error": "not_found"}
        if row["recurring_rule"]:
            return {"error": "event_is_recurring"}
        if row["done"] == 1:
            return {"error": "event_already_done"}

        try:
            event_dt = datetime.fromisoformat(row["datetime"])
        except ValueError:
            return {"error": "bad_datetime"}

        now = datetime.fromisoformat(date_utils.now_iso())
        fire_time = event_dt - timedelta(minutes=minutes_before)
        fires_immediately = fire_time <= now

        conn.execute(
            "INSERT INTO event_reminders "
            "(event_id, offset_minutes, sent, created_at) "
            "VALUES (?, ?, ?, ?)",
            (
                event_id,
                minutes_before,
                1 if fires_immediately else 0,
                date_utils.now_iso(),
            ),
        )

    return {
        "event_id": event_id,
        "offset_minutes": minutes_before,
        "fires_immediately": fires_immediately,
    }
```

(Confirma que `datetime` y `timedelta` están importados al inicio del archivo — `from datetime import datetime, timedelta, date`. Si falta `timedelta`, añade.)

- [ ] **Step 4: Verificar que pasan**

```
./.venv/bin/python -m pytest tests/test_tools_reminders.py -v
```

Esperado: 6 PASS.

- [ ] **Step 5: Suite**

```
./.venv/bin/python -m pytest
```

- [ ] **Step 6: Commit**

```
git add tools.py tests/test_tools_reminders.py
git commit -m "$(cat <<'EOF'
feat(tools): add_event_reminder con validaciones y modo pendiente

Crea recordatorios custom sobre eventos puntuales. Valida que el
evento exista, no sea recurrente, no esté marcado como hecho y que
el offset sea positivo. Inserta fila con sent=0 si el momento del
aviso está en el futuro.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `add_event_reminder` — fires_immediately + idempotencia

**Files:**
- Modify: `tools.py` (función `add_event_reminder` ya existente)
- Modify: `tests/test_tools_reminders.py`

- [ ] **Step 1: Añadir tests al final de `tests/test_tools_reminders.py`**

```python
def test_add_event_reminder_past_window_fires_immediately():
    """Evento dentro de 10 min, offset 30 min → fire_time ya pasó →
    sent=1 y fires_immediately=True."""
    ev = _seed_future_event(offset_hours=0.16)  # ~10 min en el futuro
    res = tools.add_event_reminder(ev["id"], 30)
    assert res["fires_immediately"] is True
    with db.connect() as conn:
        row = conn.execute(
            "SELECT sent FROM event_reminders WHERE event_id = ?",
            (ev["id"],),
        ).fetchone()
    assert row["sent"] == 1


def test_add_event_reminder_idempotent_same_offset():
    """Llamar dos veces con (event_id, offset) iguales no duplica."""
    ev = _seed_future_event(offset_hours=24)
    r1 = tools.add_event_reminder(ev["id"], 30)
    assert "already_exists" not in r1
    r2 = tools.add_event_reminder(ev["id"], 30)
    assert r2.get("already_exists") is True
    with db.connect() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM event_reminders WHERE event_id = ?",
            (ev["id"],),
        ).fetchone()[0]
    assert count == 1


def test_add_event_reminder_different_offsets_coexist():
    """Dos offsets distintos en el mismo evento son dos filas independientes."""
    ev = _seed_future_event(offset_hours=24)
    tools.add_event_reminder(ev["id"], 30)
    tools.add_event_reminder(ev["id"], 180)
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT offset_minutes FROM event_reminders "
            "WHERE event_id = ? ORDER BY offset_minutes",
            (ev["id"],),
        ).fetchall()
    assert [r["offset_minutes"] for r in rows] == [30, 180]
```

- [ ] **Step 2: Verificar que fallan los relevantes**

```
./.venv/bin/python -m pytest tests/test_tools_reminders.py -v -k "idempotent or fires_immediately or different_offsets"
```

(El de `fires_immediately` probablemente pasa porque Task 2 ya lo cubre; el de `idempotent` falla.)

- [ ] **Step 3: Añadir idempotencia en `add_event_reminder`**

En `tools.py`, dentro de `add_event_reminder`, **antes** del `conn.execute("INSERT INTO event_reminders ...")` y después de validar el evento, añadir:

```python
        existing = conn.execute(
            "SELECT id FROM event_reminders "
            "WHERE event_id = ? AND offset_minutes = ?",
            (event_id, minutes_before),
        ).fetchone()
        if existing:
            return {
                "event_id": event_id,
                "offset_minutes": minutes_before,
                "already_exists": True,
            }
```

- [ ] **Step 4: Verificar pass**

```
./.venv/bin/python -m pytest tests/test_tools_reminders.py -v
```

Esperado: 9 PASS (los 6 anteriores + 3 nuevos).

- [ ] **Step 5: Suite**

```
./.venv/bin/python -m pytest
```

- [ ] **Step 6: Commit**

```
git add tools.py tests/test_tools_reminders.py
git commit -m "$(cat <<'EOF'
feat(tools): add_event_reminder idempotente y fires_immediately

Si (event_id, offset_minutes) ya existe, no duplica y devuelve
already_exists=True. fires_immediately=True cuando el momento del
aviso ya pasó al añadirlo.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Registrar `add_event_reminder` en `TOOL_DEFINITIONS` y `_DISPATCH`

**Files:**
- Modify: `tools.py` (bloques `TOOL_DEFINITIONS` y `_DISPATCH`)

- [ ] **Step 1: Añadir entrada en `TOOL_DEFINITIONS`**

Tras la entrada de `mark_event_done` (busca su bloque dict en `TOOL_DEFINITIONS`), añadir:

```python
    {
        "name": "add_event_reminder",
        "description": (
            "Añade un recordatorio personalizado a un evento puntual existente. "
            "minutes_before es la antelación en minutos (30 = 30 min antes, "
            "60 = 1h antes, 1440 = 1 día antes, 10080 = 1 semana antes). "
            "Si el evento ya tiene cualquier recordatorio custom, los avisos "
            "por defecto (1d y 1h antes) NO se mandarán para ese evento. "
            "No usar en eventos recurrentes/rutinas."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "event_id": {"type": "integer"},
                "minutes_before": {
                    "type": "integer",
                    "description": "Minutos antes del evento. Debe ser > 0.",
                },
            },
            "required": ["event_id", "minutes_before"],
        },
    },
```

- [ ] **Step 2: Añadir entrada en `_DISPATCH`**

```python
    "add_event_reminder": add_event_reminder,
```

- [ ] **Step 3: Verificar que la tool es invocable vía dispatch**

```
./.venv/bin/python -c "import tools; print(tools.dispatch('add_event_reminder', {'event_id': 99999, 'minutes_before': 30}))"
```

Esperado: `{'error': 'not_found'}` (sin tracebacks).

- [ ] **Step 4: Suite**

```
./.venv/bin/python -m pytest
```

- [ ] **Step 5: Commit**

```
git add tools.py
git commit -m "$(cat <<'EOF'
feat(tools): registrar add_event_reminder en TOOL_DEFINITIONS

Claude ya puede invocar la tool. La descripción menciona la regla
de que custom desactiva defaults y la unidad (minutos).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `add_event` acepta `reminders=[...]` opcional

**Files:**
- Modify: `tools.py` (`add_event` + entrada en `TOOL_DEFINITIONS`)
- Modify: `tests/test_tools_reminders.py`

- [ ] **Step 1: Añadir tests al final de `tests/test_tools_reminders.py`**

```python
def test_add_event_with_reminders_creates_rows():
    when = (datetime.now() + timedelta(hours=24)).replace(microsecond=0)
    res = tools.add_event(
        "Cita María",
        when.isoformat(),
        "personal",
        reminders=[30, 180],
    )
    assert "id" in res
    assert sorted(res.get("reminders_added", [])) == [30, 180]
    assert res.get("reminders_skipped", []) == []
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT offset_minutes FROM event_reminders "
            "WHERE event_id = ? ORDER BY offset_minutes",
            (res["id"],),
        ).fetchall()
    assert [r["offset_minutes"] for r in rows] == [30, 180]


def test_add_event_with_reminders_skips_invalid_offsets():
    """Offsets <= 0 se ignoran silenciosamente; los válidos sí entran."""
    when = (datetime.now() + timedelta(hours=24)).replace(microsecond=0)
    res = tools.add_event(
        "Cita",
        when.isoformat(),
        "personal",
        reminders=[30, 0, -10, 60],
    )
    assert sorted(res["reminders_added"]) == [30, 60]
    assert sorted(res["reminders_skipped"]) == [-10, 0]


def test_add_event_without_reminders_is_unchanged():
    """Sin reminders no aparecen las nuevas claves en la respuesta."""
    when = (datetime.now() + timedelta(hours=24)).replace(microsecond=0)
    res = tools.add_event("Cita", when.isoformat(), "personal")
    assert "reminders_added" not in res
    assert "reminders_skipped" not in res
```

- [ ] **Step 2: Verificar que fallan**

```
./.venv/bin/python -m pytest tests/test_tools_reminders.py -v -k "with_reminders or without_reminders"
```

- [ ] **Step 3: Modificar la signatura y cuerpo de `add_event`**

Cambiar la signatura:

```python
def add_event(
    title: str,
    datetime_iso: str,
    category: str,
    recurring_rule: Optional[str] = None,
    notes: Optional[str] = None,
    sync_to_calendar: bool = False,
    reminders: Optional[list[int]] = None,
) -> dict:
```

Tras la última `return result` (al final de la función), antes de retornar, insertar la lógica para procesar los reminders. Resulta más limpio extraer ese tramo final. La estructura actual termina con `return result` justo después del bloque `sync_to_calendar`. Cambiar el final para:

```python
    # Procesar reminders custom si vienen
    if reminders is not None:
        added: list[int] = []
        skipped: list[int] = []
        for offset in reminders:
            if not isinstance(offset, int) or offset <= 0:
                skipped.append(offset)
                continue
            sub = add_event_reminder(new_id, offset)
            if sub.get("event_id") and not sub.get("already_exists"):
                added.append(offset)
            elif sub.get("already_exists"):
                # ya estaba (caso muy raro al recién crear), no la contamos como skipped
                added.append(offset)
            else:
                skipped.append(offset)
        result["reminders_added"] = added
        result["reminders_skipped"] = skipped

    return result
```

(El último `return result` original sigue siendo el final de la función. Asegúrate de no romper el flujo de `sync_to_calendar`.)

- [ ] **Step 4: Actualizar la entrada en `TOOL_DEFINITIONS` para `add_event`**

Añadir el campo `reminders` en `properties`:

```python
                "reminders": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": (
                        "Lista opcional de antelaciones (en minutos) para "
                        "recordatorios custom. Si se pasa, los avisos por "
                        "defecto (1d y 1h antes) NO se mandarán para este "
                        "evento. Solo válido si recurring_rule es null."
                    ),
                },
```

- [ ] **Step 5: Verificar pass**

```
./.venv/bin/python -m pytest tests/test_tools_reminders.py -v
```

Esperado: 12 PASS.

- [ ] **Step 6: Suite**

```
./.venv/bin/python -m pytest
```

Si alguna pieza vieja comprueba el shape exacto del retorno de `add_event` y rompe por las claves nuevas, ajustar el test a `assert "id" in res` en vez de comparar dict completos. No relajar tests nuevos.

- [ ] **Step 7: Commit**

```
git add tools.py tests/test_tools_reminders.py
git commit -m "$(cat <<'EOF'
feat(tools): add_event acepta reminders=[...] opcional

Permite crear evento + recordatorios custom en una sola tool call.
Offsets inválidos (<=0) se ignoran silenciosamente y se devuelven
en reminders_skipped. Si no se pasan reminders, el retorno es
exactamente igual que antes.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: `check_reminders` — desactivar defaults cuando hay customs

**Files:**
- Modify: `scheduler.py` (función `check_reminders`)
- Modify: `tests/test_scheduler.py`

- [ ] **Step 1: Añadir test al final de `tests/test_scheduler.py`**

```python
@pytest.mark.asyncio
async def test_check_reminders_skips_defaults_when_event_has_customs(monkeypatch):
    """Un evento con cualquier event_reminders NO recibe los defaults
    aunque caigan dentro de la ventana."""
    monkeypatch.setattr(scheduler, "ALLOWED_USER_ID", 42)
    import tools
    # Evento dentro de la ventana de 1h (entre 50 y 70 min)
    when = (datetime.now() + timedelta(minutes=60)).replace(microsecond=0)
    ev = tools.add_event("Cita", when.isoformat(), "personal")
    # Añadir un recordatorio custom de 30 min antes (queda sent=0)
    tools.add_event_reminder(ev["id"], 30)

    send_mock = AsyncMock()
    await scheduler.check_reminders(_fake_context(send_mock))

    # NO debió haberse mandado el default 1h (ni 1d, fuera de ventana de
    # todos modos)
    assert send_mock.call_count == 0
    with db.connect() as conn:
        row = conn.execute(
            "SELECT reminder_1h_sent FROM events WHERE id = ?",
            (ev["id"],),
        ).fetchone()
    assert row["reminder_1h_sent"] == 0
```

(Asume que `_fake_context`, `AsyncMock`, y `datetime`/`timedelta` ya están importados en `tests/test_scheduler.py`. Si falta alguno, añade.)

- [ ] **Step 2: Verificar que falla**

```
./.venv/bin/python -m pytest tests/test_scheduler.py -v -k "skips_defaults_when_event_has_customs"
```

Esperado: FAIL — `send_mock` se llamó 1 vez (mandó el default 1h aunque el evento tiene un custom).

- [ ] **Step 3: Modificar la query de `check_reminders` para excluir eventos con customs**

En `scheduler.py`, localizar la query dentro de `check_reminders` (alrededor de la línea ~140):

```python
    with db.connect() as conn:
        rows = conn.execute(
            """
            SELECT id, title, datetime, reminder_1d_sent, reminder_1h_sent
            FROM events
            WHERE done = 0
              AND recurring_rule IS NULL
              AND datetime >= ?
              AND datetime <= ?
            """,
            (now.isoformat(timespec="seconds"), upper.isoformat(timespec="seconds")),
        ).fetchall()
```

Sustituir por:

```python
    with db.connect() as conn:
        rows = conn.execute(
            """
            SELECT id, title, datetime, reminder_1d_sent, reminder_1h_sent
            FROM events
            WHERE done = 0
              AND recurring_rule IS NULL
              AND datetime >= ?
              AND datetime <= ?
              AND NOT EXISTS (
                  SELECT 1 FROM event_reminders
                  WHERE event_reminders.event_id = events.id
              )
            """,
            (now.isoformat(timespec="seconds"), upper.isoformat(timespec="seconds")),
        ).fetchall()
```

- [ ] **Step 4: Verificar pass del test nuevo**

```
./.venv/bin/python -m pytest tests/test_scheduler.py -v -k "skips_defaults_when_event_has_customs"
```

- [ ] **Step 5: Suite**

```
./.venv/bin/python -m pytest
```

Confirmar que NO se rompió el comportamiento de defaults sin customs (los tests previos de `check_reminders` deben seguir verdes).

- [ ] **Step 6: Commit**

```
git add scheduler.py tests/test_scheduler.py
git commit -m "$(cat <<'EOF'
feat(scheduler): defaults OFF cuando el evento tiene recordatorios custom

check_reminders filtra los eventos con cualquier fila en event_reminders
vía NOT EXISTS. Pablo toma el control total de los avisos cuando añade
un custom — los defaults 1d/1h no se mandan para ese evento.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: `check_reminders` — bloque para recordatorios custom + helper de formato

**Files:**
- Modify: `scheduler.py` (función `check_reminders` + helper nuevo `_format_offset`)
- Modify: `tests/test_scheduler.py`

- [ ] **Step 1: Añadir tests al final de `tests/test_scheduler.py`**

```python
@pytest.mark.asyncio
async def test_check_reminders_sends_custom_within_window(monkeypatch):
    """Un custom cuyo fire_time cae dentro de la ventana ±5 min se manda
    y se marca sent=1."""
    monkeypatch.setattr(scheduler, "ALLOWED_USER_ID", 42)
    import tools
    # Evento dentro de 35 min; custom 30 min antes → fire_time = en 5 min,
    # dentro de la ventana ±5 min.
    when = (datetime.now() + timedelta(minutes=35)).replace(microsecond=0)
    ev = tools.add_event("Dentista", when.isoformat(), "personal")
    tools.add_event_reminder(ev["id"], 30)

    send_mock = AsyncMock()
    await scheduler.check_reminders(_fake_context(send_mock))

    send_mock.assert_called_once()
    text = send_mock.call_args.kwargs["text"]
    assert "Dentista" in text
    assert "30 min" in text
    with db.connect() as conn:
        row = conn.execute(
            "SELECT sent FROM event_reminders WHERE event_id = ?",
            (ev["id"],),
        ).fetchone()
    assert row["sent"] == 1


@pytest.mark.asyncio
async def test_check_reminders_does_not_resend_sent_custom(monkeypatch):
    monkeypatch.setattr(scheduler, "ALLOWED_USER_ID", 42)
    import tools
    when = (datetime.now() + timedelta(minutes=35)).replace(microsecond=0)
    ev = tools.add_event("Dentista", when.isoformat(), "personal")
    tools.add_event_reminder(ev["id"], 30)
    # Forzar sent=1
    with db.connect() as conn:
        conn.execute(
            "UPDATE event_reminders SET sent = 1 WHERE event_id = ?",
            (ev["id"],),
        )

    send_mock = AsyncMock()
    await scheduler.check_reminders(_fake_context(send_mock))

    assert send_mock.call_count == 0


@pytest.mark.asyncio
async def test_check_reminders_ignores_custom_outside_window(monkeypatch):
    """Custom cuyo fire_time está fuera de la ventana ±5 min no se manda."""
    monkeypatch.setattr(scheduler, "ALLOWED_USER_ID", 42)
    import tools
    # Evento dentro de 24h; custom 30 min antes → fire_time aún lejos
    when = (datetime.now() + timedelta(hours=24)).replace(microsecond=0)
    ev = tools.add_event("Cita", when.isoformat(), "personal")
    tools.add_event_reminder(ev["id"], 30)

    send_mock = AsyncMock()
    await scheduler.check_reminders(_fake_context(send_mock))

    assert send_mock.call_count == 0


@pytest.mark.asyncio
async def test_check_reminders_ignores_custom_for_done_event(monkeypatch):
    monkeypatch.setattr(scheduler, "ALLOWED_USER_ID", 42)
    import tools
    when = (datetime.now() + timedelta(minutes=35)).replace(microsecond=0)
    ev = tools.add_event("Cita", when.isoformat(), "personal")
    tools.add_event_reminder(ev["id"], 30)
    with db.connect() as conn:
        conn.execute("UPDATE events SET done = 1 WHERE id = ?", (ev["id"],))

    send_mock = AsyncMock()
    await scheduler.check_reminders(_fake_context(send_mock))

    assert send_mock.call_count == 0
```

- [ ] **Step 2: Verificar que fallan**

```
./.venv/bin/python -m pytest tests/test_scheduler.py -v -k "custom_within_window or does_not_resend_sent_custom or ignores_custom_outside_window or ignores_custom_for_done_event"
```

- [ ] **Step 3: Añadir helper `_format_offset` en `scheduler.py`**

Antes de `check_reminders`:

```python
def _format_offset(minutes: int) -> str:
    """Formatea un offset en minutos a una cadena legible en español.

    < 60 → "30 min", 60 → "1 h", 60-1439 → "X h", 1440 → "1 día",
    múltiplos de 1440 → "N días", 10080 → "1 semana", resto → "N días".
    """
    if minutes < 60:
        return f"{minutes} min"
    if minutes == 60:
        return "1 h"
    if minutes < 1440:
        hours = minutes // 60
        return f"{hours} h"
    if minutes == 1440:
        return "1 día"
    if minutes == 10080:
        return "1 semana"
    days = minutes // 1440
    return f"{days} días"
```

- [ ] **Step 4: Añadir el bloque de customs en `check_reminders`**

Al final de la función `check_reminders`, después del bucle existente de defaults (tras el `if (_HOUR_REMINDER_MIN_MIN <= minutes <= _HOUR_REMINDER_MAX_MIN ...)`), añadir:

```python
    # Recordatorios custom dentro de la ventana ±5 min
    with db.connect() as conn:
        custom_rows = conn.execute(
            """
            SELECT er.id AS reminder_id, er.event_id, er.offset_minutes,
                   e.title, e.datetime
            FROM event_reminders er
            JOIN events e ON e.id = er.event_id
            WHERE er.sent = 0
              AND e.done = 0
              AND e.recurring_rule IS NULL
            """
        ).fetchall()

    for r in custom_rows:
        try:
            event_dt = datetime.fromisoformat(r["datetime"])
        except ValueError:
            log.warning(
                "Evento %s con datetime inválido: %r",
                r["event_id"], r["datetime"],
            )
            continue
        fire_time = event_dt - timedelta(minutes=r["offset_minutes"])
        diff_sec = abs((fire_time - now).total_seconds())
        if diff_sec <= 5 * 60:
            pretty = _format_offset(r["offset_minutes"])
            text = f"⏰ En {pretty} tienes: <b>{r['title']}</b>"
            try:
                await context.bot.send_message(
                    chat_id=ALLOWED_USER_ID,
                    text=text,
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                log.exception(
                    "Error enviando recordatorio custom %s",
                    r["reminder_id"],
                )
                continue
            with db.connect() as conn:
                conn.execute(
                    "UPDATE event_reminders SET sent = 1 WHERE id = ?",
                    (r["reminder_id"],),
                )
```

(Confirma que `ParseMode` ya está importado en `scheduler.py`. Si falta, añade.)

- [ ] **Step 5: Verificar pass**

```
./.venv/bin/python -m pytest tests/test_scheduler.py -v
```

- [ ] **Step 6: Suite**

```
./.venv/bin/python -m pytest
```

- [ ] **Step 7: Commit**

```
git add scheduler.py tests/test_scheduler.py
git commit -m "$(cat <<'EOF'
feat(scheduler): envío de recordatorios custom en check_reminders

Añade un bloque que recorre event_reminders pendientes, verifica
que su fire_time cae en la ventana ±5 min, manda el mensaje
("⏰ En {pretty} tienes: <b>{title}</b>") y marca sent=1. Helper
_format_offset formatea minutos a texto legible (min/h/día/semana).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Brain — `_pending_immediate_reminders` para entregar avisos `fires_immediately`

**Files:**
- Modify: `brain.py` (nuevo dict + funciones + captura en handle_message)
- Modify: `tests/test_brain.py`

- [ ] **Step 1: Añadir tests al final de `tests/test_brain.py`**

```python
def test_record_and_pop_immediate_reminders():
    import brain
    brain.record_immediate_reminder(42, event_id=7, offset_minutes=30, title="Cita")
    brain.record_immediate_reminder(42, event_id=9, offset_minutes=60, title="Médico")
    res = brain.pop_immediate_reminders(42)
    assert len(res) == 2
    titles = {r["title"] for r in res}
    assert titles == {"Cita", "Médico"}
    # Segunda llamada → lista vacía
    assert brain.pop_immediate_reminders(42) == []


def test_pop_immediate_reminders_unknown_user_returns_empty():
    import brain
    assert brain.pop_immediate_reminders(99999) == []
```

- [ ] **Step 2: Verificar que fallan**

```
./.venv/bin/python -m pytest tests/test_brain.py -v -k "immediate_reminder"
```

- [ ] **Step 3: Añadir state y funciones en `brain.py`**

Cerca del existente `_pending_level_up`:

```python
# Recordatorios custom que deben enviarse inmediatamente (offset ya pasado
# al añadirlos). Se rellenan cuando una tool devuelve fires_immediately=True
# y se consumen en bot.py tras enviar la respuesta normal de Claude.
_pending_immediate_reminders: dict[int, list[dict]] = {}


def record_immediate_reminder(
    user_id: int, event_id: int, offset_minutes: int, title: str
) -> None:
    _pending_immediate_reminders.setdefault(user_id, []).append({
        "event_id": event_id,
        "offset_minutes": offset_minutes,
        "title": title,
    })


def pop_immediate_reminders(user_id: int) -> list[dict]:
    return _pending_immediate_reminders.pop(user_id, [])
```

- [ ] **Step 4: Integrar captura en el bucle de tool_use**

Añadir `import db` al inicio de `brain.py` (junto a `import tools`).

Dentro de `handle_message`, en la zona donde ya se procesa `result` (después de `result = tools.dispatch(...)`, junto al bloque que captura `level_before`/`level_after`), añadir:

```python
                    if isinstance(result, dict):
                        # Caso 1: la tool fue add_event_reminder y disparó inmediato
                        if (
                            result.get("fires_immediately")
                            and result.get("event_id")
                            and result.get("offset_minutes")
                        ):
                            # Necesitamos el title; buscarlo en BD
                            with db.connect() as _c:
                                _r = _c.execute(
                                    "SELECT title FROM events WHERE id = ?",
                                    (result["event_id"],),
                                ).fetchone()
                            if _r:
                                record_immediate_reminder(
                                    user_id,
                                    event_id=result["event_id"],
                                    offset_minutes=result["offset_minutes"],
                                    title=_r["title"],
                                )
                        # Caso 2: la tool fue add_event con reminders y alguno
                        # disparó inmediato. add_event no marca fires_immediately
                        # en su retorno principal porque procesa una lista; para
                        # detectarlo, leer event_reminders con sent=1 recién
                        # insertadas para este event_id.
                        if (
                            block.name == "add_event"
                            and result.get("reminders_added")
                        ):
                            with db.connect() as _c:
                                _ev = _c.execute(
                                    "SELECT title FROM events WHERE id = ?",
                                    (result["id"],),
                                ).fetchone()
                                _rows = _c.execute(
                                    "SELECT offset_minutes FROM event_reminders "
                                    "WHERE event_id = ? AND sent = 1",
                                    (result["id"],),
                                ).fetchall()
                            if _ev:
                                for _row in _rows:
                                    record_immediate_reminder(
                                        user_id,
                                        event_id=result["id"],
                                        offset_minutes=_row["offset_minutes"],
                                        title=_ev["title"],
                                    )
```

- [ ] **Step 5: Verificar pass**

```
./.venv/bin/python -m pytest tests/test_brain.py -v
```

- [ ] **Step 6: Suite**

```
./.venv/bin/python -m pytest
```

- [ ] **Step 7: Commit**

```
git add brain.py tests/test_brain.py
git commit -m "$(cat <<'EOF'
feat(brain): _pending_immediate_reminders + captura desde tools

Añade dict/record/pop paralelo a _pending_level_up para recordatorios
que tienen que enviarse inmediatamente (offset ya pasado al añadirlos).
En el bucle de tool_use captura los resultados de add_event_reminder
(fires_immediately) y de add_event(reminders=[...]) que insertaron
filas sent=1.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Bot — enviar inmediatos tras la respuesta de Claude

**Files:**
- Modify: `bot.py` (`_on_message` y `_on_voice` + helper `_render_reminder_message`)
- Modify: `tests/test_bot.py`

- [ ] **Step 1: Añadir test al final de `tests/test_bot.py`**

```python
@pytest.mark.asyncio
async def test_on_message_sends_immediate_reminders(monkeypatch):
    """Si brain registró inmediatos, _on_message los manda aparte tras la
    respuesta normal."""
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    import brain
    brain.record_immediate_reminder(
        42, event_id=1, offset_minutes=30, title="Dentista"
    )

    update = MagicMock()
    update.message.text = "hola"
    update.message.reply_text = AsyncMock()
    update.effective_user.id = 42

    ctx = MagicMock()
    ctx.bot.send_message = AsyncMock()

    monkeypatch.setattr(
        bot, "process_incoming", lambda text, from_user_id: "ok"
    )

    await bot._on_message(update, ctx)

    # Al menos una llamada a send_message con texto que menciona Dentista
    sends = [c.kwargs["text"] for c in ctx.bot.send_message.call_args_list]
    matches = [t for t in sends if "Dentista" in t and "30 min" in t]
    assert len(matches) == 1
```

- [ ] **Step 2: Verificar que falla**

```
./.venv/bin/python -m pytest tests/test_bot.py -v -k "sends_immediate_reminders"
```

- [ ] **Step 3: Añadir helper `_render_reminder_message` en `bot.py`**

Cerca de `_render_level_up_message`:

```python
def _render_reminder_message(offset_minutes: int, title: str) -> str:
    """Texto HTML del recordatorio inmediato (mismo formato que el scheduler)."""
    from scheduler import _format_offset
    pretty = _format_offset(offset_minutes)
    return f"⏰ En {pretty} tienes: <b>{title}</b>"
```

- [ ] **Step 4: Llamar a pop_immediate_reminders en `_on_message`**

Después del bloque existente de `pop_level_up` en `_on_message`, añadir:

```python
    # Recordatorios custom inmediatos disparados por la respuesta de Claude
    for rem in brain.pop_immediate_reminders(user_id):
        try:
            await context.bot.send_message(
                chat_id=ALLOWED_USER_ID,
                text=_render_reminder_message(
                    rem["offset_minutes"], rem["title"]
                ),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            log.exception(
                "Error enviando recordatorio inmediato del evento %s",
                rem["event_id"],
            )
```

- [ ] **Step 5: Mismo bloque en `_on_voice`**

Repetir el bloque en `_on_voice` después de su `pop_level_up`. Usar `from_user_id` (que es la variable en `_on_voice`) en vez de `user_id`.

- [ ] **Step 6: Verificar pass**

```
./.venv/bin/python -m pytest tests/test_bot.py -v
```

- [ ] **Step 7: Suite**

```
./.venv/bin/python -m pytest
```

- [ ] **Step 8: Commit**

```
git add bot.py tests/test_bot.py
git commit -m "$(cat <<'EOF'
feat(bot): envío de recordatorios inmediatos tras respuesta de Claude

_on_message y _on_voice consumen brain.pop_immediate_reminders y
mandan un mensaje aparte por cada uno con el formato del scheduler
("⏰ En {pretty} tienes: <b>{title}</b>"). Se ejecuta tras la
respuesta normal de Claude y tras el mensaje de subida de nivel.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: System prompt — regla para Claude + verificación end-to-end

**Files:**
- Modify: `brain.py` (`_system_prompt` o cadena `system`)
- Modify: `tests/test_tools_reminders.py`

- [ ] **Step 1: Añadir regla al system prompt en `brain.py`**

Localizar la sección "Distinción de tipos" (la que tocamos en F3 para objetivos). Justo después de la línea sobre "Objetivos de la semana" y antes de la línea sobre "qué tengo hoy", añadir:

```
- **Recordatorios custom**: cuando Pablo diga "avísame X antes" sobre un evento, llama a `add_event_reminder(event_id, minutes_before)`. Si lo dice en el mismo mensaje que crea el evento ("tengo cita el viernes a las 5, avísame 30 min antes"), llama a `add_event` con `reminders=[X_en_minutos]` en una sola tool call. Convierte el lenguaje natural a minutos: "30 min"=30, "1 hora"=60, "3 horas"=180, "1 día"=1440, "2 días"=2880, "1 semana"=10080. Importante: NO uses recordatorios custom en eventos recurrentes/rutinas — la tool los rechazará. Si añades cualquier recordatorio custom, los avisos por defecto (1d y 1h antes) NO se mandarán para ese evento. Confirma con una frase corta: "Hecho, te aviso 30 min antes."
```

- [ ] **Step 2: Smoke test e2e en `tests/test_tools_reminders.py`**

Añadir al final:

```python
def test_e2e_add_event_with_reminders_and_query():
    """Smoke: añadir evento con reminders + leer y verificar shape."""
    when = (datetime.now() + timedelta(hours=24)).replace(microsecond=0)
    res = tools.add_event(
        "Reunión equipo",
        when.isoformat(),
        "work",
        reminders=[30, 1440],  # 30 min + 1 día
    )
    assert sorted(res["reminders_added"]) == [30, 1440]
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT offset_minutes, sent FROM event_reminders "
            "WHERE event_id = ? ORDER BY offset_minutes",
            (res["id"],),
        ).fetchall()
    assert [r["offset_minutes"] for r in rows] == [30, 1440]
    # Ambos pendientes (1 día y 30 min en el futuro)
    assert all(r["sent"] == 0 for r in rows)
```

- [ ] **Step 3: Verificar pass**

```
./.venv/bin/python -m pytest tests/test_tools_reminders.py -v -k "e2e"
```

- [ ] **Step 4: Suite completa**

```
./.venv/bin/python -m pytest -v 2>&1 | tail -5
```

Esperado: ALL PASSED.

- [ ] **Step 5: Verificación de arranque local**

```
./.venv/bin/python -c "import bot; print('OK')"
```

(Si tira por falta de env vars como ya pasó en niveles, no es regresión — está bien.)

- [ ] **Step 6: Commit final**

```
git add brain.py tests/test_tools_reminders.py
git commit -m "$(cat <<'EOF'
feat(brain): regla de recordatorios custom en system prompt + smoke e2e

Enseña a Claude a parsear "avísame X antes" a minutos y elegir entre
add_event_reminder (evento existente) o add_event con reminders (al
crear). Smoke test añadido para verificar el shape del retorno
cuando se crean evento + reminders en una llamada.

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

- [ ] Arranque sin errores nuevos:
```
./start.sh
```

- [ ] Probar manualmente en Telegram:
   - "Tengo cita el viernes a las 17:00, avísame 30 min antes" → bot confirma, no manda nada aún.
   - El viernes, ~30 min antes de las 17:00, llega el aviso "⏰ En 30 min tienes: ...".
   - Para ese evento NO debe llegar el 1h default.
   - "Avísame 1 semana antes de [evento futuro existente]" → bot confirma.
   - Pedir un aviso para un evento dentro de 5 min con offset 30 → llega INMEDIATAMENTE tras la respuesta de Claude.

- [ ] Deploy a Fly:
```
flyctl deploy --app mi-secretaria-pablo
```

- [ ] Verificar en logs el arranque limpio:
```
flyctl logs --app mi-secretaria-pablo --no-tail
```

Esperado: `Application started` + `Menú de comandos actualizado en Telegram (9 comandos)` sin tracebacks.

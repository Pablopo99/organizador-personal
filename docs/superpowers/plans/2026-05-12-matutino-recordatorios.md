# Mensaje matutino y Recordatorios — Plan de Implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** El bot envía proactivamente un saludo matutino a las 09:00 cada día y avisos de eventos próximos (1 día antes y 1 hora antes), usando el `job_queue` integrado de python-telegram-bot.

**Architecture:** Nuevo módulo `scheduler.py` con dos callbacks async. Pequeño módulo `formatting.py` para compartir el helper de Markdown→HTML entre `bot.py` y `scheduler.py`. Migración en `events` añade flags `reminder_1d_sent` y `reminder_1h_sent`. `update_event` resetea esos flags si cambia `datetime`.

**Tech Stack:** Python 3.12, `python-telegram-bot` 21.6 (job_queue), SQLite, `pytest-asyncio` para callbacks async.

**Spec de referencia:** `docs/superpowers/specs/2026-05-12-matutino-recordatorios-design.md`

---

## Convenciones

- TDD: test que falla → implementación → test pasa → commit.
- Cada Task termina en commit.
- Comandos desde `/Users/pablocansinos/Desktop/Proyecto Prueba`.
- ALLOWED_USER_ID en tests es `42` (fijado en `tests/conftest.py`).

---

## Task 1: Helper de formato compartido (`formatting.py`)

Extraemos `_markdown_to_html` de `bot.py` a un módulo aparte para poder usarlo también desde `scheduler.py` sin importación circular.

**Files:**
- Create: `formatting.py`
- Create: `tests/test_formatting.py`
- Modify: `bot.py`
- Modify: `tests/test_bot.py`

- [ ] **Step 1: Crear `formatting.py`**

Contenido completo:
```python
"""Helpers de formato compartidos entre bot.py y scheduler.py."""
import re

_BOLD_MD_RE = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)


def markdown_to_html(text: str) -> str:
    """Convierte Markdown bold (**texto**) a HTML (<b>texto</b>).

    Defensa por si Claude se le escapa el formato Markdown a pesar del system prompt.
    """
    return _BOLD_MD_RE.sub(r"<b>\1</b>", text)
```

- [ ] **Step 2: Crear `tests/test_formatting.py`**

Contenido completo:
```python
import formatting


def test_markdown_to_html_converts_bold():
    assert formatting.markdown_to_html("hola **mundo**") == "hola <b>mundo</b>"


def test_markdown_to_html_handles_multiple():
    out = formatting.markdown_to_html("**A** y **B**")
    assert out == "<b>A</b> y <b>B</b>"


def test_markdown_to_html_multiline():
    out = formatting.markdown_to_html("**línea1\nlínea2**")
    assert out == "<b>línea1\nlínea2</b>"


def test_markdown_to_html_leaves_plain_alone():
    assert formatting.markdown_to_html("sin formato") == "sin formato"
```

- [ ] **Step 3: Actualizar `bot.py` para usar el helper compartido**

Reemplazar las primeras líneas de `bot.py` (donde define `_BOLD_MD_RE` y `_markdown_to_html`):
```python
"""Listener de Telegram. Filtra por usuario autorizado y delega en el cerebro."""
import asyncio
import logging
from typing import Optional

from telegram import BotCommand, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import brain
import db
import transcriber
from config import ALLOWED_USER_ID, TELEGRAM_TOKEN
from formatting import markdown_to_html
```

Y eliminar el bloque que tenía:
```python
_BOLD_MD_RE = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)

def _markdown_to_html(text: str) -> str:
    ...
```

Y sustituir cada uso de `_markdown_to_html(` en `bot.py` por `markdown_to_html(`. Hay tres lugares: en `process_slash_command`, en `process_incoming`, en `process_voice_transcription`.

También quitar `import re` si no se usa en otro sitio del archivo.

- [ ] **Step 4: Actualizar tests de `bot.py` que referenciaban el helper local**

En `tests/test_bot.py`, reemplazar `bot._markdown_to_html` por `bot.markdown_to_html` en los tests existentes:
- `test_markdown_to_html_helper_handles_multiline`
- `test_markdown_to_html_helper_leaves_plain_text_alone`

Localizar las líneas:
```python
out = bot._markdown_to_html(text)
```
Y reemplazarlas por:
```python
out = bot.markdown_to_html(text)
```

(Las dos asserciones siguen igual; solo cambia el nombre.)

- [ ] **Step 5: Ejecutar suite completa**

```bash
source .venv/bin/activate
python -m pytest -v
```

Expected: TODO PASS, total 85 tests (81 previos + 4 nuevos en test_formatting).

- [ ] **Step 6: Commit**

```bash
git add formatting.py tests/test_formatting.py bot.py tests/test_bot.py
git commit -m "refactor: extract markdown_to_html into formatting module"
```

---

## Task 2: Migración de flags de recordatorio + reset en update_event

**Files:**
- Modify: `db.py`
- Modify: `tools.py`
- Modify: `tests/test_db.py`
- Modify: `tests/test_tools_events.py`

- [ ] **Step 1: Añadir flags al schema base en `db.py`**

Localizar la sección `_SCHEMA` y reemplazar la definición de la tabla `events` por:
```sql
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
    reminder_1h_sent  INTEGER NOT NULL DEFAULT 0
);
```

- [ ] **Step 2: Añadir migración idempotente en `_migrate`**

Reemplazar la función `_migrate` por:
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

    tasks_cols = [row[1] for row in conn.execute("PRAGMA table_info(tasks)").fetchall()]
    if "done_at" not in tasks_cols:
        conn.execute("ALTER TABLE tasks ADD COLUMN done_at TEXT")
```

- [ ] **Step 3: Añadir tests de migración en `tests/test_db.py`**

Añadir al final del archivo:
```python


def test_migration_adds_reminder_flags_to_events(monkeypatch):
    """BD vieja sin flags de recordatorio: init_schema los añade."""
    import os
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    monkeypatch.setattr(db, "DB_PATH", path)
    with sqlite3.connect(path) as conn:
        conn.execute("""
            CREATE TABLE events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                datetime TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'other',
                recurring_rule TEXT,
                notes TEXT,
                created_at TEXT NOT NULL
            )
        """)
        conn.commit()

    db.init_schema()

    with sqlite3.connect(path) as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(events)").fetchall()]
    assert "reminder_1d_sent" in cols
    assert "reminder_1h_sent" in cols
    os.unlink(path)
```

- [ ] **Step 4: Modificar `update_event` en `tools.py` para resetear flags**

Localizar la función `update_event` y reemplazarla por:
```python
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

    # Si cambia el datetime, reseteamos los flags de recordatorio
    if "datetime" in fields:
        sets.append("reminder_1d_sent = 0")
        sets.append("reminder_1h_sent = 0")

    params.append(event_id)
    with db.connect() as conn:
        cur = conn.execute(
            f"UPDATE events SET {', '.join(sets)} WHERE id = ?", params
        )
        return {"id": event_id, "updated": cur.rowcount}
```

- [ ] **Step 5: Añadir tests de reset en `tests/test_tools_events.py`**

Añadir al final del archivo:
```python


def test_update_event_with_datetime_resets_reminder_flags():
    import sqlite3
    created = tools.add_event("X", "2026-06-01T10:00:00", "work")
    # Marcamos manualmente los flags como enviados
    with db.connect() as conn:
        conn.execute(
            "UPDATE events SET reminder_1d_sent = 1, reminder_1h_sent = 1 WHERE id = ?",
            (created["id"],),
        )

    tools.update_event(created["id"], {"datetime": "2026-06-02T10:00:00"})

    with db.connect() as conn:
        row = conn.execute(
            "SELECT reminder_1d_sent, reminder_1h_sent FROM events WHERE id = ?",
            (created["id"],),
        ).fetchone()
    assert row[0] == 0
    assert row[1] == 0


def test_update_event_with_title_keeps_reminder_flags():
    """Si solo cambia el título, los flags se preservan."""
    created = tools.add_event("X", "2026-06-01T10:00:00", "work")
    with db.connect() as conn:
        conn.execute(
            "UPDATE events SET reminder_1d_sent = 1 WHERE id = ?",
            (created["id"],),
        )

    tools.update_event(created["id"], {"title": "Y"})

    with db.connect() as conn:
        row = conn.execute(
            "SELECT reminder_1d_sent FROM events WHERE id = ?",
            (created["id"],),
        ).fetchone()
    assert row[0] == 1
```

- [ ] **Step 6: Ejecutar suite completa**

```bash
python -m pytest -v
```

Expected: TODO PASS, +3 nuevos.

- [ ] **Step 7: Commit**

```bash
git add db.py tools.py tests/test_db.py tests/test_tools_events.py
git commit -m "feat(events): reminder_1d_sent and reminder_1h_sent flags with reset on datetime change"
```

---

## Task 3: Mensaje matutino (`scheduler.morning_summary`)

**Files:**
- Create: `scheduler.py`
- Create: `tests/test_scheduler.py`

- [ ] **Step 1: Escribir tests del matutino**

Crear `tests/test_scheduler.py`:
```python
import os
import tempfile
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import db
import scheduler


@pytest.fixture(autouse=True)
def temp_db(monkeypatch):
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init_schema()
    yield path
    os.unlink(path)


def _fake_context(send_message_mock=None):
    """Crea un fake context de python-telegram-bot."""
    ctx = SimpleNamespace()
    ctx.bot = SimpleNamespace()
    ctx.bot.send_message = send_message_mock or AsyncMock()
    return ctx


@pytest.mark.asyncio
async def test_morning_summary_sends_to_allowed_user(monkeypatch):
    monkeypatch.setattr(scheduler, "ALLOWED_USER_ID", 42)
    monkeypatch.setattr(
        scheduler.brain, "handle_message",
        lambda text, user_id=0: "🌅 Buenos días Pablo. Hoy no tienes nada."
    )

    send_mock = AsyncMock()
    await scheduler.morning_summary(_fake_context(send_mock))

    send_mock.assert_called_once()
    call = send_mock.call_args
    assert call.kwargs["chat_id"] == 42
    assert "Buenos días" in call.kwargs["text"]
    assert call.kwargs["parse_mode"] == "HTML"


@pytest.mark.asyncio
async def test_morning_summary_converts_markdown_to_html(monkeypatch):
    monkeypatch.setattr(scheduler, "ALLOWED_USER_ID", 42)
    monkeypatch.setattr(
        scheduler.brain, "handle_message",
        lambda text, user_id=0: "Hola **Pablo**"
    )

    send_mock = AsyncMock()
    await scheduler.morning_summary(_fake_context(send_mock))

    text = send_mock.call_args.kwargs["text"]
    assert "<b>Pablo</b>" in text
    assert "**" not in text


@pytest.mark.asyncio
async def test_morning_summary_handles_brain_exception(monkeypatch):
    monkeypatch.setattr(scheduler, "ALLOWED_USER_ID", 42)

    def explode(text, user_id=0):
        raise RuntimeError("boom")

    monkeypatch.setattr(scheduler.brain, "handle_message", explode)

    send_mock = AsyncMock()
    # No debe lanzar excepción, solo loguear
    await scheduler.morning_summary(_fake_context(send_mock))
    # No se envía mensaje cuando el cerebro falla
    send_mock.assert_not_called()
```

- [ ] **Step 2: Ejecutar, ver que falla**

```bash
python -m pytest tests/test_scheduler.py -v
```

Expected: FAIL — `No module named 'scheduler'`.

- [ ] **Step 3: Crear `scheduler.py` con `morning_summary`**

Contenido inicial (Task 4 añadirá `check_reminders`):
```python
"""Jobs programados: mensaje matutino y recordatorios proactivos."""
import logging
from datetime import datetime, timedelta

from telegram.constants import ParseMode
from telegram.ext import ContextTypes

import brain
import db
from config import ALLOWED_USER_ID
from formatting import markdown_to_html

log = logging.getLogger("scheduler")

_WEEKDAYS_ES = [
    "lunes", "martes", "miércoles", "jueves",
    "viernes", "sábado", "domingo",
]


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
        "   📅 HOY = eventos del paso 1 con done=0\n"
        "   📝 PENDIENTES = tareas del paso 2 con done=0\n"
        "   ✅ COMPLETADO HOY = eventos del paso 1 con done=1 + tareas del paso 2 con done_at de hoy\n"
        "4. Si no hay nada en ninguna sección, di solo que puede disfrutar del día libre.\n"
        "5. Cierra con una frase motivadora breve si encaja."
    )


async def morning_summary(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Envía el saludo matutino con el resumen del día."""
    try:
        reply = brain.handle_message(_morning_prompt(), user_id=ALLOWED_USER_ID)
    except Exception:
        log.exception("Error generando el saludo matutino")
        return

    text = markdown_to_html(reply)
    try:
        await context.bot.send_message(
            chat_id=ALLOWED_USER_ID,
            text=text,
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        log.exception("Error enviando el saludo matutino")
```

- [ ] **Step 4: Ejecutar tests**

```bash
python -m pytest tests/test_scheduler.py -v
```

Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add scheduler.py tests/test_scheduler.py
git commit -m "feat(scheduler): morning_summary job sends daily greeting via Claude"
```

---

## Task 4: Recordatorios (`scheduler.check_reminders`)

**Files:**
- Modify: `scheduler.py`
- Modify: `tests/test_scheduler.py`

- [ ] **Step 1: Añadir tests para `check_reminders`**

Añadir al final de `tests/test_scheduler.py`:
```python


def _add_event_at_offset(hours: float, title: str = "Evento", category: str = "work", done: int = 0):
    """Helper: añade un evento que ocurre en `hours` horas (puede ser negativo) desde ahora."""
    import sqlite3
    dt = datetime.now() + timedelta(hours=hours)
    with db.connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO events (title, datetime, category, created_at, done,
                                reminder_1d_sent, reminder_1h_sent)
            VALUES (?, ?, ?, ?, ?, 0, 0)
            """,
            (title, dt.isoformat(timespec="seconds"), category,
             datetime.now().isoformat(timespec="seconds"), done),
        )
        return cur.lastrowid


@pytest.mark.asyncio
async def test_check_reminders_sends_1h_reminder(monkeypatch):
    monkeypatch.setattr(scheduler, "ALLOWED_USER_ID", 42)
    event_id = _add_event_at_offset(hours=1.0, title="Cita médico")

    send_mock = AsyncMock()
    await scheduler.check_reminders(_fake_context(send_mock))

    send_mock.assert_called_once()
    assert "1h" in send_mock.call_args.kwargs["text"].lower() or "una hora" in send_mock.call_args.kwargs["text"].lower()
    assert "Cita médico" in send_mock.call_args.kwargs["text"]

    # Flag marcado
    with db.connect() as conn:
        row = conn.execute(
            "SELECT reminder_1h_sent FROM events WHERE id = ?", (event_id,)
        ).fetchone()
    assert row[0] == 1


@pytest.mark.asyncio
async def test_check_reminders_sends_1d_reminder(monkeypatch):
    monkeypatch.setattr(scheduler, "ALLOWED_USER_ID", 42)
    event_id = _add_event_at_offset(hours=24.0, title="Dentista")

    send_mock = AsyncMock()
    await scheduler.check_reminders(_fake_context(send_mock))

    send_mock.assert_called_once()
    assert "mañana" in send_mock.call_args.kwargs["text"].lower()
    assert "Dentista" in send_mock.call_args.kwargs["text"]

    with db.connect() as conn:
        row = conn.execute(
            "SELECT reminder_1d_sent FROM events WHERE id = ?", (event_id,)
        ).fetchone()
    assert row[0] == 1


@pytest.mark.asyncio
async def test_check_reminders_skips_already_sent(monkeypatch):
    monkeypatch.setattr(scheduler, "ALLOWED_USER_ID", 42)
    event_id = _add_event_at_offset(hours=1.0, title="Ya avisado")
    with db.connect() as conn:
        conn.execute(
            "UPDATE events SET reminder_1h_sent = 1 WHERE id = ?", (event_id,)
        )

    send_mock = AsyncMock()
    await scheduler.check_reminders(_fake_context(send_mock))

    send_mock.assert_not_called()


@pytest.mark.asyncio
async def test_check_reminders_skips_done_events(monkeypatch):
    monkeypatch.setattr(scheduler, "ALLOWED_USER_ID", 42)
    _add_event_at_offset(hours=1.0, title="Hecho", done=1)

    send_mock = AsyncMock()
    await scheduler.check_reminders(_fake_context(send_mock))

    send_mock.assert_not_called()


@pytest.mark.asyncio
async def test_check_reminders_skips_recurring_events(monkeypatch):
    monkeypatch.setattr(scheduler, "ALLOWED_USER_ID", 42)
    import sqlite3
    dt = datetime.now() + timedelta(hours=1.0)
    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO events (title, datetime, category, recurring_rule, created_at, done,
                                reminder_1d_sent, reminder_1h_sent)
            VALUES (?, ?, 'personal', 'WEEKLY:MON', ?, 0, 0, 0)
            """,
            ("Gimnasio", dt.isoformat(timespec="seconds"),
             datetime.now().isoformat(timespec="seconds")),
        )

    send_mock = AsyncMock()
    await scheduler.check_reminders(_fake_context(send_mock))

    send_mock.assert_not_called()


@pytest.mark.asyncio
async def test_check_reminders_no_events_no_messages(monkeypatch):
    monkeypatch.setattr(scheduler, "ALLOWED_USER_ID", 42)

    send_mock = AsyncMock()
    await scheduler.check_reminders(_fake_context(send_mock))

    send_mock.assert_not_called()


@pytest.mark.asyncio
async def test_check_reminders_event_outside_window(monkeypatch):
    """Eventos muy lejos en el tiempo no disparan recordatorios."""
    monkeypatch.setattr(scheduler, "ALLOWED_USER_ID", 42)
    _add_event_at_offset(hours=48.0, title="Lejos")

    send_mock = AsyncMock()
    await scheduler.check_reminders(_fake_context(send_mock))

    send_mock.assert_not_called()
```

- [ ] **Step 2: Ejecutar tests, ver que fallan**

```bash
python -m pytest tests/test_scheduler.py -v
```

Expected: 7 tests nuevos FAIL — `check_reminders` no existe.

- [ ] **Step 3: Añadir `check_reminders` a `scheduler.py`**

Añadir al final del archivo (los imports `timedelta` y `db` ya están al principio del archivo desde Task 3):
```python


_DAY_REMINDER_MIN_HOURS = 23.0
_DAY_REMINDER_MAX_HOURS = 25.0
_HOUR_REMINDER_MIN_MIN = 50.0
_HOUR_REMINDER_MAX_MIN = 70.0


async def check_reminders(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Cada 5 min: revisa eventos próximos y manda recordatorios pendientes."""
    now = datetime.now()
    upper = now + timedelta(hours=26)

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

    for row in rows:
        try:
            event_dt = datetime.fromisoformat(row["datetime"])
        except ValueError:
            log.warning("Evento %s con datetime inválido: %r", row["id"], row["datetime"])
            continue

        delta = event_dt - now
        hours = delta.total_seconds() / 3600.0
        minutes = delta.total_seconds() / 60.0

        # Recordatorio de 1 día
        if (_DAY_REMINDER_MIN_HOURS <= hours <= _DAY_REMINDER_MAX_HOURS
                and row["reminder_1d_sent"] == 0):
            time_str = event_dt.strftime("%H:%M")
            text = f"📅 Mañana a las {time_str} tienes: <b>{row['title']}</b>"
            await _safe_send_and_mark(context, text, row["id"], "reminder_1d_sent")

        # Recordatorio de 1 hora
        if (_HOUR_REMINDER_MIN_MIN <= minutes <= _HOUR_REMINDER_MAX_MIN
                and row["reminder_1h_sent"] == 0):
            text = f"⏰ En 1h tienes: <b>{row['title']}</b>"
            await _safe_send_and_mark(context, text, row["id"], "reminder_1h_sent")


async def _safe_send_and_mark(context, text: str, event_id: int, flag_column: str) -> None:
    """Envía el recordatorio y marca el flag. Si falla, loguea pero no levanta."""
    try:
        await context.bot.send_message(
            chat_id=ALLOWED_USER_ID,
            text=text,
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        log.exception("Error enviando recordatorio para evento %s", event_id)
        return

    with db.connect() as conn:
        conn.execute(
            f"UPDATE events SET {flag_column} = 1 WHERE id = ?",
            (event_id,),
        )
```

- [ ] **Step 4: Ejecutar tests**

```bash
python -m pytest tests/test_scheduler.py -v
```

Expected: 10 tests PASS (3 anteriores + 7 nuevos).

- [ ] **Step 5: Commit**

```bash
git add scheduler.py tests/test_scheduler.py
git commit -m "feat(scheduler): check_reminders sends 1-day and 1-hour proactive reminders"
```

---

## Task 5: Registrar los jobs en `bot.py`

**Files:**
- Modify: `bot.py`

- [ ] **Step 1: Modificar `main()` de `bot.py`**

Localizar la función `main()` en `bot.py` y reemplazarla por:
```python
def main() -> None:
    db.init_schema()
    log.info("Base de datos lista en %s", db.DB_PATH)

    app = Application.builder().token(TELEGRAM_TOKEN).post_init(_set_bot_commands).build()

    # Slash commands
    for cmd in ("hoy", "semana", "pendientes", "objetivos"):
        app.add_handler(CommandHandler(cmd, _make_slash_handler(f"/{cmd}")))

    # Mensajes de texto y voz
    app.add_handler(MessageHandler(filters.TEXT, _on_message))
    app.add_handler(MessageHandler(filters.VOICE, _on_voice))

    # Jobs programados
    from datetime import time as dtime
    import pytz

    import scheduler

    madrid = pytz.timezone("Europe/Madrid")
    app.job_queue.run_daily(
        scheduler.morning_summary,
        time=dtime(hour=9, minute=0, tzinfo=madrid),
        name="morning_summary",
    )
    app.job_queue.run_repeating(
        scheduler.check_reminders,
        interval=300,  # cada 5 minutos
        first=30,      # primera ejecución 30s tras arrancar
        name="check_reminders",
    )

    log.info("Bot arrancando (polling)…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)
```

- [ ] **Step 2: Instalar `pytz` (necesario para timezone-aware time)**

`python-telegram-bot` 21.6 ya trae `pytz` como dependencia indirecta, pero por si acaso:

```bash
source .venv/bin/activate
pip install pytz
```

Y añadir a `requirements.txt`:
```
pytz>=2024.1
```

- [ ] **Step 3: Verificar que la suite completa pasa**

```bash
python -m pytest -v
```

Expected: TODO PASS.

- [ ] **Step 4: Commit**

```bash
git add bot.py requirements.txt
git commit -m "feat(bot): register morning_summary and check_reminders jobs at startup"
```

---

## Task 6: Validación manual end-to-end

Esta tarea verifica que los jobs se disparan correctamente en condiciones reales.

- [ ] **Step 1: Reiniciar el bot**

```bash
pkill -9 -f "python bot.py"
pkill -9 -f "caffeinate"
sleep 10
cd "/Users/pablocansinos/Desktop/Proyecto Prueba"
./start.sh
```

Expected: logs muestran "Bot arrancando (polling)…" sin errores. **No debe aparecer ningún ERROR de scheduler.**

- [ ] **Step 2: Verificar que los jobs están registrados**

En los logs del bot, durante el arranque, debería verse alguna línea de `telegram.ext` o similar sobre el job_queue. Si no aparece nada explícito, no es problema — comprobamos con la prueba real.

- [ ] **Step 3: Smoke test de recordatorio de 1 hora**

Pedir a Pablo desde Telegram:
> "Apunta un evento de prueba en 1 hora, categoría work, título 'Recordatorio test'"

Esperar aproximadamente **30-90 segundos** (siguiente tick del scheduler). Debería llegar un mensaje:
> ⏰ En 1h tienes: **Recordatorio test**

- [ ] **Step 4: Smoke test de no-duplicado**

Esperar otros 5-6 minutos. **No debe llegar otro recordatorio** del mismo evento.

- [ ] **Step 5: Limpieza del evento de prueba**

Pablo: "borra el evento de prueba"

- [ ] **Step 6: Comprobación del matutino (manual o esperar)**

El job matutino se dispara a las 09:00 del día siguiente. Para validar antes:
- **Opción A:** esperar al día siguiente a las 09:00 y comprobar que llega el saludo.
- **Opción B (manual ahora):** ejecutar el callback a mano desde un script Python para verificar:
  ```bash
  source .venv/bin/activate
  python -c "
  import asyncio
  from telegram.ext import Application
  import scheduler
  from config import TELEGRAM_TOKEN

  async def main():
      app = Application.builder().token(TELEGRAM_TOKEN).build()
      await app.initialize()
      class Ctx:
          bot = app.bot
      await scheduler.morning_summary(Ctx())
      await app.shutdown()

  asyncio.run(main())
  "
  ```
  Esperado: llega un mensaje matutino a Telegram con el formato del resumen del día.

- [ ] **Step 7: Push a GitHub**

```bash
git push
```

---

## Resumen de entregables

- `formatting.py`: helper compartido `markdown_to_html`.
- `db.py`: columnas `reminder_1d_sent`, `reminder_1h_sent` en `events`, con migración idempotente.
- `tools.py`: `update_event` resetea los flags al cambiar `datetime`.
- `scheduler.py`: `morning_summary` (matutino) y `check_reminders` (recordatorios).
- `bot.py`: registra ambos jobs en el `job_queue` al arrancar.
- Tests nuevos: 4 (formatting) + 3 (db/tools migraciones y reset) + 10 (scheduler) = +17 sobre los 81 actuales. Total esperado: 98.
- Validación manual end-to-end con un evento de prueba.

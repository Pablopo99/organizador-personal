# Marcado rápido con botones inline — Plan de Implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Añadir botones inline a `/hoy` y al saludo matutino para marcar/desmarcar eventos, rutinas y tareas con un tap.

**Architecture:** Nuevo módulo `views.py` con `render_today_view(today, conn) -> (text, keyboard)` que es la fuente única del formato de `/hoy` y saludo matutino. `/hoy` y `morning_summary` dejan de pasar por Claude — los genera el bot directamente. Nuevo `CallbackQueryHandler` parsea `callback_data`, muta la BD y edita el mensaje en sitio.

**Tech Stack:** Python 3.12, python-telegram-bot 21.6 (InlineKeyboardMarkup, CallbackQueryHandler), pytest, pytest-asyncio.

**Spec de referencia:** `docs/superpowers/specs/2026-05-19-marcado-rapido-design.md`

---

## Convenciones

- TDD: test que falla → implementación → test pasa → commit.
- Cada Task termina en commit.
- Comandos desde `/Users/pablocansinos/Desktop/Otros/Proyecto Prueba`.
- Activar venv con ruta absoluta: `./.venv/bin/python -m pytest ...`.
- ALLOWED_USER_ID en tests es `42`.

---

## Task 1: Funciones unmark en `tools.py`

Tres funciones nuevas para deshacer el marcado. No se exponen como tools a Claude (son uso interno del callback handler).

**Files:**
- Modify: `tools.py`
- Modify: `tests/test_tools_events.py`
- Modify: `tests/test_tools_tasks.py`

- [ ] **Step 1: Escribir tests**

Añadir al final de `tests/test_tools_events.py`:

```python


def test_unmark_event_done_sets_done_zero():
    """Evento puntual marcado como hecho vuelve a done=0."""
    e = tools.add_event("Médico", "2026-05-20T10:00:00", "medical")
    tools.mark_event_done(e["id"])

    tools.unmark_event_done(e["id"])

    with db.connect() as conn:
        row = conn.execute("SELECT done FROM events WHERE id = ?", (e["id"],)).fetchone()
    assert row[0] == 0


def test_unmark_event_done_idempotent_on_unmarked():
    """Desmarcar algo no marcado no rompe ni cambia nada."""
    e = tools.add_event("Médico", "2026-05-20T10:00:00", "medical")
    tools.unmark_event_done(e["id"])

    with db.connect() as conn:
        row = conn.execute("SELECT done FROM events WHERE id = ?", (e["id"],)).fetchone()
    assert row[0] == 0


def test_uncomplete_routine_today_removes_today_completion(monkeypatch):
    """Borra la fila de routine_completions para event_id y today_madrid."""
    from datetime import date
    import date_utils
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 19))

    e = tools.add_event("Flexiones", "2026-05-19T08:00:00", "personal", recurring_rule="DAILY")
    tools.mark_event_done(e["id"])  # crea fila 2026-05-19

    tools.uncomplete_routine_today(e["id"])

    with db.connect() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM routine_completions WHERE event_id = ? AND completion_date = ?",
            (e["id"], "2026-05-19"),
        ).fetchone()[0]
    assert count == 0


def test_uncomplete_routine_today_preserves_other_days(monkeypatch):
    """Solo borra la fila de HOY, otras fechas se quedan."""
    from datetime import date
    import date_utils
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 19))

    e = tools.add_event("Flexiones", "2026-05-17T08:00:00", "personal", recurring_rule="DAILY")
    with db.connect() as conn:
        for d in ("2026-05-17", "2026-05-18", "2026-05-19"):
            conn.execute(
                "INSERT INTO routine_completions (event_id, completion_date, created_at) VALUES (?, ?, ?)",
                (e["id"], d, "2026-05-19T08:00:00"),
            )

    tools.uncomplete_routine_today(e["id"])

    with db.connect() as conn:
        dates = [r[0] for r in conn.execute(
            "SELECT completion_date FROM routine_completions WHERE event_id = ? ORDER BY completion_date",
            (e["id"],),
        ).fetchall()]
    assert dates == ["2026-05-17", "2026-05-18"]


def test_uncomplete_routine_today_idempotent_when_not_completed(monkeypatch):
    """Si no había completion hoy, no rompe."""
    from datetime import date
    import date_utils
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 19))

    e = tools.add_event("Flexiones", "2026-05-19T08:00:00", "personal", recurring_rule="DAILY")
    tools.uncomplete_routine_today(e["id"])  # no error
```

Añadir al final de `tests/test_tools_tasks.py`:

```python


def test_uncomplete_task_resets_done_and_done_at():
    """Tarea hecha vuelve a pendiente (done=0, done_at=NULL)."""
    t = tools.add_task("comprar pan")
    tools.complete_task(t["id"])

    tools.uncomplete_task(t["id"])

    with db.connect() as conn:
        row = conn.execute(
            "SELECT done, done_at FROM tasks WHERE id = ?", (t["id"],)
        ).fetchone()
    assert row[0] == 0
    assert row[1] is None


def test_uncomplete_task_idempotent_when_pending():
    """Desmarcar una tarea ya pendiente no rompe."""
    t = tools.add_task("comprar pan")
    tools.uncomplete_task(t["id"])

    with db.connect() as conn:
        row = conn.execute(
            "SELECT done FROM tasks WHERE id = ?", (t["id"],)
        ).fetchone()
    assert row[0] == 0
```

- [ ] **Step 2: Ejecutar tests, verificar que fallan**

```bash
./.venv/bin/python -m pytest tests/test_tools_events.py tests/test_tools_tasks.py -v -k "unmark or uncomplete" 2>&1 | tail -10
```

Expected: 7 FAIL — funciones no existen.

- [ ] **Step 3: Implementar las funciones en `tools.py`**

Añadir en `tools.py`, justo después de la función `mark_event_done`:

```python


def unmark_event_done(event_id: int) -> dict:
    """Quita el done=1 de un evento puntual (no-op para recurrentes)."""
    with db.connect() as conn:
        cur = conn.execute(
            "UPDATE events SET done = 0 WHERE id = ?", (event_id,)
        )
    return {"id": event_id, "updated": cur.rowcount}


def uncomplete_routine_today(event_id: int) -> dict:
    """Borra la completion de hoy (Madrid) para una rutina."""
    import date_utils
    today = date_utils.today_madrid().isoformat()
    with db.connect() as conn:
        cur = conn.execute(
            "DELETE FROM routine_completions WHERE event_id = ? AND completion_date = ?",
            (event_id, today),
        )
    return {"event_id": event_id, "completion_date": today, "deleted": cur.rowcount}
```

Y en la sección de tasks, justo después de `complete_task`:

```python


def uncomplete_task(task_id: int) -> dict:
    """Desmarca una tarea: done=0, done_at=NULL."""
    with db.connect() as conn:
        cur = conn.execute(
            "UPDATE tasks SET done = 0, done_at = NULL WHERE id = ?",
            (task_id,),
        )
    return {"id": task_id, "updated": cur.rowcount}
```

(No se añaden a `TOOL_DEFINITIONS` ni `_DISPATCH` — son uso interno.)

- [ ] **Step 4: Ejecutar tests, verificar que pasan**

```bash
./.venv/bin/python -m pytest tests/test_tools_events.py tests/test_tools_tasks.py -v -k "unmark or uncomplete"
```

Expected: 7 PASS.

- [ ] **Step 5: Ejecutar suite completa**

```bash
./.venv/bin/python -m pytest
```

Expected: todo PASS.

- [ ] **Step 6: Commit**

```bash
git add tools.py tests/test_tools_events.py tests/test_tools_tasks.py
git commit -m "feat(tools): unmark helpers for events, routines and tasks

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Módulo `views.py` con `render_today_view`

Función pura que dado `today` y `conn` devuelve el texto HTML y el `InlineKeyboardMarkup` para `/hoy` y saludo matutino.

**Files:**
- Create: `views.py`
- Create: `tests/test_views.py`

- [ ] **Step 1: Crear `tests/test_views.py`**

Contenido completo:

```python
import os
import tempfile
from datetime import date, datetime

import pytest

import db
import tools
import views


@pytest.fixture(autouse=True)
def temp_db(monkeypatch):
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init_schema()
    yield path
    os.unlink(path)


def _render(today=None):
    today = today or date(2026, 5, 19)
    with db.connect() as conn:
        return views.render_today_view(today, conn)


def test_render_empty_db_returns_day_libre():
    text, keyboard = _render()
    assert "Día libre" in text
    assert keyboard is None


def test_render_one_event_pending_creates_one_button():
    tools.add_event("Reunión", "2026-05-19T10:00:00", "work")

    text, keyboard = _render()

    assert "📅" in text
    assert "HOY" in text
    assert "10:00 — Reunión" in text
    assert keyboard is not None
    assert len(keyboard.inline_keyboard) == 1
    btn = keyboard.inline_keyboard[0][0]
    assert btn.text.startswith("🔲")
    assert "Reunión" in btn.text
    assert btn.callback_data.startswith("mE:")


def test_render_event_done_appears_in_completado_with_check_button():
    e = tools.add_event("Reunión", "2026-05-19T10:00:00", "work")
    tools.mark_event_done(e["id"])

    text, keyboard = _render()

    assert "COMPLETADO HOY" in text
    assert "<s>10:00 — Reunión</s>" in text
    assert len(keyboard.inline_keyboard) == 1
    btn = keyboard.inline_keyboard[0][0]
    assert btn.text.startswith("✅")
    assert btn.callback_data == f"uE:{e['id']}"


def test_render_routine_pending_in_rutinas_section(monkeypatch):
    import date_utils
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 19))
    e = tools.add_event("Flexiones", "2026-05-19T08:00:00", "personal", recurring_rule="DAILY")

    text, keyboard = _render()

    assert "🔁" in text
    assert "RUTINAS" in text
    assert "Flexiones" in text
    btn = keyboard.inline_keyboard[0][0]
    assert btn.callback_data == f"mR:{e['id']}"


def test_render_routine_done_today_in_completado_section(monkeypatch):
    import date_utils
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 19))
    e = tools.add_event("Flexiones", "2026-05-19T08:00:00", "personal", recurring_rule="DAILY")
    tools.mark_event_done(e["id"])

    text, keyboard = _render()

    assert "COMPLETADO HOY" in text
    assert "<s>Flexiones" in text  # streak no aparece aquí porque current=1
    btn = keyboard.inline_keyboard[0][0]
    assert btn.text.startswith("✅")
    assert btn.callback_data == f"uR:{e['id']}"


def test_render_routine_with_streak_shows_fire(monkeypatch):
    import date_utils
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 19))
    e = tools.add_event("Flexiones", "2026-05-17T08:00:00", "personal", recurring_rule="DAILY")
    with db.connect() as conn:
        for d in ("2026-05-17", "2026-05-18"):
            conn.execute(
                "INSERT INTO routine_completions (event_id, completion_date, created_at) VALUES (?, ?, ?)",
                (e["id"], d, "2026-05-19T08:00:00"),
            )

    text, _ = _render()

    assert "🔥 2" in text


def test_render_task_pending_with_button():
    t = tools.add_task("comprar pan")

    text, keyboard = _render()

    assert "PENDIENTES" in text
    assert "comprar pan" in text
    btn = keyboard.inline_keyboard[0][0]
    assert btn.callback_data == f"mT:{t['id']}"


def test_render_task_done_today_in_completado(monkeypatch):
    import date_utils
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 19))
    monkeypatch.setattr(date_utils, "now_iso", lambda: "2026-05-19T10:00:00")
    t = tools.add_task("comprar pan")
    tools.complete_task(t["id"])

    text, keyboard = _render()

    assert "COMPLETADO HOY" in text
    assert "<s>comprar pan</s>" in text
    btn = keyboard.inline_keyboard[0][0]
    assert btn.callback_data == f"uT:{t['id']}"


def test_render_task_done_yesterday_not_shown(monkeypatch):
    import date_utils
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 19))
    monkeypatch.setattr(date_utils, "now_iso", lambda: "2026-05-18T10:00:00")
    t = tools.add_task("comprar pan")
    tools.complete_task(t["id"])

    text, keyboard = _render()

    assert "COMPLETADO HOY" not in text
    assert "PENDIENTES" not in text  # tarea ya hecha, no aparece en pendientes
    # No buttons for this task
    if keyboard is not None:
        for row in keyboard.inline_keyboard:
            for btn in row:
                assert "comprar pan" not in btn.text


def test_render_full_mix_keyboard_order():
    """Orden: events pendientes, rutinas pendientes, tareas pendientes, completados (en mismo orden)."""
    # Setup
    tools.add_event("Reunión", "2026-05-19T10:00:00", "work")
    e_done = tools.add_event("Cita", "2026-05-19T11:00:00", "work")
    tools.mark_event_done(e_done["id"])

    text, keyboard = _render()

    btn_texts = [row[0].text for row in keyboard.inline_keyboard]
    btn_data = [row[0].callback_data for row in keyboard.inline_keyboard]

    # Reunión (pendiente) viene antes que Cita (hecha)
    assert btn_texts[0].startswith("🔲")
    assert "Reunión" in btn_texts[0]
    assert btn_texts[-1].startswith("✅")
    assert "Cita" in btn_texts[-1]
```

- [ ] **Step 2: Ejecutar tests, verificar que fallan**

```bash
./.venv/bin/python -m pytest tests/test_views.py -v 2>&1 | tail -5
```

Expected: TODOS FAIL — `views` no existe.

- [ ] **Step 3: Crear `views.py`**

Contenido completo:

```python
"""Render determinístico de la vista /hoy y el saludo matutino.

Devuelve texto HTML + InlineKeyboardMarkup para Telegram. Sin Claude
en el camino, así un tap edita el mensaje en sitio sin latencia.
"""
from datetime import date, datetime
from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

import tools


def render_today_view(today: date, conn) -> tuple[str, Optional[InlineKeyboardMarkup]]:
    today_start = f"{today.isoformat()}T00:00:00"
    today_end = f"{today.isoformat()}T23:59:59"

    events = tools.query_events(today_start, today_end, include_done=True)
    tasks_all = tools.list_tasks(include_done=True)
    routines = tools.routine_summary(today.isoformat(), today.isoformat())
    streak_by_id = {r["event_id"]: r["current_streak"] for r in routines}

    hoy_pending = [e for e in events if not e.get("recurring_rule") and e["done"] == 0]
    hoy_done = [e for e in events if not e.get("recurring_rule") and e["done"] == 1]
    rutina_pending = [e for e in events if e.get("recurring_rule") and e["done"] == 0]
    rutina_done = [e for e in events if e.get("recurring_rule") and e["done"] == 1]

    task_pending = [t for t in tasks_all if t["done"] == 0]
    today_prefix = today.isoformat()
    task_done_today = [
        t for t in tasks_all
        if t["done"] == 1 and (t.get("done_at") or "").startswith(today_prefix)
    ]

    sections: list[str] = []

    if hoy_pending:
        lines = []
        for e in hoy_pending:
            dt = datetime.fromisoformat(e["datetime"])
            lines.append(f"• {dt.strftime('%H:%M')} — {e['title']}")
        sections.append("📅 <b>HOY</b>\n\n" + "\n".join(lines))

    if rutina_pending:
        lines = []
        for e in rutina_pending:
            streak = streak_by_id.get(e["id"], 0)
            suffix = f" 🔥 {streak}" if streak >= 2 else ""
            lines.append(f"• {e['title']}{suffix}")
        sections.append("🔁 <b>RUTINAS</b>\n\n" + "\n".join(lines))

    if task_pending:
        lines = [f"• {t['text']}" for t in task_pending]
        sections.append("📝 <b>PENDIENTES</b>\n\n" + "\n".join(lines))

    if hoy_done or rutina_done or task_done_today:
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
        sections.append("✅ <b>COMPLETADO HOY</b>\n\n" + "\n".join(lines))

    if not sections:
        return "Día libre, disfrútalo 💪", None

    text = "\n\n".join(sections)

    buttons: list[list[InlineKeyboardButton]] = []
    for e in hoy_pending:
        buttons.append([InlineKeyboardButton(
            f"🔲 {e['title']}", callback_data=f"mE:{e['id']}"
        )])
    for e in rutina_pending:
        buttons.append([InlineKeyboardButton(
            f"🔲 {e['title']}", callback_data=f"mR:{e['id']}"
        )])
    for t in task_pending:
        buttons.append([InlineKeyboardButton(
            f"🔲 {t['text']}", callback_data=f"mT:{t['id']}"
        )])
    for e in hoy_done:
        buttons.append([InlineKeyboardButton(
            f"✅ {e['title']}", callback_data=f"uE:{e['id']}"
        )])
    for e in rutina_done:
        buttons.append([InlineKeyboardButton(
            f"✅ {e['title']}", callback_data=f"uR:{e['id']}"
        )])
    for t in task_done_today:
        buttons.append([InlineKeyboardButton(
            f"✅ {t['text']}", callback_data=f"uT:{t['id']}"
        )])

    keyboard = InlineKeyboardMarkup(buttons)
    return text, keyboard
```

- [ ] **Step 4: Ejecutar tests**

```bash
./.venv/bin/python -m pytest tests/test_views.py -v
```

Expected: TODO PASS.

- [ ] **Step 5: Ejecutar suite completa**

```bash
./.venv/bin/python -m pytest
```

Expected: TODO PASS.

- [ ] **Step 6: Commit**

```bash
git add views.py tests/test_views.py
git commit -m "feat(views): render_today_view returns text + inline keyboard

Pure function reads events, tasks and routine streaks and produces
the HTML body plus one button per item (🔲 pending, ✅ done) ready
for /hoy and the morning summary. Source of truth for the format.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: `/hoy` y morning summary usan `views.render_today_view`

Reescribimos los dos handlers para que generen el contenido directamente desde `views`, sin pasar por Claude.

**Files:**
- Modify: `bot.py`
- Modify: `scheduler.py`
- Modify: `tests/test_bot.py`
- Modify: `tests/test_scheduler.py`

- [ ] **Step 1: Escribir tests de `/hoy` deterministic**

Reemplazar en `tests/test_bot.py` los dos tests existentes que asumen Claude:

Localizar y BORRAR:
```python
def test_hoy_prompt_mentions_rutinas_section():
    prompt = bot._SLASH_PROMPTS["/hoy"]
    assert "RUTINAS" in prompt
    assert "query_events" in prompt
```

(Y `test_hoy_prompt_mentions_streak_threshold` también — Pablo no usa Claude para /hoy ahora.)

Añadir al final del archivo:

```python


def test_hoy_no_longer_in_slash_prompts():
    """/hoy ya no se procesa via Claude — tiene handler dedicado."""
    assert "/hoy" not in bot._SLASH_PROMPTS
```

- [ ] **Step 2: Borrar entradas `/hoy` de `_SLASH_PROMPTS` en `bot.py`**

Localizar `_SLASH_PROMPTS` y borrar el bloque que empieza con `"/hoy": (` y termina con `),`. Mantener el resto del dict intacto.

- [ ] **Step 3: Añadir handler dedicado `_on_hoy` en `bot.py`**

Añadir al inicio del archivo (junto a los otros imports):

```python
import date_utils
import tools
import views
```

Añadir nuevo handler antes de `_make_slash_handler`:

```python
async def _on_hoy(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    """/hoy: vista generada por views.render_today_view (sin Claude)."""
    if not update.message or not update.effective_user:
        return
    if update.effective_user.id != ALLOWED_USER_ID:
        log.warning("/hoy ignorado de user_id no autorizado: %s", update.effective_user.id)
        return

    today = date_utils.today_madrid()
    with db.connect() as conn:
        text, keyboard = views.render_today_view(today, conn)

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )
```

- [ ] **Step 4: Modificar registro de handlers en `main()`**

Localizar en `bot.main()`:

```python
    for cmd in ("hoy", "semana", "pendientes", "objetivos", "rachas"):
        app.add_handler(CommandHandler(cmd, _make_slash_handler(f"/{cmd}")))
```

Sustituir por:

```python
    app.add_handler(CommandHandler("hoy", _on_hoy))
    for cmd in ("semana", "pendientes", "objetivos", "rachas"):
        app.add_handler(CommandHandler(cmd, _make_slash_handler(f"/{cmd}")))
```

- [ ] **Step 5: Modificar `scheduler.morning_summary` para usar views**

En `scheduler.py`, sustituir la función `morning_summary` y eliminar `_morning_prompt` y `_SCHEDULER_USER_ID`. El bloque entre `_WEEKDAYS_ES = [...]` y `async def check_reminders` queda:

```python
_WEEKDAYS_ES = [
    "lunes", "martes", "miércoles", "jueves",
    "viernes", "sábado", "domingo",
]

_ES_MONTHS = [
    "ene", "feb", "mar", "abr", "may", "jun",
    "jul", "ago", "sep", "oct", "nov", "dic",
]


async def morning_summary(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Envía el saludo matutino con la vista de hoy."""
    import date_utils
    import db
    import views

    today = date_utils.today_madrid()
    weekday = _WEEKDAYS_ES[today.weekday()]
    date_str = f"{today.day} {_ES_MONTHS[today.month - 1]}"
    greeting = f"Buenos días Pablo 🌅 — <b>{weekday}, {date_str}</b>\n\n"

    try:
        with db.connect() as conn:
            body, keyboard = views.render_today_view(today, conn)
    except Exception:
        log.exception("Error generando el saludo matutino")
        return

    try:
        await context.bot.send_message(
            chat_id=ALLOWED_USER_ID,
            text=greeting + body,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )
    except Exception:
        log.exception("Error enviando el saludo matutino")
```

También borrar el import `brain` si ya no se usa en scheduler. Si solo lo usaba el morning summary, quitar `import brain` arriba. (Comprobar que `check_reminders` no lo usa — no lo usa.)

Y quitar el import de `markdown_to_html` si ya no se usa en scheduler. (`check_reminders` no lo usa, así que se elimina.)

Cabecera final de `scheduler.py`:

```python
"""Jobs programados: mensaje matutino y recordatorios proactivos."""
import logging
from datetime import datetime, timedelta

from telegram.constants import ParseMode
from telegram.ext import ContextTypes

import db
from config import ALLOWED_USER_ID

log = logging.getLogger("scheduler")
```

- [ ] **Step 6: Actualizar tests de scheduler**

Los tests `test_morning_summary_*` actuales mockean `brain.handle_message`. Hay que actualizarlos.

En `tests/test_scheduler.py`, **borrar** los tests:
- `test_morning_summary_sends_to_allowed_user`
- `test_morning_summary_converts_markdown_to_html`
- `test_morning_summary_handles_brain_exception`
- `test_morning_prompt_includes_rutinas_section`

Añadir al final del archivo (con los imports ya presentes arriba):

```python


@pytest.mark.asyncio
async def test_morning_summary_sends_greeting_with_view(monkeypatch):
    monkeypatch.setattr(scheduler, "ALLOWED_USER_ID", 42)

    send_mock = AsyncMock()
    await scheduler.morning_summary(_fake_context(send_mock))

    send_mock.assert_called_once()
    call = send_mock.call_args
    assert call.kwargs["chat_id"] == 42
    assert "Buenos días Pablo" in call.kwargs["text"]
    assert call.kwargs["parse_mode"] == "HTML"


@pytest.mark.asyncio
async def test_morning_summary_empty_db_says_day_libre(monkeypatch):
    monkeypatch.setattr(scheduler, "ALLOWED_USER_ID", 42)

    send_mock = AsyncMock()
    await scheduler.morning_summary(_fake_context(send_mock))

    text = send_mock.call_args.kwargs["text"]
    assert "Día libre" in text


@pytest.mark.asyncio
async def test_morning_summary_with_pending_item_includes_keyboard(monkeypatch):
    import tools
    monkeypatch.setattr(scheduler, "ALLOWED_USER_ID", 42)
    tools.add_task("comprar pan")

    send_mock = AsyncMock()
    await scheduler.morning_summary(_fake_context(send_mock))

    keyboard = send_mock.call_args.kwargs["reply_markup"]
    assert keyboard is not None
    assert len(keyboard.inline_keyboard) == 1
```

- [ ] **Step 7: Borrar tests obsoletos de bot que dependían de prompt /hoy**

En `tests/test_bot.py`, **borrar** los siguientes tests porque /hoy ya no usa Claude ni prompt:
- `test_hoy_prompt_mentions_rutinas_section`
- `test_hoy_prompt_mentions_streak_threshold`
- `test_process_incoming_routes_known_slash_to_command_handler` (probaba que `/hoy` se ruteaba via `_SLASH_PROMPTS`; ya no aplica, `/hoy` lo coge `CommandHandler` antes de llegar a `process_incoming`)

Dejar `test_hoy_no_longer_in_slash_prompts` que añadimos en Step 1.

- [ ] **Step 8: Ejecutar suite completa**

```bash
./.venv/bin/python -m pytest
```

Expected: TODO PASS.

- [ ] **Step 9: Commit**

```bash
git add bot.py scheduler.py tests/test_bot.py tests/test_scheduler.py
git commit -m "feat(bot,scheduler): /hoy and morning summary use views.render_today_view

/hoy gets a dedicated handler that bypasses Claude. morning_summary
is rewritten to prepend a greeting line and send views output with
the keyboard attached. Removes _morning_prompt, _SCHEDULER_USER_ID,
and the brain import from scheduler.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: CallbackQueryHandler

Handler que recibe el tap de un botón, parsea `callback_data`, muta la BD y edita el mensaje en sitio.

**Files:**
- Modify: `bot.py`
- Modify: `tests/test_bot.py`

- [ ] **Step 1: Escribir tests**

Añadir al final de `tests/test_bot.py`:

```python


@pytest.fixture
def temp_db_for_bot(monkeypatch):
    import os
    import tempfile

    import db as db_mod

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    monkeypatch.setattr(db_mod, "DB_PATH", path)
    db_mod.init_schema()
    yield path
    os.unlink(path)


def _make_callback_query(data: str, user_id: int = 42):
    """Crea un mock de CallbackQuery con métodos async."""
    from unittest.mock import AsyncMock, MagicMock
    query = MagicMock()
    query.data = data
    query.from_user = MagicMock()
    query.from_user.id = user_id
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    return query


def _make_update_with_callback(query):
    from unittest.mock import MagicMock
    update = MagicMock()
    update.callback_query = query
    update.effective_user = query.from_user
    return update


def _make_context_with_bot():
    from unittest.mock import AsyncMock, MagicMock
    context = MagicMock()
    context.bot = MagicMock()
    context.bot.send_message = AsyncMock()
    return context


import pytest


@pytest.mark.asyncio
async def test_callback_mark_event_done(temp_db_for_bot, monkeypatch):
    import tools
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    e = tools.add_event("Reunión", "2026-05-19T10:00:00", "work")

    query = _make_callback_query(f"mE:{e['id']}")
    await bot._on_callback_query(_make_update_with_callback(query), _make_context_with_bot())

    import db as db_mod
    with db_mod.connect() as conn:
        row = conn.execute("SELECT done FROM events WHERE id = ?", (e["id"],)).fetchone()
    assert row[0] == 1
    query.edit_message_text.assert_called_once()
    query.answer.assert_called()


@pytest.mark.asyncio
async def test_callback_unmark_event_done(temp_db_for_bot, monkeypatch):
    import tools
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    e = tools.add_event("Reunión", "2026-05-19T10:00:00", "work")
    tools.mark_event_done(e["id"])

    query = _make_callback_query(f"uE:{e['id']}")
    await bot._on_callback_query(_make_update_with_callback(query), _make_context_with_bot())

    import db as db_mod
    with db_mod.connect() as conn:
        row = conn.execute("SELECT done FROM events WHERE id = ?", (e["id"],)).fetchone()
    assert row[0] == 0


@pytest.mark.asyncio
async def test_callback_mark_routine_inserts_completion(temp_db_for_bot, monkeypatch):
    import tools
    import date_utils
    from datetime import date
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 19))
    e = tools.add_event("Flexiones", "2026-05-19T08:00:00", "personal", recurring_rule="DAILY")

    query = _make_callback_query(f"mR:{e['id']}")
    await bot._on_callback_query(_make_update_with_callback(query), _make_context_with_bot())

    import db as db_mod
    with db_mod.connect() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM routine_completions WHERE event_id = ? AND completion_date = ?",
            (e["id"], "2026-05-19"),
        ).fetchone()[0]
    assert count == 1


@pytest.mark.asyncio
async def test_callback_unmark_routine_deletes_completion(temp_db_for_bot, monkeypatch):
    import tools
    import date_utils
    from datetime import date
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 19))
    e = tools.add_event("Flexiones", "2026-05-19T08:00:00", "personal", recurring_rule="DAILY")
    tools.mark_event_done(e["id"])

    query = _make_callback_query(f"uR:{e['id']}")
    await bot._on_callback_query(_make_update_with_callback(query), _make_context_with_bot())

    import db as db_mod
    with db_mod.connect() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM routine_completions WHERE event_id = ?",
            (e["id"],),
        ).fetchone()[0]
    assert count == 0


@pytest.mark.asyncio
async def test_callback_mark_task(temp_db_for_bot, monkeypatch):
    import tools
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    t = tools.add_task("comprar pan")

    query = _make_callback_query(f"mT:{t['id']}")
    await bot._on_callback_query(_make_update_with_callback(query), _make_context_with_bot())

    import db as db_mod
    with db_mod.connect() as conn:
        row = conn.execute("SELECT done FROM tasks WHERE id = ?", (t["id"],)).fetchone()
    assert row[0] == 1


@pytest.mark.asyncio
async def test_callback_unmark_task(temp_db_for_bot, monkeypatch):
    import tools
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    t = tools.add_task("comprar pan")
    tools.complete_task(t["id"])

    query = _make_callback_query(f"uT:{t['id']}")
    await bot._on_callback_query(_make_update_with_callback(query), _make_context_with_bot())

    import db as db_mod
    with db_mod.connect() as conn:
        row = conn.execute("SELECT done, done_at FROM tasks WHERE id = ?", (t["id"],)).fetchone()
    assert row[0] == 0
    assert row[1] is None


@pytest.mark.asyncio
async def test_callback_unauthorized_user_no_mutation(temp_db_for_bot, monkeypatch):
    import tools
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    e = tools.add_event("Reunión", "2026-05-19T10:00:00", "work")

    query = _make_callback_query(f"mE:{e['id']}", user_id=999)
    await bot._on_callback_query(_make_update_with_callback(query), _make_context_with_bot())

    import db as db_mod
    with db_mod.connect() as conn:
        row = conn.execute("SELECT done FROM events WHERE id = ?", (e["id"],)).fetchone()
    assert row[0] == 0
    query.edit_message_text.assert_not_called()


@pytest.mark.asyncio
async def test_callback_malformed_data_does_not_crash(temp_db_for_bot, monkeypatch):
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)

    query = _make_callback_query("garbage")
    await bot._on_callback_query(_make_update_with_callback(query), _make_context_with_bot())

    query.answer.assert_called()
    query.edit_message_text.assert_not_called()


@pytest.mark.asyncio
async def test_callback_edit_failure_sends_new_message(temp_db_for_bot, monkeypatch):
    """Si edit_message_text falla (mensaje >48h), enviar mensaje nuevo."""
    from telegram.error import BadRequest
    import tools
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    e = tools.add_event("Reunión", "2026-05-19T10:00:00", "work")

    query = _make_callback_query(f"mE:{e['id']}")
    query.edit_message_text.side_effect = BadRequest("Message to edit not found")

    context = _make_context_with_bot()
    await bot._on_callback_query(_make_update_with_callback(query), context)

    context.bot.send_message.assert_called_once()
```

- [ ] **Step 2: Ejecutar tests, verificar que fallan**

```bash
./.venv/bin/python -m pytest tests/test_bot.py -v -k "callback" 2>&1 | tail -8
```

Expected: 9 FAIL — `_on_callback_query` no existe.

- [ ] **Step 3: Añadir `_on_callback_query` en `bot.py`**

Añadir imports necesarios al inicio:

```python
from telegram.error import BadRequest
from telegram.ext import CallbackQueryHandler
```

Añadir la función después de `_on_voice`:

```python
async def _on_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Procesa taps en botones inline de /hoy y saludo matutino."""
    query = update.callback_query
    if query is None:
        return
    if query.from_user.id != ALLOWED_USER_ID:
        log.warning("Callback ignorado de user_id no autorizado: %s", query.from_user.id)
        await query.answer("No autorizado")
        return

    data = query.data or ""
    if len(data) < 4 or ":" not in data:
        log.warning("callback_data malformado: %r", data)
        await query.answer("Acción no reconocida")
        return

    action_type = data[:2]
    try:
        item_id = int(data.split(":", 1)[1])
    except ValueError:
        log.warning("callback_data sin id válido: %r", data)
        await query.answer("Acción no reconocida")
        return

    handler = _CALLBACK_ACTIONS.get(action_type)
    if handler is None:
        log.warning("Acción de callback desconocida: %r", action_type)
        await query.answer("Acción no reconocida")
        return

    try:
        handler(item_id)
    except Exception:
        log.exception("Error aplicando mutación de callback %s", data)

    today = date_utils.today_madrid()
    with db.connect() as conn:
        text, keyboard = views.render_today_view(today, conn)

    try:
        await query.edit_message_text(
            text, parse_mode=ParseMode.HTML, reply_markup=keyboard,
        )
    except BadRequest:
        log.warning("Mensaje no editable (probablemente >48h), enviando nuevo")
        await context.bot.send_message(
            chat_id=ALLOWED_USER_ID,
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )

    await query.answer()


_CALLBACK_ACTIONS = {
    "mE": lambda i: tools.mark_event_done(i),
    "uE": lambda i: tools.unmark_event_done(i),
    "mR": lambda i: tools.mark_event_done(i),
    "uR": lambda i: tools.uncomplete_routine_today(i),
    "mT": lambda i: tools.complete_task(i),
    "uT": lambda i: tools.uncomplete_task(i),
}
```

- [ ] **Step 4: Registrar `CallbackQueryHandler` en `main()`**

En `bot.main()`, después del `MessageHandler` de voz y antes de los jobs, añadir:

```python
    app.add_handler(CallbackQueryHandler(_on_callback_query))
```

- [ ] **Step 5: Ejecutar tests**

```bash
./.venv/bin/python -m pytest tests/test_bot.py -v -k "callback"
```

Expected: 9 PASS.

- [ ] **Step 6: Ejecutar suite completa**

```bash
./.venv/bin/python -m pytest
```

Expected: TODO PASS.

- [ ] **Step 7: Commit**

```bash
git add bot.py tests/test_bot.py
git commit -m "feat(bot): CallbackQueryHandler for inline mark/unmark buttons

Six actions (mE/uE/mR/uR/mT/uT) route through tools functions to
mutate the relevant table, then re-render via views.render_today_view
and edit the message in place. Falls back to a new message if the
original is too old to edit.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Deploy a Fly + validación end-to-end

- [ ] **Step 1: Confirmar suite completa**

```bash
./.venv/bin/python -m pytest
```

Expected: TODO PASS.

- [ ] **Step 2: Deploy a Fly**

```bash
flyctl deploy --app mi-secretaria-pablo
```

Expected: build OK, máquina actualizada sin errores.

- [ ] **Step 3: Verificar logs**

```bash
flyctl logs --app mi-secretaria-pablo --no-tail | tail -15
```

Expected: arranque limpio, jobs registrados, polling activo.

- [ ] **Step 4: Validar `/hoy` con botones**

Pablo envía `/hoy` en Telegram. Esperado:
- Mensaje con secciones HOY/RUTINAS/PENDIENTES/COMPLETADO HOY (las que apliquen).
- Bajo el mensaje, un botón `🔲 {título}` por cada item pendiente y `✅ {título}` por cada completado de hoy.

- [ ] **Step 5: Validar tap en pendiente**

Pablo tap en `🔲 Flexiones`. Esperado:
- En <1 segundo, el bullet salta de RUTINAS a COMPLETADO HOY tachado.
- El botón cambia a `✅ Flexiones`.

- [ ] **Step 6: Validar tap en completado (deshacer)**

Pablo tap en `✅ Flexiones`. Esperado:
- Vuelve a RUTINAS pendiente con `🔲 Flexiones`.

- [ ] **Step 7: Validar interacción con chat**

Pablo escribe al bot (sin slash): *"añade tarea comprar leche"*. Esperado:
- El bot confirma vía chat (Claude responde).
- Al pedir `/hoy` de nuevo, "comprar leche" aparece en PENDIENTES con su botón.

- [ ] **Step 8: Validar saludo matutino (manual o esperar 09:00)**

Si quieres comprobarlo ahora sin esperar:

```bash
flyctl ssh console --app mi-secretaria-pablo -C "python -c '
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
'"
```

Esperado: llega el saludo matutino con `Buenos días Pablo 🌅 — {weekday}, {fecha}` y el cuerpo + botones.

- [ ] **Step 9: Push a GitHub**

```bash
git push
```

---

## Resumen de entregables

- `tools.py`: funciones nuevas `unmark_event_done`, `uncomplete_routine_today`, `uncomplete_task` (uso interno, no expuestas como tools).
- `views.py` (nuevo): `render_today_view(today, conn)` devuelve `(html, keyboard)`. Fuente única del formato.
- `bot.py`: handler dedicado `_on_hoy`, nuevo `CallbackQueryHandler` con 6 acciones (mE/uE/mR/uR/mT/uT), edición in-place con fallback a mensaje nuevo si el original es muy viejo.
- `scheduler.py`: `morning_summary` reescrito para usar `views.render_today_view` (sin Claude). `_morning_prompt` y `_SCHEDULER_USER_ID` eliminados.
- Tests nuevos: 7 (unmark) + 10 (views) + 9 (callback) + 3 (morning_summary nuevos) - varios (tests obsoletos eliminados) = ~+22 sobre la base.
- Deploy a Fly y validación end-to-end de los 3 escenarios principales.

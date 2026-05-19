# Botones en /pendientes y /semana — Plan de Implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Añadir botones inline a `/pendientes` (uno por tarea) y `/semana` (solo objetivos), siguiendo el patrón de `/hoy` desplegado esta tarde.

**Architecture:** Dos renderers nuevos en `views.py` (`render_pending_view`, `render_week_view`). Una función interna en `tools.py` (`unmark_objective_done`). `callback_data` gana un sufijo de vista (`:H`/`:P`/`:W`) para que el callback handler re-pinte la vista correcta; formato antiguo sin sufijo se trata como `H` para no romper mensajes existentes. `/pendientes` y `/semana` dejan de pasar por Claude.

**Tech Stack:** Python 3.12, python-telegram-bot 21.6, pytest, pytest-asyncio.

**Spec de referencia:** `docs/superpowers/specs/2026-05-19-botones-pendientes-semana-design.md`

---

## Convenciones

- TDD: test que falla → implementación → test pasa → commit.
- Cada Task termina en commit.
- Comandos desde `/Users/pablocansinos/Desktop/Otros/Proyecto Prueba`.
- Activar venv con ruta absoluta: `./.venv/bin/python -m pytest ...`.

---

## Task 1: `unmark_objective_done` en `tools.py`

Función interna (no expuesta como Claude tool) para deshacer un objetivo.

**Files:**
- Modify: `tools.py`
- Modify: `tests/test_tools_objectives.py`

- [ ] **Step 1: Escribir tests**

Añadir al final de `tests/test_tools_objectives.py`:

```python


def test_unmark_objective_done_sets_done_zero():
    o = tools.add_objective("Terminar pres", "2026-05-18")
    tools.mark_objective_done(o["id"])

    tools.unmark_objective_done(o["id"])

    with db.connect() as conn:
        row = conn.execute(
            "SELECT done FROM objectives WHERE id = ?", (o["id"],)
        ).fetchone()
    assert row[0] == 0


def test_unmark_objective_done_idempotent():
    o = tools.add_objective("Terminar pres", "2026-05-18")
    tools.unmark_objective_done(o["id"])  # no error en pendiente

    with db.connect() as conn:
        row = conn.execute(
            "SELECT done FROM objectives WHERE id = ?", (o["id"],)
        ).fetchone()
    assert row[0] == 0
```

Si `tests/test_tools_objectives.py` no importa `db`, añadirlo al principio (`import db`).

- [ ] **Step 2: Ejecutar tests, verificar que fallan**

```bash
./.venv/bin/python -m pytest tests/test_tools_objectives.py -v -k "unmark"
```

Expected: 2 FAIL — función no existe.

- [ ] **Step 3: Implementar en `tools.py`**

Localizar la función `mark_objective_done` en `tools.py` y, justo después, añadir:

```python


def unmark_objective_done(objective_id: int) -> dict:
    """Desmarca un objetivo: done=0. Uso interno (callback de /semana)."""
    with db.connect() as conn:
        cur = conn.execute(
            "UPDATE objectives SET done = 0 WHERE id = ?", (objective_id,)
        )
    return {"id": objective_id, "updated": cur.rowcount}
```

NO añadirla a `TOOL_DEFINITIONS` ni `_DISPATCH` (es interna).

- [ ] **Step 4: Verificar tests pasan**

```bash
./.venv/bin/python -m pytest tests/test_tools_objectives.py -v
```

Expected: TODO PASS.

- [ ] **Step 5: Suite completa**

```bash
./.venv/bin/python -m pytest
```

Expected: TODO PASS.

- [ ] **Step 6: Commit**

```bash
git add tools.py tests/test_tools_objectives.py
git commit -m "feat(tools): unmark_objective_done internal helper

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: `render_pending_view` en `views.py`

Renderer determinístico para `/pendientes`.

**Files:**
- Modify: `views.py`
- Modify: `tests/test_views.py`

- [ ] **Step 1: Escribir tests**

Añadir al final de `tests/test_views.py`:

```python


def test_render_pending_view_empty_returns_celebration():
    with db.connect() as conn:
        text, keyboard = views.render_pending_view(conn)

    assert "No tienes tareas pendientes" in text
    assert "🎉" in text
    assert keyboard is None


def test_render_pending_view_lists_tasks_with_buttons():
    t1 = tools.add_task("Solucionar Spotify")
    t2 = tools.add_task("Comprar pan")

    with db.connect() as conn:
        text, keyboard = views.render_pending_view(conn)

    assert "PENDIENTES" in text
    assert "Solucionar Spotify" in text
    assert "Comprar pan" in text
    assert keyboard is not None
    assert len(keyboard.inline_keyboard) == 2

    datas = [row[0].callback_data for row in keyboard.inline_keyboard]
    assert f"mT:{t1['id']}:P" in datas
    assert f"mT:{t2['id']}:P" in datas

    for row in keyboard.inline_keyboard:
        assert row[0].text.startswith("🔲")


def test_render_pending_view_skips_done_tasks():
    t = tools.add_task("Ya hecha")
    tools.complete_task(t["id"])
    tools.add_task("Pendiente")

    with db.connect() as conn:
        text, keyboard = views.render_pending_view(conn)

    assert "Ya hecha" not in text
    assert "Pendiente" in text
    assert len(keyboard.inline_keyboard) == 1
```

- [ ] **Step 2: Verificar fallan**

```bash
./.venv/bin/python -m pytest tests/test_views.py -v -k "pending"
```

Expected: 3 FAIL — `render_pending_view` no existe.

- [ ] **Step 3: Implementar `render_pending_view`**

Añadir al final de `views.py`:

```python


def render_pending_view(conn) -> tuple[str, Optional[InlineKeyboardMarkup]]:
    """Vista de /pendientes: una tarea por línea, un botón por tarea."""
    tasks_all = tools.list_tasks(include_done=False)

    if not tasks_all:
        return "No tienes tareas pendientes. 🎉", None

    lines = [f"• {t['text']}" for t in tasks_all]
    text = "📝 <b>PENDIENTES</b>\n\n" + "\n".join(lines)

    buttons: list[list[InlineKeyboardButton]] = []
    for t in tasks_all:
        buttons.append([InlineKeyboardButton(
            f"🔲 {t['text']}", callback_data=f"mT:{t['id']}:P"
        )])

    return text, InlineKeyboardMarkup(buttons)
```

- [ ] **Step 4: Verificar tests pasan**

```bash
./.venv/bin/python -m pytest tests/test_views.py -v -k "pending"
```

Expected: 3 PASS.

- [ ] **Step 5: Suite completa**

```bash
./.venv/bin/python -m pytest
```

Expected: TODO PASS.

- [ ] **Step 6: Commit**

```bash
git add views.py tests/test_views.py
git commit -m "feat(views): render_pending_view for /pendientes with task buttons

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: `render_week_view` en `views.py`

Renderer determinístico para `/semana`. Cuatro secciones, botones solo en objetivos.

**Files:**
- Modify: `views.py`
- Modify: `tests/test_views.py`

- [ ] **Step 1: Escribir tests**

Añadir al final de `tests/test_views.py`:

```python


def _render_week(today=None):
    today = today or date(2026, 5, 18)  # lunes
    with db.connect() as conn:
        return views.render_week_view(today, conn)


def test_render_week_view_empty_returns_semana_tranquila():
    text, keyboard = _render_week()
    assert "Semana tranquila" in text
    assert keyboard is None


def test_render_week_view_only_objective_has_button():
    """1 evento + 1 objetivo pendiente + 1 rutina → solo el objetivo lleva botón."""
    tools.add_event("Reunión Marta", "2026-05-19T10:00:00", "work")
    o = tools.add_objective("Terminar pres Spotify", "2026-05-18")
    tools.add_event("Flexiones", "2026-05-18T08:00:00", "personal", recurring_rule="DAILY")

    text, keyboard = _render_week()

    assert "ESTA SEMANA" in text
    assert "Reunión Marta" in text
    assert "OBJETIVOS" in text
    assert "Terminar pres Spotify" in text
    assert "RUTINAS" in text
    assert "Flexiones" in text

    assert keyboard is not None
    assert len(keyboard.inline_keyboard) == 1
    btn = keyboard.inline_keyboard[0][0]
    assert btn.text == f"🔲 Terminar pres Spotify"
    assert btn.callback_data == f"mO:{o['id']}:W"


def test_render_week_view_done_objective_has_undo_button():
    o = tools.add_objective("Subir vídeos", "2026-05-18")
    tools.mark_objective_done(o["id"])

    text, keyboard = _render_week()

    assert "OBJETIVOS" in text
    assert "✅ Subir vídeos" in text or "✅" in text  # inline ✅ en el bullet
    assert keyboard is not None
    btn = keyboard.inline_keyboard[0][0]
    assert btn.text == f"✅ Subir vídeos"
    assert btn.callback_data == f"uO:{o['id']}:W"


def test_render_week_view_pending_and_done_objectives_both_get_buttons():
    o1 = tools.add_objective("Pendiente", "2026-05-18")
    o2 = tools.add_objective("Hecho", "2026-05-18")
    tools.mark_objective_done(o2["id"])

    text, keyboard = _render_week()

    assert keyboard is not None
    datas = [row[0].callback_data for row in keyboard.inline_keyboard]
    assert f"mO:{o1['id']}:W" in datas
    assert f"uO:{o2['id']}:W" in datas


def test_render_week_view_completed_task_in_completado_section_without_button(monkeypatch):
    import date_utils
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 19))
    t = tools.add_task("Comprar pan")
    with db.connect() as conn:
        conn.execute(
            "UPDATE tasks SET done=1, done_at=? WHERE id=?",
            ("2026-05-19T10:00:00", t["id"]),
        )

    text, keyboard = _render_week()

    assert "COMPLETADO" in text
    assert "<s>Comprar pan</s>" in text
    # No button for the completed task
    if keyboard is not None:
        for row in keyboard.inline_keyboard:
            for btn in row:
                assert "Comprar pan" not in btn.text


def test_render_week_view_objectives_filtered_by_current_week():
    """Solo objetivos del lunes de esta semana (no de semanas pasadas)."""
    today = date(2026, 5, 18)  # lunes
    tools.add_objective("De esta semana", "2026-05-18")
    tools.add_objective("De la pasada", "2026-05-11")

    with db.connect() as conn:
        text, keyboard = views.render_week_view(today, conn)

    assert "De esta semana" in text
    assert "De la pasada" not in text
```

- [ ] **Step 2: Verificar fallan**

```bash
./.venv/bin/python -m pytest tests/test_views.py -v -k "week"
```

Expected: 6 FAIL — `render_week_view` no existe.

- [ ] **Step 3: Implementar `render_week_view`**

Añadir al final de `views.py`:

```python


def render_week_view(today: date, conn) -> tuple[str, Optional[InlineKeyboardMarkup]]:
    """Vista de /semana: 4 secciones (ESTA SEMANA, OBJETIVOS, RUTINAS, COMPLETADO).

    Solo los objetivos llevan botón. Eventos, rutinas y completados se quedan como texto.
    """
    from datetime import timedelta

    from date_utils import monday_of_week

    monday = monday_of_week(today)
    sunday = monday + timedelta(days=6)
    week_start_iso = f"{monday.isoformat()}T00:00:00"
    week_end_iso = f"{sunday.isoformat()}T23:59:59"

    events = tools.query_events(week_start_iso, week_end_iso, include_done=True)
    objectives = tools.query_objectives(monday.isoformat())
    tasks_all = tools.list_tasks(include_done=True)
    routines = tools.routine_summary(monday.isoformat(), sunday.isoformat())

    week_pending = [e for e in events if not e.get("recurring_rule") and e["done"] == 0]
    week_done = [e for e in events if not e.get("recurring_rule") and e["done"] == 1]

    monday_prefix = monday.isoformat()
    task_done_week = []
    for t in tasks_all:
        if t["done"] != 1:
            continue
        done_at = t.get("done_at") or ""
        if not done_at:
            continue
        try:
            done_date = date.fromisoformat(done_at.split("T")[0])
        except ValueError:
            continue
        if monday <= done_date <= sunday:
            task_done_week.append(t)

    weekdays_es = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]

    sections: list[str] = []

    if week_pending:
        lines = []
        for e in week_pending:
            dt = datetime.fromisoformat(e["datetime"])
            wd = weekdays_es[dt.weekday()]
            lines.append(f"• {wd} {dt.strftime('%H:%M')} — {e['title']}")
        sections.append("📅 <b>ESTA SEMANA</b>\n\n" + "\n".join(lines))

    if objectives:
        lines = []
        for o in objectives:
            mark = "✅" if o["done"] else "🔲"
            lines.append(f"{mark} {o['text']}")
        sections.append("🎯 <b>OBJETIVOS</b>\n\n" + "\n".join(lines))

    if routines:
        lines = []
        for r in routines:
            base = f"• {r['title']} ({r['completed_days']}/{r['scheduled_days']} días)"
            if r["current_streak"] >= 2:
                base += f" 🔥 {r['current_streak']} seguidos"
            lines.append(base)
        sections.append("🔁 <b>RUTINAS</b>\n\n" + "\n".join(lines))

    if week_done or task_done_week:
        lines = []
        for e in week_done:
            dt = datetime.fromisoformat(e["datetime"])
            wd = weekdays_es[dt.weekday()]
            lines.append(f"• <s>{wd} {dt.strftime('%H:%M')} — {e['title']}</s>")
        for t in task_done_week:
            lines.append(f"• <s>{t['text']}</s>")
        sections.append("✅ <b>COMPLETADO</b>\n\n" + "\n".join(lines))

    if not sections:
        return "Semana tranquila 💆", None

    text = "\n\n".join(sections)

    buttons: list[list[InlineKeyboardButton]] = []
    for o in objectives:
        if o["done"]:
            buttons.append([InlineKeyboardButton(
                f"✅ {o['text']}", callback_data=f"uO:{o['id']}:W"
            )])
        else:
            buttons.append([InlineKeyboardButton(
                f"🔲 {o['text']}", callback_data=f"mO:{o['id']}:W"
            )])

    keyboard = InlineKeyboardMarkup(buttons) if buttons else None
    return text, keyboard
```

- [ ] **Step 4: Verificar tests pasan**

```bash
./.venv/bin/python -m pytest tests/test_views.py -v -k "week"
```

Expected: 6 PASS.

- [ ] **Step 5: Suite completa**

```bash
./.venv/bin/python -m pytest
```

Expected: TODO PASS.

- [ ] **Step 6: Commit**

```bash
git add views.py tests/test_views.py
git commit -m "feat(views): render_week_view for /semana with objective buttons

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Handlers `_on_pendientes` y `_on_semana` + callback routing por vista

Tres cambios en `bot.py`: dos handlers nuevos, eliminación de `/pendientes` y `/semana` del dict de prompts, y extender el callback handler para parsear la letra de vista y despachar al renderer correcto.

**Files:**
- Modify: `bot.py`
- Modify: `tests/test_bot.py`

- [ ] **Step 1: Escribir tests**

Añadir al final de `tests/test_bot.py`:

```python


def test_pendientes_no_longer_in_slash_prompts():
    assert "/pendientes" not in bot._SLASH_PROMPTS


def test_semana_no_longer_in_slash_prompts():
    assert "/semana" not in bot._SLASH_PROMPTS


@pytest.mark.asyncio
async def test_callback_mark_objective_in_week_view(temp_db_for_bot, monkeypatch):
    import tools
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    o = tools.add_objective("Terminar pres", "2026-05-18")

    query = _make_callback_query(f"mO:{o['id']}:W")
    await bot._on_callback_query(_make_update_with_callback(query), _make_context_with_bot())

    import db as db_mod
    with db_mod.connect() as conn:
        row = conn.execute(
            "SELECT done FROM objectives WHERE id = ?", (o["id"],)
        ).fetchone()
    assert row[0] == 1
    query.edit_message_text.assert_called_once()


@pytest.mark.asyncio
async def test_callback_unmark_objective_in_week_view(temp_db_for_bot, monkeypatch):
    import tools
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    o = tools.add_objective("Subir vídeos", "2026-05-18")
    tools.mark_objective_done(o["id"])

    query = _make_callback_query(f"uO:{o['id']}:W")
    await bot._on_callback_query(_make_update_with_callback(query), _make_context_with_bot())

    import db as db_mod
    with db_mod.connect() as conn:
        row = conn.execute(
            "SELECT done FROM objectives WHERE id = ?", (o["id"],)
        ).fetchone()
    assert row[0] == 0


@pytest.mark.asyncio
async def test_callback_mark_task_in_pending_view(temp_db_for_bot, monkeypatch):
    import tools
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    t = tools.add_task("comprar pan")

    query = _make_callback_query(f"mT:{t['id']}:P")
    await bot._on_callback_query(_make_update_with_callback(query), _make_context_with_bot())

    import db as db_mod
    with db_mod.connect() as conn:
        row = conn.execute("SELECT done FROM tasks WHERE id = ?", (t["id"],)).fetchone()
    assert row[0] == 1
    # Verifica que el edit usa render_pending_view (texto contiene "tareas pendientes" porque está vacío)
    edit_kwargs = query.edit_message_text.call_args.kwargs
    text = edit_kwargs.get("text") or query.edit_message_text.call_args.args[0]
    assert "No tienes tareas pendientes" in text


@pytest.mark.asyncio
async def test_callback_old_format_no_view_suffix_defaults_to_hoy(temp_db_for_bot, monkeypatch):
    """callback_data sin sufijo de vista (mE:42) se trata como H."""
    import tools
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    e = tools.add_event("Reunión", "2026-05-19T10:00:00", "work")

    query = _make_callback_query(f"mE:{e['id']}")  # sin :H
    await bot._on_callback_query(_make_update_with_callback(query), _make_context_with_bot())

    import db as db_mod
    with db_mod.connect() as conn:
        row = conn.execute("SELECT done FROM events WHERE id = ?", (e["id"],)).fetchone()
    assert row[0] == 1
    query.edit_message_text.assert_called_once()
```

- [ ] **Step 2: Verificar fallan**

```bash
./.venv/bin/python -m pytest tests/test_bot.py -v -k "pendientes_no_longer or semana_no_longer or objective_in_week or task_in_pending or old_format"
```

Expected: los nuevos FAIL.

- [ ] **Step 3: Quitar `/pendientes` y `/semana` de `_SLASH_PROMPTS`**

En `bot.py`, localizar y eliminar las dos entradas del diccionario `_SLASH_PROMPTS` que empiezan con `"/pendientes": (` y `"/semana": (`. El dict resultante solo contendrá `/objetivos` y `/rachas`.

- [ ] **Step 4: Añadir handlers `_on_pendientes` y `_on_semana`**

En `bot.py`, justo después de `_on_hoy`, añadir:

```python
async def _on_pendientes(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    """/pendientes: lista de tareas pendientes con botón por tarea."""
    if not update.message or not update.effective_user:
        return
    if update.effective_user.id != ALLOWED_USER_ID:
        log.warning("/pendientes ignorado de user_id no autorizado: %s", update.effective_user.id)
        return

    with db.connect() as conn:
        text, keyboard = views.render_pending_view(conn)

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


async def _on_semana(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    """/semana: resumen de la semana con botones solo en objetivos."""
    if not update.message or not update.effective_user:
        return
    if update.effective_user.id != ALLOWED_USER_ID:
        log.warning("/semana ignorado de user_id no autorizado: %s", update.effective_user.id)
        return

    today = date_utils.today_madrid()
    with db.connect() as conn:
        text, keyboard = views.render_week_view(today, conn)

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )
```

- [ ] **Step 5: Registrar los handlers en `main()`**

En `bot.main()`, sustituir:

```python
    app.add_handler(CommandHandler("hoy", _on_hoy))
    for cmd in ("semana", "pendientes", "objetivos", "rachas"):
        app.add_handler(CommandHandler(cmd, _make_slash_handler(f"/{cmd}")))
```

por:

```python
    app.add_handler(CommandHandler("hoy", _on_hoy))
    app.add_handler(CommandHandler("pendientes", _on_pendientes))
    app.add_handler(CommandHandler("semana", _on_semana))
    for cmd in ("objetivos", "rachas"):
        app.add_handler(CommandHandler(cmd, _make_slash_handler(f"/{cmd}")))
```

- [ ] **Step 6: Extender `_CALLBACK_ACTIONS` con `mO`/`uO`**

En `bot.py`, sustituir el dict `_CALLBACK_ACTIONS` por:

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
}
```

- [ ] **Step 7: Parsear sufijo de vista y despachar al renderer correcto**

En `bot.py`, sustituir la función `_on_callback_query` por:

```python
async def _on_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Procesa taps en botones inline. callback_data: '{action}{type}:{id}[:{view}]'."""
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
    parts = data[3:].split(":", 1)
    try:
        item_id = int(parts[0])
    except ValueError:
        log.warning("callback_data sin id válido: %r", data)
        await query.answer("Acción no reconocida")
        return

    view_letter = parts[1] if len(parts) > 1 else "H"

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
        if view_letter == "P":
            text, keyboard = views.render_pending_view(conn)
        elif view_letter == "W":
            text, keyboard = views.render_week_view(today, conn)
        else:
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
```

- [ ] **Step 8: Verificar tests pasan**

```bash
./.venv/bin/python -m pytest tests/test_bot.py -v -k "pendientes_no_longer or semana_no_longer or objective_in_week or task_in_pending or old_format or callback"
```

Expected: TODO PASS.

- [ ] **Step 9: Suite completa**

```bash
./.venv/bin/python -m pytest
```

Expected: TODO PASS.

- [ ] **Step 10: Commit**

```bash
git add bot.py tests/test_bot.py
git commit -m "feat(bot): /pendientes and /semana use views with inline buttons

/pendientes gets a button per task. /semana gets buttons only on
objectives. callback_data gains a view-letter suffix (:H/:P/:W) so
taps re-render the correct view; legacy format without suffix is
treated as H for backward compatibility.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Deploy a Fly + validación end-to-end

- [ ] **Step 1: Suite completa**

```bash
./.venv/bin/python -m pytest
```

Expected: TODO PASS.

- [ ] **Step 2: Deploy**

```bash
flyctl deploy --app mi-secretaria-pablo
```

Expected: build OK, máquina actualizada.

- [ ] **Step 3: Verificar logs**

```bash
flyctl logs --app mi-secretaria-pablo --no-tail | tail -10
```

Expected: arranque limpio, jobs registrados, sin excepciones.

- [ ] **Step 4: Validar `/pendientes`**

Pablo envía `/pendientes`. Esperado:
- Sección 📝 PENDIENTES con sus tareas.
- Un botón `🔲 {texto}` por tarea bajo el mensaje.
- Tap a una → la tarea desaparece del mensaje (re-render).
- Cuando todas hechas → "No tienes tareas pendientes. 🎉" sin botones.

- [ ] **Step 5: Validar `/semana`**

Pablo envía `/semana`. Esperado:
- 4 secciones (las que apliquen): ESTA SEMANA, OBJETIVOS, RUTINAS, COMPLETADO.
- Botones SOLO en la sección OBJETIVOS, ninguno en el resto.
- Tap a `🔲 Objetivo X` → pasa a `✅` inline y botón cambia a `✅`.
- Tap a `✅` → vuelve a `🔲`.

- [ ] **Step 6: Validar compatibilidad hacia atrás**

Pedir `/hoy` y comprobar que sigue funcionando (callback_data antiguo sin sufijo se interpreta como vista H).

- [ ] **Step 7: Push a GitHub**

```bash
git push
```

---

## Resumen de entregables

- `tools.py`: `unmark_objective_done` (interna, no expuesta).
- `views.py`: `render_pending_view`, `render_week_view`.
- `bot.py`: handlers `_on_pendientes`, `_on_semana`; `_CALLBACK_ACTIONS` con `mO`/`uO`; `_on_callback_query` con sufijo de vista; eliminadas entradas `/pendientes` y `/semana` de `_SLASH_PROMPTS`.
- Tests nuevos: 2 (unmark_objective) + 3 (pending view) + 6 (week view) + 6 (callback view-routing) = **+17 sobre la base**.
- Deploy a Fly y validación end-to-end de ambos comandos.

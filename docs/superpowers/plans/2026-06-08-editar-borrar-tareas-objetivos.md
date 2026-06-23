# Editar y borrar tareas/objetivos por chat — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permitir a Claude borrar tareas y objetivos, y editar su texto y fecha, mediante 4 herramientas nuevas registradas en `TOOL_DEFINITIONS`.

**Architecture:** Tres helpers nuevos en `tools.py` (`delete_objective`, `update_task`, `update_objective`) más exposición del helper existente `delete_task`. Las dos `update_*` siguen el patrón ya consolidado de `update_event`: reciben un dict `fields` con los campos a tocar; campos ausentes no se modifican; un campo presente con valor `null` significa "borrar" (solo aplica a `due_date` de tarea). Reglas nuevas en el system prompt de `brain.py` para que Claude liste→confirme→ejecuta.

**Tech Stack:** Python 3.12, SQLite, pytest, Anthropic SDK tool use.

**Spec:** `docs/superpowers/specs/2026-06-08-editar-borrar-tareas-objetivos-design.md`

---

## Task 1: Exponer `delete_task` a Claude

**Files:**
- Modify: `tools.py` (añadir entrada en `TOOL_DEFINITIONS` y en `_DISPATCH`)
- Test: `tests/test_tools_registry.py`

**Contexto**: el helper `def delete_task(task_id: int) -> dict` ya existe (línea ~1207) pero no está en `TOOL_DEFINITIONS` ni en `_DISPATCH`. Solo hay que enchufarlo.

- [ ] **Step 1: Escribe el test que falla en `tests/test_tools_registry.py`**

Añade al final del archivo:

```python
def test_delete_task_registered():
    names = [t["name"] for t in tools.TOOL_DEFINITIONS]
    assert "delete_task" in names


def test_delete_task_dispatches_to_helper(monkeypatch):
    called = {}
    def fake(task_id):
        called["id"] = task_id
        return {"id": task_id, "deleted": 1}
    monkeypatch.setattr(tools, "delete_task", fake)
    result = tools.dispatch("delete_task", {"task_id": 42})
    assert called["id"] == 42
    assert result["deleted"] == 1
```

- [ ] **Step 2: Verifica que falla**

```bash
./.venv/bin/python -m pytest tests/test_tools_registry.py::test_delete_task_registered -v
```

Esperado: FAIL con `assert "delete_task" in names`.

- [ ] **Step 3: Registra `delete_task` en `TOOL_DEFINITIONS`**

Localiza la entrada de `complete_task` en `tools.py` y añade INMEDIATAMENTE DEBAJO de ella:

```python
    {
        "name": "delete_task",
        "description": (
            "Borra una tarea por su id. Confirmar con el usuario antes "
            "mostrando el texto a borrar."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"task_id": {"type": "integer"}},
            "required": ["task_id"],
        },
    },
```

Y en `_DISPATCH` (diccionario al final del archivo), añade:

```python
    "delete_task": delete_task,
```

- [ ] **Step 4: Verifica que pasa**

```bash
./.venv/bin/python -m pytest tests/test_tools_registry.py -v
```

Esperado: PASS (los dos nuevos + los previos siguen verdes).

- [ ] **Step 5: Commit**

```bash
git add tools.py tests/test_tools_registry.py
git commit -m "feat(tools): expone delete_task a Claude

Helper ya existía como uso interno (botón 🗑️ de /pendientes).
Tras esto Pablo puede pedir 'borra la tarea de X' por chat.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Helper y tool `delete_objective`

**Files:**
- Modify: `tools.py` (añadir función + entrada `TOOL_DEFINITIONS` + `_DISPATCH`)
- Test: `tests/test_tools_objectives.py`, `tests/test_tools_registry.py`

- [ ] **Step 1: Escribe los tests que fallan**

Al final de `tests/test_tools_objectives.py`:

```python
def test_delete_objective_existing():
    o = tools.add_objective("Leer 2 libros", "2026-06-08")
    result = tools.delete_objective(o["id"])
    assert result["deleted"] == 1
    assert tools.query_objectives(None) == []


def test_delete_objective_not_found():
    result = tools.delete_objective(99999)
    assert result["deleted"] == 0
```

Al final de `tests/test_tools_registry.py`:

```python
def test_delete_objective_registered():
    names = [t["name"] for t in tools.TOOL_DEFINITIONS]
    assert "delete_objective" in names
```

- [ ] **Step 2: Verifica que fallan**

```bash
./.venv/bin/python -m pytest tests/test_tools_objectives.py::test_delete_objective_existing tests/test_tools_objectives.py::test_delete_objective_not_found tests/test_tools_registry.py::test_delete_objective_registered -v
```

Esperado: 3 FAIL (AttributeError o assertion error).

- [ ] **Step 3: Implementa el helper en `tools.py`**

Localiza la función `mark_objective_done` y añade INMEDIATAMENTE DEBAJO:

```python
def delete_objective(objective_id: int) -> dict:
    """Borra un objetivo por id. No revierte XP de objetivos ya completados:
    si fueron marcados hechos, ese XP queda en el log (igual que ocurre con
    delete_task cuando hay tareas completadas)."""
    with db.connect() as conn:
        cur = conn.execute(
            "DELETE FROM objectives WHERE id = ?", (objective_id,)
        )
    return {"id": objective_id, "deleted": cur.rowcount}
```

- [ ] **Step 4: Registra en `TOOL_DEFINITIONS`**

Localiza la entrada de `mark_objective_done` en `TOOL_DEFINITIONS` y añade DEBAJO:

```python
    {
        "name": "delete_objective",
        "description": (
            "Borra un objetivo semanal por su id. Confirmar con el usuario "
            "antes mostrando el texto a borrar."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"objective_id": {"type": "integer"}},
            "required": ["objective_id"],
        },
    },
```

Y en `_DISPATCH`:

```python
    "delete_objective": delete_objective,
```

- [ ] **Step 5: Verifica que pasan**

```bash
./.venv/bin/python -m pytest tests/test_tools_objectives.py tests/test_tools_registry.py -v
```

Esperado: PASS.

- [ ] **Step 6: Commit**

```bash
git add tools.py tests/test_tools_objectives.py tests/test_tools_registry.py
git commit -m "feat(tools): delete_objective + expone a Claude

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Helper y tool `update_task`

**Files:**
- Modify: `tools.py`
- Test: `tests/test_tools_tasks.py`, `tests/test_tools_registry.py`

**Patrón**: copia el de `update_event(event_id, fields)` — recibe un dict; campos ausentes no se tocan; campos presentes con valor null borran (solo aplica a `due_date`).

- [ ] **Step 1: Escribe los tests que fallan**

Al final de `tests/test_tools_tasks.py`:

```python
def test_update_task_text_only():
    t = tools.add_task("Comprar pan", due_date="2026-06-10")
    result = tools.update_task(t["id"], {"text": "Comprar pan integral"})
    assert result["updated"] == 1
    rows = tools.list_tasks()
    row = next(r for r in rows if r["id"] == t["id"])
    assert row["text"] == "Comprar pan integral"
    assert row["due_date"] == "2026-06-10"  # intacta


def test_update_task_due_date_to_value():
    t = tools.add_task("Comprar pan")
    result = tools.update_task(t["id"], {"due_date": "2026-06-15"})
    assert result["updated"] == 1
    rows = tools.list_tasks()
    row = next(r for r in rows if r["id"] == t["id"])
    assert row["due_date"] == "2026-06-15"


def test_update_task_due_date_to_null_clears_date():
    t = tools.add_task("Comprar pan", due_date="2026-06-10")
    result = tools.update_task(t["id"], {"due_date": None})
    assert result["updated"] == 1
    rows = tools.list_tasks()
    row = next(r for r in rows if r["id"] == t["id"])
    assert row["due_date"] is None


def test_update_task_empty_fields_is_noop():
    t = tools.add_task("Comprar pan", due_date="2026-06-10")
    result = tools.update_task(t["id"], {})
    assert result["updated"] == 0
    rows = tools.list_tasks()
    row = next(r for r in rows if r["id"] == t["id"])
    assert row["text"] == "Comprar pan"
    assert row["due_date"] == "2026-06-10"


def test_update_task_not_found():
    result = tools.update_task(99999, {"text": "X"})
    assert result["updated"] == 0


def test_update_task_invalid_field_raises():
    t = tools.add_task("Comprar pan")
    import pytest
    with pytest.raises(ValueError):
        tools.update_task(t["id"], {"done": 1})
```

Al final de `tests/test_tools_registry.py`:

```python
def test_update_task_registered():
    names = [t["name"] for t in tools.TOOL_DEFINITIONS]
    assert "update_task" in names
```

- [ ] **Step 2: Verifica que fallan**

```bash
./.venv/bin/python -m pytest tests/test_tools_tasks.py -k "update_task" tests/test_tools_registry.py::test_update_task_registered -v
```

Esperado: 7 FAIL.

- [ ] **Step 3: Implementa el helper en `tools.py`**

Localiza `delete_task` y añade INMEDIATAMENTE ARRIBA (justo después de `complete_task`):

```python
def update_task(task_id: int, fields: dict) -> dict:
    """Actualiza campos parciales de una tarea. Patrón coherente con
    update_event: las claves ausentes no se tocan; due_date=None borra
    la fecha (la deja sin fecha)."""
    allowed = {"text", "due_date"}
    sets = []
    params: list = []
    for key, value in fields.items():
        if key not in allowed:
            raise ValueError(f"campo no actualizable: {key}")
        sets.append(f"{key} = ?")
        params.append(value)
    if not sets:
        return {"id": task_id, "updated": 0}
    params.append(task_id)
    with db.connect() as conn:
        cur = conn.execute(
            f"UPDATE tasks SET {', '.join(sets)} WHERE id = ?", params
        )
    return {"id": task_id, "updated": cur.rowcount}
```

- [ ] **Step 4: Registra en `TOOL_DEFINITIONS` y `_DISPATCH`**

En `TOOL_DEFINITIONS`, añade DEBAJO de la entrada de `add_task`:

```python
    {
        "name": "update_task",
        "description": (
            "Modifica campos de una tarea. fields={text?, due_date?}. "
            "Solo incluye en fields las claves que cambien. "
            "due_date=null quita la fecha; omítela para no tocarla."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer"},
                "fields": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "due_date": {"type": ["string", "null"]},
                    },
                },
            },
            "required": ["task_id", "fields"],
        },
    },
```

Y en `_DISPATCH`:

```python
    "update_task": update_task,
```

- [ ] **Step 5: Verifica que pasan**

```bash
./.venv/bin/python -m pytest tests/test_tools_tasks.py tests/test_tools_registry.py -v
```

Esperado: PASS.

- [ ] **Step 6: Commit**

```bash
git add tools.py tests/test_tools_tasks.py tests/test_tools_registry.py
git commit -m "feat(tools): update_task + expone a Claude

Patrón coherente con update_event: dict fields parcial; due_date=null
borra la fecha, ausente no toca.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Helper y tool `update_objective`

**Files:**
- Modify: `tools.py`
- Test: `tests/test_tools_objectives.py`, `tests/test_tools_registry.py`

- [ ] **Step 1: Escribe los tests que fallan**

Al final de `tests/test_tools_objectives.py`:

```python
def test_update_objective_text_only():
    o = tools.add_objective("Leer 2 libros", "2026-06-08")
    result = tools.update_objective(o["id"], {"text": "Leer 3 libros"})
    assert result["updated"] == 1
    rows = tools.query_objectives(None)
    row = next(r for r in rows if r["id"] == o["id"])
    assert row["text"] == "Leer 3 libros"
    assert row["week_start"] == "2026-06-08"  # intacto (es lunes)


def test_update_objective_week_start_normalizes_to_monday():
    o = tools.add_objective("Meditar", "2026-06-08")  # lunes
    # mueve a un miércoles → debe normalizar a su lunes (2026-06-15)
    result = tools.update_objective(o["id"], {"week_start": "2026-06-17"})
    assert result["updated"] == 1
    rows = tools.query_objectives(None)
    row = next(r for r in rows if r["id"] == o["id"])
    assert row["week_start"] == "2026-06-15"


def test_update_objective_empty_fields_is_noop():
    o = tools.add_objective("Meditar", "2026-06-08")
    result = tools.update_objective(o["id"], {})
    assert result["updated"] == 0


def test_update_objective_not_found():
    result = tools.update_objective(99999, {"text": "X"})
    assert result["updated"] == 0


def test_update_objective_invalid_field_raises():
    o = tools.add_objective("Meditar", "2026-06-08")
    import pytest
    with pytest.raises(ValueError):
        tools.update_objective(o["id"], {"done": 1})
```

Al final de `tests/test_tools_registry.py`:

```python
def test_update_objective_registered():
    names = [t["name"] for t in tools.TOOL_DEFINITIONS]
    assert "update_objective" in names
```

- [ ] **Step 2: Verifica que fallan**

```bash
./.venv/bin/python -m pytest tests/test_tools_objectives.py -k "update_objective" tests/test_tools_registry.py::test_update_objective_registered -v
```

Esperado: 6 FAIL.

- [ ] **Step 3: Implementa el helper en `tools.py`**

Localiza `delete_objective` (creado en Task 2) y añade INMEDIATAMENTE ARRIBA:

```python
def update_objective(objective_id: int, fields: dict) -> dict:
    """Actualiza campos parciales de un objetivo. week_start se normaliza
    al lunes de la semana indicada (igual que add_objective)."""
    from date_utils import monday_of_week
    allowed = {"text", "week_start"}
    sets = []
    params: list = []
    for key, value in fields.items():
        if key not in allowed:
            raise ValueError(f"campo no actualizable: {key}")
        if key == "week_start":
            parsed = date.fromisoformat(value)
            value = monday_of_week(parsed).isoformat()
        sets.append(f"{key} = ?")
        params.append(value)
    if not sets:
        return {"id": objective_id, "updated": 0}
    params.append(objective_id)
    with db.connect() as conn:
        cur = conn.execute(
            f"UPDATE objectives SET {', '.join(sets)} WHERE id = ?", params
        )
    return {"id": objective_id, "updated": cur.rowcount}
```

- [ ] **Step 4: Registra en `TOOL_DEFINITIONS` y `_DISPATCH`**

En `TOOL_DEFINITIONS`, añade DEBAJO de la entrada de `add_objective`:

```python
    {
        "name": "update_objective",
        "description": (
            "Modifica campos de un objetivo. fields={text?, week_start?}. "
            "Solo incluye las claves que cambien. week_start se normaliza al "
            "lunes de esa semana."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "objective_id": {"type": "integer"},
                "fields": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "week_start": {"type": "string"},
                    },
                },
            },
            "required": ["objective_id", "fields"],
        },
    },
```

Y en `_DISPATCH`:

```python
    "update_objective": update_objective,
```

- [ ] **Step 5: Verifica que pasan**

```bash
./.venv/bin/python -m pytest tests/test_tools_objectives.py tests/test_tools_registry.py -v
```

Esperado: PASS.

- [ ] **Step 6: Commit**

```bash
git add tools.py tests/test_tools_objectives.py tests/test_tools_registry.py
git commit -m "feat(tools): update_objective + expone a Claude

week_start se normaliza a lunes igual que add_objective.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Reglas nuevas en el system prompt

**Files:**
- Modify: `brain.py` (sección de reglas en `_system_prompt`)
- Test: `tests/test_brain.py`

**Objetivo**: que Claude sepa cómo identificar, confirmar y ejecutar borrados/ediciones de tareas y objetivos. Texto conciso (~6 líneas) para no inflar tokens.

- [ ] **Step 1: Escribe el test que falla**

Al final de `tests/test_brain.py`:

```python
def test_system_prompt_mentions_delete_task_and_objective():
    prompt = brain._system_prompt()
    assert "delete_task" in prompt
    assert "delete_objective" in prompt


def test_system_prompt_mentions_update_task_and_objective():
    prompt = brain._system_prompt()
    assert "update_task" in prompt
    assert "update_objective" in prompt


def test_system_prompt_mentions_semana_que_viene_mapping():
    """Claude tiene que saber traducir 'la que viene' → próximo lunes."""
    prompt = brain._system_prompt().lower()
    assert "la que viene" in prompt or "próxima semana" in prompt
```

- [ ] **Step 2: Verifica que fallan**

```bash
./.venv/bin/python -m pytest tests/test_brain.py -k "system_prompt_mentions" -v
```

Esperado: 3 FAIL.

- [ ] **Step 3: Añade las reglas al system prompt**

En `brain.py`, dentro de `_system_prompt`, localiza la línea que dice:

```
- Si pregunta "¿qué tengo hoy?", consulta TANTO eventos del día COMO tareas pendientes. Muestra ambas listas si hay algo en cada una.
```

INMEDIATAMENTE DESPUÉS de esa línea (manteniendo la indentación y el formato del bloque), añade:

```
- **Borrar tareas u objetivos**: si el usuario dice "borra la tarea/el objetivo de X", lista primero (list_tasks o query_objectives), identifica el id por coincidencia de texto, confirma con UNA frase ("¿Borro 'X'?") y SOLO ejecuta `delete_task`/`delete_objective` tras confirmación explícita. No revierte XP.
- **Editar tareas u objetivos**: "cambia/edita/mueve la tarea/objetivo de X": lista, identifica id, llama a `update_task(task_id, fields)` o `update_objective(objective_id, fields)` con SOLO los campos que cambian. Para mover de semana un objetivo: "esta semana" = lunes actual, "la que viene"/"próxima semana" = lunes próximo, "la pasada" = lunes anterior. Para `update_task` con `due_date`: omítelo si no cambia; pásalo como `null` solo si el usuario pide quitarle la fecha.
```

- [ ] **Step 4: Verifica que pasan**

```bash
./.venv/bin/python -m pytest tests/test_brain.py -v
```

Esperado: PASS (los nuevos + los previos siguen verdes).

- [ ] **Step 5: Commit**

```bash
git add brain.py tests/test_brain.py
git commit -m "feat(brain): reglas para borrar/editar tareas y objetivos

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Suite completa + smoke test de tamaño

**Files:**
- (sin cambios de código)

- [ ] **Step 1: Suite completa pasa**

```bash
./.venv/bin/python -m pytest
```

Esperado: 438 + ~15 nuevos = ~453 tests, todos verdes.

- [ ] **Step 2: Verifica el tamaño del system prompt y tools**

```bash
SIRI_TOKEN=x TELEGRAM_TOKEN=x ANTHROPIC_API_KEY=x ALLOWED_USER_ID=1 ./.venv/bin/python -c "
import brain, tools, json
sp = brain._system_prompt()
td = json.dumps(tools.TOOL_DEFINITIONS)
print('system prompt chars:', len(sp))
print('tools JSON chars:', len(td))
print('TOTAL chars:', len(sp)+len(td))
print('num tools:', len(tools.TOOL_DEFINITIONS))
"
```

Esperado: 20 tools (era 16 + 4 nuevas). Total chars bajo 20.000 (objetivo).

Si supera 22.000 chars, parar y avisar a Pablo (puede empujarnos al límite ITPM con más frecuencia).

---

## Task 7: Deploy y verificación manual

**Files:**
- (sin cambios de código)

- [ ] **Step 1: Deploy**

```bash
flyctl deploy --app mi-secretaria-pablo
```

Esperado: deploy OK, machine arranca, no hay tracebacks en `flyctl logs --app mi-secretaria-pablo --no-tail | head -50`.

- [ ] **Step 2: Pedir a Pablo los siguientes test cases manuales**

Por Telegram, en orden:

1. "apunta tarea: comprar pan" → bot añade. Anota el texto exacto.
2. "borra la tarea de comprar pan" → bot debe pedir confirmación → respondes "sí" → confirma borrado → `/pendientes` ya no la muestra.
3. "apunta tarea: comprar pan integral" → añade.
4. "cambia comprar pan integral por comprar pan de espelta" → cambia texto sin pedir fecha.
5. "mueve la tarea de comprar pan de espelta a mañana" → due_date = mañana.
6. "apunta objetivo de esta semana: leer 2 libros".
7. "borra el objetivo de leer 2 libros" → confirma → borra. `/objetivos` ya no lo muestra.
8. "apunta objetivo: meditar 10 min" → añade en esta semana.
9. "mueve el objetivo de meditar a la semana que viene" → cambia week_start al próximo lunes.

- [ ] **Step 3: Reportar a Pablo el resultado** del paso 2 y cerrar la tarea.

---

## Notas finales

- **No tocar XP retroactivamente**: si Pablo borra un objetivo o tarea que ya estaba marcada hecha, NO se le retira el XP. El historial XP es append-only para preservar coherencia del nivel.
- **Conflictos de nombre**: si Pablo tiene dos tareas con texto parecido ("comprar pan" y "comprar pan integral"), Claude debe preguntar cuál antes de borrar. Esto ya está cubierto por la regla genérica del prompt ("confirma antes de borrar") más la nueva regla específica.
- **Compatibilidad**: los botones existentes en `/pendientes`, `/duplicados` y `/objetivos` siguen funcionando idénticos — no se toca ningún callback.

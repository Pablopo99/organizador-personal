# Editar y borrar tareas/objetivos por chat — Design Spec

- Fecha: 2026-06-08
- Estado: aprobado por Pablo (brainstorming 2026-06-08)
- Spec previa relacionada: ninguna directa; complementa el conjunto de tools de gestión

## Problema

Hoy, desde el chat libre con Claude, Pablo puede:

- Para **eventos/rutinas**: añadir, modificar (`update_event`), borrar (`delete_event`), marcar hecho.
- Para **tareas**: solo añadir, listar y completar. Borrar exige ir a `/pendientes` y pulsar 🗑️. Editar el texto no es posible por ningún canal.
- Para **objetivos semanales**: solo añadir, listar y marcar hecho. Ni borrar ni editar.

Pablo lo probó y le frustró el hueco. Es un gap importante en la simetría de UX: el chat debería ser canal completo para los cuatro tipos (eventos, rutinas, tareas, objetivos).

## Objetivos

- Pablo puede pedir por chat: «borra la tarea de comprar pan» → Claude lista, confirma, ejecuta.
- Pablo puede pedir: «cambia comprar pan por comprar pan integral» → Claude actualiza texto sin borrar.
- Pablo puede pedir: «mueve la tarea de comprar pan a mañana» → Claude actualiza `due_date`.
- Pablo puede pedir: «borra el objetivo de leer 2 libros» → confirma y borra.
- Pablo puede pedir: «mueve el objetivo de meditar a la semana que viene» → Claude actualiza `week_start`.
- Misma semántica de confirmación previa que ya tiene `delete_event` (regla genérica del system prompt).

## No-objetivos

- **No** revertir XP al borrar items completados. Borrar = quitar de las listas, no rebobinar la historia. El XP ya ganado se queda; lo coherente con cómo se comporta hoy el botón 🗑️ de `/pendientes`.
- **No** añadir botones inline de editar (`✏️`) en `/pendientes` ni `/objetivos`. Editar por chat es suficiente; botones de editar son complicación de UI que puede venir después.
- **No** tocar rutinas: ya tienen `update_event` y `delete_event` expuestos.
- **No** rediseñar el flujo de duplicados ni cómo Claude busca por texto fuzzy; reusa el mismo patrón que con eventos (lista, encuentra, confirma).

## Modelo de datos

Sin cambios. Las tablas `tasks` y `objectives` ya soportan UPDATE y DELETE; solo hace falta exponer las operaciones.

## Tools

### Nuevas en `tools.py`

#### `delete_task(task_id: int) -> dict`

Ya existe como helper interno (línea 1207, usado por el botón 🗑️). Solo hay que añadirlo a `TOOL_DEFINITIONS`. Comportamiento intacto:

- Borra la fila por id.
- Retorna `{"ok": True, "deleted_id": id}` o `{"error": "not_found"}` si no existe.
- No reverte XP.

#### `delete_objective(objective_id: int) -> dict` (nueva)

```python
def delete_objective(objective_id: int) -> dict:
    with db.connect() as conn:
        row = conn.execute("SELECT id FROM objectives WHERE id = ?", (objective_id,)).fetchone()
        if row is None:
            return {"error": "not_found"}
        conn.execute("DELETE FROM objectives WHERE id = ?", (objective_id,))
    return {"ok": True, "deleted_id": objective_id}
```

#### `update_task(task_id: int, text: str | None = None, due_date: str | None = "__UNCHANGED__") -> dict` (nueva)

Centinela `"__UNCHANGED__"` para distinguir «no toques due_date» de «pon due_date = null (sin fecha)». Esto es el patrón estándar para campos nulables en updates parciales.

- `text=None` → no toca el campo. `text="..."` → actualiza.
- `due_date="__UNCHANGED__"` (default) → no toca. `due_date=None` → la deja sin fecha. `due_date="YYYY-MM-DD"` → actualiza.
- Retorna `{"ok": True, "id": id, "text": new_text, "due_date": new_due_date}` o `{"error": "not_found"}`.
- Valida formato de `due_date` igual que `add_task`.

#### `update_objective(objective_id: int, text: str | None = None, week_start: str | None = None) -> dict` (nueva)

- `text=None` → no toca. `text="..."` → actualiza.
- `week_start=None` → no toca. `week_start="YYYY-MM-DD"` → normaliza al lunes de esa semana (igual que `add_objective`) y actualiza.
- Retorna `{"ok": True, "id": id, "text": new_text, "week_start": new_week_start}` o `{"error": "not_found"}`.
- `week_start` no se puede poner a null (todo objetivo pertenece a una semana).

### Registro en `TOOL_DEFINITIONS`

Añadir 4 entradas a la lista (en `tools.py`), con descripciones cortas para no inflar tokens innecesariamente. Total estimado: ~1.5-2k chars adicionales (~500 tokens).

## System prompt — reglas nuevas

Añadir al bloque «Distinción de tipos» o cercano. Texto propuesto (conciso para no engordar el prompt):

> **Borrar tareas u objetivos**: si Pablo dice «borra la tarea de X» o «borra el objetivo de Y», primero lista (`list_tasks` / `query_objectives`), encuentra el id por coincidencia de texto, confirma con UNA frase ("¿Borro 'X'?") y SOLO ejecuta tras "sí". Usa `delete_task` o `delete_objective`. No revierte XP.
>
> **Editar tareas u objetivos**: «cambia/edita/mueve la tarea/objetivo de X»: lista, identifica id, llama a `update_task(text=..., due_date=...)` o `update_objective(text=..., week_start=...)` con SOLO los campos que cambian. Para mover de semana: «esta semana»=lunes actual, «la que viene»=lunes próximo, «la pasada»=lunes anterior. Confirma con frase corta tras ejecutar.

## Bot — sin cambios

La integración va por la ruta normal de tool use en `brain.py`. No hace falta tocar `bot.py` ni callbacks: las nuevas tools son llamadas por Claude desde el flujo libre de texto.

## Tests

### `tests/test_tools_tasks.py` — añadir

- `test_delete_task_existing` — crea, borra, comprueba que `list_tasks` ya no la devuelve.
- `test_delete_task_not_found` — id inexistente → `{"error": "not_found"}`.
- `test_update_task_text_only` — cambia texto, `due_date` queda intacto.
- `test_update_task_due_date_to_value` — cambia fecha.
- `test_update_task_due_date_to_null` — pasa `due_date=None` explícito (centinela) → fila queda sin fecha.
- `test_update_task_no_op_keeps_due_date` — no pasar `due_date` (centinela default) → fecha previa intacta.
- `test_update_task_not_found` — id inexistente → error.
- `test_update_task_invalid_date_format` — `"mañana"` no válido → error.

### `tests/test_tools_objectives.py` — añadir

- `test_delete_objective_existing` — crea, borra, comprueba.
- `test_delete_objective_not_found` — error.
- `test_update_objective_text_only` — texto cambia, semana intacta.
- `test_update_objective_week_start_normalizes_to_monday` — pasar miércoles → guardado como lunes.
- `test_update_objective_not_found` — error.

### `tests/test_tools_registry.py` — añadir

- `test_delete_task_in_tool_definitions` — name está registrado.
- `test_delete_objective_in_tool_definitions` — name está registrado.
- `test_update_task_in_tool_definitions` — name está registrado.
- `test_update_objective_in_tool_definitions` — name está registrado.
- `test_all_four_dispatch_correctly` — `tools.dispatch("delete_task", {...})` etc. ejecuta el helper correcto.

## Migración y compatibilidad

Ninguna. Sin cambios de schema. Sin breaking changes en tools existentes. El sistema previo (botón 🗑️ que usa `delete_task`) sigue funcionando idéntico.

## Riesgos y consideraciones

1. **Coste de tokens**: ~500 tokens más por llamada Claude (system+tools). Tier 1 = 30k ITPM. Antes del cambio cada llamada gasta ~9-10k; tras el cambio ~10-10.5k. Aún margen, pero más cerca del techo. Si vemos un repunte de 429 tras el deploy, plan de reducción del system prompt (varias secciones de plantilla de resúmenes que ya no aplican porque los slash son deterministas).
2. **Confusión Claude/usuario al identificar item**: Pablo puede tener varios objetivos parecidos («leer 2 libros», «leer 30 min al día»). Si Claude no está seguro, debe preguntar antes de borrar, no adivinar. La regla del system prompt («confirma antes») cubre esto, pero conviene un test manual post-deploy.
3. **`due_date=null` accidental**: si Claude pasa `due_date=None` cuando Pablo no pidió quitar fecha, la tarea pierde su fecha silenciosamente. Mitigado por el patrón del centinela: el default NO toca el campo. Claude solo manda `due_date` explícito si Pablo dice «sin fecha» o una fecha nueva.

## Métrica de éxito

Post-deploy, verificar manualmente con un mensaje real:

- «borra la tarea de comprar pan» → confirma, borra, desaparece de `/pendientes`.
- «cambia comprar pan por comprar pan integral» → texto cambia, fecha intacta.
- «mueve la tarea de comprar pan a mañana» → due_date actualizado.
- «borra el objetivo de leer 2 libros» → confirma, borra, desaparece de `/objetivos`.
- «mueve el objetivo X a la semana que viene» → `week_start` saltó al próximo lunes.
- Suite de tests completa en verde tras los nuevos casos.

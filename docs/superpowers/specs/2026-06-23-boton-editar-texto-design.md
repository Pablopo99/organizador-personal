# Botón ✏️ para editar texto (tareas y objetivos) — Design Spec

- Fecha: 2026-06-23
- Estado: aprobado por Pablo (brainstorming 2026-06-23)
- Spec previa relacionada: 2026-06-08-editar-borrar-tareas-objetivos-design.md (creó update_task/update_objective)

## Problema

`update_task` y `update_objective` ya existen y funcionan por chat ("cambia X por Y"),
pero requieren escribir la frase completa e identificar el item por texto. Pablo quiere
editar el texto de una tarea/objetivo con un toque desde `/pendientes` y `/objetivos`,
igual que ya marca/desmarca con botón.

## Objetivos

- En `/pendientes`, cada tarea pendiente muestra `[🔲 texto] [✏️]`.
- En `/objetivos`, cada objetivo pendiente muestra `[🔲 texto] [✏️]`.
- Al pulsar ✏️: el bot pide el nuevo texto; el siguiente mensaje lo aplica vía
  `update_task`/`update_objective(fields={"text": ...})`.
- `/cancelar` (o cualquier comando) anula el modo edición.

## No-objetivos

- **Solo texto.** Cambiar `due_date` de tarea o `week_start` de objetivo se sigue
  haciendo por chat. Añadir eso al botón multiplicaría los estados.
- **No editar eventos por botón** (tienen fecha/hora/categoría/notas; demasiado para
  un flujo de un solo campo). Se siguen editando por chat.
- **No editar items ya completados** (en `/objetivos` la sección 🏆 COMPLETADO no
  lleva ✏️).
- **No re-render automático** tras editar: el bot confirma con texto y el usuario
  re-pulsa el comando para ver la lista. Mantiene `_on_message` sin tocar.

## Arquitectura

### Estado en memoria (bot.py)

```python
# user_id → {"kind": "task"|"objective", "id": int}
_pending_edit: dict[int, dict] = {}

def _set_pending_edit(user_id, kind, item_id): ...
def _pop_pending_edit(user_id): ...   # devuelve y elimina, None si no hay
def _peek_pending_edit(user_id): ...  # consulta sin eliminar
```

Se pierde al reiniciar el bot (igual que `_history` y `_undo_store`). Aceptable: la
edición es inmediata.

### Botones en las vistas (views.py)

`render_pending_view` y `render_objectives_view`: cada fila de item pendiente pasa de
una columna a dos:

```python
buttons.append([
    InlineKeyboardButton(f"🔲 {t['text']}", callback_data=f"mT:{t['id']}:P"),
    InlineKeyboardButton("✏️", callback_data=f"eT:{t['id']}:P"),
])
```

Para objetivos: `mO`/`eO` con view `O`. Los objetivos en 🏆 COMPLETADO (acción `uO`)
NO llevan ✏️.

Códigos de callback nuevos: `eT` (editar tarea), `eO` (editar objetivo). Libres (no
colisionan con mE/uE/mR/uR/mT/uT/mO/uO/xT/xE/tg/gc/rE/rT/rO/dE/dT/dO/zD).

### Callback al pulsar ✏️ (bot._on_callback_query)

Caso especial `eT`/`eO`, manejado como early-return (igual estilo que `gc`/`zD`),
ANTES del handler genérico:

1. Lee el texto actual del item (para mostrarlo en el prompt).
2. `_set_pending_edit(user_id, kind, item_id)`.
3. `query.edit_message_text` o `answer`: deja la lista visible y manda un mensaje
   nuevo: «✏️ Escríbeme el nuevo texto para «{texto}» (o /cancelar).»
   - Mejor un mensaje nuevo (no editar la lista) para no perder los botones.
4. Si el item ya no existe → answer "Ese item ya no existe" y no entra en modo edición.

### Intercepción del texto (bot.process_incoming)

Al inicio de `process_incoming`, tras el check de autorización y ANTES de
`_RESET_COMMANDS`/slash/brain:

```python
pending = _peek_pending_edit(from_user_id)
if pending is not None:
    cleaned = text.strip()
    if cleaned.lower() == "/cancelar":
        _pop_pending_edit(from_user_id)
        return "Edición cancelada."
    if cleaned.startswith("/"):
        # Un comando: cancela el modo y deja que el flujo normal lo trate.
        _pop_pending_edit(from_user_id)
        # cae al procesamiento normal de abajo
    elif not cleaned:
        return "Dame el nuevo texto, o /cancelar."
    else:
        _pop_pending_edit(from_user_id)
        kind = pending["kind"]
        if kind == "task":
            res = tools.update_task(pending["id"], {"text": cleaned})
        else:
            res = tools.update_objective(pending["id"], {"text": cleaned})
        if res.get("updated"):
            return f"✅ Cambiado a «{cleaned}»."
        return "Ese item ya no existe (¿lo borraste?)."
```

Nota: `cleaned.startswith("/")` cubre `/cancelar` ya tratado arriba y cualquier slash
que llegue a `process_incoming` (los slash no registrados, p. ej. typos). Los slash
REGISTRADOS (`/hoy`, `/pendientes`, …) no pasan por `process_incoming` — van a su
`CommandHandler`. Para que esos también cancelen el modo, ver siguiente sección.

### Cancelar al usar un comando registrado (bot.main)

Los comandos registrados (`/hoy`, etc.) van a su `CommandHandler`, no a
`process_incoming`. Para que cancelen el modo edición sin tocar cada handler, se añade
UN handler en grupo -1 (se ejecuta antes, no consume el update):

```python
app.add_handler(MessageHandler(filters.COMMAND, _cancel_edit_on_command), group=-1)

async def _cancel_edit_on_command(update, context):
    uid = update.effective_user.id if update.effective_user else None
    if uid is not None:
        _pop_pending_edit(uid)
    # no return especial: el update sigue a los handlers de grupo 0
```

Esto NO modifica ningún handler existente; solo añade uno nuevo de limpieza.

## Manejo de errores

- Item borrado mientras editabas → `update_*` devuelve `updated=0` → mensaje claro.
- Texto vacío → se pide de nuevo, sin salir del modo.
- HTML en el texto: la confirmación usa «...» con texto plano (no parse HTML del
  contenido del usuario); si se manda con parse_mode HTML, escapar con `html.escape`.

## Tests

### tests/test_bot.py
- `test_pending_edit_store_set_peek_pop` — set/peek/pop del estado.
- `test_pop_pending_edit_unknown_user_returns_none`.
- `test_process_incoming_applies_text_edit_to_task` — con pending_edit task, un
  mensaje normal actualiza el texto y confirma.
- `test_process_incoming_applies_text_edit_to_objective`.
- `test_process_incoming_edit_cancelar_aborts` — "/cancelar" cancela, no actualiza.
- `test_process_incoming_edit_slash_command_aborts_and_falls_through` — un slash
  (p. ej. "/nueva") en modo edición cancela el modo (no se usa como texto).
- `test_process_incoming_edit_empty_text_keeps_mode` — texto vacío mantiene el modo.
- `test_process_incoming_edit_deleted_item_graceful` — item borrado → mensaje claro.
- `test_process_incoming_no_pending_edit_goes_to_brain` — sin pending, flujo normal
  intacto (regresión: NO se intercepta nada).
- `test_callback_eT_enters_edit_mode` (async) — pulsar ✏️ guarda estado y manda
  mensaje pidiendo texto.
- `test_callback_eO_enters_edit_mode` (async).
- `test_callback_eT_missing_item_no_edit_mode` (async) — item inexistente no entra
  en modo.
- `test_cancel_edit_on_command_clears_state` (async) — el handler grupo -1 limpia.

### tests/test_views.py
- `test_pending_view_has_edit_button` — cada fila pendiente tiene un `eT:*` además
  del `mT:*`.
- `test_objectives_view_pending_has_edit_button` — objetivos pendientes con `eO:*`.
- `test_objectives_view_completed_has_no_edit_button` — los 🏆 COMPLETADO (uO) NO
  llevan `eO`.

### Regresión (lo que NO debe cambiar)
- Los callbacks mT/uT/mO/uO siguen funcionando (tests existentes verdes).
- `/nueva` sigue reseteando (no lo absorbe el modo edición porque empieza por "/").
- process_incoming sin pending_edit manda a brain como siempre.

## Migración y compatibilidad

Ninguna. Sin cambios de schema. Reusa `update_task`/`update_objective` existentes.
El handler grupo -1 es aditivo.

## Riesgos

1. **Mensaje no intencionado interpretado como edición**: si pulsas ✏️ y escribes
   otra cosa, se toma como nuevo texto. Mitigado: aviso claro + `/cancelar` +
   cualquier comando cancela. Bot de un usuario → asumible.
2. **Estado en memoria perdido al reiniciar**: si el bot reinicia entre ✏️ y tu
   texto, el modo se pierde y tu mensaje va a la IA. Raro y sin daño (la IA
   responderá normal). Aceptable.

## Métrica de éxito

Post-deploy, manual:
- /pendientes → ✏️ en una tarea → escribir nuevo texto → confirma → /pendientes
  muestra el texto nuevo.
- /objetivos → ✏️ → nuevo texto → confirma.
- ✏️ y luego /cancelar → "Edición cancelada", texto intacto.
- ✏️ y luego /hoy → /hoy se muestra y el modo se cancela (escribir después va a la IA
  normal).
- Suite completa verde.

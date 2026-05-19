# Botones inline en /pendientes y /semana — Diseño

**Fecha:** 2026-05-19
**Estado:** Diseño aprobado, pendiente de plan de implementación
**Sigue a:** marcado rápido en /hoy (2026-05-19-marcado-rapido-design.md)

## Objetivo

Extender el feature de botones inline (introducido esta tarde en `/hoy` y saludo matutino) a los comandos `/pendientes` y `/semana`. La motivación es la misma: eliminar la fricción de tener que escribir *"completa la tarea X"* o *"marca el objetivo Y"* cada vez.

## Decisiones clave

- **`/pendientes`**: botón `🔲` en cada tarea pendiente. Tap → tarea marcada como hecha. Re-renderiza el mensaje (la tarea desaparece de la lista). No se muestran tareas ya hechas en esta vista (consistente con el nombre y el comportamiento actual).
- **`/semana`**: botones SOLO en la sección 🎯 OBJETIVOS. Pendientes con `🔲`, hechos con `✅` (tap deshace). Eventos, rutinas y completados se mantienen como texto plano sin botones.
- **`/pendientes` y `/semana` dejan de pasar por Claude** (igual que se hizo con `/hoy` esta tarde): los genera el bot directamente. Trade-off ya validado:
  - Tap instantáneo, sin coste por edit.
  - Texto predecible, edit-in-place sin inconsistencias.
  - Se pierde la prosa variable de Claude (incluido el cierre motivador en /semana).
- **Encoding de vista en `callback_data`**: el callback necesita saber qué vista lo originó para re-renderizar correctamente. Nuevo formato `{acción}{tipo}:{id}:{vista}` con vista ∈ {H, P, W} (Hoy, Pendientes, semana=Week). El formato antiguo sin sufijo (`mE:42`) se sigue interpretando como vista H para que los mensajes ya enviados sigan funcionando tras el deploy.

## Arquitectura

```
                    ┌──────────────────────────────────────┐
                    │             bot.py                   │
                    │  /hoy        → _on_hoy ──────────────┼── render_today_view
                    │  /pendientes → _on_pendientes ──────┼── render_pending_view
                    │  /semana     → _on_semana ──────────┼── render_week_view
                    │  callback    → _on_callback_query   │       │
                    └──────────────────────────────────────┘       │
                                       │                            │
                                       ▼                            │
                            ┌──────────────────────┐                │
                            │      views.py        │ ◄──────────────┘
                            │  render_today_view   │
                            │  render_pending_view │  (new)
                            │  render_week_view    │  (new)
                            └──────────────────────┘
                                       │
                                       ▼
                            ┌──────────────────────┐
                            │      tools.py        │
                            │  + unmark_objective_done
                            └──────────────────────┘
```

**Archivos afectados:**

- **`views.py`** — dos funciones nuevas:
  - `render_pending_view(conn) -> (str, InlineKeyboardMarkup | None)`. Lista `list_tasks(include_done=False)` con un botón `🔲 {text}` por tarea. Si vacía, texto "No tienes tareas pendientes. 🎉" y keyboard None.
  - `render_week_view(today, conn) -> (str, InlineKeyboardMarkup | None)`. Construye las cuatro secciones (📅 ESTA SEMANA, 🎯 OBJETIVOS, 🔁 RUTINAS, ✅ COMPLETADO) usando `query_events`, `query_objectives`, `list_tasks`, `routine_summary`. Solo los objetivos tienen entrada en el keyboard. Si todas las secciones están vacías → "Semana tranquila 💆", keyboard None.
- **`tools.py`** — nueva función interna `unmark_objective_done(objective_id) -> dict` (no expuesta como tool). Setea `done=0`.
- **`bot.py`** —
  - Dos handlers nuevos `_on_pendientes` y `_on_semana` siguiendo el patrón de `_on_hoy`.
  - `_SLASH_PROMPTS` deja de tener entradas para `/pendientes` y `/semana` (paralelo a la eliminación de `/hoy` esta tarde).
  - `main()` registra `CommandHandler("pendientes", _on_pendientes)` y `CommandHandler("semana", _on_semana)` en lugar del bucle compartido.
  - `_on_callback_query` se extiende:
    1. Parsea opcionalmente la letra de vista al final del `callback_data`. Default `H` si ausente.
    2. Añade dos acciones nuevas al `_CALLBACK_ACTIONS`: `mO` → `tools.mark_objective_done`, `uO` → `tools.unmark_objective_done`.
    3. Tras la mutación, despacha al renderer correcto: H → `render_today_view`, P → `render_pending_view`, W → `render_week_view`.

## Formato visual

**`/pendientes`** (caso con tareas):

```
📝 <b>PENDIENTES</b>

• Solucionar Spotify
• Comprar pan
• Llamar fontanero
```

Bajo el mensaje:

```
[🔲 Solucionar Spotify]
[🔲 Comprar pan]
[🔲 Llamar fontanero]
```

`callback_data`: `mT:{id}:P`.

**`/pendientes`** (caso vacío):

```
No tienes tareas pendientes. 🎉
```

(sin botones)

**`/semana`** (estructura completa):

```
📅 <b>ESTA SEMANA</b>

• Lun 10:00 — Reunión con Marta
• Vie 17:00 — Dentista

🎯 <b>OBJETIVOS</b>

🔲 Terminar la pres de Spotify
✅ Subir 2 vídeos a YouTube

🔁 <b>RUTINAS</b>

• 50 flexiones diarias (4/7 días) 🔥 4 seguidos
• Leer 5 páginas (5/7 días)

✅ <b>COMPLETADO</b>

• <s>Lun 10:00 — Reunión con Marta</s>
• <s>Comprar pan</s>
```

Bajo el mensaje:

```
[🔲 Terminar la pres de Spotify]
[✅ Subir 2 vídeos a YouTube]
```

`callback_data` en orden: `mO:{id}:W` (pendientes), `uO:{id}:W` (hechos, para deshacer).

Si TODAS las secciones están vacías: texto "Semana tranquila 💆" y sin botones.

## Encoding de callback_data

Formato nuevo: `{acción}{tipo}:{id}:{vista}` donde:

- acción ∈ {`m` (mark), `u` (unmark)}.
- tipo ∈ {`E` (event), `R` (routine), `T` (task), `O` (objective)}.
- id es entero positivo.
- vista ∈ {`H` (hoy), `P` (pendientes), `W` (semana)}.

Ejemplos: `mT:5:P`, `uO:7:W`, `mE:42:H`.

**Compatibilidad hacia atrás**: si no hay sufijo de vista (formato antiguo `mE:42`), el handler asume vista `H`. Esto evita que los mensajes pre-deploy se rompan.

Validación en el handler: `len(data) >= 4 and ":" in data`. Mismo umbral que hoy.

## Comportamiento por comando

### `/pendientes`

1. `_on_pendientes(update, context)`:
   - Auth-gate `ALLOWED_USER_ID`.
   - `views.render_pending_view(conn)`.
   - `reply_text(text, parse_mode=HTML, reply_markup=keyboard)`.

2. Tap en `🔲 Comprar pan` (callback `mT:5:P`):
   - `_on_callback_query` parsea: acción `mT`, id `5`, vista `P`.
   - Aplica `tools.complete_task(5)`.
   - Re-renderiza vía `render_pending_view`.
   - Edita el mensaje. La tarea ha desaparecido (porque `list_tasks(include_done=False)` ya no la incluye).

3. Última tarea completada → mensaje pasa a "No tienes tareas pendientes. 🎉" sin botones.

### `/semana`

1. `_on_semana(update, context)`:
   - Auth-gate.
   - Calcula lunes/domingo de la semana en Madrid.
   - `views.render_week_view(today, conn)`.
   - `reply_text(...)`.

2. Tap en `🔲 Terminar la pres de Spotify` (callback `mO:3:W`):
   - `_on_callback_query` parsea: acción `mO`, id `3`, vista `W`.
   - Aplica `tools.mark_objective_done(3)`.
   - Re-renderiza vía `render_week_view`.
   - Edita el mensaje. El objetivo ahora muestra `✅` inline y el botón cambia a `✅ Terminar la pres de Spotify` (para poder deshacer).

3. Tap en `✅ Subir 2 vídeos a YouTube` (callback `uO:7:W`):
   - Aplica `tools.unmark_objective_done(7)`.
   - Re-renderiza. El objetivo vuelve a `🔲` inline y botón `🔲`.

## Modelo de datos

Sin cambios. Reutilizamos `tasks`, `events`, `objectives`, `routine_completions`. Una sola función nueva en `tools.py`.

## Edge cases

- **Tarea borrada entre render y tap**: mutación silenciosa no-op; el re-render muestra la lista actualizada sin esa tarea.
- **Objetivo de OTRA semana**: si el objetivo pertenece a una semana pasada y de algún modo el usuario tapa en un mensaje viejo, la mutación se aplica al objetivo (correctamente), pero el re-render usa la semana actual, así que el objetivo desaparece del mensaje editado. El usuario verá una vista actual coherente.
- **Mensaje >48h** (no editable): `BadRequest` capturado, se envía mensaje nuevo. Misma fallback que `/hoy`.
- **`callback_data` antiguo sin sufijo**: se asume vista H. Mensajes pre-deploy siguen funcionando, pero el re-render será `render_today_view` (no `render_pending_view` ni `render_week_view`). Aceptable, mejor que romper el botón.
- **Última tarea en `/pendientes`**: el keyboard se vuelve None y el mensaje pasa al texto "No tienes tareas pendientes. 🎉". El `edit_message_text` con `reply_markup=None` elimina el keyboard.
- **`/semana` con cero objetivos**: la sección 🎯 OBJETIVOS se omite; el keyboard queda vacío o None. Si NINGUNA sección tiene contenido, mensaje "Semana tranquila 💆" sin botones.

## Tests

1. `views.render_pending_view` con 0 tareas → "No tienes tareas pendientes" y keyboard None.
2. `render_pending_view` con 3 tareas → 3 bullets en texto y 3 botones `🔲 … callback_data=mT:{id}:P`.
3. `render_pending_view` ignora tareas con `done=1` aunque tengan done_at de hoy.
4. `render_week_view` con 0 de todo → "Semana tranquila 💆" y keyboard None.
5. `render_week_view` con 1 evento + 1 objetivo + 1 rutina → texto con 3 secciones, **un solo botón** (el del objetivo, `mO:{id}:W`).
6. `render_week_view` con 1 objetivo hecho y 1 pendiente → ambos visibles en OBJETIVOS, dos botones (`uO:…:W` y `mO:…:W`).
7. `render_week_view` con tarea completada esta semana → aparece tachada en ✅ COMPLETADO **sin botón**.
8. `tools.unmark_objective_done` deja `done=0`.
9. `tools.unmark_objective_done` idempotente sobre un objetivo ya pendiente.
10. Callback `mO:3:W` aplica `mark_objective_done(3)` y edita con `render_week_view`.
11. Callback `uO:7:W` aplica `unmark_objective_done(7)` y edita con `render_week_view`.
12. Callback `mT:5:P` aplica `complete_task(5)` y edita con `render_pending_view`.
13. Callback `mE:42` (formato viejo sin sufijo) usa vista H (compatibilidad). El re-render llama a `render_today_view`.
14. Callback `mO:3:H` (objetivo desde vista hoy) — caso teórico que NO debería ocurrir porque /hoy no muestra objetivos. El handler aplica la mutación y re-renderiza vista H (sin objetivos visibles). No rompe.
15. `bot._SLASH_PROMPTS` ya no contiene `/pendientes` ni `/semana`.

## Criterios de éxito

- Pido `/pendientes` y veo mis tareas con un botón por cada una.
- Tap en `🔲 Comprar pan` → en <1 segundo la tarea desaparece de la lista.
- Pido `/semana` y veo las 4 secciones; los objetivos llevan botones, el resto no.
- Tap en `🔲 Objetivo X` → el objetivo pasa a `✅` inline y el botón cambia a `✅`.
- Tap en `✅ Objetivo Y` → vuelve a pendiente con `🔲`.
- Mensajes anteriores (con callback_data antiguo) siguen funcionando: tapas y editan al menos la vista de hoy.

## Fuera del alcance

- ❌ Botones para eventos en `/semana` (queda como texto).
- ❌ Botones para rutinas en `/semana` (su naturaleza agregada no encaja con "mark one").
- ❌ Botones para items completados en `/pendientes` (la vista solo muestra pendientes).
- ❌ Renderers determinísticos para `/objetivos` y `/rachas` (siguen pasando por Claude — no hay UI interactiva que justifique bypass).
- ❌ Cierre motivador variable en `/pendientes` y `/semana` (se pierde a cambio de la velocidad de tap, igual que pasó con `/hoy`).
- ❌ Cambio en la BD ni en la API expuesta a Claude.

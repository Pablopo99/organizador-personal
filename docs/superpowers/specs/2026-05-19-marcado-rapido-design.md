# Marcado rápido con botones inline — Diseño

**Fecha:** 2026-05-19
**Estado:** Diseño aprobado, pendiente de plan de implementación
**Sigue a:** rachas en rutinas (2026-05-19-rachas-design.md)

## Objetivo

Eliminar la fricción de tener que escribir *"ya hice las flexiones"* / *"marca como hecho el dentista"* cada vez. En su lugar, el usuario ve en `/hoy` y en el saludo matutino una lista con un botón por item; un tap lo marca como hecho. Otro tap en un item completado lo deshace.

## Decisiones clave

- **Ámbito**: solo `/hoy` y saludo matutino. `/semana`, `/pendientes`, `/objetivos` siguen siendo texto sin botones (mantienen Claude).
- **Items soportados**: eventos puntuales (📅 HOY), rutinas (🔁 RUTINAS) y tareas (📝 PENDIENTES). Los tres tipos.
- **Iconografía**: el botón muestra el **estado**, no la acción:
  - `🔲 {título}` = pendiente. Tap → marca como hecho.
  - `✅ {título}` = completado. Tap → deshace.
- **Edición in-place**: tras un tap, el mismo mensaje se actualiza (texto y botones). Sin mensaje nuevo.
- **`/hoy` y morning summary dejan de pasar por Claude**: los genera el bot directamente desde la BD, sin LLM en el camino. Trade-off explícito: se pierde el cierre motivador variable de Claude a cambio de:
  - Respuesta a tap instantánea (sin llamada a API).
  - Coste cero por tap.
  - Texto totalmente predecible (clave para que la edición in-place no produzca inconsistencias).

## Arquitectura

```
                ┌──────────────────────────┐
                │       bot.py             │
                │  /hoy handler ───────────┼──> views.render_today_view(today, conn)
                │  CallbackQueryHandler ───┼──> _on_callback_query
                └──────────────────────────┘
                              │
                              ▼
                ┌──────────────────────────┐
                │      views.py (nuevo)    │
                │  render_today_view()     │
                │   → (html_text,          │
                │      InlineKeyboardMarkup)│
                └──────────────────────────┘
                              │
                              ▼
                ┌──────────────────────────┐
                │   tools / db queries     │
                │   query_events,          │
                │   list_tasks,            │
                │   routine_summary, etc.  │
                └──────────────────────────┘
```

**Archivos:**

- **`views.py`** (nuevo) — función pura `render_today_view(today_date, conn) -> tuple[str, InlineKeyboardMarkup]`. Fuente única de verdad del formato. Usada por `/hoy`, morning summary y el callback handler tras un tap.
- **`bot.py`** —
  - `/hoy` handler reescrito: llama a `views.render_today_view` directamente, sin Claude.
  - Nuevo `CallbackQueryHandler` registrado que enruta callbacks a `_on_callback_query`.
  - `_on_callback_query`: parsea `callback_data`, valida usuario, aplica mutación a BD, re-renderiza y edita mensaje.
- **`scheduler.py`** — `morning_summary` simplificado: prepende un saludo fijo ("Buenos días Pablo 🌅 — {weekday}, {fecha}") al resultado de `render_today_view`, lo envía a Telegram con el keyboard. Se elimina `_morning_prompt` y la llamada a Claude.
- **`brain.py`** — sin cambios.

## Formato visual

```
📅 <b>HOY</b>

• 10:00 — Reunión con Marta
• 17:00 — Dentista

🔁 <b>RUTINAS</b>

• 50 flexiones diarias 🔥 3
• Anotar 3 cosas buenas del día

📝 <b>PENDIENTES</b>

• Solucionar Spotify
• Comprar pan

✅ <b>COMPLETADO HOY</b>

• <s>Leer 5 páginas</s>
```

Bajo el mensaje, un botón por fila, en este orden:

```
[🔲 Reunión con Marta]
[🔲 Dentista]
[🔲 50 flexiones diarias]
[🔲 Anotar 3 cosas buenas del día]
[🔲 Solucionar Spotify]
[🔲 Comprar pan]
[✅ Leer 5 páginas]
```

Si una sección está vacía, no aparece en el texto (pero sí pueden existir botones de items completados en COMPLETADO HOY).

**Caso "día libre"**: si no hay nada en ninguna sección (pendiente ni completado), el mensaje es: `"Día libre, disfrútalo 💪"` y sin botones.

## Modelo de callbacks

Cada botón lleva `callback_data` con formato `{acción}{tipo}:{id}`. Acción es 1 letra (`m` = mark, `u` = unmark), tipo es 1 letra (`E`/`R`/`T`). Bajo el límite de Telegram (64 bytes) con muchísimo margen.

| `callback_data` | Acción | Efecto |
|---|---|---|
| `mE:42` | mark event 42 | `mark_event_done(42)` → `events.done=1` |
| `uE:42` | unmark event 42 | `UPDATE events SET done=0 WHERE id=42` |
| `mR:5` | mark routine 5 hoy | inserta en `routine_completions(5, today_madrid)` (idempotente vía UNIQUE) |
| `uR:5` | unmark routine 5 hoy | `DELETE FROM routine_completions WHERE event_id=5 AND completion_date=today_madrid` |
| `mT:7` | mark task 7 | `complete_task(7)` → `tasks.done=1, done_at=now_iso()` |
| `uT:7` | unmark task 7 | `UPDATE tasks SET done=0, done_at=NULL WHERE id=7` |

`mE` y `mR` ya tienen función en `tools.py` (mediante `mark_event_done`, que es smart routing). Las acciones `u*` son nuevas y se añaden en `tools.py` como funciones internas (no se exponen como tools a Claude — son solo para callbacks).

## Flujo de un tap

1. Usuario tap en `🔲 Flexiones`. Telegram manda `CallbackQuery` con `data="mR:5"` al bot.
2. `_on_callback_query(update, context)`:
   1. Valida `update.effective_user.id == ALLOWED_USER_ID`. Si no, `query.answer("No autorizado")` y return.
   2. Parsea `data` → `acción='m', tipo='R', id=5`.
   3. Aplica mutación. Si falla (item borrado, race), captura y continúa.
   4. Recalcula `views.render_today_view(today, conn) → (html, keyboard)`.
   5. `query.edit_message_text(html, parse_mode=HTML, reply_markup=keyboard)`.
   6. `query.answer()` (toast vacío, cierra el spinner).
3. Si `edit_message_text` falla (mensaje > 48h, Telegram lo rechaza con `BadRequest`):
   - Capturamos la excepción.
   - `query.answer("Mensaje antiguo, te mando uno nuevo")`.
   - Enviamos nuevo mensaje con `context.bot.send_message(...)` y mismo contenido.

## Generación deterministic de `/hoy`

`render_today_view(today, conn)` consulta directamente:

1. `events` no recurrentes cuya `datetime` cae hoy y `done=0` → 📅 HOY.
2. `events` recurrentes con instancia hoy y `done_today=0` → 🔁 RUTINAS pendientes.
3. `tasks` con `done=0` → 📝 PENDIENTES.
4. Eventos no recurrentes hoy con `done=1` + eventos recurrentes hoy con instancia hecha + tareas con `done_at` de hoy → ✅ COMPLETADO HOY.

Para rutinas recurrentes, también lee `routine_summary` (o equivalente) para incluir `🔥 N` cuando `current_streak >= 2`.

Toda la lógica está aislada en `views.py`. Tests unitarios validan formato sin tocar Telegram.

## Morning summary tras el cambio

```python
async def morning_summary(context):
    today = date_utils.today_madrid()
    weekday = _WEEKDAYS_ES[today.weekday()]
    date_str = today.strftime("%-d %b").lower()

    with db.connect() as conn:
        text, keyboard = views.render_today_view(today, conn)

    greeting = f"Buenos días Pablo 🌅 — <b>{weekday}, {date_str}</b>\n\n"
    await context.bot.send_message(
        chat_id=ALLOWED_USER_ID,
        text=greeting + text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )
```

Se elimina la dependencia con `brain.handle_message` y el `SCHEDULER_USER_ID` deja de necesitarse (puede quedar como variable muerta, se borra para limpieza).

## Edge cases

- **Mensaje > 48h** (Telegram no permite editar): captura `BadRequest`, manda mensaje nuevo en su lugar.
- **Item borrado entre render y tap**: la mutación es no-op silenciosa, el re-render lo omite del mensaje editado.
- **Doble tap rápido**: las mutaciones son idempotentes (UNIQUE en `routine_completions`, `UPDATE done=1` setea 1 aunque ya esté en 1). El segundo tap no rompe nada.
- **Usuario no autorizado**: filtrado en `_on_callback_query` antes de aplicar nada.
- **`callback_data` malformado**: try/except → log + `query.answer("Acción no reconocida")`.
- **Mensaje vacío sin botones (día libre)**: tras marcar la última cosa, el mensaje se queda como "Día libre". Si luego se añade algo nuevo (por chat), ese nuevo item aparecerá en el SIGUIENTE `/hoy`, no se actualiza retroactivamente el mensaje viejo. Aceptable: el usuario sabe pedir `/hoy` cuando quiere ver el estado actual.

## Tests

1. `views.render_today_view` con BD vacía → texto "Día libre, disfrútalo 💪", keyboard vacío.
2. `render_today_view` con 1 evento pendiente → sección 📅 HOY con bullet + 1 botón `🔲 {título}` con `callback_data=mE:{id}`.
3. `render_today_view` con 1 rutina hecha hoy + 1 pendiente → tachada en ✅ COMPLETADO con botón `✅`, pendiente en 🔁 RUTINAS con `🔲`.
4. `render_today_view` con racha ≥ 2 → bullet de rutina incluye `🔥 N`.
5. `render_today_view` con 3 tipos de items pendientes y 2 completados → 5 botones en orden correcto.
6. Callback handler `mE:42` aplica `events.done=1`, re-renderiza, edita mensaje.
7. Callback handler `mR:5` inserta fila en `routine_completions` con today_madrid.
8. Callback handler `mT:7` aplica `tasks.done=1, done_at=now_iso()`.
9. Callback handler `uE:42` aplica `events.done=0`.
10. Callback handler `uR:5` borra fila de `routine_completions` para today_madrid.
11. Callback handler `uT:7` aplica `tasks.done=0, done_at=NULL`.
12. Callback de usuario no autorizado no aplica cambio y responde con texto.
13. Callback con `callback_data` malformado responde con error pero no crashea.
14. Callback con id inexistente no crashea, re-renderiza igualmente.
15. Si `edit_message_text` lanza `BadRequest`, se envía mensaje nuevo (mock).

## Criterios de éxito

- Pido `/hoy` por Telegram, veo el texto con secciones + un botón por item bajo el mensaje.
- Tap a `🔲 Flexiones` → en menos de 1 segundo, el bullet se mueve a COMPLETADO HOY tachado y el botón cambia a `✅ Flexiones`.
- Tap a `✅ Flexiones` → vuelve a 🔁 RUTINAS pendiente con `🔲`.
- A las 09:00 del día siguiente, el saludo matutino tiene la misma estructura y botones.
- Si toco un botón en un mensaje de hace 3 días, el bot me responde con un mensaje nuevo (no falla en silencio).
- `/semana`, `/pendientes`, `/objetivos` siguen funcionando exactamente como antes.

## Fuera del alcance

- ❌ Botones en `/semana`, `/pendientes`, `/objetivos`.
- ❌ Botones de "borrar" o "editar" item.
- ❌ Botón "marcar todo" / "completar el día".
- ❌ Cierre motivador variable en `/hoy` y saludo matutino (Claude deja de generar texto en estos dos sitios).
- ❌ Auto-refresh del mensaje cuando se añade un item nuevo por chat (el usuario pide `/hoy` de nuevo si quiere ver el estado actualizado).
- ❌ Persistir el "message_id" para futuras ediciones automáticas (cada `/hoy` es independiente).

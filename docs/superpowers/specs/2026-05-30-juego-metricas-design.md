# Mi Secretaria: el juego — gracia, perdidos y métricas

Fecha: 2026-05-30
Autor: Pablo (brainstorming guiado por Claude)
Estado: propuesto, pendiente de plan de implementación

## 1. Motivación

Pablo necesita un incentivo estructural para cerrar lo que se compromete a hacer cuando dice que lo hará. Hoy el bot registra eventos, tareas, objetivos y rutinas pero no diferencia entre "hecho a tiempo", "hecho tarde" y "perdido". El resultado: las cosas que se le pasan se arrastran indefinidamente como culpa silenciosa, sin decisión.

Este diseño introduce tres mecánicas:

1. **Día de gracia (o semana en objetivos)** que permite recuperar algo con un día de margen.
2. **Estado "perdido"** que dispara una decisión explícita: recrear o descartar.
3. **Métricas** que distinguen *a tiempo / al día siguiente / perdido* por tipo de ítem, para que Pablo vea su patrón real.

El objetivo psicológico: convertir "se me pasó" en "qué hago con esto" antes de que se acumule.

## 2. Reglas del juego

### 2.1 Estados de un ítem

Cada ítem que entra al juego tiene un `outcome` final:

- `null` → activo, todavía dentro de su ventana.
- `'on_time'` → completado dentro de la ventana principal.
- `'grace'` → completado en la ventana de gracia.
- `'missed'` → cruzó el umbral y Pablo lo descartó (después del aviso proactivo).

Los ítems recreados son entradas nuevas con `outcome=null`. La entrada original que originó la recreación pasa a `'missed'` (Pablo eligió "Pasar a hoy", equivalente a descartar la original y crear una nueva).

### 2.2 Ventanas por tipo

| Tipo | A tiempo | Día/semana de gracia | Perdido (recrear) |
|---|---|---|---|
| **Rutina** (recurring_rule) | la fecha esperada (mismo día) | día siguiente completo | a partir del día +2 |
| **Evento puntual** (datetime, sin recurring_rule) | día del evento (cualquier hora) | día +1 completo | día +2 en adelante |
| **Tarea con `due_date`** | el `due_date` | día +1 completo | día +2 en adelante |
| **Tarea sin `due_date`** | — fuera del juego — | — | — |
| **Objetivo semanal** | su semana (lun-dom) | semana siguiente completa | a partir del lunes +14 |

Las rutinas WEEKLY:X heredan la misma regla: si toca el lunes y no se hace, el martes es gracia y el miércoles ya es perdida (esa instancia). La siguiente instancia esperada (el lunes siguiente) es independiente.

### 2.3 Efecto en la racha (solo rutinas)

- `on_time` → la racha continúa.
- `grace` → **la racha continúa** (el día de gracia te salva la racha).
- `missed` → la racha se rompe (vuelve a 0).

La racha se calcula con `_current_streak` ya existente en [tools.py:367](tools.py#L367), que solo mira si hay completion en cada fecha esperada consecutiva. La clave para que `grace` no rompa la racha: ver §3.2.

### 2.4 Métrica vs racha

El día de gracia salva la racha pero **siempre** queda registrado como `grace` en métricas. Pablo verá su porcentaje real de "a tiempo" vs "al día siguiente" sin engañarse.

## 3. Comportamientos clave

### 3.1 Marcar un ítem como hecho

Al recibir un mark, el sistema calcula el `outcome` automáticamente comparando la fecha asignada con `date_utils.today_madrid()`:

- Si `today == fecha_asignada` → `outcome = 'on_time'`.
- Si `today == fecha_asignada + 1` → `outcome = 'grace'`.
- Si `today > fecha_asignada + 1` → **rechazar el mark**. El ítem ya está fuera de ventana; debe pasar por el flujo de recrear/descartar.
- Si `today < fecha_asignada` (lo marcas antes de tiempo, raro pero posible) → `outcome = 'on_time'`.

Para objetivos semanales el cálculo es por semana: `monday_of_week(today) == week_start` → on_time; `monday_of_week(today) == week_start + 7 días` → grace; más allá → rechazar.

### 3.2 Marcar una rutina en día de gracia

Caso especial e importante. Cuando se marca una rutina y `today` es la fecha de gracia (día siguiente a una fecha esperada perdida):

- Se inserta `routine_completions` con `completion_date = fecha_esperada_perdida` (no `today`) y `status = 'grace'`.
- Esto preserva la continuidad del set de fechas que mira `_current_streak`, así la racha no se rompe.

Si `today` es a su vez la fecha esperada (rutina DAILY o WEEKLY que toca hoy), se inserta con `completion_date = today, status = 'on_time'`.

Para WEEKLY:X cuya fecha esperada anterior fue hace más de un día calendario, no hay gracia (estaríamos saltándonos varias instancias). El mark se rechaza.

### 3.3 Job nocturno `detect_missed_items`

Nuevo job en [scheduler.py](scheduler.py), programado a las **00:05 hora Madrid**, todos los días.

Para cada tipo, busca ítems que han cruzado el umbral de "perdido" en las últimas 24h y no han sido aún notificados:

- **Rutinas**: para cada rutina activa, calcular la fecha esperada inmediatamente anterior a `today - 1` (es decir, dos fechas esperadas atrás). Si esa fecha no tiene completion **y** la fecha esperada *aún anterior* sí tiene completion (= antes había racha viva, ahora se rompió), notificar. Esto evita spam para rutinas crónicamente abandonadas.
- **Eventos puntuales** con `recurring_rule IS NULL`, `done=0`, `outcome IS NULL` y `datetime < today - 1 día`.
- **Tareas** con `due_date IS NOT NULL`, `done=0`, `outcome IS NULL` y `due_date < today - 1 día`.
- **Objetivos** con `done=0`, `outcome IS NULL` y `week_start < monday_of_week(today) - 14 días`.

Para cada ítem detectado:

1. Comprobar si ya existe registro en `missed_notifications` (con la UNIQUE adecuada — ver §4.3). Si existe, saltar.
2. Insertar en `missed_notifications`.
3. Enviar el mensaje correspondiente (ver §3.4).

Si el job no corre una noche (Fly caído, deploy en curso), la próxima ejecución detecta los acumulados porque la condición es por fecha, no por "ayer estrictamente". La UNIQUE evita duplicar notificaciones.

### 3.4 Mensajes al cruzar a "perdido"

**Rutinas — racha rota** (mensaje sin botones, informativo):

```
⚠️ Se rompió tu racha de Meditar (llevabas 12 días).
La rutina sigue activa, vuelve a empezar cuando quieras.
```

**Eventos / tareas / objetivos — recrear o descartar** (con botones inline):

```
⚠️ Se te ha pasado: Llamar al dentista

[📌 Pasar a hoy]  [🗑️ Descartar]
```

callback_data:
- `rE:{id}` / `rT:{id}` / `rO:{id}` — recreate event/task/objective
- `dE:{id}` / `dT:{id}` / `dO:{id}` — discard event/task/objective

### 3.5 Acción "Pasar a hoy" (recrear)

Al pulsar `rE/rT/rO:{id}`:

1. Cargar el ítem original.
2. Crear **una entrada nueva** con los mismos atributos pero fecha actualizada:
   - Evento → `datetime` con la misma hora pero `today` como fecha.
   - Tarea → `due_date = today`.
   - Objetivo → `week_start = monday_of_week(today)`.
3. Marcar el original con `outcome='missed'` (Pablo eligió descartarlo en favor del nuevo).
4. Registrar `decision='recreate'` en `missed_notifications` para auditoría.
5. Editar el mensaje original con confirmación: `✅ Pasado a hoy.` y eliminar los botones.

No se valida si la nueva entrada duplica algo existente (Pablo puede tener dos veces "leer 30 min" si quiere).

**Sincronización con Google Calendar al recrear un evento**: la entrada nueva **no** se sincroniza automáticamente con Calendar aunque la original tuviera `gcal_event_id`. Pablo decide si quiere mandarla con el botón inline 📅 habitual (ver `_calendar_button_keyboard` en [bot.py:123](bot.py#L123)). La entrada original conserva su `gcal_event_id`; el evento en Google Calendar queda intacto (Pablo lo gestiona allí si quiere).

### 3.6 Acción "Descartar"

Al pulsar `dE/dT/dO:{id}`:

1. Marcar el ítem con `outcome='missed'`.
2. Registrar `decision='discard'` en `missed_notifications`.
3. Editar el mensaje original con `🗑️ Descartado.` y eliminar los botones.

Los ítems descartados no vuelven a aparecer en `/hoy`, `/pendientes`, `/semana`. Sí aparecen en métricas como "perdido".

## 4. Modelo de datos

Todas las migraciones son aditivas idempotentes, siguiendo el patrón de [db.py:70](db.py#L70).

### 4.1 Cambios en tablas existentes

```sql
-- events
ALTER TABLE events ADD COLUMN outcome TEXT;
-- Valores: NULL | 'on_time' | 'grace' | 'missed'
-- Solo relevante para eventos no recurrentes (recurring_rule IS NULL).
-- En eventos recurrentes, outcome queda NULL siempre (la información de
-- estado por instancia vive en routine_completions).

-- tasks
ALTER TABLE tasks ADD COLUMN due_date TEXT;
-- Formato 'YYYY-MM-DD'. NULL = tarea flotante, fuera del juego.
ALTER TABLE tasks ADD COLUMN outcome TEXT;

-- objectives
ALTER TABLE objectives ADD COLUMN outcome TEXT;

-- routine_completions
ALTER TABLE routine_completions ADD COLUMN status TEXT NOT NULL DEFAULT 'on_time';
-- Valores: 'on_time' | 'grace'
```

### 4.2 Reglas de consistencia

- `done=1` ↔ `outcome IN ('on_time', 'grace')` para events/tasks/objectives no recurrentes. El código que actualiza `done` también escribe `outcome`.
- `outcome='missed'` puede coexistir con `done=0`. Los ítems missed no se filtran por `done`; se filtran por `outcome != 'missed' OR outcome IS NULL`.
- `routine_completions` no cambia su semántica: una fila por (rutina, fecha esperada) cuando se ha completado. El nuevo campo `status` solo dice si fue a tiempo o tarde.

### 4.3 Nueva tabla `missed_notifications`

```sql
CREATE TABLE missed_notifications (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    item_type       TEXT NOT NULL,         -- 'routine' | 'event' | 'task' | 'objective'
    item_id         INTEGER NOT NULL,
    occurrence_date TEXT,                  -- solo para rutinas (YYYY-MM-DD); NULL para los demás
    notified_at     TEXT NOT NULL,
    decision        TEXT,                  -- NULL | 'recreate' | 'discard'
    decided_at      TEXT
);

CREATE UNIQUE INDEX idx_missed_notif_routine
    ON missed_notifications(item_type, item_id, occurrence_date)
    WHERE item_type = 'routine';

CREATE UNIQUE INDEX idx_missed_notif_other
    ON missed_notifications(item_type, item_id)
    WHERE item_type != 'routine';
```

La UNIQUE diferenciada permite:
- Para rutinas: registrar una notificación por cada fecha esperada perdida (distinta).
- Para tareas/eventos/objetivos: una sola notificación por ítem (no tiene más ocurrencias).

## 5. Métricas

### 5.1 Categorías

Tres categorías visibles, con código de color:

- 🟢 **A tiempo** (`on_time`)
- 🟡 **Al día siguiente** / Semana siguiente para objetivos (`grace`)
- 🔴 **Perdido** (`missed`)

### 5.2 Tres puntos de acceso

**(a) `/metricas`** — comando dedicado.

Vista determinística (sin Claude). Ventana fija: **últimos 30 días naturales**.

```
📊 Métricas — últimos 30 días

🔁 Rutinas
   Meditar:   🟢 24  🟡 4  🔴 2   (80% / 13% / 7%)
   Lectura:   🟢 18  🟡 6  🔴 6   (60% / 20% / 20%)
   Total:     🟢 70%  🟡 18%  🔴 12%

📅 Eventos puntuales
   🟢 8  🟡 1  🔴 1   (80% / 10% / 10%)

✅ Tareas (con fecha)
   🟢 12  🟡 3  🔴 2   (71% / 18% / 12%)

🎯 Objetivos semanales (últimas 4 semanas)
   🟢 6  🟡 1  🔴 1   (75% / 12% / 12%)
```

Si no hay datos en una categoría, se omite la sección. Si Pablo no tiene tareas con fecha, no aparece la sección de tareas.

**(b) `/rachas` enriquecido**.

El comando sigue pasando por Claude (como hoy, ver [bot.py:42](bot.py#L42)). El prompt se enriquece con instrucciones para incluir mini-stats de los últimos 30 días por rutina:

```
🔁 Meditar — racha 12 días (30d: 🟢 80% 🟡 13% 🔴 7%)
🔁 Lectura — racha 3 días  (30d: 🟢 60% 🟡 20% 🔴 20%)
```

Esto requiere que `routine_summary` devuelva también los conteos por status (a tiempo vs gracia) en el rango pedido, además de los streaks que ya devuelve.

**(c) Bloque semanal automático**.

Solo los **lunes**, en `morning_summary` ([scheduler.py:24](scheduler.py#L24)), antes del cuerpo de `render_today_view`:

```
📊 Tu semana pasada
   Rutinas:   🟢 85% 🟡 10% 🔴 5%
   Tareas:    🟢 70% 🟡 20% 🔴 10%
   Objetivos: 2 de 3 cumplidos
```

Derivado en el scheduler sin Claude. Si la semana pasada está vacía (no había nada), omitir el bloque.

### 5.3 Nuevo tool `metrics_summary`

```python
def metrics_summary(date_from: str, date_to: str) -> dict
```

Devuelve un dict con conteos agregados por tipo y status, listo para renderizar:

```python
{
    "routines": {
        "per_event": [
            {"event_id": 1, "title": "Meditar", "on_time": 24, "grace": 4, "missed": 2},
            ...
        ],
        "totals": {"on_time": 42, "grace": 10, "missed": 8},
    },
    "events": {"on_time": 8, "grace": 1, "missed": 1},
    "tasks": {"on_time": 12, "grace": 3, "missed": 2},
    "objectives": {"on_time": 6, "grace": 1, "missed": 1},
}
```

Para rutinas, `missed` se calcula como: `scheduled_days - completed_on_time - completed_grace` en el rango. Para no-rutinas, se cuenta directamente por `outcome`.

`metrics_summary` se registra en `TOOL_DEFINITIONS` para que Claude pueda invocarlo si lo necesita (por ejemplo si Pablo pregunta "¿cómo voy este mes?"), y se llama directamente desde `views.render_metrics_view` y desde `scheduler` para el bloque del lunes.

## 6. Cambios en UX existente

### 6.1 Creación de tareas con fecha

`add_task(text)` cambia a `add_task(text, due_date=None)`. `TOOL_DEFINITIONS` se actualiza.

System prompt en [brain.py](brain.py) — añadir regla:

> Cuando Pablo quiera crear una tarea y no diga fecha explícitamente, antes de llamar a `add_task` pregúntale "¿Para qué día? (hoy / mañana / esta semana / sin fecha)". Si responde "sin fecha", pasa `due_date=None`. Si dice "hoy" o un día concreto, pasa la fecha ISO correspondiente.

Las tareas existentes sin `due_date` siguen siendo válidas (flotantes).

### 6.2 `/hoy` y `render_today_view`

Cambios:

1. **Nueva subsección visual al inicio** cuando hay ítems en gracia:

   ```
   🟡 AYER (último día)
   • Llamar al dentista
   • Comprar leche
   ```

   Estos ítems son: eventos puntuales con `datetime` de ayer + `done=0 + outcome IS NULL` y tareas con `due_date = ayer + done=0 + outcome IS NULL`.

2. **Filtrado de tareas por fecha**: en lugar de listar todas las tareas con `done=0`, listar solo las con `due_date IN (hoy, ayer)`. Las flotantes y las futuras quedan en `/pendientes`.

3. Botones para ítems en gracia siguen siendo `mE:{id}` / `mT:{id}` (mismo handler, el cálculo de `outcome='grace'` lo hace `mark_event_done` / `complete_task` al detectar la fecha).

### 6.3 `/pendientes` y `render_pending_view`

Reorganización en secciones:

```
🟡 EN GRACIA
• Tarea X (ayer)

📅 CON FECHA
• Lun 1 jun — Tarea Y
• Mar 2 jun — Tarea Z

🌊 FLOTANTES
• Tarea sin fecha A
• Tarea sin fecha B
```

Cada sección con sus botones (callback_data sigue siendo `mT:{id}:P`).

### 6.4 `query_events` con `include_grace`

Añadir parámetro opcional `include_grace: bool = False`. Cuando es `True` y el rango pedido empieza en `today`, también devolver eventos puntuales con `datetime` de `today - 1 día` que tengan `done=0 + outcome IS NULL`.

Las vistas que muestran "lo que se puede hacer hoy" pasan `include_grace=True`. Claude por defecto no, salvo que sea relevante.

### 6.5 `mark_event_done` y `complete_task` — calcular `outcome`

Modificar para que, al marcar hecho:

1. Cargar la fecha asignada (`datetime` para eventos, `due_date` para tareas).
2. Comparar con `today_madrid()`:
   - Si la fecha asignada es NULL (tarea flotante) → `outcome` queda NULL pero `done=1`. (Las flotantes no tienen estado de juego.)
   - On time → `outcome='on_time'`.
   - Gracia (today == asignada + 1) → `outcome='grace'`.
   - Fuera de ventana (today > asignada + 1) → **devolver error**. El cliente (callback o brain) debe dirigir a Pablo al flujo recrear/descartar.

Para rutinas (caso especial), el cálculo es por instancia esperada (ver §3.2).

### 6.6 `mark_objective_done` — calcular `outcome`

Análogo: comparar `monday_of_week(today)` con `week_start` del objetivo.

### 6.7 Callback handler — nuevas acciones

[bot.py:263](bot.py#L263) `_CALLBACK_ACTIONS` añadir:

```python
"rE": lambda i: tools.recreate_event(i),
"rT": lambda i: tools.recreate_task(i),
"rO": lambda i: tools.recreate_objective(i),
"dE": lambda i: tools.discard_event(i),
"dT": lambda i: tools.discard_task(i),
"dO": lambda i: tools.discard_objective(i),
```

En `_on_callback_query`, tratar `rE/rT/rO/dE/dT/dO` como caso especial (como `gc`): editar el mensaje original con confirmación y no re-renderizar ninguna vista. El callback_data para estos no lleva sufijo de vista.

Las funciones `recreate_event/task/objective` y `discard_event/task/objective` viven en [tools.py](tools.py) como funciones públicas pero **no se registran en `TOOL_DEFINITIONS`** (no son tools que Claude pueda invocar — son operaciones gatilladas por callbacks, igual que `uncomplete_routine_today` o `unmark_event_done`). Se llaman directamente desde `_CALLBACK_ACTIONS` en `bot.py`.

### 6.8 Nuevo comando `/metricas`

Handler dedicado `_on_metricas` en [bot.py](bot.py) (paralelo a `_on_hoy`). Registra `BotCommand("metricas", "Métricas de cumplimiento")` en `_set_bot_commands`.

## 7. Edge cases

- **Rutinas pausadas**: no existe el concepto. El aviso de racha rota es solo informativo, la rutina sigue activa. Si Pablo ya no la quiere, la elimina manualmente.
- **Editar fecha de una tarea antes de cruzar a perdido**: la ventana se "reinicia" porque la nueva fecha determina las nuevas ventanas. Aceptable y deseable.
- **Editar fecha después de cruzar a perdido**: el ítem ya tiene `outcome='missed'` (si Pablo respondió al aviso); editar la fecha no lo "resucita". Si quiere volver a hacerlo, debe ser por el flujo recrear o crear uno nuevo.
- **Bot caído cuando debía mandar notificación**: el job `detect_missed_items` la próxima vez detecta los acumulados (la query es por fecha, no por "ayer estrictamente"). La UNIQUE evita duplicados si por alguna razón el job se ejecuta dos veces el mismo día.
- **Marcar hecho un ítem ya en `outcome='missed'`**: devolver error. Pablo no debería poder hacerlo desde la UI (los descartados no aparecen). Si llega por brain.py (Claude), Claude lo trata como tarea inexistente.
- **Tarea creada con `due_date` en el pasado**: válida pero entra inmediatamente en gracia o perdida según la fecha. No bloquear, dejar que el flujo normal la gestione.
- **Rutinas WEEKLY:X con la fecha esperada hace varios días**: si hoy es jueves y la rutina es WEEKLY:MON, no hay gracia (martes era el último día). Marcar la rutina hoy registra un completion con `completion_date=today, status='on_time'` solo si today es un MON. Cualquier intento de marcar en otro día se rechaza (el current flow ya no encuentra la rutina en `/hoy` esos días, no debería ocurrir desde UI).
- **Recrear un objetivo semanal idéntico al que ya hay en la semana actual**: no se valida, se permite duplicado.

## 8. Tests

Basándonos en el patrón ya existente en `tests/`:

### 8.1 Unit tests

- `tools.complete_task` con `due_date=hoy` → `outcome='on_time'`.
- `tools.complete_task` con `due_date=ayer` → `outcome='grace'`.
- `tools.complete_task` con `due_date=anteayer` → error / rechazo.
- `tools.complete_task` con `due_date=NULL` (flotante) → `outcome` queda NULL, `done=1`.
- `tools.mark_event_done` paralelo para eventos puntuales.
- `tools.mark_event_done` para rutina DAILY en día de gracia → inserta `routine_completions` con la fecha de ayer y `status='grace'`.
- `tools.mark_event_done` para rutina WEEKLY:MON un martes (gracia) → completion con fecha del lunes, `status='grace'`. Racha intacta.
- `tools.mark_objective_done` con `week_start` actual → `on_time`. Con `week_start` la semana pasada → `grace`. Más allá → error.
- `tools.recreate_event/task/objective` → crea entrada nueva con fecha actual, marca original `missed`, devuelve nuevo id.
- `tools.discard_*` → marca `missed`.
- `metrics_summary` para un rango con un mix de outcomes → conteos correctos.

### 8.2 Integration tests

- `scheduler.detect_missed_items` con rutina DAILY recién rota → inserta `missed_notifications` con `occurrence_date` correcta + manda mensaje.
- Mismo job, segunda corrida → no duplica notificación (UNIQUE).
- Job con rutina ya crónicamente rota (sin completion previo) → **no** notifica.
- Job con tarea de hace 3 días `due_date` y `done=0` → notifica + botones.
- Callback `rT:{id}` → crea tarea nueva con `due_date=hoy`, original a `missed`, mensaje editado.
- Callback `dT:{id}` → original a `missed`, mensaje editado.

### 8.3 View tests

- `render_today_view` con tarea de ayer pendiente → aparece en sección "🟡 AYER".
- `render_pending_view` con mix de tareas → tres secciones diferenciadas.
- `render_metrics_view` con datos sintéticos → texto correcto con porcentajes.
- `morning_summary` un lunes → incluye bloque semanal antes del cuerpo.
- `morning_summary` un martes → no incluye bloque semanal.

### 8.4 Gotchas a respetar (ya conocidas)

- `tools.now_iso` se importa por nombre en `tools.py`. Tests que necesiten fijar fecha deben patchear `date_utils.today_madrid`, no `tools.now_iso`.
- Migraciones tienen que ser idempotentes — comprobar con `PRAGMA table_info` antes de `ALTER TABLE`.
- `connect()` activa `PRAGMA foreign_keys = ON`; los tests heredan el comportamiento.

## 9. Out of scope (explícito)

- Sistema de "vidas", "puntos", "logros", "badges" o cualquier elemento de gamificación más allá de las métricas honestas.
- Validación de duplicados al recrear.
- Pausar / archivar rutinas (sigue siendo borrado manual).
- `recreated_from` / auditoría de cadenas de recreación.
- Ventana de métricas configurable (fija en 30 días).
- Métricas históricas más allá de "últimos 30 días" o "última semana".
- Cambios en `check_reminders` (los recordatorios proactivos de eventos a 1h y 1 día siguen como están; los "perdidos" son una notificación independiente y posterior).

## 10. Resumen ejecutivo

Pablo gana tres cosas:

1. **Un día/semana de margen** sin perder la racha cuando algo se le va por horas.
2. **Una decisión forzada** ("pasar a hoy / descartar") cuando algo lleva demasiado pendiente.
3. **Una métrica honesta** que mide cuánto cumple a tiempo vs cuánto recupera tarde vs cuánto pierde, por tipo de ítem.

El coste técnico es contenido: una columna `outcome` en tres tablas, una columna `due_date` en `tasks`, una columna `status` en `routine_completions`, una tabla nueva `missed_notifications`, un job nocturno, un comando nuevo, modificaciones quirúrgicas en `mark_*_done`, `query_events`, `render_today_view`, `render_pending_view`, `morning_summary` y system prompt de brain.

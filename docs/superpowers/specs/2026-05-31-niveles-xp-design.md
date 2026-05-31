# Mi Secretaria — niveles y XP

Fecha: 2026-05-31
Autor: Pablo (brainstorming guiado por Claude)
Estado: propuesto, pendiente de plan de implementación

## 1. Motivación

Pablo quiere un sistema de gamificación encima del juego de gracia/perdidos ya existente, para reforzar la motivación a través de progresión visible. Cada acción que ya cuenta como "buena" (completar a tiempo o en gracia) suma puntos. Al acumular puntos, el usuario sube de nivel, lo que da una métrica de progreso a largo plazo distinta de las métricas honestas de cumplimiento.

Objetivo psicológico: añadir un eje de **progresión irreversible** que conviva con la honestidad del panel `/metricas`. Las métricas miden tu cumplimiento actual (porcentajes); los niveles celebran lo que ya hiciste y no se pueden perder.

## 2. Fuentes de XP

XP solo se gana al completar ítems o al cumplir condiciones específicas. **Missed y discard no dan ni quitan XP**.

### 2.1 XP base por item completado

| Tipo | on_time | grace |
|---|---|---|
| Rutina (`recurring_rule` no NULL) | 5 XP | 2 XP |
| Tarea con `due_date` | 10 XP | 5 XP |
| Evento puntual (`recurring_rule IS NULL`) | 10 XP | 5 XP |
| Objetivo semanal | 50 XP | 25 XP |

**Tareas flotantes (sin `due_date`) dan 0 XP**: están fuera del juego, no entran a la economía.

### 2.2 Bonus de racha (solo rutinas)

Al marcar una rutina con éxito (`on_time` o `grace`), se añade un bonus = `min(current_streak, 7)`:

| Día de racha | Bonus | Total rutina on_time |
|---|---|---|
| 1 | +1 | 6 XP |
| 2 | +2 | 7 XP |
| 3 | +3 | 8 XP |
| 4 | +4 | 9 XP |
| 5 | +5 | 10 XP |
| 6 | +6 | 11 XP |
| 7 | +7 | 12 XP |
| 8+ | +7 (capado) | 12 XP siempre |

El `current_streak` se calcula **después** de insertar la completion (incluyendo la del día actual). Si Pablo lleva 6 días seguidos y marca el 7º, su `current_streak` tras insertar es 7 → bonus +7.

Para rutinas marcadas en gracia (status='grace'), el bonus también aplica con la misma fórmula: el `current_streak` tras la inserción es el que se usa.

### 2.3 Bonus día perfecto

Si al final del día Pablo tiene **todas** las rutinas esperadas, **todas** las tareas con `due_date=hoy`, **y** todos los eventos puntuales de hoy en estado `done=1` con `outcome IN ('on_time', 'grace')`, se otorga `+20 XP`.

**Idempotencia**: solo una vez por día. Se comprueba consultando `xp_log` para una fila con `item_type='perfect_day'` y `awarded_at` empezando por la fecha de hoy.

**Cuándo se evalúa**: en cada `complete_task` o `mark_event_done` exitoso. **No** en `mark_objective_done` (los objetivos no influyen al día perfecto, solo a la semana perfecta). Tras insertar el XP del item, ejecutar la comprobación. Si se cumple y todavía no se ha otorgado hoy, insertar fila `perfect_day` y notificar.

**Caso borde**: si Pablo no tiene NADA programado hoy (cero rutinas, cero tareas, cero eventos), NO cuenta como día perfecto (sería un regalo gratis sin esfuerzo). Requisito: al menos un item evaluable.

### 2.4 Bonus semana perfecta

Si al final de la semana Pablo tiene los 3 objetivos (o los que haya) en estado `done=1` con `outcome IN ('on_time', 'grace')`, **y** la semana tenía al menos 1 objetivo definido, se otorga `+100 XP`.

**Cuándo se evalúa**: al iniciar `morning_summary` del **lunes**, antes de renderizar el bloque semanal. Mirar los objetivos cuyo `week_start = monday_of_week(today) - 7 días` (es decir, la semana que acaba de terminar). Si todos están `done=1` con outcome válido, otorgar `+100 XP` y meter mensaje en el saludo.

**Idempotencia**: una sola fila por semana. `item_type='perfect_week'`, `item_id` = semana ISO (YYYYWW), o usar `awarded_at` con substring para detectar el lunes evaluado.

**Caso borde**: si la semana pasada no tenía objetivos definidos, no aplica.

## 3. Curva de niveles

### 3.1 Fórmula

```
XP_total_para_nivel_N = 10 × N × (N + 2)
```

XP necesario para subir del nivel N al N+1 = `XP(N+1) - XP(N)` = `10 × ((N+1)(N+3) - N(N+2))` = `10 × (2N + 3)`. Crece linealmente (+20 XP por cada nivel).

### 3.2 Tabla de referencia

| Nivel | XP acumulado | Δ vs nivel anterior |
|---|---|---|
| 1 | 30 | — |
| 2 | 80 | 50 |
| 3 | 150 | 70 |
| 4 | 240 | 90 |
| 5 | 350 | 110 |
| 6 | 480 | 130 |
| 7 | 630 | 150 |
| 8 | 800 | 170 |
| 9 | 990 | 190 |
| 10 | 1200 | 210 |
| 15 | 2550 | … |
| 20 | 4400 | … |
| 30 | 9600 | … |
| 50 | 26000 | … |

A ritmo de ~60-80 XP/día con rutinas + ocasional tarea: nivel 1 en 1 día, nivel 5 en ~10 días, nivel 10 en ~5-6 semanas, nivel 20 en ~6-9 meses.

### 3.3 Cálculo del nivel actual

`compute_level(xp_total)`:
- Resolver `N` tal que `10 × N × (N + 2) <= xp_total < 10 × (N+1) × (N+3)`.
- Implementación: iterar `N` desde 1 hasta que `XP(N+1) > xp_total`. Para totales grandes (raro en este uso), se podría usar fórmula cuadrática inversa, pero un loop simple es suficiente y claro.

```python
def compute_level(xp_total: int) -> int:
    if xp_total < 30:
        return 0  # Nivel 0 = aún no llegó al primer nivel
    n = 1
    while 10 * (n + 1) * (n + 3) <= xp_total:
        n += 1
    return n
```

### 3.4 Estado inicial

Nivel 0 = 0 XP. Pablo empieza en nivel 0. La primera acción exitosa le pondrá inmediatamente a algún XP > 0, pero nivel 1 requiere acumular 30 XP.

## 4. Tramos visuales (medallas)

| Rango de nivel | Emoji | Significado |
|---|---|---|
| 0 | (sin medalla, solo número) | Empezando |
| 1-5 | 🥉 | Bronce |
| 6-15 | 🥈 | Plata |
| 16-30 | 🥇 | Oro |
| 31-60 | 💎 | Diamante |
| 61+ | 👑 | Leyenda |

Función helper `medal_for_level(level: int) -> str` que devuelve el emoji.

## 5. Visibilidad

### 5.1 Línea de cabecera en vistas

Una línea fija al inicio del mensaje, formato:

```
🥉 <b>Nivel 3</b>
```

(Si nivel 0: `<b>Nivel 0</b>` sin medalla.)

Vistas que incluyen la línea (encima de todo el contenido):
- `morning_summary` (sobre el saludo "Buenos días Pablo…")
- `render_today_view` (`/hoy`)
- `render_pending_view` (`/pendientes`)
- `render_week_view` (`/semana`)
- `render_metrics_view` (`/metricas`)
- `render_tomorrow_view` (`/manana`)

No aparece en:
- Confirmaciones del bot tras un marcado (texto suelto generado por Claude).
- Recordatorios proactivos (`check_reminders`, `detect_missed_items`).
- Mensajes del flujo OAuth de Calendar.
- `/objetivos` y `/rachas` — son generados por Claude, no determinísticos. Pueden añadirse después si se quiere.

### 5.2 Comando `/nivel`

Handler determinístico (sin Claude) similar a `/hoy`. Render:

```
🥈 <b>Nivel 8</b> — 850 XP

Para nivel 9 faltan: <b>140 XP</b>
Progreso del nivel: ▓▓▓▓▓▓▓▒▒▒ 70%

📊 <b>Últimos 30 días</b>: 420 XP ganados
  Rutinas:    180 XP
  Tareas:      80 XP
  Eventos:     40 XP
  Objetivos:  120 XP
```

Cálculos:
- "XP ganados últimos 30 días" = `SELECT SUM(xp_amount) FROM xp_log WHERE awarded_at >= (hoy - 29 días)`.
- Breakdown por tipo: agrupar por `item_type`.
- Progreso del nivel: `(xp_total - XP(N)) / (XP(N+1) - XP(N)) × 100`.
- Barra de progreso: 10 bloques, `▓` para cumplido, `▒` para pendiente.

Si nivel 0: cambiar mensaje a "Aún no has alcanzado el nivel 1. Faltan X XP."

### 5.3 Mensaje de subida de nivel

Cuando una operación de marcado dispara una subida de nivel, el bot manda un mensaje **adicional aparte** (no edit de la confirmación normal):

```
🎉 ¡Nivel 5 desbloqueado! 🥉 → 🥈
1000 XP totales. ¡Sigue así!
```

- Si el nivel nuevo cae en un nuevo tramo (cambio de medalla): mostrar transición `<medalla_anterior> → <medalla_nueva>`.
- Si no cambia tramo: omitir la transición, solo `🎉 ¡Nivel 5 desbloqueado! 🥈`.
- El mensaje se envía después del callback (en `_on_callback_query`) o después del tool dispatch (en `brain.handle_message`) — según el origen del marcado.

**Una sola notificación por subida**: si una acción otorga suficiente XP para saltar varios niveles a la vez (raro pero posible si se otorgan bonuses grandes), notificar solo del nivel final alcanzado.

## 6. Modelo de datos

Una sola tabla nueva, append-only, audit-friendly:

```sql
CREATE TABLE xp_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    item_type     TEXT    NOT NULL,
    item_id       INTEGER NOT NULL DEFAULT 0,
    outcome       TEXT    NOT NULL,
    xp_amount     INTEGER NOT NULL,
    streak_bonus  INTEGER NOT NULL DEFAULT 0,
    awarded_at    TEXT    NOT NULL
);
CREATE INDEX idx_xp_log_awarded_at ON xp_log(awarded_at);
```

### 6.1 Valores admitidos

`item_type`:
- `'task'` — fila de tarea.
- `'event'` — evento puntual.
- `'routine'` — instancia de rutina.
- `'objective'` — objetivo semanal.
- `'perfect_day'` — bonus día perfecto. `item_id=0`.
- `'perfect_week'` — bonus semana perfecta. `item_id=0`.
- `'reversal'` — fila negativa por desmarcar.

`outcome`:
- `'on_time'`, `'grace'` — para items completados.
- `'bonus'` — para `perfect_day` y `perfect_week`.
- `'reversal'` — para reversiones.

`xp_amount`: positivo en ganancias, negativo en reversiones.

`streak_bonus`: el componente del XP que vino del bonus de racha. Solo > 0 cuando `item_type='routine'`. Útil para auditar.

`awarded_at`: ISO 8601 sin TZ en hora Madrid (igual que `now_iso()` de `date_utils`).

### 6.2 Cálculo derivado de XP total y nivel

XP total = `SUM(xp_amount) FROM xp_log` (incluye reversiones).

Nivel = `compute_level(xp_total)`.

No hay tabla `user_progress` — un solo usuario y la suma es trivial. Si en el futuro hay multiusuario, añadir columna `user_id` a `xp_log`.

## 7. Integración

### 7.1 Helper `_calculate_xp` en `tools.py`

```python
def _calculate_xp(
    item_type: str,           # 'task' | 'event' | 'routine' | 'objective'
    outcome: str,             # 'on_time' | 'grace'
    streak_after: int = 0,    # solo relevante para routine
) -> tuple[int, int]:
    """Devuelve (xp_amount, streak_bonus_component)."""
    base_table = {
        'task':      {'on_time': 10, 'grace':  5},
        'event':     {'on_time': 10, 'grace':  5},
        'routine':   {'on_time':  5, 'grace':  2},
        'objective': {'on_time': 50, 'grace': 25},
    }
    base = base_table[item_type][outcome]
    streak_bonus = 0
    if item_type == 'routine':
        streak_bonus = min(max(streak_after, 0), 7)
    return base + streak_bonus, streak_bonus
```

### 7.2 Inserción en `xp_log`

Después de cada marcado exitoso en `tools.py`:

```python
# Dentro de complete_task, tras UPDATE:
xp_amount, streak_bonus = _calculate_xp('task', outcome)
_insert_xp_log(conn, 'task', task_id, outcome, xp_amount, streak_bonus)
```

`_insert_xp_log` es helper interno que hace el INSERT y devuelve el nuevo `xp_total` y nivel calculado para que el caller decida si notificar subida.

Devolución de `complete_task` / `mark_event_done` / `mark_objective_done` se amplía:

```python
{
    "id": ...,
    "updated": 1,
    "outcome": "on_time",
    "xp_awarded": 10,                  # NUEVO
    "level_before": 4,                 # NUEVO
    "level_after": 5,                  # NUEVO (si cambió)
    "perfect_day_bonus": 0,            # NUEVO
}
```

Para rutinas (`mark_event_done` con `recurring_rule`):

```python
{
    "event_id": ...,
    "completion_date": "2026-05-31",
    "status": "on_time",
    "updated": 1,
    "xp_awarded": 12,                  # NUEVO (incluye streak bonus)
    "streak_bonus": 7,                 # NUEVO
    "level_before": 4,
    "level_after": 4,
    "perfect_day_bonus": 0,
}
```

### 7.3 Reversiones

Cuando se llama a `unmark_event_done`, `uncomplete_routine_today`, `uncomplete_task`, `unmark_objective_done`, se inserta una fila negativa:

```python
# Buscar la fila de xp_log original del item:
original = conn.execute(
    "SELECT xp_amount FROM xp_log "
    "WHERE item_type = ? AND item_id = ? AND outcome != 'reversal' "
    "ORDER BY id DESC LIMIT 1",
    (item_type, item_id),
).fetchone()
if original:
    conn.execute(
        "INSERT INTO xp_log (item_type, item_id, outcome, xp_amount, awarded_at) "
        "VALUES (?, ?, 'reversal', ?, ?)",
        (item_type, item_id, -original['xp_amount'], now_iso()),
    )
```

Esto compensa el XP exactamente. Si la fila a revertir disparó un perfect_day_bonus o subida de nivel, **no** se revierte el bonus ni el nivel (el bonus ya está concedido). Filosóficamente: "ya te lo gastaste".

### 7.4 Día perfecto: comprobación

Helper `_check_and_award_perfect_day(conn, today)` ejecutado tras cada `complete_task` y `mark_event_done` (no en mark_objective_done):

```python
def _check_and_award_perfect_day(conn, today: date) -> int:
    """Devuelve XP otorgado por día perfecto (0 si no aplica)."""
    today_iso = today.isoformat()
    # ¿Ya otorgado hoy?
    existing = conn.execute(
        "SELECT 1 FROM xp_log "
        "WHERE item_type = 'perfect_day' "
        "AND substr(awarded_at, 1, 10) = ?",
        (today_iso,),
    ).fetchone()
    if existing:
        return 0

    # Rutinas esperadas hoy y completadas hoy
    routines = conn.execute(
        "SELECT id, recurring_rule FROM events WHERE recurring_rule IS NOT NULL"
    ).fetchall()
    expected_routine_ids = set()
    for r in routines:
        expected = _most_recent_expected_date(r["recurring_rule"], today)
        if expected == today:
            expected_routine_ids.add(r["id"])
    if expected_routine_ids:
        completed = conn.execute(
            f"SELECT event_id FROM routine_completions "
            f"WHERE completion_date = ? "
            f"AND event_id IN ({','.join('?' * len(expected_routine_ids))})",
            [today_iso, *expected_routine_ids],
        ).fetchall()
        completed_ids = {c["event_id"] for c in completed}
        if completed_ids != expected_routine_ids:
            return 0

    # Tareas con due_date=hoy
    pending_tasks = conn.execute(
        "SELECT COUNT(*) FROM tasks "
        "WHERE due_date = ? AND done = 0 AND (outcome IS NULL OR outcome != 'missed')",
        (today_iso,),
    ).fetchone()[0]
    if pending_tasks > 0:
        return 0

    # Eventos puntuales de hoy
    pending_events = conn.execute(
        "SELECT COUNT(*) FROM events "
        "WHERE recurring_rule IS NULL "
        "AND substr(datetime, 1, 10) = ? "
        "AND done = 0 "
        "AND (outcome IS NULL OR outcome != 'missed')",
        (today_iso,),
    ).fetchone()[0]
    if pending_events > 0:
        return 0

    # ¿Había algo evaluable hoy?
    total_today = len(expected_routine_ids) + conn.execute(
        "SELECT COUNT(*) FROM tasks WHERE due_date = ?",
        (today_iso,),
    ).fetchone()[0] + conn.execute(
        "SELECT COUNT(*) FROM events WHERE recurring_rule IS NULL AND substr(datetime,1,10) = ?",
        (today_iso,),
    ).fetchone()[0]
    if total_today == 0:
        return 0  # sin nada que cumplir, no es perfecto

    # Otorgar
    conn.execute(
        "INSERT INTO xp_log (item_type, item_id, outcome, xp_amount, awarded_at) "
        "VALUES ('perfect_day', 0, 'bonus', 20, ?)",
        (date_utils.now_iso(),),
    )
    return 20
```

### 7.5 Semana perfecta: comprobación en `morning_summary` del lunes

Helper `_check_and_award_perfect_week(conn, today)` ejecutado solo si `today.weekday() == 0`:

```python
def _check_and_award_perfect_week(conn, today: date) -> int:
    """Devuelve XP otorgado por semana perfecta (0 si no aplica). Solo lunes."""
    from date_utils import monday_of_week
    last_monday = monday_of_week(today) - timedelta(days=7)
    last_monday_iso = last_monday.isoformat()

    # ¿Ya otorgado para esa semana?
    existing = conn.execute(
        "SELECT 1 FROM xp_log "
        "WHERE item_type = 'perfect_week' "
        "AND substr(awarded_at, 1, 10) = ?",
        (today.isoformat(),),
    ).fetchone()
    if existing:
        return 0

    objs = conn.execute(
        "SELECT done, outcome FROM objectives WHERE week_start = ?",
        (last_monday_iso,),
    ).fetchall()
    if not objs:
        return 0
    all_done = all(
        o["done"] == 1 and o["outcome"] in ("on_time", "grace")
        for o in objs
    )
    if not all_done:
        return 0

    conn.execute(
        "INSERT INTO xp_log (item_type, item_id, outcome, xp_amount, awarded_at) "
        "VALUES ('perfect_week', 0, 'bonus', 100, ?)",
        (date_utils.now_iso(),),
    )
    return 100
```

El resultado se incluye en el texto del bloque semanal:

```
📊 Tu semana pasada
   Rutinas:   🟢 85% 🟡 10% 🔴 5%
   Tareas:    🟢 70% 🟡 20% 🔴 10%
   Objetivos: 3 de 3 cumplidos
   🏆 ¡Semana perfecta! +100 XP
```

### 7.6 Render de la cabecera

Helper `_render_level_header(conn) -> str`:

```python
def _render_level_header(conn) -> str:
    total = conn.execute(
        "SELECT COALESCE(SUM(xp_amount), 0) FROM xp_log"
    ).fetchone()[0]
    level = compute_level(total)
    if level == 0:
        return f"<b>Nivel 0</b>\n\n"
    medal = medal_for_level(level)
    return f"{medal} <b>Nivel {level}</b>\n\n"
```

Llamado al inicio de cada vista que la incluye. Se prepende al text final.

### 7.7 Notificación de subida en callbacks

En `bot._on_callback_query`, tras `handler(item_id)`:

```python
result = handler(item_id)
if isinstance(result, dict):
    level_before = result.get("level_before")
    level_after = result.get("level_after")
    if level_before is not None and level_after is not None and level_after > level_before:
        await context.bot.send_message(
            chat_id=ALLOWED_USER_ID,
            text=_render_level_up_message(level_before, level_after, result.get("xp_total_after")),
            parse_mode=ParseMode.HTML,
        )
```

`_render_level_up_message(before, after, xp_total)` devuelve el texto `🎉 ¡Nivel N desbloqueado!...` con transición de medalla si cambia de tramo.

### 7.8 Notificación de subida desde Claude

`brain.handle_message` ya despacha tools y devuelve la respuesta textual. Cuando una llamada a tool devuelve `level_after > level_before` en su result dict, hay que enviar el mensaje de subida.

Opciones:
1. Que `brain` lo detecte y lo añada al final de la respuesta de Claude.
2. Que el handler de mensajes en `bot.py` lo detecte mirando un campo cacheado (similar a `pop_pending_calendar_button`).

Mejor opción 2 para mantener `brain.py` limpio. Añadir:

```python
_pending_level_up: dict[int, tuple[int, int]] = {}  # user_id -> (level_before, level_after)

def record_level_up(user_id: int, level_before: int, level_after: int) -> None:
    _pending_level_up[user_id] = (level_before, level_after)

def pop_level_up(user_id: int) -> Optional[tuple[int, int]]:
    return _pending_level_up.pop(user_id, None)
```

Y en `brain.handle_message`, después de cada `tools.dispatch`, si el resultado tiene `level_after > level_before`, llamar a `record_level_up`.

En `bot._on_message`, tras enviar la respuesta de Claude, comprobar `pop_level_up` y enviar mensaje aparte si aplica.

## 8. Migración de esquema

Una sola migración aditiva en `db._migrate`:

```python
if "xp_log" not in tables:
    conn.execute("""
        CREATE TABLE xp_log (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            item_type     TEXT    NOT NULL,
            item_id       INTEGER NOT NULL DEFAULT 0,
            outcome       TEXT    NOT NULL,
            xp_amount     INTEGER NOT NULL,
            streak_bonus  INTEGER NOT NULL DEFAULT 0,
            awarded_at    TEXT    NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_xp_log_awarded_at
            ON xp_log(awarded_at)
    """)
```

Idempotente, no destructiva, no toca tablas existentes.

## 9. Edge cases

- **Reset de métricas**: las tablas `events`, `tasks`, `objectives`, `routine_completions` pueden ser modificadas por un reset (como hicimos hace unas horas). `xp_log` **NO se toca** en resets. El nivel es persistente.
- **Tarea recreada (`recreate_task`)**: la fila original tiene `outcome='missed'` y nunca dio XP. La nueva fila, al completarse, dará XP normal. Sin doble premio.
- **Desmarcar y volver a marcar**: la reversión inserta XP negativo, y la nueva marca inserta XP positivo. Si entre medias se evaluó día perfecto y se otorgó, el bonus se queda (filosofía "ya te lo gastaste"). El siguiente día perfecto sí se puede otorgar de nuevo si vuelve a darse.
- **Marcado en gracia tras desmarcar a tiempo**: el item había recibido XP on_time, se desmarca → reversión, se vuelve a marcar pero ahora ya está fuera de ventana → error `out_of_window` → no se vuelve a otorgar XP. Resultado neto: 0 XP. Razonable.
- **Eventos recurrentes con muchas instancias y `routine_completions` con outcome 'grace'**: cada completion da su propio XP (5 si on_time, 2 si grace, más streak bonus). No hay límite de cuántos XP se pueden ganar por una misma rutina a lo largo de los días — es por instancia.
- **Subida de varios niveles en una sola acción**: rara pero posible si hay un perfect_day o perfect_week + completion en el límite. Se notifica solo el nivel final.
- **Job nocturno `detect_missed_items`**: no afecta XP. Solo notifica perdidos.
- **Brain con `_MAX_TOOL_TURNS = 8`**: si el bucle se corta antes de procesar el resultado de la tool, el XP igual está insertado en BD (insertado dentro del tool dispatch). La notificación de subida puede perderse si el bucle se rompe entre el record_level_up y el envío. Aceptable: la subida queda registrada en `xp_log`, y el usuario lo verá en `/nivel` o en la próxima vista.

## 10. Tests

### 10.1 Unit tests — cálculo

- `_calculate_xp('task', 'on_time')` → `(10, 0)`.
- `_calculate_xp('task', 'grace')` → `(5, 0)`.
- `_calculate_xp('routine', 'on_time', streak_after=1)` → `(6, 1)`.
- `_calculate_xp('routine', 'on_time', streak_after=7)` → `(12, 7)`.
- `_calculate_xp('routine', 'on_time', streak_after=14)` → `(12, 7)` (cap).
- `_calculate_xp('routine', 'grace', streak_after=3)` → `(5, 3)` — base 2 + bonus 3.
- `_calculate_xp('objective', 'on_time')` → `(50, 0)`.

- `compute_level(0)` → 0.
- `compute_level(29)` → 0.
- `compute_level(30)` → 1.
- `compute_level(79)` → 1.
- `compute_level(80)` → 2.
- `compute_level(1000)` → 9 (porque `10*9*11=990`, `10*10*12=1200`).
- `compute_level(1200)` → 10.

- `medal_for_level(0)` → `''` (sin medalla).
- `medal_for_level(3)` → `'🥉'`.
- `medal_for_level(10)` → `'🥈'`.

### 10.2 Integration tests — flujo de marcado

- `complete_task` con `due_date=hoy`: outcome `on_time`, inserta fila xp_log con `item_type='task'`, `xp_amount=10`. Resultado dict incluye `xp_awarded=10`, `level_before=0`, `level_after=0`.
- `complete_task` que sube de nivel: completar varias tareas hasta acumular > 30 XP, comprobar `level_after=1` en la última.
- `mark_event_done` de rutina con racha 5: inserta xp_log con `xp_amount=10` (5 base + 5 bonus), `streak_bonus=5`.
- `mark_event_done` de rutina en gracia con racha 3: inserta xp_log con `xp_amount=5` (2 base + 3 bonus).
- `uncomplete_task` después de complete_task: inserta fila de reversión con `xp_amount=-10`. Total derivado = 0.
- `complete_task` que dispara día perfecto: comprobar que la fila `perfect_day` se inserta tras agotar todas las pending del día.
- Día perfecto **NO** se duplica: marcar todos, desmarcar uno, volver a marcar — solo una fila `perfect_day` para hoy.

### 10.3 Integration tests — semana perfecta

- `morning_summary` un lunes con objetivos de la semana pasada todos hechos (on_time o grace): inserta fila `perfect_week`, +100 XP. Texto incluye "🏆 ¡Semana perfecta! +100 XP".
- `morning_summary` un lunes con objetivos NO todos hechos: no inserta, no menciona.
- `morning_summary` un lunes sin objetivos definidos: no aplica.
- `morning_summary` un martes: no evalúa (solo lunes).
- Idempotencia: dos ejecuciones de morning_summary el mismo lunes → solo una fila `perfect_week`.

### 10.4 Tests de vistas

- `_render_level_header` con xp_log vacío → "**Nivel 0**".
- `_render_level_header` con xp_total=50 → "🥉 **Nivel 1**".
- `_render_level_header` con xp_total=15000 → "🥇 **Nivel N**" (N apropiado).
- `render_today_view` incluye la línea de cabecera al inicio del text.
- `render_metrics_view` incluye la línea de cabecera.
- `render_nivel_view(today, conn)` con datos: muestra nivel, XP, faltan, barra de progreso, breakdown por tipo.

### 10.5 Tests del comando `/nivel`

- Handler `_on_nivel` responde con HTML correcto.
- Auth gate funciona.

### 10.6 Tests de mensaje subida

- `_render_level_up_message(4, 5)` con cambio de tramo (5→6 nuevo tramo? No, 5 sigue en bronze; 6 entra en plata). Ajustar: `_render_level_up_message(5, 6)` → incluye transición 🥉 → 🥈.
- `_render_level_up_message(2, 3)` → solo nivel sin transición.

### 10.7 Gotchas conocidas

- `tools.now_iso` importado por nombre — los tests fijan fecha con `monkeypatch.setattr(date_utils, "today_madrid", ...)` y NO con `tools.now_iso`. El `awarded_at` se generará con la fecha real del sistema en tests, lo cual está OK si los tests no asumen una hora concreta. Si necesitan asumirla, monkeypatch a `date_utils.now_iso`.

## 11. Out of scope (explícito)

- **Milestones de racha** (7/30/100 días → bonus puntual). Pospuesto a fase 2.
- **Achievements / logros** (medallas por hitos específicos como "primera rutina creada", "10 tareas en una semana"). Pospuesto.
- **Reset de XP** (un comando para volver a nivel 0). YAGNI — el nivel es persistente por filosofía.
- **Multiplicadores temporales** (eventos especiales tipo "doble XP el día de tu cumpleaños"). Pospuesto.
- **Leaderboard / comparativa con otros usuarios**: el bot es de un solo usuario.
- **Avatar / título personalizado**: estética para más adelante.
- **Notificación de XP en cada marcado**: explícitamente rechazado en el brainstorming (ruido).

## 12. Resumen ejecutivo

Pablo gana XP por completar items, con bonus de racha en rutinas y dos premios contextuales (día perfecto +20, semana perfecta +100). XP se acumula sin perderse en una tabla `xp_log` append-only. El nivel se calcula al vuelo con fórmula cuadrática suave (`10×N×(N+2)`). Visible como cabecera discreta en todas las vistas; detalle vía nuevo comando `/nivel`. Al subir de nivel, el bot manda mensaje de celebración (incluyendo transición de medalla si cambia de tramo).

El coste técnico es contenido: una migración aditiva, helpers en `tools.py`, modificación de cada `complete_*` / `mark_*_done` / `uncomplete_*`, prependeo de cabecera en cuatro renderers existentes y dos nuevos, un comando nuevo, y dos checkpoints (día perfecto en cada marcado, semana perfecta en `morning_summary` del lunes).

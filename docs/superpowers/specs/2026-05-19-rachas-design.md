# Rachas (streaks) en rutinas — Diseño

**Fecha:** 2026-05-19
**Estado:** Diseño aprobado, pendiente de plan de implementación
**Sigue a:** rutinas en resúmenes (2026-05-19-rutinas-en-resumenes-design.md)

## Objetivo

Mostrar al usuario la racha actual y la mejor racha histórica de cada rutina recurrente. Es una mejora motivacional encima del feature "rutinas en resúmenes" desplegado hoy mismo: ahora que tenemos `routine_completions` con fechas de cumplimiento, podemos calcular streaks sin estructura nueva.

## Decisiones clave

- **Tres puntos de aparición**: `/hoy`, `/semana` y un nuevo comando `/rachas`.
- **Umbral visual**: el 🔥 solo aparece en `/hoy` y `/semana` cuando la racha actual es ≥ 2. Para racha 0 o 1, se omite (evita ruido visual). En `/rachas` se muestra siempre el valor exacto, incluido 0.
- **Semántica "alive"**: si la rutina toca hoy y aún no se ha hecho, la racha contada hasta ayer sigue viva. Si llega la medianoche sin marcarla, mañana es 0.
- **Mejor racha (best_streak)** = la racha más larga histórica para esa rutina. Si la racha actual la iguala, en `/rachas` se marca con 🏆.
- **Reutilización**: extendemos `routine_summary` para devolver también `current_streak` y `best_streak`. No se crea una tool nueva — Claude ya conoce `routine_summary`.
- **`/rachas` como slash command** en el menú de Telegram, paralelo a `/hoy`, `/semana`, `/pendientes`, `/objetivos`.

## Arquitectura

```
┌─────────────────────────┐
│   tools.routine_summary │  (mismo tool, ahora con streaks)
│                         │
│  scheduled_days         │  ← range-dependent (ya existía)
│  completed_days         │  ← range-dependent (ya existía)
│  current_streak         │  ← global, NUEVO
│  best_streak            │  ← global, NUEVO
└────────────┬────────────┘
             │ usa
             ▼
   _calculate_streaks(event_id, recurring_rule, conn)
             │
             ▼
   routine_completions  (tabla ya existe, no migración)
```

**Archivos:**

- **`tools.py`** — extender `routine_summary` con dos nuevos campos; función auxiliar privada `_calculate_streaks(event_id, recurring_rule, today, conn)` que devuelve `(current, best)`. Lógica de "fechas esperadas" reutiliza `_count_scheduled_days` o se crea un helper paralelo `_iter_expected_dates_descending`.
- **`brain.py`** — system prompt aprende cómo usar `current_streak`/`best_streak` en los resúmenes y el formato de `/rachas`.
- **`bot.py`** — añadir `/rachas` a `_SLASH_PROMPTS`, registrar `CommandHandler("rachas", ...)` en `main()`, añadir `BotCommand("rachas", ...)` en `_set_bot_commands`. Actualizar los prompts de `/hoy` y `/semana` para incluir streak donde aplique.

No hay cambios en BD ni migración: `routine_completions` ya tiene toda la información necesaria.

## Modelo de datos

Sin cambios. La función `_calculate_streaks` lee `routine_completions` directamente.

Nuevos campos añadidos al dict que devuelve `routine_summary`:

| Campo | Tipo | Significado |
|---|---|---|
| `current_streak` | int | Racha actual ≥ 0. Cuenta hasta el día expected más reciente; si ese día es hoy y aún pendiente, cuenta hasta ayer. |
| `best_streak` | int | Racha más larga histórica para esa rutina. ≥ `current_streak` siempre. |

## Algoritmo de streaks

### Racha actual

Pseudocódigo (Python):

```python
def _current_streak(event_id, rule, today, conn) -> int:
    """
    Cuenta hacia atrás desde la fecha expected más reciente.
    Si hoy es expected y NO está hecho, la racha sigue viva contando desde ayer expected.
    """
    completions = set(_get_completion_dates(event_id, conn))  # {"2026-05-19", ...}
    expected = _iter_expected_dates_descending(rule, today)   # generator: today, today-1d, ...

    streak = 0
    for d in expected:
        if d == today and d.isoformat() not in completions:
            # Hoy esperado y pendiente — vivo, no rompe
            continue
        if d.isoformat() in completions:
            streak += 1
        else:
            break
    return streak
```

Para DAILY: `_iter_expected_dates_descending` produce hoy, ayer, anteayer… para siempre.
Para WEEKLY:X: produce solo los días cuya weekday == X, descendientes desde la última ocurrencia ≤ hoy.

### Mejor racha histórica

```python
def _best_streak(event_id, rule, conn) -> int:
    """
    Recorre todas las completions ordenadas y cuenta la racha máxima
    sin "huecos" en el patrón esperado.
    """
    completions = sorted(_get_completion_dates(event_id, conn))  # ordenadas asc
    if not completions:
        return 0

    best = 1
    current = 1
    for i in range(1, len(completions)):
        prev = completions[i - 1]
        curr = completions[i]
        if _is_consecutive_expected(prev, curr, rule):
            current += 1
            best = max(best, current)
        else:
            current = 1
    return best
```

`_is_consecutive_expected`:
- DAILY → diff de 1 día.
- WEEKLY:X → diff de 7 días.

## Comportamiento por comando

### `/hoy`

El prompt sigue llamando `query_events` (para done por instancia). Añadimos un paso para llamar `routine_summary(today, today)` y extraer `current_streak` por evento. Cuando se renderiza la sección 🔁 RUTINAS, si `current_streak >= 2` se añade ` 🔥 N` al final de la línea.

### `/semana`

Ya llama `routine_summary(monday, sunday)`. Solo cambia el formato de la línea de cada rutina: `"{title} ({completed_days}/{scheduled_days} días)"` se enriquece con ` 🔥 N seguidos` cuando `current_streak >= 2`.

### `/rachas` (nuevo)

Nuevo entry en `_SLASH_PROMPTS["/rachas"]`. El prompt instruye:
1. Llamar `routine_summary(today, today)` (rango cualquiera, los streaks son globales).
2. Para cada rutina, formato:
   `• {title} — actual: {current_streak} · mejor: {best_streak}{ 🏆 si current == best y best > 0}`
3. Cierre motivador opcional, una frase.

Y `bot.main()` registra `CommandHandler("rachas", _make_slash_handler("/rachas"))`. `_set_bot_commands` añade `BotCommand("rachas", "Mis rachas")`.

## Edge cases

- **Rutina sin completions todavía**: `current_streak=0, best_streak=0`. En `/hoy` y `/semana` se omite 🔥. En `/rachas` aparece `actual: 0 · mejor: 0`.
- **Rutina hecha solo hoy**: `current_streak=1, best_streak=1`. Sin 🔥 (umbral 2). En `/rachas`: `actual: 1 · mejor: 1 🏆` (es récord aunque sea bajo).
- **WEEKLY cuyo día NO es hoy**: la fecha expected más reciente fue el último weekday X anterior. La racha mira ahí.
- **WEEKLY cuyo día ES hoy pero aún pendiente**: vivo, racha contada hasta el lunes anterior.
- **Zona horaria**: `today_madrid()` es la fuente de verdad para "hoy" (consistente con el resto del sistema).
- **Cambio de regla recurring de un evento**: si se cambia `recurring_rule` (poco probable, no hay tool actual para ello), los streaks pasados se mantienen pero su patrón de "consecutivo" cambia. Aceptable, no es escenario real.

## Tests

1. `_current_streak` DAILY: 3 días seguidos hasta hoy completados → 3.
2. `_current_streak` DAILY: 3 días seguidos hasta ayer, hoy pendiente → 3 (alive).
3. `_current_streak` DAILY: ayer no hecho, anteayer sí → 0 (broken).
4. `_current_streak` DAILY: hoy es el primer día y está hecho → 1.
5. `_current_streak` WEEKLY:MON con 2 lunes consecutivos hechos, hoy es miércoles → 2.
6. `_current_streak` WEEKLY:MON con último lunes no hecho → 0.
7. `_current_streak` WEEKLY:MON hoy es lunes pendiente, los 2 anteriores hechos → 2 (alive).
8. `_best_streak` DAILY con histórico de 5 seguidos, luego salto, luego 3 seguidos → 5.
9. `_best_streak` WEEKLY:MON con 3 lunes seguidos, salto, 2 lunes seguidos → 3.
10. `_best_streak` sin completions → 0.
11. `routine_summary` ahora incluye `current_streak` y `best_streak` en cada dict.
12. `/rachas` aparece en `_SLASH_PROMPTS` y su prompt contiene "RACHAS".
13. `/rachas` está registrado como CommandHandler en `bot.main` (test indirecto vía `_make_slash_handler`).
14. String-match en system prompt de `brain.py`: incluye "🔥" y referencia a streaks.

## Criterios de éxito

- En `/hoy`, si he hecho una rutina 3 días seguidos, veo `🔥 3` al final de su línea.
- En `/hoy`, una rutina sin racha (0 o 1) no muestra 🔥.
- En `/semana`, las líneas de rutinas muestran `🔥 N seguidos` cuando N ≥ 2.
- En `/rachas`, veo todas mis rutinas con su actual y su récord, con 🏆 cuando son lo mismo.
- A las 23:50 sin haber hecho la rutina de hoy, sigo viendo la racha de ayer (alive). A las 00:30 del día siguiente, si no la hice, ya es 0.

## Fuera del alcance

- ❌ Notificaciones especiales por hitos ("¡llevas 30 días!").
- ❌ Gráficos de evolución de rachas.
- ❌ Comparativa entre rutinas o leaderboards.
- ❌ "Pausar" o "freezar" una racha por un día concreto.
- ❌ Streaks para eventos no recurrentes (no aplica).
- ❌ Streaks para tareas u objetivos (no aplica).

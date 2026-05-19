# Rutinas en los resúmenes — Diseño

**Fecha:** 2026-05-19
**Estado:** Diseño aprobado, pendiente de plan de implementación
**Sigue a:** matutino + recordatorios proactivos (2026-05-12-matutino-recordatorios-design.md)

## Objetivo

Que las rutinas (eventos recurrentes) tengan un sitio propio en los resúmenes diarios y semanales, y que se puedan marcar como hechas día a día sin que desaparezcan para siempre.

Actualmente los eventos recurrentes (con `recurring_rule` no nulo) aparecen mezclados con los eventos puntuales del día, y no se pueden marcar como hechos: al usar `mark_event_done` se ponen `done=1` y dejan de salir nunca más.

## Decisiones clave

- **Nueva sección `🔁 RUTINAS`** en `/hoy`, `/semana` y el saludo matutino. Aglutina las rutinas (DAILY y WEEKLY que toquen ese rango).
- **Marcar una rutina como hecha registra "hecha hoy", no "hecha para siempre"**. Mañana vuelve a aparecer pendiente.
- **`/semana` muestra conteo `X/N días`** por rutina (motivación visual tipo racha).
- **`mark_event_done` se hace inteligente**: detecta si el evento es recurrente y enruta a la tabla correcta. Sin tools nuevos, sin cambio en la interfaz que ve Claude.
- **Zona horaria Madrid** para todos los cálculos de "hoy" / "esta semana". Se arregla el bug latente de `datetime.now()` sin tz en el contenedor UTC de Fly.

## Arquitectura

Una nueva tabla `routine_completions` para registrar cuándo se ha cumplido cada instancia de una rutina:

```
events                          routine_completions
──────                          ───────────────────
id (PK)                ─┐       id (PK)
title                   │       event_id ──── FK → events.id (ON DELETE CASCADE)
datetime                │       completion_date  (TEXT "YYYY-MM-DD")
recurring_rule          │       created_at       (TEXT ISO)
…                       │
done                    │       UNIQUE(event_id, completion_date)
```

**Archivos afectados:**

- **`db.py`** — esquema y migración añaden la tabla `routine_completions` con PK, FK con ON DELETE CASCADE y UNIQUE compuesto.
- **`tools.py`** — `mark_event_done` enruta según `recurring_rule`. Nueva función auxiliar `complete_routine(event_id, date)` interna (no expuesta como tool a Claude).
- **`tools.py`** — `query_events` opcionalmente devuelve un campo derivado `done_today` para recurrentes, basado en si hay fila en `routine_completions` con `completion_date = hoy_madrid`. Es la pieza que permite a Claude distinguir rutinas pendientes/tachadas hoy.
- **`brain.py`** — el system prompt aprende a usar la sección 🔁 RUTINAS en los resúmenes, basándose en `done_today`/`recurring_rule`.
- **`bot.py`** — los prompts de `/hoy` y `/semana` incluyen los pasos necesarios para construir la sección.
- **`scheduler.py`** — el prompt de `morning_summary` incluye también la sección.
- **`date_utils.py`** — nuevo helper `today_madrid()` (y `now_madrid()` si hace falta) que devuelve la fecha "hoy" en zona horaria Europe/Madrid, no UTC.

## Modelo de datos

Nueva tabla:

```sql
CREATE TABLE IF NOT EXISTS routine_completions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id         INTEGER NOT NULL,
    completion_date  TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    UNIQUE(event_id, completion_date),
    FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_routine_completions_date
    ON routine_completions(completion_date);
```

Importante: `PRAGMA foreign_keys = ON` debe activarse en cada conexión SQLite (no es default en SQLite). Si no se hace, ON DELETE CASCADE no se aplica.

## Comportamiento

### Marcar una rutina como hecha

Cuando el usuario dice *"ya hice las flexiones"*:

1. Claude llama a `mark_event_done(event_id)` como ahora.
2. La función comprueba si `events.recurring_rule IS NOT NULL`:
   - **Sí (rutina):** intenta INSERT en `routine_completions` con `event_id`, `completion_date = today_madrid()`, `created_at = now_iso()`. Si choca con el UNIQUE → atrapamos la `IntegrityError` y devolvemos `{"id": event_id, "already_done_today": True}`.
   - **No (evento puntual):** `UPDATE events SET done=1 WHERE id=?` (comportamiento actual intacto).
3. Devuelve dict con la info → Claude responde con frase de ánimo o "ya estaba marcado".

### `/hoy` con sección RUTINAS

1. `query_events(today_madrid_00, today_madrid_2359, include_done=true)` devuelve todo lo del día — eventos puntuales **y** instancias recurrentes expandidas. Para los recurrentes, cada instancia trae `done_today` (bool) calculado contra `routine_completions`.
2. Claude construye:
   - **📅 HOY**: eventos sin `recurring_rule`, con `done=0`.
   - **🔁 RUTINAS**: eventos con `recurring_rule`. Si `done_today=true` → con `<s>` (tachado); si no → normales.
   - **📝 PENDIENTES**: `list_tasks(include_done=false)`.
   - **✅ COMPLETADO HOY**: eventos no recurrentes con `done=1` + rutinas con `done_today=true` (tachadas) + tareas con `done_at` de hoy.

Si una sección está vacía, se omite (regla existente).

### `/semana` con conteo

1. `query_events(lunes_madrid, domingo_madrid_2359)` da los eventos no recurrentes y las instancias recurrentes de la semana.
2. Nueva función `count_routine_completions(event_id, date_from, date_to)` en `tools.py` (o consulta directa desde el prompt vía `query_events` con un campo derivado `completions_in_range`).
3. Claude construye:
   - **📅 ESTA SEMANA**: eventos puntuales `done=0`.
   - **🎯 OBJETIVOS**: como ahora.
   - **🔁 RUTINAS**: una línea por rutina activa esta semana con `"{título} (X/N días)"` donde N = nº de instancias programadas en la semana (7 para DAILY, 1 para WEEKLY:LUN, etc.) y X = filas en `routine_completions` para esa rutina en el rango.
   - **✅ COMPLETADO**: eventos puntuales `done=1` + tareas `done_at` de la semana. **No** se duplican las rutinas aquí (su estado ya está en la sección RUTINAS).

### Saludo matutino

Mismo formato que `/hoy`. El prompt de `scheduler.morning_summary` se actualiza para incluir la sección 🔁 RUTINAS.

## Zona horaria

Bug latente: `datetime.now()` en el contenedor de Fly (UTC) considera "hoy" en UTC, no en Madrid. A las 00:30 Madrid (= 22:30 / 23:30 UTC en verano / invierno) "hoy" todavía sería el día anterior. Esto rompería:
- El cálculo de `completion_date` al marcar rutinas tarde por la noche.
- El cálculo de "hoy" en `/hoy`.
- El cálculo de "esta semana" en `/semana`.

**Fix:** nuevo helper en `date_utils.py`:

```python
import pytz
from datetime import datetime, date

_MADRID = pytz.timezone("Europe/Madrid")

def now_madrid() -> datetime:
    return datetime.now(_MADRID)

def today_madrid() -> date:
    return now_madrid().date()
```

Todos los cálculos de "hoy" / "esta semana" en `tools.py`, `scheduler.py` y donde haga falta pasan por estos helpers. Los `datetime.now()` puros existentes que afecten a lógica de fechas se reemplazan.

(Los `datetime` guardados en BD para eventos siguen siendo ISO sin tz — son fechas locales del usuario, ya estaban funcionando así.)

## Migración

Idempotente en `db._migrate`:

1. Si tabla `routine_completions` no existe → crearla.
2. Si índice `idx_routine_completions_date` no existe → crearlo.
3. Datos existentes no requieren backfill: la tabla nueva nace vacía y se llena según el usuario marca rutinas.

`PRAGMA foreign_keys = ON` se añade al contextmanager `db.connect()` para que afecte a TODAS las conexiones.

## Limitaciones aceptadas

- **Recordatorios proactivos para rutinas siguen sin funcionar** ([[pending-recurring-reminders]] — fuera del alcance de esta iteración). Las rutinas aparecen en resúmenes pero no disparan ⏰ ni 📅. Una iteración futura puede aprovechar `routine_completions` para flags por instancia.
- **No hay UI de "deshacer marcar como hecha"**: si te equivocas y dices "ya hice X" cuando no, tendrías que decir explícitamente *"borra la marca de hoy de X"* y Claude tendrá que hacer DELETE. Si se vuelve un patrón frecuente, en una iteración futura se añade `unmark_routine_today` como tool.
- **WEEKLY soporta un solo día por evento** (ya existente, sin cambios). Para "lunes, miércoles y viernes" siguen siendo 3 eventos separados.
- **Histórico de rachas**: la tabla guarda histórico pero no hay vista todavía. Si más adelante quieres "llevas 12 días seguidos con las flexiones", ya están los datos.

## Tests

1. `add_event` + `mark_event_done` en evento puntual → `done=1` (comportamiento intacto).
2. `add_event` con `recurring_rule="DAILY"` + `mark_event_done` → crea fila en `routine_completions`, NO toca `done` en `events`.
3. `mark_event_done` en rutina ya marcada hoy → devuelve `already_done_today=True`, no duplica.
4. `delete_event` de una rutina con completions → CASCADE borra las completions (verificar con `PRAGMA foreign_keys=ON`).
5. `today_madrid()` con `monkeypatch` simulando contenedor UTC a las 22:30 UTC del 2026-05-19 → devuelve `date(2026, 5, 20)` (porque en Madrid son las 00:30).
6. `query_events` para un rango de hoy devuelve rutinas DAILY con campo `done_today` reflejando estado real.
7. `count_routine_completions` (o equivalente) sobre rango semanal cuenta correctamente.
8. Migración `_migrate` crea `routine_completions` idempotentemente.
9. Smoke test del prompt: comprobar que el system prompt actualizado pide la sección RUTINAS donde corresponde (test de string match, no de LLM).

## Criterios de éxito

- En `/hoy` veo una sección "🔁 RUTINAS" con mis 3 rutinas diarias.
- Si digo "ya hice las flexiones", esa rutina aparece tachada en RUTINAS y también en COMPLETADO HOY.
- Mañana a las 00:00 Madrid (o cuando vuelva a pedir `/hoy`), las flexiones reaparecen pendientes.
- En `/semana` veo "50 flexiones (X/7 días)" con X siendo los días en que la marqué.
- Marcar una rutina dos veces el mismo día no rompe nada; el bot avisa que ya estaba marcada.
- Si borro la rutina, su historial de completions desaparece.
- A las 23:50 Madrid sigo viendo la rutina pendiente si no la he marcado (el día no ha cambiado aún).

## Fuera del alcance

- ❌ Recordatorios proactivos para rutinas (⏰ y 📅) — sigue siendo gap conocido.
- ❌ Vista de rachas / streaks ("llevas X días con la rutina").
- ❌ Tool para deshacer marca de hoy (se hace via DELETE explícito si hace falta).
- ❌ Rutinas con múltiples días en una sola fila ("WEEKLY:MON,WED,FRI").
- ❌ Rutinas con frecuencias no soportadas (mensual, cada N días, etc.).
- ❌ Notificaciones de cumplimiento de rutina (ej. "¡5 días seguidos con flexiones!").

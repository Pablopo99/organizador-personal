# Recordatorios personalizados — Design Spec

**Fecha:** 2026-06-01
**Estado:** propuesto (pendiente aprobación de Pablo)
**Spec previa relacionada:** ninguna directa (extiende `scheduler.check_reminders` existente)

## Problema

Hoy todo evento puntual (no recurrente) recibe automáticamente dos avisos: uno ~24h antes y otro ~1h antes. No hay forma de pedir más, ni de pedir uno a un offset arbitrario ("avísame 30 min antes" o "avísame 1 semana antes").

Pablo quiere poder decirle a Claude en lenguaje natural cuándo quiere ser avisado, además de los dos avisos por defecto, y para tantos offsets como considere por cada evento.

## Objetivos

- Pablo puede añadir uno o varios recordatorios custom a un evento puntual al crearlo: "Tengo cita el viernes a las 5, avísame 30 min antes".
- Pablo puede añadir recordatorios custom a un evento ya existente: "Avísame 30 min antes de la cita con María".
- Si un evento tiene **cualquier** recordatorio custom, los dos defaults (24h y 1h antes) **no se mandan** para ese evento. Pablo toma el control total. Si no añade ningún custom, los defaults siguen funcionando como hoy.
- Soporta múltiples recordatorios por evento.

## No-objetivos (fuera de alcance)

- Recordatorios custom para rutinas/eventos recurrentes (descarte explícito: Pablo prefiere mantener las rutinas sin avisos).
- Eliminar recordatorios desde lenguaje natural ("quita el de 30 min"). Si se borra el evento, sus recordatorios se borran en cascada — eso sí está cubierto.
- Listar los recordatorios de un evento como tool ("¿qué avisos tiene la cita?"). Pablo no lo pidió.
- Editar/modificar un recordatorio existente. Si se equivoca al añadirlo, lo borra rehaciendo el evento o añade uno nuevo encima.
- UI de botones inline para gestionar recordatorios. Todo se hace por lenguaje natural.

## Modelo de datos

### Nueva tabla `event_reminders`

```sql
CREATE TABLE event_reminders (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id        INTEGER NOT NULL,
    offset_minutes  INTEGER NOT NULL,
    sent            INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT    NOT NULL,
    FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE
);

CREATE INDEX idx_event_reminders_event ON event_reminders(event_id);
CREATE INDEX idx_event_reminders_pending ON event_reminders(sent, event_id);
```

- `offset_minutes`: minutos antes del evento. Entero positivo. 30 = 30 min antes; 60 = 1h; 1440 = 1 día; 10080 = 1 semana.
- `sent`: 0 = pendiente, 1 = ya enviado. Una vez enviado no se reenvía (igual que los flags `reminder_1d_sent`/`reminder_1h_sent` actuales).
- FK con `ON DELETE CASCADE`: si se borra el evento, sus recordatorios desaparecen.
- Migración idempotente (`if "event_reminders" not in tables`).

### Sin cambios en `events`

Los flags `reminder_1d_sent` y `reminder_1h_sent` siguen como están — los avisos por defecto no migran a la tabla nueva.

## Tools

### Nueva: `add_event_reminder(event_id, minutes_before)`

Registrada en `TOOL_DEFINITIONS` (Claude puede llamarla).

Comportamiento:
- Si `event_id` no existe → `{"error": "not_found"}`.
- Si el evento es recurrente (`recurring_rule IS NOT NULL`) → `{"error": "event_is_recurring"}`. Se explica en el system prompt para que Claude no lo intente.
- Si `minutes_before <= 0` → `{"error": "invalid_offset"}`.
- Si el evento ya está marcado como hecho (`done = 1`) → `{"error": "event_already_done"}`.
- Calcula `reminder_time = event.datetime - timedelta(minutes=minutes_before)`.
- Si `reminder_time <= now`:
  - Inserta la fila con `sent = 1` (ya marcado como enviado, para no reenviarlo después).
  - Devuelve `{"event_id": ..., "offset_minutes": ..., "fires_immediately": True}` para que el bot pueda mandar el aviso ahora mismo.
- Si `reminder_time > now`:
  - Inserta con `sent = 0`.
  - Devuelve `{"event_id": ..., "offset_minutes": ..., "fires_immediately": False}`.
- Idempotencia: si ya existe una fila con mismo `event_id` + `offset_minutes`, no duplica — devuelve `{"already_exists": True}`.

### Modificada: `add_event(...)`

Añade un parámetro opcional `reminders: list[int]` (lista de offsets en minutos). Si se pasa, tras insertar el evento llama internamente a `add_event_reminder` por cada offset.

Permite a Claude resolver "tengo cita el viernes a las 5, avísame 30 min antes" en una sola tool call:

```json
{"name": "add_event", "arguments": {
    "title": "Cita",
    "datetime": "2026-06-05T17:00:00",
    "category": "personal",
    "reminders": [30]
}}
```

**Comportamiento con offsets inválidos durante creación**: si alguno de los `reminders` es `<= 0`, el evento se crea igual y ese recordatorio concreto se ignora silenciosamente (no se inserta fila ni se aborta la creación del evento). El resto de offsets válidos sí se insertan. La tool devuelve adicionalmente `reminders_added` (lista de los que entraron) y `reminders_skipped` (lista de offsets descartados), para que Claude pueda informar al usuario si fuera relevante.

## `scheduler.check_reminders` — extensión

Hoy el job corre cada 5 min y para cada evento próximo (<26h) revisa los dos flags fijos. Se cambian dos cosas:

**1. Filtrar defaults cuando el evento tenga customs.** La consulta que selecciona eventos próximos para los avisos por defecto (los del `reminder_1d_sent`/`reminder_1h_sent`) añade un guard:

```sql
WHERE done = 0
  AND recurring_rule IS NULL
  AND datetime >= ? AND datetime <= ?
  AND NOT EXISTS (
      SELECT 1 FROM event_reminders WHERE event_id = events.id
  )
```

Si el evento tiene cualquier fila en `event_reminders`, los defaults se omiten silenciosamente (no se envía nada y los flags `reminder_*_sent` quedan como están — si Pablo borra el evento, no importa; si en el futuro hubiera una operación de "borrar todos los customs", los defaults volverían a activarse automáticamente porque el `NOT EXISTS` deja de cumplirse).

**2. Añadir bloque para customs.** Se añade un bloque equivalente para `event_reminders`:

```python
# Recordatorios custom pendientes cuyo momento está dentro de la ventana
rows = conn.execute("""
    SELECT er.id, er.event_id, er.offset_minutes,
           e.title, e.datetime
    FROM event_reminders er
    JOIN events e ON e.id = er.event_id
    WHERE er.sent = 0
      AND e.done = 0
      AND e.recurring_rule IS NULL
""").fetchall()

for r in rows:
    event_dt = datetime.fromisoformat(r["datetime"])
    fire_time = event_dt - timedelta(minutes=r["offset_minutes"])
    if abs((fire_time - now).total_seconds()) <= 5 * 60:  # ventana ±5 min
        await _send_custom_reminder(...)
        # marcar sent=1
```

- **Ventana ±5 min** porque el job corre cada 5. Si la fila se añade a las 14:32 con offset 30 min y el evento es a las 15:00, el primer tick que la mira es a las 14:35 → fire_time = 14:30 → diff de 5 min → se manda. (Edge: si el job se retrasa, podría perderse; igual que ya pasa con los defaults. No es nuevo problema.)
- **`fires_immediately` desde la tool**: cuando `add_event_reminder` devuelve `fires_immediately=True`, el bot tiene que mandar el aviso por su cuenta (porque el scheduler no va a tocarlo, está `sent=1`). Esto se hace en el callback del flujo de Claude (similar a cómo `bot.py` maneja la notificación de subida de nivel).

## Formato del mensaje

```
⏰ En {pretty} tienes: <b>{title}</b>
```

Donde `pretty` se formatea según el offset:

| offset_minutes | pretty   |
|----------------|----------|
| < 60           | "X min"  |
| 60             | "1 h"    |
| 120-1439       | "X h"    |
| 1440           | "1 día"  |
| 2880-10079     | "X días" |
| 10080          | "1 semana" |
| > 10080        | "X días" (no compongo semanas+días)|

(Helper `_format_offset(minutes) -> str` en `scheduler.py` o `views.py`.)

## System prompt — regla nueva

Añadir en `brain.py`, después de las reglas de creación de eventos:

> **Recordatorios custom**: si Pablo añade "avísame X antes" a una petición de evento, llama a `add_event` con `reminders=[X_en_minutos]`. Si Pablo dice "avísame X antes de [evento ya existente]", busca el evento con `query_events` y llama a `add_event_reminder(event_id, X_en_minutos)`. Convierte tú el lenguaje natural a minutos: "30 min"=30, "1 hora"=60, "3 horas"=180, "1 día"=1440, "2 días"=2880, "1 semana"=10080. NO uses recordatorios custom en eventos recurrentes/rutinas. Confirma con una frase corta tipo "Hecho, te aviso 30 min antes" o "Recordatorio puesto, te aviso 3h antes".

## Bot — manejo de `fires_immediately`

Cuando `add_event_reminder` o `add_event` (vía `reminders`) devuelven una fila con `fires_immediately=True`, hay que mandar el aviso en el momento. Patrón propuesto, paralelo al de niveles:

- `brain.py` lleva un `_pending_immediate_reminders: dict[user_id, list[(event_id, offset_minutes, title)]]`.
- Cuando una tool devuelve `fires_immediately`, brain anota la entrada.
- `bot.py` en `_on_message`/`_on_voice` consume las entradas vía `pop_immediate_reminders(user_id)` después de enviar la respuesta normal de Claude y manda un mensaje por cada una con el mismo formato que el job (`⏰ En X tienes: <b>title</b>`).

(Para callbacks, Pablo no llega por aquí — sólo crea recordatorios por lenguaje natural.)

## Tests

Nuevos tests, todos en TDD:

**`tests/test_db.py`**
- `event_reminders` tabla existe con columnas y FK.

**`tests/test_tools_reminders.py`** (nuevo)
- `add_event_reminder` inserta fila con sent=0 cuando el momento está en el futuro.
- `add_event_reminder` inserta con sent=1 y `fires_immediately=True` cuando el momento ya pasó.
- `add_event_reminder` con offset <= 0 → error.
- `add_event_reminder` con evento recurrente → error `event_is_recurring`.
- `add_event_reminder` con evento done=1 → error `event_already_done`.
- `add_event_reminder` con event_id inexistente → error `not_found`.
- `add_event_reminder` idempotente: misma (event_id, offset) dos veces → la 2ª devuelve `already_exists`, no duplica.
- `add_event` con `reminders=[30, 180]` crea evento + 2 filas en `event_reminders`.
- `CASCADE`: borrar el evento elimina sus recordatorios.

**`tests/test_scheduler.py`**
- `check_reminders` manda aviso cuando el momento de un custom está dentro de la ventana ±5 min y marca `sent=1`.
- `check_reminders` NO reenvía un recordatorio ya `sent=1`.
- `check_reminders` ignora recordatorios de eventos `done=1`.
- `check_reminders` ignora recordatorios fuera de la ventana.
- **Defaults OFF cuando hay customs**: un evento con `event_reminders` no recibe ni el aviso 1d ni el 1h, aunque caigan dentro de la ventana. Y un evento SIN `event_reminders` sigue recibiendo defaults como siempre (regresión cubierta por tests existentes).

**`tests/test_brain.py`**
- `_pending_immediate_reminders` se rellena/consume correctamente (paralelo a `_pending_level_up`).

**`tests/test_bot.py`**
- `_on_message` envía el mensaje de recordatorio inmediato tras la respuesta normal cuando hay entradas pendientes.

## Migración y compatibilidad

- Migración aditiva: nueva tabla `event_reminders`. Los flags actuales `reminder_1d_sent`/`reminder_1h_sent` no se tocan.
- Eventos existentes en producción no quedan afectados — siguen recibiendo sus dos avisos.
- Pablo puede empezar a usar la nueva funcionalidad desde el primer despliegue.

## Riesgos y consideraciones

1. **Rate limit ya pegado**: Pablo está cerca del techo de Sonnet en Anthropic. Esta feature añade ~1 llamada de Claude por petición (no aumenta carga estructural). Más relevante: cuando suene un recordatorio el bot solo envía un mensaje de Telegram, no llama a Claude.
2. **Defaults desactivados cuando hay customs**: si Pablo añade un solo custom para un evento, pierde los defaults (1d + 1h) automáticamente. Esto es la conducta esperada y la confirmó él, pero el coste es que para recuperar los defaults tendría que borrar todos los customs (operación no soportada hoy). En la práctica el problema es marginal: si Pablo se equivoca, recrea el evento.
3. **El job corre cada 5 min**: precisión de los avisos es ±5 min, no exacta. Es el mismo comportamiento que hoy.
4. **Si Fly reinicia justo en la ventana de un recordatorio**, podría perderse igual que ahora (no es regresión, pero merece flag).

## Métrica de éxito

Después del despliegue:
- Pablo prueba "tengo X mañana a las Y, avísame 30 min antes" → al día siguiente recibe el aviso 25-35 min antes.
- Pablo prueba "avísame 1 semana antes de [evento existente]" → 1 semana antes recibe el aviso.
- No hay duplicados de aviso por la misma fila (idempotencia).

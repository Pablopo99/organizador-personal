# Sincronización con Google Calendar — Diseño

**Fecha:** 2026-05-28
**Estado:** Diseño aprobado, pendiente de plan de implementación

## Objetivo

Permitir a Pablo enviar eventos del bot a su Google Calendar **de forma explícita** (no automática), manteniendo el bot como fuente de verdad. Si Pablo modifica o borra un evento sincronizado en el bot, el cambio se propaga a Calendar.

## Decisiones clave

- **Sentido único**: bot → Google Calendar. Los eventos creados o modificados directamente en Calendar **no** aparecen en el bot. Sin lecturas, sin polling de Calendar.
- **On-demand, no automático**: solo los eventos que Pablo marque explícitamente se sincronizan.
- **Dos formas de marcar un evento para Calendar**:
  - **Lenguaje natural**: *"apunta dentista mañana 10 y mételo en el calendario"* / *"pásalo a Google Calendar"* / variantes. Claude detecta la intención y llama a la tool.
  - **Botón inline**: cada vez que el bot crea un evento via chat, su mensaje de confirmación lleva un botón `📅 Mandar a Calendar`. Tap → se sincroniza.
- **Updates y deletes propagan**: si Pablo edita la fecha o el título de un evento sincronizado en el bot, Calendar se actualiza. Si lo borra, Calendar lo borra.
- **Calendario destino**: el calendario principal de la cuenta de Google del usuario.
- **Auth OAuth 2.0** con flujo web: Pablo autoriza una vez en su navegador y el bot guarda los tokens (access + refresh) en SQLite. Los renueva automáticamente.
- **Solo eventos puntuales en MVP**: rutinas (eventos recurrentes con `recurring_rule`), tareas y objetivos NO se sincronizan inicialmente. Si Pablo lo pide explícitamente, podemos extender después.

## Configuración manual (one-off por Pablo)

Ya completado el 2026-05-28:

1. Proyecto creado en Google Cloud Console.
2. Google Calendar API habilitada.
3. Pantalla de consentimiento OAuth configurada (Externa, Testing mode, scope `https://www.googleapis.com/auth/calendar.events`, Pablo añadido como test user).
4. OAuth 2.0 client creado tipo "Aplicación web" con redirect URI `https://mi-secretaria-pablo.fly.dev/oauth/callback`.
5. Credenciales (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`) guardadas como secrets de Fly (staged, pendientes de deploy).

## Arquitectura

```
┌─────────────────────────────────────────────────────────────┐
│  bot.py                                                      │
│  - Handler de mensajes y comandos (sin cambios)              │
│  - Nuevo endpoint /oauth/callback (en siri_server o aparte)  │
└──────────┬───────────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────────┐
│  brain.py                                                    │
│  - Nuevas tools que Claude puede invocar                     │
└──────────┬───────────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────────┐
│  tools.py                                                    │
│  - add_event y update_event llaman a gcal_sync si procede   │
└──────────┬───────────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────────┐
│  gcal_sync.py (nuevo)                                        │
│  - oauth_start_url() → genera URL de autorización            │
│  - exchange_code(code) → intercambia code por tokens         │
│  - ensure_valid_token() → renueva con refresh_token si toca  │
│  - push_event(event_dict) → POST a Calendar API              │
│  - update_event(gcal_event_id, fields)                       │
│  - delete_event(gcal_event_id)                               │
└─────────────────────────────────────────────────────────────┘
```

**Archivos:**

- **`gcal_sync.py`** (nuevo) — toda la lógica de Calendar aislada en un módulo. Funciones puras testeables; las llamadas a Google se mockean en tests.
- **`db.py`** — esquema y migración para:
  - Nueva columna `gcal_event_id TEXT` en tabla `events` (NULL si no sincronizado).
  - Nueva tabla `oauth_tokens(provider, access_token, refresh_token, expires_at, created_at)` con `provider` como PK (solo una fila por proveedor; aquí `provider='google'`).
- **`tools.py`** — modificaciones:
  - `add_event` acepta nuevo flag opcional `sync_to_calendar: bool = False`. Si `True`, llama a `gcal_sync.push_event` después de insertar y guarda el `gcal_event_id` resultante en la fila.
  - `update_event` mira el `gcal_event_id` del evento; si no es NULL, llama a `gcal_sync.update_event` con los campos cambiados.
  - `delete_event` mira el `gcal_event_id`; si no es NULL, llama a `gcal_sync.delete_event` antes de borrar la fila local.
  - Nueva tool `push_event_to_calendar(event_id: int)` que Claude puede llamar cuando Pablo pide explícitamente sincronizar un evento existente.
- **`bot.py`** — modificaciones:
  - Nuevo handler en aiohttp para `/oauth/callback` que recibe el code, intercambia por tokens y los guarda. Responde con un HTML simple de éxito ("Autorización completada, vuelve a Telegram").
  - El mensaje de confirmación de `add_event` añade un botón inline `📅 Mandar a Calendar` cuando el evento NO se haya sincronizado todavía. Callback `gcs:{event_id}` (gcal sync, view-letter irrelevante aquí).
  - Nuevo callback handler `gcs` que llama a `tools.push_event_to_calendar(event_id)` y edita el mensaje quitando el botón y añadiendo `✅` o un emoji similar.
- **`brain.py`** — el system prompt aprende que existe la tool `push_event_to_calendar` y describe las frases naturales que la disparan (*"al calendario"*, *"a Google Calendar"*, etc.). Mantiene el comportamiento de chat normal cuando no se pide sync.
- **`config.py`** — añade `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` (no `_require` — el bot debe arrancar sin Calendar si no están).
- **`requirements.txt`** — `google-api-python-client>=2.0`, `google-auth>=2.0`, `google-auth-oauthlib>=1.0`.

## Modelo de datos

**Nueva columna en `events`**:

```sql
ALTER TABLE events ADD COLUMN gcal_event_id TEXT;
```

NULL si el evento no se ha sincronizado nunca. Contiene el `id` del evento en Calendar si está sincronizado.

**Nueva tabla `oauth_tokens`**:

```sql
CREATE TABLE IF NOT EXISTS oauth_tokens (
    provider      TEXT PRIMARY KEY,
    access_token  TEXT NOT NULL,
    refresh_token TEXT NOT NULL,
    expires_at    TEXT NOT NULL,
    created_at    TEXT NOT NULL
);
```

`provider='google'` para Google Calendar. PK garantiza una sola fila por proveedor.

## Flujo OAuth en runtime

**Primera autorización**:

1. Pablo dice "conecta con calendar" (o intenta usar Calendar antes de autorizar).
2. Claude llama a una tool `connect_calendar()` que devuelve la URL de autorización generada por `gcal_sync.oauth_start_url()`.
3. El bot manda en Telegram: *"Autoriza al bot a acceder a tu Calendar: [enlace]"*.
4. Pablo toca → navegador → consent screen de Google → autoriza.
5. Google redirige a `https://mi-secretaria-pablo.fly.dev/oauth/callback?code=...&state=...`.
6. Endpoint `/oauth/callback`:
   - Llama a `gcal_sync.exchange_code(code)` que hace POST a Google con `client_id + client_secret + code` y obtiene `access_token`, `refresh_token`, `expires_in`.
   - Guarda en `oauth_tokens` (provider='google').
   - Responde con HTML simple: *"Calendar conectado ✅. Vuelve a Telegram."*
7. Bot manda mensaje en Telegram: *"Calendar conectado ✅"*.

**Renovación de tokens**:

Antes de cada llamada a la API, `ensure_valid_token()` mira `expires_at`. Si está a punto de caducar (< 5 min), hace POST a Google con `refresh_token` para obtener nuevo `access_token` y actualiza la fila.

**Errores de auth (token revocado en Google, etc.)**:

Si una llamada devuelve 401 y `ensure_valid_token` no consigue renovar, el bot manda a Telegram: *"Se ha perdido la conexión con Calendar. Di 'conecta con calendar' para reautorizar."* y borra los tokens viejos.

## Sincronización: detalles

### Crear evento (push)

`gcal_sync.push_event(event)` recibe el dict del evento del bot:
```python
{
    "title": "Dentista",
    "datetime": "2026-05-29T10:00:00",
    "notes": "Calle Doctor San Juan 26",
    "category": "medical",
}
```

Hace POST a `https://www.googleapis.com/calendar/v3/calendars/primary/events` con body:
```json
{
  "summary": "Dentista",
  "description": "Calle Doctor San Juan 26",
  "start": {"dateTime": "2026-05-29T10:00:00+02:00", "timeZone": "Europe/Madrid"},
  "end": {"dateTime": "2026-05-29T11:00:00+02:00", "timeZone": "Europe/Madrid"}
}
```

Duración por defecto: **1 hora**. Si en el futuro queremos eventos con duración variable, ampliamos.

Devuelve el `id` del evento creado. El caller lo guarda en `events.gcal_event_id`.

### Update

`gcal_sync.update_event(gcal_event_id, fields)`. PATCH a `/calendars/primary/events/{gcal_event_id}` con los campos cambiados.

Si cambia `datetime`, recalcula `start` y `end`. Si cambia `title`, actualiza `summary`. Si cambia `notes`, actualiza `description`.

### Delete

`gcal_sync.delete_event(gcal_event_id)`. DELETE a `/calendars/primary/events/{gcal_event_id}`. Si Google devuelve 404 (el evento ya no existía), tratamos como éxito.

### Detección de cambios desde el bot

`tools.update_event` y `tools.delete_event` se modifican así:

```python
def update_event(event_id, fields):
    # ... lógica actual ...
    # AL FINAL, antes de devolver:
    gcal_event_id = obtener_de_la_fila(event_id)
    if gcal_event_id:
        try:
            gcal_sync.update_event(gcal_event_id, fields)
        except Exception:
            log.exception("Error propagando update a Calendar")
            # No degrada el update local — el evento queda actualizado en el bot
            # pero el sync de Calendar se desincroniza. Avisamos en logs.
    return result
```

Filosofía: **el bot es la fuente de verdad**. Si Calendar falla por la razón que sea (red, token caducado, evento ya borrado en Google), el bot sigue adelante. Avisamos en logs y, si es un error grave (token revocado), avisamos al usuario por Telegram.

## Triggers

### Lenguaje natural

El system prompt de `brain.py` aprende:

> Cuando Pablo apunta un evento y añade "y mételo en el calendario", "y pásalo a Google Calendar", "y al calendario", o variantes similares, además de `add_event` llama a `push_event_to_calendar(event_id)` con el id del evento recién creado.
>
> Cuando Pablo pide explícitamente sincronizar un evento ya existente ("manda la reunión de Marta al calendario"), busca el evento con `query_events` y llama a `push_event_to_calendar(event_id)`.
>
> Cuando Pablo dice "conecta con calendar" o equivalente, llama a `connect_calendar()` que devuelve el URL de autorización.

### Botón inline

Cuando `add_event` se ejecuta y NO ha sincronizado (porque Pablo no lo pidió), el mensaje de confirmación del bot incluye un botón `📅 Mandar a Calendar` con callback `gcs:{event_id}`. Tap → se sincroniza.

Nota: el botón aparece SOLO en la confirmación inmediata de crear el evento, no en `/hoy` ni en `/semana` (saturaría la vista).

## Edge cases

- **Token caducado y refresh OK**: transparente, se renueva.
- **Token revocado en Google**: bot detecta 401 persistente, borra tokens, avisa al usuario por Telegram, no se sincroniza nada hasta reautorizar.
- **Evento ya borrado en Google al hacer update**: 404 al patch → log warning, asumimos desync intencional, no rompemos.
- **Push de evento sin tokens guardados**: bot avisa *"Conecta con Calendar primero"*.
- **Doble push del mismo evento**: si `gcal_event_id` ya existe, no se crea otro; el bot lo detecta y devuelve *"Ya está sincronizado"*.
- **Update de evento sin `gcal_event_id`**: simplemente no propaga (no estaba sincronizado).
- **Borrado de evento con `gcal_event_id`**: intenta DELETE en Google. Si falla, sigue borrando local (mejor desincronización que data corruption).
- **Conexión a Internet caída**: las llamadas a Google fallan, el bot sigue funcionando con la BD local. Logs reflejan los fallos.

## Tests

1. `gcal_sync.oauth_start_url()` devuelve URL con los parámetros correctos (client_id, scope, redirect_uri, state).
2. `gcal_sync.exchange_code(code)` mockea respuesta de Google y verifica que se guardan tokens.
3. `gcal_sync.ensure_valid_token()` renueva el access_token cuando está a punto de caducar.
4. `gcal_sync.push_event` hace POST con el body correcto al endpoint correcto (mock HTTP).
5. `gcal_sync.push_event` devuelve el `gcal_event_id` parseado de la respuesta.
6. `gcal_sync.update_event` hace PATCH con los campos correctos.
7. `gcal_sync.delete_event` hace DELETE y trata 404 como éxito.
8. `tools.add_event` con `sync_to_calendar=True` llama a `push_event` y guarda `gcal_event_id` en la fila.
9. `tools.update_event` propaga a Calendar solo si la fila tiene `gcal_event_id`.
10. `tools.delete_event` llama a `gcal_sync.delete_event` solo si la fila tiene `gcal_event_id`.
11. Si `gcal_sync` falla, `tools.update_event` y `tools.delete_event` no rompen — log + continúan.
12. Migración de BD añade columna `gcal_event_id` y tabla `oauth_tokens` idempotentemente.
13. Callback `gcs:{event_id}` llama a `push_event_to_calendar`, actualiza el mensaje quitando el botón.
14. Endpoint `/oauth/callback` con código válido guarda tokens y devuelve HTML de éxito.
15. Endpoint `/oauth/callback` con código inválido devuelve HTML de error.

## Criterios de éxito

- Pablo dice *"conecta con calendar"* → recibe un enlace → autoriza en navegador → recibe confirmación en Telegram → tokens guardados.
- Pablo dice *"apunta dentista mañana a las 10 y mételo en el calendario"* → el evento aparece en el bot Y en su Google Calendar.
- Pablo apunta un evento sin pedir sync → el bot le responde con un botón `📅 Mandar a Calendar` → tap → aparece en Calendar.
- Pablo edita la fecha de un evento sincronizado en el bot → el evento en Calendar cambia de fecha.
- Pablo borra un evento sincronizado en el bot → desaparece de Calendar.
- Si Google está caído, el bot sigue funcionando como siempre y reporta el fallo en logs.
- El access_token se renueva sin intervención del usuario.

## Fuera del alcance (MVP)

- ❌ Lectura desde Calendar al bot. Sincronización es unidireccional.
- ❌ Sync automático sin que el usuario lo pida.
- ❌ Sincronizar rutinas (eventos recurrentes), tareas, objetivos.
- ❌ Elegir calendario distinto al principal.
- ❌ Configurar duración del evento (siempre 1h).
- ❌ Invitar a otros participantes a los eventos creados.
- ❌ Notificaciones push de Calendar al bot (webhooks).
- ❌ Soporte multi-cuenta de Google (1 usuario, 1 cuenta).
- ❌ Persistir tokens cifrados en BD (van en plano, suficiente para personal).

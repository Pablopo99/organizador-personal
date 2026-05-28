# Endpoint HTTPS para Siri — Diseño

**Fecha:** 2026-05-28
**Estado:** Diseño aprobado, pendiente de plan de implementación

## Objetivo

Permitir a Pablo apuntar tareas, eventos y consultas dictándoselos a Siri (*"Oye Siri, apuntar"* → dictar texto → Siri lee la respuesta). El bot acepta un POST HTTPS desde un atajo de iOS y procesa el texto exactamente como si llegara por Telegram. La respuesta del cerebro se envía también al chat de Telegram como mensaje normal del bot, así Pablo tiene registro persistente de lo apuntado por voz.

## Decisiones clave

- **Un solo proceso**, dos puertas de entrada: el polling de Telegram (PTB) y un servidor HTTP (aiohttp) corren en el mismo event loop async.
- **Mismo cerebro**: el endpoint llama a `brain.handle_message(text, user_id=ALLOWED_USER_ID)`, exactamente la misma función que usa el handler de Telegram. Sin lógica de negocio nueva.
- **Eco a Telegram**: la respuesta del cerebro se envía como mensaje al chat de Pablo (igual que con audios). Siri lee el texto plano; Telegram recibe el HTML con su formato.
- **Auth con bearer estático**: un secret `SIRI_TOKEN` generado al desplegar (`openssl rand -hex 32`), guardado como secret de Fly. El atajo de iOS lo lleva en el header `Authorization`.
- **Una sola sesión**: solo Pablo (mismo `ALLOWED_USER_ID`). Si en el futuro comparte, será replicando la instancia entera con su propio token.
- **YAGNI**: sin rate limiting, sin logs estructurados, sin métricas. Cuando se necesiten, se añaden.

## Arquitectura

```
┌─────────────────┐                    ┌─────────────────┐
│  Telegram       │                    │  Siri / iOS      │
│  (polling)      │                    │  Shortcut        │
└────────┬────────┘                    └────────┬─────────┘
         │ updates                              │ POST /ingest
         ▼                                      ▼
   ┌─────────────────────────────────────────────────┐
   │       Un solo proceso Python en Fly             │
   │                                                  │
   │  ┌──────────────┐         ┌──────────────────┐  │
   │  │ PTB polling  │         │ aiohttp server   │  │
   │  │ loop         │         │ (puerto 8080)    │  │
   │  └──────┬───────┘         └────────┬─────────┘  │
   │         │                          │            │
   │         └──────────┬───────────────┘            │
   │                    ▼                            │
   │            brain.handle_message()               │
   │            (compartido)                         │
   └─────────────────────────────────────────────────┘
```

**Archivos afectados:**

- **`bot.py`** — `main()` deja de usar `Application.run_polling()` (bloqueante). Pasa a una versión async que arranca PTB + aiohttp en el mismo event loop usando `asyncio.gather` (o equivalente con `app.initialize` + `app.start` + `app.updater.start_polling`). Los handlers de Telegram no cambian.
- **`siri_server.py` (nuevo)** — módulo aislado con:
  - Función `build_app(telegram_bot, ingest_callback, siri_token)` que devuelve una `aiohttp.web.Application` con la ruta `/ingest`.
  - Handler `_on_ingest(request)` que valida auth, parsea JSON, llama a `ingest_callback(text)` (que internamente hace `brain.handle_message` + envío a Telegram), y responde con `{"reply": ...}`.
- **`config.py`** — añade `SIRI_TOKEN = _require("SIRI_TOKEN")`.
- **`fly.toml`** — añade bloque `[[services]]` con `internal_port = 8080`, `http_service` con puerto 443 externo, health checks deshabilitados (el bot se reinicia solo si crashea).
- **`Dockerfile`** — `EXPOSE 8080`.
- **`requirements.txt`** — `aiohttp>=3.10`.
- **Tests**: `tests/test_siri_server.py` con `aiohttp.test_utils.AioHTTPTestCase` o `pytest-aiohttp` (no instalado todavía — usaremos los test helpers de aiohttp directamente).

## Endpoint `/ingest`

**Request** (POST):

```http
POST /ingest HTTP/1.1
Host: mi-secretaria-pablo.fly.dev
Authorization: Bearer {SIRI_TOKEN}
Content-Type: application/json

{"text": "apunta dentista mañana a las 10"}
```

**Response 200**:

```json
{"reply": "Listo, 'Dentista' apuntado para mañana 10:00 ✅"}
```

**Códigos de error**:

| Caso | Status | Body |
|---|---|---|
| Falta header `Authorization` o token inválido | 401 | `{"reply": "No autorizado"}` |
| JSON malformado | 400 | `{"reply": "Petición inválida"}` |
| Falta campo `text` | 400 | `{"reply": "Falta el texto"}` |
| `text` vacío o solo espacios | 400 | `{"reply": "No te he entendido. Repite, por favor."}` |
| Excepción en `brain.handle_message` | 500 | `{"reply": "Algo ha fallado, vuelve a intentarlo en un momento."}` |

En todos los casos el body es JSON con un campo `reply` que Siri puede leer directamente.

## Flujo del happy path

1. Siri en iPhone manda POST con el dictado.
2. aiohttp middleware/handler valida `Authorization: Bearer SIRI_TOKEN`. Si OK, sigue. Si no, 401.
3. Parsea JSON. Si falla, 400.
4. Lee campo `text`. Si vacío, 400.
5. Llama `brain.handle_message(text, user_id=ALLOWED_USER_ID)` — la misma función que usa el handler de Telegram. Esto puede tardar (Claude API). Devuelve un string HTML.
6. Convierte HTML a texto plano para Siri usando una función auxiliar (quita `<b>`, `<i>`, `<s>`, etc.) — Siri no entiende HTML.
7. En paralelo, envía la respuesta original (HTML) a Telegram como mensaje del bot al `ALLOWED_USER_ID`. Si falla (red caída, etc.), se loguea pero NO se degrada la respuesta a Siri.
8. Devuelve 200 con `{"reply": <texto plano>}`.

## Refactor de `main()` en bot.py

Versión actual (simplificada):

```python
def main() -> None:
    db.init_schema()
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    # ... registros de handlers ...
    app.job_queue.run_daily(...)
    app.run_polling(allowed_updates=Update.ALL_TYPES)  # bloqueante
```

Versión nueva:

```python
async def _async_main() -> None:
    db.init_schema()
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    # ... registros de handlers ...
    app.job_queue.run_daily(...)

    await app.initialize()
    await app.start()
    await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)

    siri_app = siri_server.build_app(
        telegram_bot=app.bot,
        siri_token=SIRI_TOKEN,
    )
    runner = web.AppRunner(siri_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8080)
    await site.start()

    log.info("Bot arrancando (polling + HTTP en :8080)…")

    try:
        await asyncio.Event().wait()  # mantener vivo
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
        await runner.cleanup()


def main() -> None:
    asyncio.run(_async_main())
```

El handler de Telegram no cambia. El job_queue tampoco.

## Conversión HTML → texto plano para Siri

Función simple en `siri_server.py`:

```python
import re

_TAG_RE = re.compile(r"<[^>]+>")

def html_to_plain(text: str) -> str:
    """Quita tags HTML simples y desescapa entidades básicas. Suficiente para Siri."""
    plain = _TAG_RE.sub("", text)
    plain = plain.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    return plain
```

No usamos un parser HTML completo (BeautifulSoup, lxml) porque el bot solo emite tags simples (`<b>`, `<i>`, `<s>`, `<tg-spoiler>`). Esta función cubre el 100% del caso real.

## Fly.toml — bloque nuevo

```toml
[[services]]
  protocol = "tcp"
  internal_port = 8080
  auto_stop_machines = false
  auto_start_machines = true
  min_machines_running = 1

  [[services.ports]]
    port = 443
    handlers = ["tls", "http"]

  [[services.ports]]
    port = 80
    handlers = ["http"]
    force_https = true
```

Esto le dice a Fly que el contenedor expone HTTP en 8080 y que rute tráfico externo HTTPS al puerto interno.

## Tests

1. `POST /ingest` sin header `Authorization` → 401, brain NO llamado (mock).
2. `POST /ingest` con token incorrecto → 401, brain NO llamado.
3. `POST /ingest` con token válido pero JSON malformado → 400.
4. `POST /ingest` con JSON válido sin campo `text` → 400.
5. `POST /ingest` con `text` vacío o solo espacios → 400.
6. `POST /ingest` con auth + texto válido → 200, brain mock llamado con (text, ALLOWED_USER_ID), `telegram_bot.send_message` mock recibe la respuesta en HTML.
7. `POST /ingest` con auth + texto, brain lanza excepción → 500 con reply amistoso, `telegram_bot.send_message` NO se llama.
8. `POST /ingest` con auth + texto + `telegram_bot.send_message` lanza excepción → 200 con reply, excepción se loguea pero no rompe.
9. `html_to_plain` quita tags `<b>`, `<i>`, `<s>` y devuelve texto limpio.
10. `html_to_plain` desescapa `&lt;`, `&gt;`, `&amp;`.

## Configuración del atajo de iOS

Pablo configura el atajo en la app "Atajos" de iOS (manual, una vez):

1. Crear atajo nuevo, nombre "Apuntar".
2. **Acción 1**: "Dictar texto" (idioma: español).
3. **Acción 2**: "Obtener contenido de URL":
   - URL: `https://mi-secretaria-pablo.fly.dev/ingest`
   - Método: `POST`
   - Headers: `Authorization: Bearer <SIRI_TOKEN>` (Pablo pega el token que generamos)
   - Headers: `Content-Type: application/json`
   - Cuerpo de la petición: JSON con campo `text` = "Texto dictado" (variable del paso 1)
4. **Acción 3**: "Obtener valor del diccionario" → clave `reply` (sobre el resultado de la URL).
5. **Acción 4**: "Hablar texto" → valor del paso 3.

Pablo lo configura cuando le pasamos URL + token después del deploy.

## Criterios de éxito

- En Fly logs aparece "Bot arrancando (polling + HTTP en :8080)" al desplegar.
- `curl -X POST https://mi-secretaria-pablo.fly.dev/ingest -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"text":"hola"}'` devuelve 200 con un `reply` real del cerebro.
- Sin auth → 401.
- En el iPhone, *"Oye Siri, apuntar"* → dictado → Siri lee la respuesta del bot.
- En Telegram aparece el mismo mensaje del bot como confirmación.
- El bot de Telegram normal sigue respondiendo a slash commands, mensajes, audios y callbacks sin regresiones.

## Fuera del alcance

- ❌ Multi-usuario (auth con un solo token estático).
- ❌ Rate limiting.
- ❌ Logs estructurados / métricas.
- ❌ Webhook de Telegram (sigue siendo polling).
- ❌ Endpoint para disparar slash commands desde Siri (Siri solo manda texto libre).
- ❌ Configuración del atajo de iOS automatizada (Pablo lo hace a mano).
- ❌ Validar formato/longitud máxima del texto (el cerebro/Claude lo absorbe).

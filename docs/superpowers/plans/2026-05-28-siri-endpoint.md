# Siri HTTPS Endpoint — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Añadir un endpoint `POST /ingest` con bearer auth que reciba texto dictado por Siri, lo procese con el mismo cerebro que Telegram, envíe la respuesta también al chat de Telegram y devuelva un JSON con `reply` para que Siri lo lea.

**Architecture:** Bot se reestructura para que su `main()` arranque PTB polling + aiohttp web server en el mismo event loop async. Nuevo módulo `siri_server.py` aislado con la lógica del endpoint. El cerebro y los handlers de Telegram no cambian.

**Tech Stack:** Python 3.12, python-telegram-bot 21.6, aiohttp 3.10+, pytest, pytest-asyncio, Fly.io.

**Spec de referencia:** `docs/superpowers/specs/2026-05-28-siri-endpoint-design.md`

---

## Convenciones

- TDD: test que falla → implementación → test pasa → commit.
- Cada Task termina en commit.
- Comandos desde `/Users/pablocansinos/Desktop/Otros/Proyecto Prueba`.
- Activar venv con ruta absoluta: `./.venv/bin/python -m pytest ...`.

---

## Task 1: Añadir aiohttp a requirements y crear `siri_server.py` con `html_to_plain`

Función auxiliar simple para convertir HTML del bot a texto plano que Siri pueda leer.

**Files:**
- Modify: `requirements.txt`
- Create: `siri_server.py`
- Create: `tests/test_siri_server.py`

- [ ] **Step 1: Añadir `aiohttp>=3.10` a `requirements.txt`**

Editar `requirements.txt` y añadir al final una línea:

```
aiohttp>=3.10
```

- [ ] **Step 2: Instalar dependencia en el venv**

```bash
./.venv/bin/pip install -r requirements.txt
```

Expected: aiohttp se instala sin errores.

- [ ] **Step 3: Crear `tests/test_siri_server.py` con tests de `html_to_plain`**

Contenido inicial completo:

```python
import siri_server


def test_html_to_plain_strips_bold_tags():
    assert siri_server.html_to_plain("Hola <b>mundo</b>") == "Hola mundo"


def test_html_to_plain_strips_italic_strike_spoiler():
    assert siri_server.html_to_plain("<i>uno</i> <s>dos</s> <tg-spoiler>tres</tg-spoiler>") == "uno dos tres"


def test_html_to_plain_handles_html_entities():
    assert siri_server.html_to_plain("a &lt; b &amp; c &gt; d") == "a < b & c > d"


def test_html_to_plain_leaves_plain_text_alone():
    assert siri_server.html_to_plain("texto sin formato") == "texto sin formato"
```

- [ ] **Step 4: Ejecutar tests, verificar que fallan**

```bash
./.venv/bin/python -m pytest tests/test_siri_server.py -v
```

Expected: 4 FAIL — módulo no existe.

- [ ] **Step 5: Crear `siri_server.py` con `html_to_plain`**

Contenido inicial:

```python
"""Servidor aiohttp con endpoint /ingest para que Siri pueda hablar al bot."""
import re

_TAG_RE = re.compile(r"<[^>]+>")


def html_to_plain(text: str) -> str:
    """Quita tags HTML simples y desescapa entidades básicas. Para que Siri pueda leer la respuesta."""
    plain = _TAG_RE.sub("", text)
    plain = plain.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    return plain
```

- [ ] **Step 6: Ejecutar tests, verificar que pasan**

```bash
./.venv/bin/python -m pytest tests/test_siri_server.py -v
```

Expected: 4 PASS.

- [ ] **Step 7: Suite completa**

```bash
./.venv/bin/python -m pytest
```

Expected: TODO PASS.

- [ ] **Step 8: Commit**

```bash
git add requirements.txt siri_server.py tests/test_siri_server.py
git commit -m "feat(siri): add aiohttp dependency and html_to_plain helper

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: `build_app()` con auth + endpoint `/ingest` (happy path)

Construcción de la aiohttp Application con el endpoint y la auth, y tests del happy path.

**Files:**
- Modify: `siri_server.py`
- Modify: `tests/test_siri_server.py`

- [ ] **Step 1: Escribir tests del happy path con `pytest-asyncio` y `aiohttp.test_utils`**

Añadir al final de `tests/test_siri_server.py`:

```python
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp.test_utils import TestClient, TestServer

import siri_server


VALID_TOKEN = "test-token-secret"


def _build_test_app(brain_reply: str = "Listo, hecho", brain_side_effect=None, send_side_effect=None):
    """Crea una app de test con brain y telegram_bot mockeados."""
    if brain_side_effect is not None:
        brain_fn = MagicMock(side_effect=brain_side_effect)
    else:
        brain_fn = MagicMock(return_value=brain_reply)

    telegram_bot = MagicMock()
    telegram_bot.send_message = AsyncMock(side_effect=send_side_effect)

    app = siri_server.build_app(
        telegram_bot=telegram_bot,
        brain_fn=brain_fn,
        siri_token=VALID_TOKEN,
        allowed_user_id=42,
    )
    # Adjunta las mocks para que los tests las puedan inspeccionar
    app["brain_fn"] = brain_fn
    app["telegram_bot"] = telegram_bot
    return app


@pytest.mark.asyncio
async def test_ingest_happy_path_returns_reply_and_calls_brain_and_telegram(aiohttp_client):
    app = _build_test_app(brain_reply="Listo, <b>Dentista</b> apuntado")
    client: TestClient = await aiohttp_client(app)

    resp = await client.post(
        "/ingest",
        json={"text": "apunta dentista mañana 10"},
        headers={"Authorization": f"Bearer {VALID_TOKEN}"},
    )

    assert resp.status == 200
    body = await resp.json()
    # Reply en texto plano (sin tags) para que Siri lo lea
    assert body["reply"] == "Listo, Dentista apuntado"

    # Brain llamado con el texto y user_id 42
    app["brain_fn"].assert_called_once_with("apunta dentista mañana 10", user_id=42)

    # Telegram recibió la respuesta en HTML
    app["telegram_bot"].send_message.assert_awaited_once()
    call = app["telegram_bot"].send_message.await_args
    assert call.kwargs["chat_id"] == 42
    assert call.kwargs["text"] == "Listo, <b>Dentista</b> apuntado"
    assert call.kwargs["parse_mode"] == "HTML"
```

`pytest-asyncio` ya está instalado en el proyecto. `aiohttp_client` es una fixture estándar de aiohttp para tests; si no está disponible, instalar `pytest-aiohttp`. Comprobamos en Step 2.

- [ ] **Step 2: Ejecutar tests, verificar que fallan o falta fixture**

```bash
./.venv/bin/python -m pytest tests/test_siri_server.py -v
```

Expected: FAIL — `build_app` no existe, o falta `pytest-aiohttp`.

Si el error es `fixture 'aiohttp_client' not found`, instalar:

```bash
./.venv/bin/pip install pytest-aiohttp
```

Y añadir a `requirements.txt`:

```
pytest-aiohttp>=1.0
```

Reejecutar el comando del Step 2.

Expected ahora: 1 FAIL — `build_app` no existe.

- [ ] **Step 3: Implementar `build_app` con happy path**

Sustituir el contenido de `siri_server.py` por:

```python
"""Servidor aiohttp con endpoint /ingest para que Siri pueda hablar al bot."""
import logging
import re
from typing import Callable

from aiohttp import web

log = logging.getLogger("siri_server")

_TAG_RE = re.compile(r"<[^>]+>")


def html_to_plain(text: str) -> str:
    """Quita tags HTML simples y desescapa entidades básicas. Para que Siri pueda leer la respuesta."""
    plain = _TAG_RE.sub("", text)
    plain = plain.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    return plain


def build_app(
    *,
    telegram_bot,
    brain_fn: Callable[..., str],
    siri_token: str,
    allowed_user_id: int,
) -> web.Application:
    """Crea la aiohttp Application con el endpoint /ingest.

    - telegram_bot: instancia del bot de python-telegram-bot para mandar el eco a Telegram.
    - brain_fn: función con la firma brain.handle_message(text, user_id=...) -> str (HTML).
    - siri_token: bearer token estático que el atajo de Siri debe llevar.
    - allowed_user_id: chat_id donde se hará el eco a Telegram.
    """
    async def _on_ingest(request: web.Request) -> web.Response:
        auth = request.headers.get("Authorization", "")
        if auth != f"Bearer {siri_token}":
            return web.json_response({"reply": "No autorizado"}, status=401)

        try:
            body = await request.json()
        except Exception:
            return web.json_response({"reply": "Petición inválida"}, status=400)

        text = body.get("text") if isinstance(body, dict) else None
        if not text or not isinstance(text, str) or not text.strip():
            return web.json_response({"reply": "Falta el texto"}, status=400)

        try:
            html_reply = brain_fn(text, user_id=allowed_user_id)
        except Exception:
            log.exception("Error procesando ingest")
            return web.json_response(
                {"reply": "Algo ha fallado, vuelve a intentarlo en un momento."},
                status=500,
            )

        try:
            await telegram_bot.send_message(
                chat_id=allowed_user_id,
                text=html_reply,
                parse_mode="HTML",
            )
        except Exception:
            log.exception("Error mandando eco a Telegram (Siri ya recibió respuesta)")

        return web.json_response({"reply": html_to_plain(html_reply)}, status=200)

    app = web.Application()
    app.router.add_post("/ingest", _on_ingest)
    return app
```

- [ ] **Step 4: Ejecutar tests, verificar happy path pasa**

```bash
./.venv/bin/python -m pytest tests/test_siri_server.py -v
```

Expected: TODO PASS.

- [ ] **Step 5: Commit**

```bash
git add requirements.txt siri_server.py tests/test_siri_server.py
git commit -m "feat(siri): /ingest endpoint with bearer auth (happy path)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Casos de error del endpoint (401, 400, 500)

Tests + asserts para todos los caminos de error definidos en la spec.

**Files:**
- Modify: `tests/test_siri_server.py`

- [ ] **Step 1: Escribir tests de errores**

Añadir al final de `tests/test_siri_server.py`:

```python


@pytest.mark.asyncio
async def test_ingest_missing_auth_returns_401(aiohttp_client):
    app = _build_test_app()
    client = await aiohttp_client(app)

    resp = await client.post("/ingest", json={"text": "hola"})

    assert resp.status == 401
    body = await resp.json()
    assert body["reply"] == "No autorizado"
    app["brain_fn"].assert_not_called()


@pytest.mark.asyncio
async def test_ingest_wrong_token_returns_401(aiohttp_client):
    app = _build_test_app()
    client = await aiohttp_client(app)

    resp = await client.post(
        "/ingest",
        json={"text": "hola"},
        headers={"Authorization": "Bearer wrong"},
    )

    assert resp.status == 401
    app["brain_fn"].assert_not_called()


@pytest.mark.asyncio
async def test_ingest_malformed_json_returns_400(aiohttp_client):
    app = _build_test_app()
    client = await aiohttp_client(app)

    resp = await client.post(
        "/ingest",
        data="not json",
        headers={
            "Authorization": f"Bearer {VALID_TOKEN}",
            "Content-Type": "application/json",
        },
    )

    assert resp.status == 400
    body = await resp.json()
    assert "inválida" in body["reply"].lower() or "falta" in body["reply"].lower()


@pytest.mark.asyncio
async def test_ingest_missing_text_field_returns_400(aiohttp_client):
    app = _build_test_app()
    client = await aiohttp_client(app)

    resp = await client.post(
        "/ingest",
        json={"otra_clave": "valor"},
        headers={"Authorization": f"Bearer {VALID_TOKEN}"},
    )

    assert resp.status == 400
    body = await resp.json()
    assert "falta" in body["reply"].lower()


@pytest.mark.asyncio
async def test_ingest_empty_text_returns_400(aiohttp_client):
    app = _build_test_app()
    client = await aiohttp_client(app)

    resp = await client.post(
        "/ingest",
        json={"text": "   "},
        headers={"Authorization": f"Bearer {VALID_TOKEN}"},
    )

    assert resp.status == 400


@pytest.mark.asyncio
async def test_ingest_brain_exception_returns_500_and_no_telegram(aiohttp_client):
    def boom(text, user_id=0):
        raise RuntimeError("boom")

    app = _build_test_app(brain_side_effect=boom)
    client = await aiohttp_client(app)

    resp = await client.post(
        "/ingest",
        json={"text": "hola"},
        headers={"Authorization": f"Bearer {VALID_TOKEN}"},
    )

    assert resp.status == 500
    body = await resp.json()
    assert "fallado" in body["reply"].lower()
    app["telegram_bot"].send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_ingest_telegram_failure_still_returns_200(aiohttp_client):
    """Si el eco a Telegram falla, Siri sigue recibiendo su 200 con el reply."""
    app = _build_test_app(
        brain_reply="ok",
        send_side_effect=RuntimeError("telegram down"),
    )
    client = await aiohttp_client(app)

    resp = await client.post(
        "/ingest",
        json={"text": "hola"},
        headers={"Authorization": f"Bearer {VALID_TOKEN}"},
    )

    assert resp.status == 200
    body = await resp.json()
    assert body["reply"] == "ok"
```

- [ ] **Step 2: Ejecutar tests**

```bash
./.venv/bin/python -m pytest tests/test_siri_server.py -v
```

Expected: TODO PASS (siri_server.py ya cubre estos casos por la implementación de Task 2).

- [ ] **Step 3: Suite completa**

```bash
./.venv/bin/python -m pytest
```

Expected: TODO PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/test_siri_server.py
git commit -m "test(siri): cover 401/400/500 paths and telegram-failure fallback

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Refactor de `main()` en `bot.py` para arrancar polling + aiohttp en el mismo event loop

Cambio mecánico pero crítico: `run_polling()` bloquea, hay que pasarse al API async no bloqueante. Después de Task 4, los tests siguen pasando pero el bot todavía NO escucha por HTTP.

**Files:**
- Modify: `bot.py`
- Modify: `config.py`

- [ ] **Step 1: Añadir `SIRI_TOKEN` a `config.py`**

Editar `config.py`. Localizar la línea:

```python
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
```

Y añadir justo después:

```python
SIRI_TOKEN = _require("SIRI_TOKEN")
```

- [ ] **Step 2: Setear SIRI_TOKEN dummy en `tests/conftest.py`**

Editar `tests/conftest.py`. Localizar:

```python
os.environ.setdefault("GROQ_API_KEY", "test-groq-key")
```

Añadir después:

```python
os.environ.setdefault("SIRI_TOKEN", "test-siri-token")
```

- [ ] **Step 3: Verificar que la suite sigue pasando con el nuevo require**

```bash
./.venv/bin/python -m pytest
```

Expected: TODO PASS.

- [ ] **Step 4: Refactorizar `main()` en `bot.py`**

Localizar la función `main()` al final de `bot.py` y sustituirla por:

```python
async def _async_main() -> None:
    from datetime import time as dtime

    import pytz

    import scheduler
    import siri_server
    from aiohttp import web
    from config import SIRI_TOKEN

    db.init_schema()
    log.info("Base de datos lista en %s", db.DB_PATH)

    app = Application.builder().token(TELEGRAM_TOKEN).post_init(_set_bot_commands).build()

    app.add_handler(CommandHandler("hoy", _on_hoy))
    app.add_handler(CommandHandler("manana", _on_manana))
    app.add_handler(CommandHandler("pendientes", _on_pendientes))
    app.add_handler(CommandHandler("semana", _on_semana))
    for cmd in ("objetivos", "rachas"):
        app.add_handler(CommandHandler(cmd, _make_slash_handler(f"/{cmd}")))

    app.add_handler(MessageHandler(filters.TEXT, _on_message))
    app.add_handler(MessageHandler(filters.VOICE, _on_voice))
    app.add_handler(CallbackQueryHandler(_on_callback_query))

    madrid = pytz.timezone("Europe/Madrid")
    app.job_queue.run_daily(
        scheduler.morning_summary,
        time=dtime(hour=9, minute=0, tzinfo=madrid),
        name="morning_summary",
    )
    app.job_queue.run_repeating(
        scheduler.check_reminders,
        interval=300,
        first=30,
        name="check_reminders",
    )
    app.job_queue.run_daily(
        scheduler.weekly_objectives_reminder,
        time=dtime(hour=13, minute=0, tzinfo=madrid),
        days=(0,),
        name="weekly_objectives_reminder",
    )

    await app.initialize()
    await app.start()
    await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)

    siri_app = siri_server.build_app(
        telegram_bot=app.bot,
        brain_fn=brain.handle_message,
        siri_token=SIRI_TOKEN,
        allowed_user_id=ALLOWED_USER_ID,
    )
    runner = web.AppRunner(siri_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8080)
    await site.start()

    log.info("Bot arrancando (polling + HTTP en :8080)…")

    try:
        await asyncio.Event().wait()
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
        await runner.cleanup()


def main() -> None:
    asyncio.run(_async_main())
```

(El `import asyncio` ya está al principio de `bot.py`.)

- [ ] **Step 5: Verificar que la suite sigue pasando**

```bash
./.venv/bin/python -m pytest
```

Expected: TODO PASS.

- [ ] **Step 6: Verificar arranque local (smoke)**

```bash
./.venv/bin/python -c "
import os
os.environ['TELEGRAM_TOKEN'] = 'fake'
os.environ['ANTHROPIC_API_KEY'] = 'fake'
os.environ['ALLOWED_USER_ID'] = '42'
os.environ['SIRI_TOKEN'] = 'fake'
import bot
print('import OK; main is callable:', callable(bot.main))
"
```

Expected: `import OK; main is callable: True` sin errores de import.

- [ ] **Step 7: Commit**

```bash
git add bot.py config.py tests/conftest.py
git commit -m "refactor(bot): main() runs polling + aiohttp in the same event loop

Lays the wiring needed to host the Siri /ingest endpoint alongside
the existing Telegram polling. Adds SIRI_TOKEN secret requirement.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Exponer puerto 8080 en Dockerfile y fly.toml

Cambios de infraestructura para que Fly enrute HTTP externo al puerto 8080 del contenedor.

**Files:**
- Modify: `Dockerfile`
- Modify: `fly.toml`

- [ ] **Step 1: `EXPOSE 8080` en Dockerfile**

Editar `Dockerfile`. Localizar la línea:

```dockerfile
CMD ["python", "bot.py"]
```

Y justo antes (después del último `COPY` o similar), añadir:

```dockerfile
EXPOSE 8080
```

- [ ] **Step 2: Añadir bloque `[[services]]` a fly.toml**

Editar `fly.toml`. Añadir al final del archivo:

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

- [ ] **Step 3: Verificar sintaxis del toml**

```bash
./.venv/bin/python -c "import tomllib; print(tomllib.load(open('fly.toml','rb')))"
```

Expected: imprime el dict parseado sin errores.

- [ ] **Step 4: Commit**

```bash
git add Dockerfile fly.toml
git commit -m "feat(deploy): expose port 8080 for Siri HTTP endpoint

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Generar SIRI_TOKEN y subirlo como secret a Fly, luego desplegar

- [ ] **Step 1: Generar token y guardarlo en un fichero local fuera del repo**

```bash
openssl rand -hex 32 > /tmp/siri_token.txt
echo "Token generado:"
cat /tmp/siri_token.txt
```

Expected: imprime un string hex de 64 caracteres. **Cópiatelo a un sitio seguro — lo vas a necesitar para el atajo de iOS.**

- [ ] **Step 2: Subirlo a Fly como secret**

```bash
flyctl secrets set --app mi-secretaria-pablo SIRI_TOKEN="$(cat /tmp/siri_token.txt)"
```

Expected: confirma que el secret se ha staged. (No despliega aún.)

- [ ] **Step 3: Borrar el fichero local del token**

```bash
rm /tmp/siri_token.txt
```

Expected: archivo borrado.

- [ ] **Step 4: Desplegar a Fly**

```bash
flyctl deploy --app mi-secretaria-pablo
```

Expected: build OK, máquina actualizada.

- [ ] **Step 5: Verificar logs de arranque**

```bash
sleep 12 && flyctl logs --app mi-secretaria-pablo --no-tail | grep -E "(Base de datos|arrancando|HTTP en :8080|ERROR|Exception)" | tail -10
```

Expected: ver "Base de datos lista", "Bot arrancando (polling + HTTP en :8080)…", scheduler "Scheduler started", **sin** errores ni excepciones.

- [ ] **Step 6: Test del endpoint con `curl` (sin token)**

```bash
curl -i -X POST https://mi-secretaria-pablo.fly.dev/ingest \
  -H "Content-Type: application/json" \
  -d '{"text":"hola"}'
```

Expected: `HTTP/2 401` con `{"reply":"No autorizado"}`.

- [ ] **Step 7: Test del endpoint con token correcto**

Pega el token (el que se generó en Step 1; mira en el dashboard de Fly o ejecuta de nuevo si lo perdiste) en una variable de shell y haz:

```bash
SIRI_TOKEN="<aquí_tu_token_de_64_chars>"
curl -i -X POST https://mi-secretaria-pablo.fly.dev/ingest \
  -H "Authorization: Bearer $SIRI_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text":"qué tengo hoy"}'
```

Expected: `HTTP/2 200` con `{"reply":"..."}` con respuesta real del cerebro (lo que el bot diría a `/hoy` literal, en texto plano).

Y en Telegram aparece el mismo mensaje en HTML del bot.

---

## Task 7: Pablo configura el atajo en iOS

(No es código — son los pasos manuales que Pablo hace en su iPhone con el token que le pasamos.)

- [ ] **Step 1: Abrir la app "Atajos" en iOS**

Buscar el atajo creado previamente ("Leer texto con voz") o crear uno nuevo desde cero.

- [ ] **Step 2: Configurar la acción "Obtener contenido de URL"**

Tocar la flechita "▶" para abrir las opciones avanzadas y configurar:

- **URL**: `https://mi-secretaria-pablo.fly.dev/ingest`
- **Método**: `POST`
- **Cabeceras**:
  - `Authorization` → `Bearer <pegar el token aquí>`
  - `Content-Type` → `application/json`
- **Cuerpo de la petición**: tipo JSON, con un campo:
  - Clave: `text`
  - Valor: variable "Texto dictado" (del paso 1 del atajo)

- [ ] **Step 3: Configurar la acción "Leer"**

La acción "Leer" debe coger como entrada el valor del campo `reply` de la respuesta JSON. En iOS:

- Tocar "Contenido de URL" en el bloque "Leer".
- Cambiar a la variable de salida de la URL → seleccionar el campo "reply" del diccionario.

(En iOS suele ser una acción adicional "Obtener valor del diccionario" → clave `reply` → y luego "Leer" sobre eso.)

- [ ] **Step 4: Probar el atajo**

Tocar el botón "▶" para ejecutar. iOS pedirá permisos:
- "Permitir dictado" → Sí.
- "Permitir acceso a la URL" → Sí (puede preguntar la primera vez).

Al hablar, debe llegar a Fly, procesar y oír la respuesta de Siri. En Telegram aparece el mensaje del bot.

- [ ] **Step 5: Probar con "Oye Siri"**

Sin abrir el atajo:

> "Oye Siri, apuntar"

(o el nombre exacto del atajo). Siri dispara el atajo, dicta, recibe, lee.

---

## Resumen de entregables

- `siri_server.py` (nuevo): `html_to_plain` + `build_app(telegram_bot, brain_fn, siri_token, allowed_user_id)` con endpoint `POST /ingest`.
- `bot.py`: `main()` reescrito en async, arranca PTB polling y aiohttp en el mismo event loop.
- `config.py`: `SIRI_TOKEN` requerido.
- `fly.toml`: nuevo bloque `[[services]]` exponiendo 443 → 8080.
- `Dockerfile`: `EXPOSE 8080`.
- `requirements.txt`: añade `aiohttp>=3.10` y posiblemente `pytest-aiohttp`.
- Tests nuevos: 4 (html_to_plain) + 1 (happy path) + 7 (errores 401/400/500 + fallback) = +12 tests.
- Deploy a Fly con `SIRI_TOKEN` configurado.
- Endpoint validado con `curl` (401 sin auth, 200 con auth).
- Atajo de iOS configurado por Pablo y probado vía Siri.

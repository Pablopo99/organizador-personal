# Mensajes de Voz — Plan de Implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Añadir soporte para mensajes de voz en el bot de Telegram: el usuario envía una nota de voz, el bot la transcribe con Groq Whisper y procesa la transcripción por el mismo flujo conversacional existente.

**Architecture:** Un módulo nuevo `transcriber.py` encapsula la llamada a Groq. `bot.py` detecta mensajes de voz, descarga el audio, lo manda al transcriber, prefija la respuesta con `📝 He entendido: «...»` y delega al cerebro existente. No se toca `brain.py` ni `tools.py`.

**Tech Stack:** Python 3.12, `groq` SDK (Whisper API), `python-telegram-bot` (ya en uso), `asyncio.to_thread` para llamar al SDK sync desde el handler async.

**Spec de referencia:** `docs/superpowers/specs/2026-05-11-mensajes-de-voz-design.md`

---

## Convenciones

- Cada Task termina en commit funcional.
- TDD: test que falla → implementación → test pasa → commit.
- Comandos desde la raíz del proyecto.
- `GROQ_API_KEY` es **opcional** en `.env` — si no está, el bot sigue funcionando con texto y al recibir voz responde "no he configurado la transcripción".

---

## Task 1: Configuración y dependencias

**Files:**
- Modify: `requirements.txt`
- Modify: `.env.example`
- Modify: `config.py`
- Modify: `tests/test_config.py`
- Modify: `tests/conftest.py`

- [ ] **Step 1: Añadir `groq` a `requirements.txt`**

Añadir esta línea al final:
```
groq>=0.11.0
```

- [ ] **Step 2: Añadir variable a `.env.example`**

Añadir al final del archivo:
```
# Clave de API de Groq para transcripción de audio. Sacar de console.groq.com
# OPCIONAL: si no se rellena, el bot funcionará solo con mensajes de texto.
GROQ_API_KEY=
```

- [ ] **Step 3: Actualizar `tests/conftest.py`**

Reemplazar el contenido por:
```python
"""Fixtures globales y entorno mínimo para todos los tests."""
import os

os.environ.setdefault("TELEGRAM_TOKEN", "test-telegram-token")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-anthropic-key")
os.environ.setdefault("ALLOWED_USER_ID", "42")
os.environ.setdefault("GROQ_API_KEY", "test-groq-key")
```

- [ ] **Step 4: Modificar `config.py` para incluir GROQ_API_KEY como opcional**

Localizar la sección con las variables de entorno y añadir, justo después de la línea `ALLOWED_USER_ID = int(_require("ALLOWED_USER_ID"))`:

```python
# Opcional: si está vacía, el bot ignorará mensajes de voz con respuesta de "no configurado".
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
```

- [ ] **Step 5: Añadir test en `tests/test_config.py`**

Añadir al final del archivo (después del último test):
```python


def test_groq_api_key_loads_optionally():
    # conftest fija un valor de test; debe existir y ser string
    assert isinstance(config.GROQ_API_KEY, str)
```

- [ ] **Step 6: Instalar la nueva dependencia**

```bash
cd "/Users/pablocansinos/Desktop/Proyecto Prueba"
source .venv/bin/activate
pip install -r requirements.txt
```

Expected: instala `groq` y sus dependencias sin errores.

- [ ] **Step 7: Ejecutar suite completa**

```bash
python -m pytest -v
```

Expected: 37 tests previos siguen pasando, +1 nuevo (`test_groq_api_key_loads_optionally`) = 38 PASS.

- [ ] **Step 8: Commit**

```bash
git add requirements.txt .env.example config.py tests/conftest.py tests/test_config.py
git commit -m "chore: add Groq SDK dependency and optional GROQ_API_KEY config"
```

---

## Task 2: Módulo de transcripción (`transcriber.py`)

**Files:**
- Create: `transcriber.py`
- Create: `tests/test_transcriber.py`

- [ ] **Step 1: Escribir tests**

Crear `tests/test_transcriber.py`:
```python
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import transcriber


def test_transcribe_returns_text_from_string_response(monkeypatch):
    """Cuando Groq devuelve directamente un string (response_format='text')."""
    mock_client = MagicMock()
    mock_client.audio.transcriptions.create.return_value = "Hola, esto es una prueba"
    monkeypatch.setattr(transcriber, "_client", mock_client)

    result = transcriber.transcribe(b"fake-audio-bytes")
    assert result == "Hola, esto es una prueba"


def test_transcribe_returns_text_from_object_response(monkeypatch):
    """Cuando Groq devuelve un objeto con atributo .text."""
    mock_client = MagicMock()
    mock_client.audio.transcriptions.create.return_value = SimpleNamespace(text="con objeto")
    monkeypatch.setattr(transcriber, "_client", mock_client)

    result = transcriber.transcribe(b"fake-audio-bytes")
    assert result == "con objeto"


def test_transcribe_strips_whitespace(monkeypatch):
    mock_client = MagicMock()
    mock_client.audio.transcriptions.create.return_value = "  texto con espacios  \n"
    monkeypatch.setattr(transcriber, "_client", mock_client)

    result = transcriber.transcribe(b"fake")
    assert result == "texto con espacios"


def test_transcribe_passes_spanish_language(monkeypatch):
    """Debe forzar language='es' para evitar transcripciones falsas en inglés."""
    mock_client = MagicMock()
    mock_client.audio.transcriptions.create.return_value = "ok"
    monkeypatch.setattr(transcriber, "_client", mock_client)

    transcriber.transcribe(b"fake")

    call_kwargs = mock_client.audio.transcriptions.create.call_args.kwargs
    assert call_kwargs["language"] == "es"
    assert call_kwargs["model"] == "whisper-large-v3"


def test_transcribe_raises_when_no_client(monkeypatch):
    monkeypatch.setattr(transcriber, "_client", None)

    with pytest.raises(transcriber.TranscriptionUnavailable):
        transcriber.transcribe(b"fake")


def test_transcribe_propagates_groq_exception(monkeypatch):
    mock_client = MagicMock()
    mock_client.audio.transcriptions.create.side_effect = RuntimeError("groq down")
    monkeypatch.setattr(transcriber, "_client", mock_client)

    with pytest.raises(RuntimeError, match="groq down"):
        transcriber.transcribe(b"fake")
```

- [ ] **Step 2: Ejecutar, ver que falla**

```bash
python -m pytest tests/test_transcriber.py -v
```

Expected: FAIL — `No module named 'transcriber'`.

- [ ] **Step 3: Implementar `transcriber.py`**

Contenido completo:
```python
"""Transcripción de audio a texto usando Groq Whisper API."""
from typing import Optional

from groq import Groq

from config import GROQ_API_KEY


class TranscriptionUnavailable(Exception):
    """Se lanza cuando no hay clave de Groq configurada."""


_client: Optional[Groq] = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None


def transcribe(audio_bytes: bytes) -> str:
    """Transcribe audio a texto en español usando Groq Whisper.

    Devuelve el texto transcrito (limpio de espacios al inicio/final).
    Lanza TranscriptionUnavailable si no hay API key configurada.
    Propaga cualquier otra excepción de la SDK de Groq al caller.
    """
    if _client is None:
        raise TranscriptionUnavailable(
            "GROQ_API_KEY no está configurada en .env"
        )

    result = _client.audio.transcriptions.create(
        file=("audio.ogg", audio_bytes),
        model="whisper-large-v3",
        language="es",
        response_format="text",
    )

    # response_format="text" suele devolver str, pero defendámonos por si cambia.
    if isinstance(result, str):
        return result.strip()
    return getattr(result, "text", "").strip()
```

- [ ] **Step 4: Ejecutar tests, todos pasan**

```bash
python -m pytest tests/test_transcriber.py -v
```

Expected: 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add transcriber.py tests/test_transcriber.py
git commit -m "feat(transcriber): Groq Whisper integration with Spanish forced"
```

---

## Task 3: Handler de voz en `bot.py`

**Files:**
- Modify: `bot.py`
- Modify: `tests/test_bot.py`

- [ ] **Step 1: Escribir tests nuevos**

Añadir al final de `tests/test_bot.py`:
```python


def test_process_voice_transcription_unauthorized_returns_none(monkeypatch):
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    reply = bot.process_voice_transcription("hola", from_user_id=999)
    assert reply is None


def test_process_voice_transcription_empty_returns_friendly_message(monkeypatch):
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    reply = bot.process_voice_transcription("", from_user_id=42)
    assert "no he entendido" in reply.lower()


def test_process_voice_transcription_whitespace_only_returns_friendly_message(monkeypatch):
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    reply = bot.process_voice_transcription("   \n  ", from_user_id=42)
    assert "no he entendido" in reply.lower()


def test_process_voice_transcription_composes_prefix(monkeypatch):
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)

    def fake_brain(text, user_id=0):
        return f"respuesta a: {text}"

    monkeypatch.setattr(bot.brain, "handle_message", fake_brain)

    reply = bot.process_voice_transcription("añade comprar pan", from_user_id=42)

    assert reply.startswith("📝 He entendido: «añade comprar pan»\n\n")
    assert "respuesta a: añade comprar pan" in reply


def test_process_voice_transcription_brain_exception_returns_friendly(monkeypatch):
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)

    def explode(text, user_id=0):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(bot.brain, "handle_message", explode)

    reply = bot.process_voice_transcription("hola", from_user_id=42)
    assert "no puedo procesar" in reply.lower()
```

- [ ] **Step 2: Ejecutar, ver que fallan**

```bash
python -m pytest tests/test_bot.py -v
```

Expected: 5 tests nuevos FAIL — `process_voice_transcription` no existe.

- [ ] **Step 3: Modificar `bot.py` para añadir lógica de voz**

Reemplazar el contenido completo de `bot.py` por:

```python
"""Listener de Telegram. Filtra por usuario autorizado y delega en el cerebro."""
import asyncio
import logging
from typing import Optional

from telegram import Update
from telegram.ext import (
    Application,
    ContextTypes,
    MessageHandler,
    filters,
)

import brain
import db
import transcriber
from config import ALLOWED_USER_ID, TELEGRAM_TOKEN

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("bot")


def process_incoming(text: str, from_user_id: int) -> Optional[str]:
    """Lógica pura: dado un mensaje de texto y user id, devuelve la respuesta (o None si no autorizado)."""
    if from_user_id != ALLOWED_USER_ID:
        log.warning("Mensaje ignorado de user_id no autorizado: %s", from_user_id)
        return None

    if text.strip().lower() in ("/nueva", "/reset", "/clear"):
        brain.reset_history(from_user_id)
        return "Conversación reiniciada. Empezamos de cero."

    try:
        return brain.handle_message(text, user_id=from_user_id)
    except Exception:
        log.exception("Error procesando mensaje")
        return (
            "Ahora mismo no puedo procesar esto. "
            "Prueba a reformularlo o vuelve a intentarlo en un momento."
        )


def process_voice_transcription(transcription: str, from_user_id: int) -> Optional[str]:
    """Lógica pura: dada una transcripción y user id, devuelve la respuesta completa con prefijo."""
    if from_user_id != ALLOWED_USER_ID:
        log.warning("Voz ignorada de user_id no autorizado: %s", from_user_id)
        return None

    cleaned = transcription.strip()
    if not cleaned:
        return "No he entendido nada del audio. ¿Puedes repetirlo o escribirme?"

    try:
        brain_reply = brain.handle_message(cleaned, user_id=from_user_id)
    except Exception:
        log.exception("Error procesando transcripción de voz")
        return (
            "Ahora mismo no puedo procesar esto. "
            "Prueba a reformularlo o vuelve a intentarlo en un momento."
        )

    return f"📝 He entendido: «{cleaned}»\n\n{brain_reply}"


async def _on_message(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return
    reply = process_incoming(
        text=update.message.text,
        from_user_id=update.effective_user.id,
    )
    if reply is not None:
        await update.message.reply_text(reply)


async def _on_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.voice:
        return

    from_user_id = update.effective_user.id
    if from_user_id != ALLOWED_USER_ID:
        log.warning("Voz ignorada de user_id no autorizado: %s", from_user_id)
        return

    try:
        tg_file = await context.bot.get_file(update.message.voice.file_id)
        audio_bytes = bytes(await tg_file.download_as_bytearray())
    except Exception:
        log.exception("Error descargando audio de Telegram")
        await update.message.reply_text(
            "No he podido descargar el audio. Inténtalo de nuevo."
        )
        return

    try:
        transcription = await asyncio.to_thread(transcriber.transcribe, audio_bytes)
    except transcriber.TranscriptionUnavailable:
        await update.message.reply_text(
            "Aún no he configurado la transcripción de voz. Mándame texto por ahora."
        )
        return
    except Exception:
        log.exception("Error en la transcripción")
        await update.message.reply_text(
            "Ahora mismo no puedo transcribir audios. "
            "Prueba a escribirme o vuelve a intentarlo en un minuto."
        )
        return

    reply = process_voice_transcription(transcription, from_user_id=from_user_id)
    if reply is not None:
        await update.message.reply_text(reply)


def main() -> None:
    db.init_schema()
    log.info("Base de datos lista en %s", db.DB_PATH)

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT, _on_message))
    app.add_handler(MessageHandler(filters.VOICE, _on_voice))

    log.info("Bot arrancando (polling)…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Ejecutar suite completa, todos pasan**

```bash
python -m pytest -v
```

Expected: TODO PASS (los previos + los 5 nuevos del bot).

- [ ] **Step 5: Commit**

```bash
git add bot.py tests/test_bot.py
git commit -m "feat(bot): voice message handler with transcription prefix"
```

---

## Task 4: Validación manual end-to-end

Esta tarea no añade código — verifica que la voz funciona en condiciones reales.

- [ ] **Step 1: Verificar `.env`**

Pedir al usuario que añada en su archivo `.env` la nueva variable:
```
GROQ_API_KEY=la-clave-que-saco-de-groq
```

Si la clave aún no está, parar y guiarlo (ver spec, sección "Coste estimado" para el flujo).

- [ ] **Step 2: Reiniciar el bot**

```bash
# Matar la instancia actual
pkill -f "python bot.py"

# Arrancar limpia
cd "/Users/pablocansinos/Desktop/Proyecto Prueba"
./start.sh
```

Expected: logs muestran "Bot arrancando (polling)…" sin errores.

- [ ] **Step 3: Smoke tests desde Telegram (móvil)**

Pedir al usuario que envíe estos mensajes y comprobar respuestas:

1. **Mensaje de texto:** "hola" → debe responder normal (sin prefijo, comportamiento previo intacto).
2. **Nota de voz corta:** "Hola, ¿cómo estás?" → respuesta empieza con `📝 He entendido: «...»` y luego la respuesta del cerebro.
3. **Nota de voz con acción:** "Apunta cita dentista el viernes a las 10" → debe transcribir correctamente, añadir el evento, y responder con prefijo + confirmación.
4. **Nota de voz silenciosa (graba 3s sin hablar):** debe responder "No he entendido nada del audio..."

- [ ] **Step 4: Verificar logs sin errores**

Revisar la salida del bot — no debe haber excepciones inesperadas.

- [ ] **Step 5: Commit final si hubo ajustes**

Si la validación reveló problemas y se hicieron arreglos:
```bash
git add -A
git commit -m "fix: ajustes encontrados en validación manual de voz"
```

Si todo limpio, no hace falta commit.

---

## Resumen de entregables

Al terminar el plan:

- Nuevo módulo `transcriber.py` que llama a Groq Whisper en español.
- `bot.py` con handler de voz, que reutiliza el cerebro existente.
- Prefijo `📝 He entendido: «...»` visible en cada respuesta a voz.
- Manejo de errores claro: voz sin transcribir, Groq caído, clave ausente.
- Tests nuevos: 6 para transcriber, 5 para el handler de voz.
- Documentación de diseño en `docs/superpowers/specs/`.

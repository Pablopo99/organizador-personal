# Tono, Comandos slash y Formato visual — Plan de Implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hacer el bot más cercano y rápido de usar: tono motivador tipo coach, 4 comandos slash para resúmenes (`/hoy`, `/semana`, `/pendientes`, `/objetivos`), formato visual con negritas y emojis usando HTML de Telegram.

**Architecture:** Cambios solo en `brain.py` (system prompt) y `bot.py` (parse_mode, handlers slash, menú de comandos). Los slash commands se traducen a frases naturales y pasan por el cerebro normal — sin lógica duplicada.

**Tech Stack:** Python 3.12, `python-telegram-bot` 21.6, HTML parse mode de Telegram.

**Spec de referencia:** `docs/superpowers/specs/2026-05-12-tono-comandos-formato-design.md`

---

## Convenciones

- TDD: test que falla → implementación → test pasa → commit.
- Cada Task termina en un commit cerrado.
- Comandos desde `/Users/pablocansinos/Desktop/Proyecto Prueba`.

---

## Task 1: Nuevo system prompt (tono + formato)

**Files:**
- Modify: `brain.py`
- Modify: `tests/test_brain.py`

- [ ] **Step 1: Añadir tests sobre el contenido del system prompt**

Añadir al final de `tests/test_brain.py`:
```python


def test_system_prompt_includes_motivator_tone():
    prompt = brain._system_prompt()
    lower = prompt.lower()
    # Debe mencionar el rol de coach/motivador y el tuteo
    assert "coach" in lower or "motivador" in lower
    assert "tutea" in lower or "tuteas" in lower


def test_system_prompt_includes_html_formatting():
    prompt = brain._system_prompt()
    # Debe instruir formato HTML
    assert "<b>" in prompt or "HTML" in prompt


def test_system_prompt_includes_emoji_guidance():
    prompt = brain._system_prompt()
    # Debe mencionar los emojis básicos
    assert "📅" in prompt
    assert "📝" in prompt
    assert "🎯" in prompt


def test_system_prompt_preserves_critical_rules():
    """Las reglas críticas anteriores deben seguir ahí."""
    prompt = brain._system_prompt()
    lower = prompt.lower()
    # Sigue exigiendo consultar antes de afirmar ausencia
    assert "consulta" in lower or "consúltala" in lower
    # Sigue exigiendo confirmación antes de borrar
    assert "borrar" in lower
    assert "confirma" in lower or "confirmaci" in lower
```

- [ ] **Step 2: Ejecutar, ver que fallan**

```bash
source .venv/bin/activate
python -m pytest tests/test_brain.py -v -k "system_prompt"
```

Expected: 3 tests nuevos FAIL (motivador, html, emoji). El de reglas críticas puede pasar o fallar, depende del texto actual.

- [ ] **Step 3: Reemplazar la función `_system_prompt` en `brain.py`**

Localizar la función `_system_prompt()` en `brain.py` y reemplazar **su cuerpo completo** por:

```python
def _system_prompt() -> str:
    now = datetime.now().isoformat(timespec="minutes")
    weekday = [
        "lunes", "martes", "miércoles", "jueves",
        "viernes", "sábado", "domingo",
    ][datetime.now().weekday()]
    return f"""Eres el coach personal de organización de Pablo, un usuario hispanohablante.

Contexto:
- Fecha y hora ahora: {now} ({weekday})
- Zona horaria: Europe/Madrid
- Idioma: español de España.

Personalidad y tono:
- Tuteas siempre. Cercano, motivador, con humor sano cuando encaja.
- Nunca distante ni acartonado. Como un coach que conoce a Pablo y se alegra de sus logros.
- Cuando cierre una tarea u objetivo, anímalo brevemente (una frase, sin discursos).
- Cuando le quedan muchas cosas pendientes, no abrumes — ayúdale a verlas manejables.
- Respuestas breves: confirma lo hecho en una frase, no listes datos que el usuario ya sabe.

Reglas críticas — consulta antes de afirmar:
- NUNCA digas "no tengo X registrado" o "no hay nada" sin haber llamado primero a la herramienta correspondiente (list_tasks, query_events, query_objectives).
- Antes de añadir una tarea, si sospechas que ya existe, llama a list_tasks primero. Si está, recuérdaselo en vez de duplicar.
- Antes de borrar algo, muestra lo que vas a borrar y pide confirmación explícita.

Manejo de fechas:
- Resuelve fechas relativas ("mañana", "el viernes") a ISO 8601 antes de llamar herramientas.
- Si una fecha es ambigua, pregunta antes de actuar.
- Para fechas sin año cuya fecha en el año actual ya ha pasado, asume el año siguiente y pregunta para confirmar.

Distinción de tipos:
- "Tareas" = lista pendiente sin fecha (list_tasks). "Eventos/citas/reuniones" = con fecha y hora (query_events). "Objetivos" = metas semanales (query_objectives).
- Si pregunta "¿qué tengo hoy?", consulta TANTO eventos del día COMO tareas pendientes. Muestra ambas listas si hay algo en cada una.

Formato de las respuestas (Telegram HTML):
- Las respuestas se envían a Telegram con parse_mode HTML. Usa <b>texto</b> para negrita e <i>texto</i> para cursiva.
- Confirmaciones cortas: texto plano sin formato.
- Resúmenes y listas: títulos de sección en negrita con emojis, bullets con "•".
- NO uses tablas Markdown ni asteriscos para negrita: solo HTML.
- Si el texto del usuario contiene <, > o & literales, escápalos (&lt;, &gt;, &amp;) al incluirlos en la respuesta.

Emojis con moderación: 📅 eventos, 📝 tareas, 🎯 objetivos, 💪 ánimo, ✅ hecho. Nunca uno por frase.

Plantilla para resúmenes (úsala como guía, ajusta lo que no encaje):

📅 <b>HOY</b>

• 09:00 — Reunión equipo
• 17:00 — Cita médico

📝 <b>PENDIENTES</b>

• Comprar pan
• Llamar fontanero

💪 [Cierre motivador opcional, 1 frase, solo si encaja]

Si una sección está vacía, ponla con "Nada por aquí" o simplemente omítela.

Puedes llamar varias herramientas en un mismo turno si la petición lo requiere. Si una herramienta devuelve error, explícalo con palabras claras y propón una alternativa."""
```

- [ ] **Step 4: Ejecutar tests, deben pasar**

```bash
python -m pytest tests/test_brain.py -v
```

Expected: todos PASS, incluidos los 4 nuevos.

- [ ] **Step 5: Commit**

```bash
git add brain.py tests/test_brain.py
git commit -m "feat(brain): coach tone, HTML formatting and emoji guidance in system prompt"
```

---

## Task 2: HTML parse mode y comandos slash en `bot.py`

**Files:**
- Modify: `bot.py`
- Modify: `tests/test_bot.py`

- [ ] **Step 1: Añadir tests para slash commands y parse_mode**

Añadir al final de `tests/test_bot.py`:
```python


def test_slash_hoy_dispatches_summary_text(monkeypatch):
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    captured = {}

    def fake_brain(text, user_id=0):
        captured["text"] = text
        captured["user_id"] = user_id
        return "respuesta"

    monkeypatch.setattr(bot.brain, "handle_message", fake_brain)

    reply = bot.process_slash_command("/hoy", from_user_id=42)
    assert reply == "respuesta"
    assert "hoy" in captured["text"].lower()
    assert captured["user_id"] == 42


def test_slash_semana_dispatches_week_summary(monkeypatch):
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)

    def fake_brain(text, user_id=0):
        assert "semana" in text.lower()
        return "ok"

    monkeypatch.setattr(bot.brain, "handle_message", fake_brain)
    reply = bot.process_slash_command("/semana", from_user_id=42)
    assert reply == "ok"


def test_slash_pendientes_dispatches_pending_tasks(monkeypatch):
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)

    def fake_brain(text, user_id=0):
        assert "pendientes" in text.lower() or "tareas" in text.lower()
        return "ok"

    monkeypatch.setattr(bot.brain, "handle_message", fake_brain)
    reply = bot.process_slash_command("/pendientes", from_user_id=42)
    assert reply == "ok"


def test_slash_objetivos_dispatches_objectives(monkeypatch):
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)

    def fake_brain(text, user_id=0):
        assert "objetivos" in text.lower()
        return "ok"

    monkeypatch.setattr(bot.brain, "handle_message", fake_brain)
    reply = bot.process_slash_command("/objetivos", from_user_id=42)
    assert reply == "ok"


def test_slash_unauthorized_user_returns_none(monkeypatch):
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    reply = bot.process_slash_command("/hoy", from_user_id=999)
    assert reply is None


def test_slash_unknown_command_returns_none(monkeypatch):
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    reply = bot.process_slash_command("/inventado", from_user_id=42)
    assert reply is None


def test_process_incoming_routes_known_slash_to_command_handler(monkeypatch):
    """process_incoming debe enrutar /hoy al handler de comandos, no al cerebro."""
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    called = {}

    def fake_brain(text, user_id=0):
        called["brain"] = text
        return "from brain"

    monkeypatch.setattr(bot.brain, "handle_message", fake_brain)

    reply = bot.process_incoming(text="/hoy", from_user_id=42)
    # El cerebro se llama (a través de process_slash_command), pero con frase traducida — no con "/hoy"
    assert "/hoy" not in called["brain"]
    assert reply == "from brain"
```

- [ ] **Step 2: Ejecutar, ver que fallan**

```bash
python -m pytest tests/test_bot.py -v
```

Expected: 7 tests nuevos FAIL — `process_slash_command` no existe.

- [ ] **Step 3: Reemplazar `bot.py` completo**

Reemplazar el contenido entero de `bot.py` por:

```python
"""Listener de Telegram. Filtra por usuario autorizado y delega en el cerebro."""
import asyncio
import logging
from typing import Optional

from telegram import BotCommand, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
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


# Mapa de comandos slash → frase natural que recibe el cerebro
_SLASH_PROMPTS = {
    "/hoy": "Hazme el resumen de hoy: eventos del día y tareas pendientes.",
    "/semana": "Hazme el resumen de la semana actual: eventos próximos y objetivos.",
    "/pendientes": "Lista mis tareas pendientes.",
    "/objetivos": "¿Cómo van mis objetivos de esta semana?",
}

# Comandos slash que NO van al cerebro (control de bot)
_RESET_COMMANDS = ("/nueva", "/reset", "/clear")


def process_slash_command(command: str, from_user_id: int) -> Optional[str]:
    """Lógica pura: ejecuta un comando slash conocido. Devuelve None si no autorizado o desconocido."""
    if from_user_id != ALLOWED_USER_ID:
        log.warning("Slash ignorado de user_id no autorizado: %s", from_user_id)
        return None
    cmd = command.strip().lower()
    prompt = _SLASH_PROMPTS.get(cmd)
    if prompt is None:
        return None
    try:
        return brain.handle_message(prompt, user_id=from_user_id)
    except Exception:
        log.exception("Error procesando comando %s", cmd)
        return (
            "Ahora mismo no puedo procesar esto. "
            "Prueba a reformularlo o vuelve a intentarlo en un momento."
        )


def process_incoming(text: str, from_user_id: int) -> Optional[str]:
    """Lógica pura: dado un mensaje de texto y user id, devuelve la respuesta (o None si no autorizado)."""
    if from_user_id != ALLOWED_USER_ID:
        log.warning("Mensaje ignorado de user_id no autorizado: %s", from_user_id)
        return None

    cleaned = text.strip().lower()

    if cleaned in _RESET_COMMANDS:
        brain.reset_history(from_user_id)
        return "Conversación reiniciada. Empezamos de cero."

    if cleaned in _SLASH_PROMPTS:
        return process_slash_command(cleaned, from_user_id)

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
        await update.message.reply_text(reply, parse_mode=ParseMode.HTML)


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
        await update.message.reply_text(reply, parse_mode=ParseMode.HTML)


def _make_slash_handler(command: str):
    """Factory: crea un handler async para un comando slash conocido."""
    async def handler(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message or not update.effective_user:
            return
        reply = process_slash_command(command, from_user_id=update.effective_user.id)
        if reply is not None:
            await update.message.reply_text(reply, parse_mode=ParseMode.HTML)
    return handler


async def _set_bot_commands(application: Application) -> None:
    """Registra el menú de comandos visible al escribir '/' en Telegram."""
    await application.bot.set_my_commands([
        BotCommand("hoy", "Resumen de hoy"),
        BotCommand("semana", "Resumen de la semana"),
        BotCommand("pendientes", "Tareas pendientes"),
        BotCommand("objetivos", "Objetivos de la semana"),
        BotCommand("nueva", "Reiniciar conversación"),
    ])


def main() -> None:
    db.init_schema()
    log.info("Base de datos lista en %s", db.DB_PATH)

    app = Application.builder().token(TELEGRAM_TOKEN).post_init(_set_bot_commands).build()

    # Slash commands
    for cmd in ("hoy", "semana", "pendientes", "objetivos"):
        app.add_handler(CommandHandler(cmd, _make_slash_handler(f"/{cmd}")))

    # Mensajes de texto (incluye /nueva, /reset, /clear que no están registrados como CommandHandler)
    app.add_handler(MessageHandler(filters.TEXT, _on_message))
    app.add_handler(MessageHandler(filters.VOICE, _on_voice))

    log.info("Bot arrancando (polling)…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Ejecutar suite completa**

```bash
python -m pytest -v
```

Expected: TODO PASS (los previos + los 7 nuevos del slash). Total esperado: 56 tests verdes.

- [ ] **Step 5: Commit**

```bash
git add bot.py tests/test_bot.py
git commit -m "feat(bot): HTML parse mode, slash commands and Telegram commands menu"
```

---

## Task 3: Validación manual end-to-end

Esta tarea no añade código — comprueba que todo funciona en condiciones reales.

- [ ] **Step 1: Reiniciar el bot**

```bash
pkill -9 -f "python bot.py"
pkill -9 -f "caffeinate"
sleep 5
cd "/Users/pablocansinos/Desktop/Proyecto Prueba"
./start.sh
```

Expected: logs muestran "Bot arrancando (polling)…" sin errores.

- [ ] **Step 2: Pruebas desde Telegram móvil**

Verificar con Pablo, en este orden:

1. **Tono nuevo:** "hola" → debe responder de forma cercana y tutearte. Diferente al "Hola, ¿en qué te ayudo?" formal anterior.

2. **Slash menu visible:** en el chat con el bot, tocar el icono "/" o "Menú". Debe aparecer la lista:
   - `/hoy` — Resumen de hoy
   - `/semana` — Resumen de la semana
   - `/pendientes` — Tareas pendientes
   - `/objetivos` — Objetivos de la semana
   - `/nueva` — Reiniciar conversación

3. **Comando `/hoy`:** debe responder con secciones en negrita real, emojis, bullets. Ejemplo esperado:

   📅 **HOY**
   • 09:00 — Reunión X
   📝 **PENDIENTES**
   • Tarea pendiente
   💪 Ánimo

4. **Comando `/pendientes`:** muestra solo tareas en formato lista con bullets.

5. **Comando `/objetivos`:** muestra objetivos de la semana con motivación.

6. **Mensaje de texto normal (que no se haya roto):** "qué tengo hoy" → debe responder con el mismo formato bonito (porque va por el cerebro igual).

7. **Mensaje de voz (regresión):** mandar una nota de voz pidiendo algo → debe seguir teniendo el prefijo "📝 He entendido…" y luego respuesta con formato.

8. **Cerrar tarea para validar tono motivador:** marcar como hecha una tarea → bot debe animar brevemente.

- [ ] **Step 3: Verificar logs sin errores**

Revisar la salida del bot — sin excepciones inesperadas.

- [ ] **Step 4: Commit si hubo ajustes**

Si la validación reveló problemas que se arreglaron:
```bash
git add -A
git commit -m "fix: ajustes encontrados en validación manual de tono/formato"
```

Si todo limpio, no hace falta commit.

- [ ] **Step 5: Push a GitHub**

```bash
git push
```

---

## Resumen de entregables

Al terminar:

- `brain.py` con system prompt de coach motivador, instrucciones HTML, plantilla de resúmenes.
- `bot.py` con HTML parse mode en todas las respuestas, 4 comandos slash funcionales, menú de Telegram registrado al arrancar.
- 11 tests nuevos (4 system prompt + 7 slash) además de la suite previa.
- Documento de diseño guardado.

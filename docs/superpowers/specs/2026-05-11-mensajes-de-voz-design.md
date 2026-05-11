# Mensajes de Voz — Diseño

**Fecha:** 2026-05-11
**Estado:** Diseño aprobado, pendiente de plan de implementación
**Sigue al MVP:** `2026-05-11-organizador-personal-design.md`

## Objetivo

Permitir que el usuario envíe notas de voz al bot por Telegram en lugar de escribir, especialmente útil cuando va andando o no puede escribir. El bot transcribe el audio a texto, muestra al usuario qué entendió y procesa el contenido por el mismo flujo conversacional que ya existe.

Filosofía: la voz es una "puerta de entrada" alternativa, no un sistema paralelo. Todo lo que entra por voz acaba como texto que pasa por el cerebro (`brain.py`) ya existente.

## Decisiones clave

- **Solo voz de entrada.** El bot transcribe lo que tú le mandas pero responde por texto. No hay text-to-speech.
- **Servicio de transcripción:** Groq Whisper API (gratis con tier generoso, rapidez ~1s, calidad excelente en español).
- **Idioma forzado a español** en la llamada a Groq para evitar transcripciones falsas en inglés.
- **Siempre mostrar la transcripción** al usuario al inicio de la respuesta, con formato `📝 He entendido: «...»`. Esto permite detectar errores de transcripción al momento.
- **Formato de audio:** Telegram entrega `.ogg` (OGG/Opus). Groq lo acepta nativo, no se convierte.

## Arquitectura

```
Usuario (graba nota de voz)
    │
    ▼
bot.py — detecta update.message.voice
    │
    ▼
Descarga el .ogg via context.bot.get_file(voice.file_id)
    │
    ▼
transcriber.transcribe(audio_bytes) → texto
    │
    ▼
brain.handle_message(texto, user_id) → respuesta
    │
    ▼
bot.py compone:
    "📝 He entendido: «{transcripcion}»\n\n{respuesta_cerebro}"
    │
    ▼
Telegram envía al usuario
```

Componentes:

- **`transcriber.py` (nuevo):** una sola función `transcribe(audio_bytes: bytes) -> str`. Encapsula la llamada al SDK de Groq. No mantiene estado.
- **`bot.py` (modificado):** añade un `MessageHandler(filters.VOICE)` que descarga el audio, lo pasa al transcriber, y delega al flujo de texto existente.
- **`config.py` (modificado):** añade `GROQ_API_KEY` como variable requerida.
- **`requirements.txt` (modificado):** añade `groq` (SDK oficial).
- **`.env.example` (modificado):** añade plantilla para `GROQ_API_KEY=`.

Lo que **no** se toca: `brain.py`, `tools.py`, `db.py`, `date_utils.py`. La voz no añade nuevas funcionalidades de dominio, solo una vía de entrada.

## Detalles técnicos

### Cliente Groq

Usar `groq.Groq(api_key=...)` y llamar a `client.audio.transcriptions.create(file=(filename, audio_bytes), model="whisper-large-v3", language="es", response_format="text")`.

Modelo: `whisper-large-v3` (el más preciso disponible en Groq, gratis para uso personal).

### Descarga del audio en Telegram

```python
voice = update.message.voice  # objeto Voice de python-telegram-bot
file = await context.bot.get_file(voice.file_id)
audio_bytes = await file.download_as_bytearray()
```

### Composición de respuesta

```python
prefix = f"📝 He entendido: «{transcripcion}»\n\n"
respuesta = brain.handle_message(transcripcion, user_id=user_id)
await update.message.reply_text(prefix + respuesta)
```

## Manejo de errores

| Situación | Respuesta del bot |
|---|---|
| Transcripción vacía (silencio) | "No he entendido nada del audio. ¿Puedes repetirlo o escribirme?" |
| Groq API falla (excepción, timeout, rate limit) | "Ahora mismo no puedo transcribir audios. Prueba a escribirme o vuelve a intentarlo en un minuto." |
| `GROQ_API_KEY` ausente o vacía en `.env` | "Aún no he configurado la transcripción de voz. Mándame texto por ahora." |
| Transcripción correcta pero contenido extraño | Se procesa normalmente; el usuario ve la transcripción en `📝 He entendido…` y puede corregir con un siguiente mensaje (memoria conversacional cubre el follow-up). |

## Seguridad

- La autorización por `ALLOWED_USER_ID` aplica igual: si un usuario no autorizado manda voz, se ignora silenciosamente (igual que con texto).
- El audio se transmite a Groq sobre HTTPS. No se persiste en disco — el bot lo descarga a memoria, lo manda a Groq, lo descarta.
- `GROQ_API_KEY` vive en `.env`, fuera del repo (gitignored).

## Tests

1. `transcriber.transcribe(audio_bytes)` con cliente Groq mockeado → devuelve string.
2. `transcriber.transcribe` cuando Groq devuelve texto vacío → función devuelve string vacío (el caller decide qué hacer).
3. `transcriber.transcribe` cuando Groq lanza excepción → la excepción se propaga (el caller la maneja).
4. `bot.py`: handler de voz con transcripción exitosa → llama al cerebro y compone la respuesta con prefijo.
5. `bot.py`: handler de voz con transcripción vacía → responde con mensaje fijo, no llama al cerebro.
6. `bot.py`: handler de voz con error de transcripción → responde con mensaje fijo de error.

## Coste estimado

Groq tier gratuito: límite generoso (cientos de minutos diarios). Para uso personal típico (10-20 audios de <30s al día), el coste es **0 €**.

Si en algún momento se supera el tier gratuito, las opciones son: (a) esperar al reset diario, (b) cambiar a OpenAI Whisper (~0,5 céntimos/minuto), (c) usar Whisper local.

## Fuera del alcance

- ❌ Respuestas en audio del bot (text-to-speech).
- ❌ Transcripción de mensajes de audio reenviados o adjuntos no nativos de Telegram.
- ❌ Multi-idioma — fuerza español.
- ❌ Persistencia de audios (no se guardan en disco ni en BD).

## Criterios de éxito

- Puedo enviar una nota de voz al bot desde Telegram móvil y recibe una respuesta correcta en menos de ~5 segundos.
- La respuesta incluye el prefijo `📝 He entendido: «…»` con el texto transcrito.
- Si grabo un audio en español pidiendo añadir un evento ("apunta cita médico el viernes a las 10"), se añade correctamente.
- Si la transcripción está vacía o falla, recibo un mensaje claro y no se rompe el bot.
- Todos los tests automáticos pasan.

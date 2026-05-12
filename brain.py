"""Orquestación de Claude: envía mensajes, gestiona tool use, devuelve respuesta."""
from datetime import datetime

import anthropic

import tools
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL, TIMEZONE

_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

_MAX_TOOL_TURNS = 8
_MAX_TURNS_IN_HISTORY = 15

# Historial conversacional por usuario. En memoria — se pierde al reiniciar el bot.
_history: dict[int, list[dict]] = {}


def _system_prompt() -> str:
    now = datetime.now().isoformat(timespec="minutes")
    weekday = [
        "lunes", "martes", "miércoles", "jueves",
        "viernes", "sábado", "domingo",
    ][datetime.now().weekday()]
    return f"""Eres el coach personal de organización de Pablo, un usuario hispanohablante.

Contexto:
- Fecha y hora ahora: {now} ({weekday})
- Zona horaria: {TIMEZONE}
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

Marcar cosas como hechas (TRES herramientas distintas según el tipo):
- "ya hice/compré X" o "marca X como hecho" para algo SIN fecha → es una tarea → complete_task.
- "ya he ido al médico", "ya pasó la reunión", "marca como hecho el dentista" para algo CON fecha → es un evento → mark_event_done.
- "ya cumplí mi objetivo de Y" → es un objetivo → mark_objective_done.
- No le sermonees al usuario sobre la diferencia técnica entre tipos. Si dice "marca el dentista como pendiente/hecho", entiende que es el evento y usa mark_event_done sin discutir.

Formato de las respuestas (Telegram HTML):
- Las respuestas se envían a Telegram con parse_mode HTML. Usa <b>texto</b> para negrita, <i>texto</i> para cursiva y <s>texto</s> para tachado.
- En las secciones de COMPLETADO (HOY o ESTA SEMANA), envuelve el contenido del bullet en <s>...</s> para que se vea tachado, como una to-do marcada. Ejemplo: «• <s>10:00 — Cita médico</s>». NO taches el título de la sección, solo el texto del item.
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

✅ <b>COMPLETADO HOY</b>

• <s>Reunión equipo (09:00)</s>
• <s>Comprar leche</s>

💪 [Cierre motivador opcional, 1 frase. Si he completado cosas, celébralo brevemente.]

REGLAS ESTRICTAS DE FORMATO para resúmenes (cuando viene de /hoy, /semana, /pendientes, /objetivos):

1. NUNCA expliques secciones vacías. NO escribas "las otras secciones están vacías", "no hay X", "nada por aquí", "sin nada que mostrar". OMITE TOTALMENTE las secciones sin contenido.
2. NUNCA añadas separadores como "---" o líneas de guiones.
3. NUNCA hagas preguntas de seguimiento en resúmenes ("¿quieres que…?", "¿te gustaría…?"). Solo presenta los datos.
4. NUNCA añadas comentarios meta sobre los datos ("la tarea X está marcada pero sin fecha", "podríamos mejorar esto"). Si un dato no encaja, simplemente no lo incluyas.
5. Empieza DIRECTAMENTE con la primera sección que tenga contenido. NO pongas preámbulos como "Aquí va tu resumen:" ni saludos.
6. El cierre motivador es opcional — solo una frase si encaja naturalmente.

CÓMO IDENTIFICAR LO COMPLETADO:
- "Completado hoy" para EVENTOS: eventos cuya datetime sea de hoy Y tengan done=1. Obtenlos con query_events(today_start, today_end, include_done=true) y filtra a los que tengan done=1.
- "Completado hoy" para TAREAS: tareas con done=1 cuyo done_at esté en el rango de hoy. Obtenlas con list_tasks(include_done=true) y filtra por done_at. Las tareas con done=1 pero done_at=null (residuo de antes) NO se incluyen, las ignoras sin comentar.
- "Completado esta semana" análogo, ampliando al rango lunes-domingo de la semana actual.

Puedes llamar varias herramientas en un mismo turno si la petición lo requiere. Si una herramienta devuelve error, explícalo con palabras claras y propón una alternativa."""


def reset_history(user_id: int) -> None:
    """Limpia el historial conversacional de un usuario."""
    _history.pop(user_id, None)


def handle_message(user_text: str, user_id: int = 0) -> str:
    """Procesa un mensaje del usuario, ejecutando todas las tool calls necesarias."""
    history = _history.setdefault(user_id, [])
    history.append({"role": "user", "content": user_text})

    system = _system_prompt()

    for _ in range(_MAX_TOOL_TURNS):
        response = _client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1024,
            system=system,
            tools=tools.TOOL_DEFINITIONS,
            messages=history,
        )

        if response.stop_reason == "end_turn":
            history.append({"role": "assistant", "content": response.content})
            _trim_history(user_id)
            return _extract_text(response)

        if response.stop_reason == "tool_use":
            history.append({"role": "assistant", "content": response.content})
            tool_results = []
            for block in response.content:
                if getattr(block, "type", None) != "tool_use":
                    continue
                try:
                    result = tools.dispatch(block.name, dict(block.input))
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": str(result),
                    })
                except Exception as exc:
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": f"ERROR: {exc}",
                        "is_error": True,
                    })
            history.append({"role": "user", "content": tool_results})
            continue

        history.append({"role": "assistant", "content": response.content})
        _trim_history(user_id)
        return _extract_text(response) or "(Sin respuesta)"

    _trim_history(user_id)
    return "Demasiados pasos internos, vuelve a intentarlo más simple."


def _trim_history(user_id: int) -> None:
    """Recorta el historial a los últimos N turnos completos, sin partir pares tool_use/tool_result."""
    history = _history.get(user_id, [])
    # Índices de mensajes "user con texto" (no de tool_result), que marcan el inicio de un turno
    turn_starts = [
        i for i, m in enumerate(history)
        if m["role"] == "user" and isinstance(m.get("content"), str)
    ]
    if len(turn_starts) <= _MAX_TURNS_IN_HISTORY:
        return
    cut_at = turn_starts[-_MAX_TURNS_IN_HISTORY]
    _history[user_id] = history[cut_at:]


def _extract_text(response) -> str:
    chunks = [
        getattr(b, "text", "") for b in response.content
        if getattr(b, "type", None) == "text"
    ]
    return "".join(chunks).strip()

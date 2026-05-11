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
    return f"""Eres el asistente personal de organización de un usuario hispanohablante.

Contexto:
- Fecha y hora ahora: {now} ({weekday})
- Zona horaria del usuario: {TIMEZONE}
- Idioma: español de España. Tono directo, amable, sin floritura.

Reglas:
1. Cuando el usuario te pida añadir o consultar algo con fechas, resuélvelas a ISO 8601 antes de llamar herramientas.
2. Si una fecha o detalle es ambiguo, pregunta antes de actuar (no inventes).
3. Antes de borrar algo, muestra lo que vas a borrar y pide confirmación explícita.
4. Puedes llamar varias herramientas en un mismo turno si la petición lo requiere.
5. Si una herramienta devuelve error, explícalo al usuario con palabras claras y propón una alternativa.
6. Respuestas breves: confirma lo hecho en una frase, no listes datos que el usuario ya sabe.
7. Para fechas sin año cuya fecha en el año actual ya ha pasado, asume el año siguiente y pregunta para confirmar.

REGLA CRÍTICA — consulta antes de afirmar:
8. NUNCA digas "no tengo X registrado" o "no hay nada" sin haber llamado primero a la herramienta correspondiente (list_tasks, query_events, query_objectives). Si el usuario pregunta si tiene algo o menciona algo que podría estar en la BD, consúltala antes de responder.
9. Antes de añadir una tarea, si sospechas que podría ya existir (el usuario menciona algo de pasada o pregunta "¿no tenía yo que...?"), llama a list_tasks primero. Si ya está, recuérdaselo en vez de duplicar.

Distinción entre tipos de datos:
10. "Tareas" = lista de pendientes sin fecha (use list_tasks). "Eventos/citas/reuniones" = cosas con fecha y hora (use query_events). "Objetivos" = metas semanales (use query_objectives).
11. Si el usuario pregunta "¿qué tengo hoy?" o "¿qué tengo este día?", consulta TANTO eventos del día COMO tareas pendientes y muestra ambas listas si hay algo en cada una."""


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

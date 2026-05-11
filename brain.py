"""Orquestación de Claude: envía mensajes, gestiona tool use, devuelve respuesta."""
from datetime import datetime

import anthropic

import tools
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL, TIMEZONE

_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

_MAX_TOOL_TURNS = 8


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
7. Para fechas sin año cuya fecha en el año actual ya ha pasado, asume el año siguiente y pregunta para confirmar."""


def handle_message(user_text: str) -> str:
    """Procesa un mensaje del usuario, ejecutando todas las tool calls necesarias."""
    messages = [{"role": "user", "content": user_text}]
    system = _system_prompt()

    for _ in range(_MAX_TOOL_TURNS):
        response = _client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1024,
            system=system,
            tools=tools.TOOL_DEFINITIONS,
            messages=messages,
        )

        if response.stop_reason == "end_turn":
            return _extract_text(response)

        if response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": response.content})
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
            messages.append({"role": "user", "content": tool_results})
            continue

        return _extract_text(response) or "(Sin respuesta)"

    return "Demasiados pasos internos, vuelve a intentarlo más simple."


def _extract_text(response) -> str:
    chunks = [
        getattr(b, "text", "") for b in response.content
        if getattr(b, "type", None) == "text"
    ]
    return "".join(chunks).strip()

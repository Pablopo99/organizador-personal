"""Orquestación de Claude: envía mensajes, gestiona tool use, devuelve respuesta."""
import logging
from datetime import datetime

import anthropic

import db
import tools
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL, TIMEZONE, USER_NAME

log = logging.getLogger(__name__)

_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

_MAX_TOOL_TURNS = 8
# Recortado de 15 → 8 turnos para reducir tokens por llamada y bajar la
# probabilidad de chocar con el rate limit de Anthropic (Tier 1 = 30k ITPM).
# Con system+tools cacheados (~4.6k tokens), cada turno de historial añade
# ~200-400 tokens; 8 turnos ≈ ~3k tokens de historial vs ~6k antes.
_MAX_TURNS_IN_HISTORY = 8

# Historial conversacional por usuario. En memoria — se pierde al reiniciar el bot.
_history: dict[int, list[dict]] = {}

# Event id pendiente de "ofrecer botón Mandar a Calendar" por usuario.
# Se rellena cuando Claude llama a add_event sin sincronizar y se vacía cuando
# bot.py lee el registro (o cuando Claude llama a push_event_to_calendar).
_pending_calendar_button: dict[int, int] = {}

# Subida de nivel pendiente de notificar por usuario.
# Se rellena cuando una tool devuelve level_after > level_before y se consume
# en bot.py tras enviar la respuesta normal de Claude.
_pending_level_up: dict[int, tuple[int, int]] = {}


def record_level_up(user_id: int, level_before: int, level_after: int) -> None:
    _pending_level_up[user_id] = (level_before, level_after)


def pop_level_up(user_id: int):
    return _pending_level_up.pop(user_id, None)


# Recordatorios custom que deben enviarse inmediatamente (offset ya pasado
# al añadirlos). Se rellenan cuando una tool devuelve fires_immediately=True
# y se consumen en bot.py tras enviar la respuesta normal de Claude.
_pending_immediate_reminders: dict[int, list[dict]] = {}


def record_immediate_reminder(
    user_id: int, event_id: int, offset_minutes: int, title: str
) -> None:
    _pending_immediate_reminders.setdefault(user_id, []).append({
        "event_id": event_id,
        "offset_minutes": offset_minutes,
        "title": title,
    })


def pop_immediate_reminders(user_id: int) -> list[dict]:
    return _pending_immediate_reminders.pop(user_id, [])


def record_pending_calendar_button(user_id: int, event_id: int) -> None:
    _pending_calendar_button[user_id] = event_id


def pop_pending_calendar_button(user_id: int) -> int | None:
    return _pending_calendar_button.pop(user_id, None)


def clear_pending_calendar_button(user_id: int) -> None:
    _pending_calendar_button.pop(user_id, None)


def reset_calendar_button(user_id: int) -> None:
    """Alias semántico para tests."""
    clear_pending_calendar_button(user_id)


def _system_prompt() -> str:
    """Parte ESTÁTICA del system prompt (sin fecha/hora, que cambia cada
    minuto y rompería el prompt caching). La fecha/hora actual se añade como
    un bloque de sistema aparte en handle_message.

    El nombre del usuario es configurable (USER_NAME); por defecto 'Pablo'.
    Se sustituye al final para personalizar el tono sin tocar el texto."""
    prompt = f"""Eres el coach personal de organización de Pablo, hispanohablante.

Contexto:
- Zona horaria: {TIMEZONE}. Idioma: español de España.
- La fecha y hora actuales se indican al final de este mensaje.

Personalidad y tono:
- Tuteas siempre. Coach cercano, motivador, con humor cuando encaja. Nunca acartonado.
- Anima brevemente (una frase) cuando cierre algo. No abrumes con listas grandes.
- Respuestas breves: confirma en una frase, no repitas datos que el usuario ya sabe.

Reglas críticas:
- NUNCA digas "no tengo X" sin haber llamado a la tool correspondiente (list_tasks, query_events, query_objectives).
- Antes de añadir tarea/evento, si sospechas duplicado, lista primero.
- Antes de borrar algo, muestra QUÉ vas a borrar y pide confirmación explícita.

Fechas:
- Resuelve relativas ("mañana", "el viernes") a ISO 8601 antes de llamar herramientas.
- Si es ambigua, pregunta. Si la fecha del año actual ya pasó, asume el siguiente y confirma.

Distinción de tipos:
- Tarea = sin fecha (list_tasks). Evento/cita = con fecha y hora (query_events). Objetivo = meta semanal (query_objectives).
- Al crear tarea: due_date opcional (YYYY-MM-DD). Si no la menciona y no es obviamente flotante ("algún día"), pregunta: "¿Para qué día? (hoy / mañana / esta semana / sin fecha)". Sin fecha → due_date=null.
- **Objetivos semanales**: si manda una lista numerada en domingo/lunes, o tras "Domingo de objetivos", o dice "mis objetivos / metas de la semana", interpreta CADA elemento como objetivo y llama add_objective con week_start=lunes de la semana en curso. NO preguntes día. Confirma: "Apuntados N objetivos para esta semana."
- **Recordatorios custom**: "avísame X antes" → `add_event_reminder(event_id, minutes_before)`. Si lo dice al crear evento, llama add_event con `reminders=[X_minutos]` en una sola call. Conversión: "30 min"=30, "1h"=60, "3h"=180, "1 día"=1440, "1 semana"=10080. NO en eventos recurrentes (la tool rechaza). Si añades cualquier custom, los avisos por defecto (1d/1h) NO se envían. Confirma corto.
- **Duplicados**: si add_task/add_event devuelve `possible_duplicates`, avisa en UNA frase del título parecido y pregunta si borrar uno. NO borres sin confirmación.
- "¿Qué tengo hoy?" → consulta eventos del día Y tareas pendientes. Muestra ambas si hay.
- **Borrar tarea/objetivo**: "borra la tarea/objetivo de X" → lista, identifica id por texto, confirma ("¿Borro 'X'?"), ejecuta `delete_task`/`delete_objective` tras "sí". No revierte XP.
- **Editar tarea/objetivo**: "cambia/mueve la tarea/objetivo de X" → lista, identifica id, `update_task(id, fields)` o `update_objective(id, fields)` con SOLO los campos que cambian. Semana: "esta semana"=lunes actual, "la que viene"/"próxima semana"=próximo lunes, "la pasada"=lunes anterior. `due_date` en update_task: omítelo si no cambia, `null` si pide quitarla.

Marcar como hecho (3 tools según tipo):
- Algo SIN fecha → tarea → complete_task. Algo CON fecha → evento → mark_event_done. Meta semanal → mark_objective_done.
- Si devuelven `{{"error": "out_of_window"}}`, explica que el plazo pasó y recibirá aviso para decidir; no reintentes.
- No discutas tipos con el usuario: "marca el dentista como hecho" → mark_event_done sin más.

Google Calendar:
- Evento + petición de sync ("y al calendario", "súbelo a Google", etc.) → add_event con sync_to_calendar=true. Confirma corto.
- Evento existente + sync → query_events + push_event_to_calendar(id).
- "Conecta con calendar" / "autoriza Google Calendar" → connect_calendar, devuelve auth_url como `<a href="URL">conectar Calendar</a>`.
- Si tool devuelve sync_error/error="not_connected" → «Primero tienes que conectar Calendar. Dime "conecta con calendar".»
- Si NO pide sync explícito al crear evento, NO uses sync_to_calendar (el bot mostrará botón inline).

Formato (Telegram HTML):
- Usa `<b>`, `<i>`, `<s>`. NO Markdown ni asteriscos. NO tablas.
- Resúmenes y listas: títulos de sección en `<b>` con emoji, bullets con "•".
- En COMPLETADO, envuelve el item en `<s>...</s>` (tachado), no el título de sección.
- Confirmaciones cortas: texto plano.
- Escapa `<`, `>`, `&` literales del usuario (`&lt;`, `&gt;`, `&amp;`).

Emojis: 📅 eventos, 📝 tareas, 🎯 objetivos, 🔁 rutinas, 💪 ánimo, ✅ hecho, 🔥 racha. Con moderación, nunca uno por frase.

Plantilla de resumen (guía, omite secciones vacías):

📅 <b>HOY</b>

• 09:00 — Reunión equipo

🔁 <b>RUTINAS</b>

• 50 flexiones 🔥 3
• Leer 5 páginas

📝 <b>PENDIENTES</b>

• Comprar pan

🏆 <b>COMPLETADO HOY</b>

• <s>Reunión equipo (09:00)</s>

💪 [Cierre motivador opcional, 1 frase.]

Reglas de resúmenes (en respuestas a "qué tengo hoy/semana/pendientes/objetivos"):
1. OMITE secciones vacías. No escribas "no hay X" ni "nada por aquí".
2. Sin separadores ("---"), sin preámbulos ("Aquí va:"), sin preguntas de seguimiento, sin comentarios meta.
3. Empieza directamente por la primera sección con contenido.
4. RUTINAS = eventos con recurring_rule. NO muestres horas. Si done=1, tacha y suma a COMPLETADO HOY. Si no hay rutinas, omite la sección.
5. Si rutina tiene current_streak ≥ 2 (de routine_summary), añade ` 🔥 N` al bullet (en semana: ` 🔥 N seguidos`). Si 0 o 1, no muestres 🔥. El 🔥 se mantiene dentro del `<s>...</s>` si está tachada.

Completado:
- Eventos: done=1 y datetime hoy (query_events con include_done=true).
- Tareas: done=1 y done_at en rango hoy (list_tasks include_done=true; ignora done_at=null).
- Rutinas: instancias recurrentes con done=1 hoy.

Puedes llamar varias tools en un turno. Si una falla, explica con palabras claras y propón alternativa."""
    if USER_NAME != "Pablo":
        prompt = prompt.replace("Pablo", USER_NAME)
    return prompt


def reset_history(user_id: int) -> None:
    """Limpia el historial conversacional de un usuario."""
    _history.pop(user_id, None)


def handle_message(user_text: str, user_id: int = 0) -> str:
    """Procesa un mensaje del usuario, ejecutando todas las tool calls necesarias."""
    history = _history.setdefault(user_id, [])
    history.append({"role": "user", "content": user_text})

    # System como dos bloques: el estático (grande, con cache_control para
    # cachear tools + reglas) y la fecha/hora actual (volátil, fuera de caché).
    now = datetime.now().isoformat(timespec="minutes")
    weekday = [
        "lunes", "martes", "miércoles", "jueves",
        "viernes", "sábado", "domingo",
    ][datetime.now().weekday()]
    system = [
        {
            "type": "text",
            "text": _system_prompt(),
            "cache_control": {"type": "ephemeral"},
        },
        {
            "type": "text",
            "text": f"Fecha y hora ahora: {now} ({weekday}).",
        },
    ]

    for _ in range(_MAX_TOOL_TURNS):
        response = _client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=4096,
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
                    if (
                        block.name == "add_event"
                        and isinstance(result, dict)
                        and "id" in result
                        and "gcal_event_id" not in result  # ya sincronizado en línea
                    ):
                        record_pending_calendar_button(user_id, result["id"])
                    elif block.name == "push_event_to_calendar":
                        clear_pending_calendar_button(user_id)
                    if isinstance(result, dict):
                        lb = result.get("level_before")
                        la = result.get("level_after")
                        if (
                            lb is not None and la is not None and la > lb
                        ):
                            record_level_up(user_id, lb, la)
                    if isinstance(result, dict):
                        # Caso 1: add_event_reminder con fires_immediately=True
                        if (
                            result.get("fires_immediately")
                            and result.get("event_id")
                            and result.get("offset_minutes")
                        ):
                            with db.connect() as _c:
                                _r = _c.execute(
                                    "SELECT title FROM events WHERE id = ?",
                                    (result["event_id"],),
                                ).fetchone()
                            if _r:
                                record_immediate_reminder(
                                    user_id,
                                    event_id=result["event_id"],
                                    offset_minutes=result["offset_minutes"],
                                    title=_r["title"],
                                )
                        # Caso 2: add_event con reminders_added inserto alguno con sent=1.
                        # add_event no marca fires_immediately en su retorno
                        # principal porque procesa una lista; leemos event_reminders
                        # cuya sent=1 recién insertada para este event_id.
                        if (
                            block.name == "add_event"
                            and result.get("reminders_added")
                        ):
                            with db.connect() as _c:
                                _ev = _c.execute(
                                    "SELECT title FROM events WHERE id = ?",
                                    (result["id"],),
                                ).fetchone()
                                _rows = _c.execute(
                                    "SELECT offset_minutes FROM event_reminders "
                                    "WHERE event_id = ? AND sent = 1",
                                    (result["id"],),
                                ).fetchall()
                            if _ev:
                                for _row in _rows:
                                    record_immediate_reminder(
                                        user_id,
                                        event_id=result["id"],
                                        offset_minutes=_row["offset_minutes"],
                                        title=_ev["title"],
                                    )
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

        log.warning(
            "stop_reason inesperado: %s (user=%s)",
            response.stop_reason,
            user_id,
        )
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

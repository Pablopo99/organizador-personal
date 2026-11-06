import os
import tempfile
from unittest.mock import MagicMock

import pytest

import db
import brain


@pytest.fixture(autouse=True)
def temp_db(monkeypatch):
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init_schema()
    # Limpia el historial conversacional para que los tests no se influyan
    brain._history.clear()
    yield path
    os.unlink(path)


def _text_response(text: str):
    """Mensaje final del asistente (formato OpenAI/AiKit)."""
    return {"role": "assistant", "content": text}


def _tool_use_then_text(tool_name: str, tool_input: dict, final_text: str):
    """Simula dos turnos: primero tool_calls, luego texto final."""
    import json
    first = {
        "role": "assistant",
        "content": None,
        "tool_calls": [{
            "id": "call_1",
            "type": "function",
            "function": {"name": tool_name, "arguments": json.dumps(tool_input)},
        }],
    }
    return [first, _text_response(final_text)]


def _mock_chat(monkeypatch):
    """Sustituye llm_client.chat por un MagicMock y lo devuelve."""
    mock = MagicMock()
    monkeypatch.setattr(brain.llm_client, "chat", mock)
    return mock


def test_handle_message_text_only(monkeypatch):
    mock = _mock_chat(monkeypatch)
    mock.return_value = _text_response("Hola, ¿en qué te ayudo?")

    reply = brain.handle_message("hola")
    assert "Hola" in reply


def test_handle_message_sends_date_in_system(monkeypatch):
    """La fecha/hora actual va al final del system prompt."""
    mock = _mock_chat(monkeypatch)
    mock.return_value = _text_response("ok")

    brain.handle_message("hola", user_id=1234)

    system = mock.call_args.kwargs["system"]
    assert isinstance(system, str)
    assert "Fecha y hora ahora" in system.splitlines()[-1]


def test_handle_message_invalid_tool_arguments_reported_to_model(monkeypatch):
    """AiKit no garantiza JSON válido: si los arguments no parsean, se devuelve
    un error a la IA en vez de reventar."""
    bad = {
        "role": "assistant", "content": None,
        "tool_calls": [{"id": "call_x", "type": "function",
                        "function": {"name": "add_task", "arguments": "{roto"}}],
    }
    seen = []

    def fake_chat(**kwargs):
        seen.append(list(kwargs["messages"]))
        return bad if len(seen) == 1 else _text_response("Perdona, repito")

    monkeypatch.setattr(brain.llm_client, "chat", fake_chat)
    reply = brain.handle_message("añade algo", user_id=5)
    assert reply == "Perdona, repito"
    tool_msg = seen[1][-1]
    assert tool_msg["role"] == "tool"
    assert tool_msg["tool_call_id"] == "call_x"
    assert "ERROR" in tool_msg["content"]


def test_handle_message_with_tool_use(monkeypatch):
    responses = _tool_use_then_text(
        "add_task", {"text": "comprar pan"}, "Hecho, añadida."
    )
    mock = _mock_chat(monkeypatch)
    mock.side_effect = responses

    reply = brain.handle_message("añade comprar pan")
    assert "Hecho" in reply

    import tools
    rows = tools.list_tasks()
    assert len(rows) == 1
    assert rows[0]["text"] == "comprar pan"


def test_history_persists_across_calls(monkeypatch):
    snapshots = []

    def fake_chat(**kwargs):
        # Capturamos una copia superficial de messages en el momento de la llamada
        snapshots.append(list(kwargs["messages"]))
        return _text_response("respuesta")

    monkeypatch.setattr(brain.llm_client, "chat", fake_chat)

    brain.handle_message("hola", user_id=1)
    brain.handle_message("y ahora?", user_id=1)

    # Primera llamada: solo el primer user
    assert snapshots[0] == [{"role": "user", "content": "hola"}]
    # Segunda llamada: primer user + assistant + segundo user
    assert len(snapshots[1]) == 3
    assert snapshots[1][0] == {"role": "user", "content": "hola"}
    assert snapshots[1][1]["role"] == "assistant"
    assert snapshots[1][2] == {"role": "user", "content": "y ahora?"}


def test_reset_history_clears_user(monkeypatch):
    mock = _mock_chat(monkeypatch)
    mock.return_value = _text_response("ok")

    brain.handle_message("hola", user_id=7)
    assert 7 in brain._history
    brain.reset_history(7)
    assert 7 not in brain._history


def test_trim_history_keeps_last_n_turns(monkeypatch):
    mock = _mock_chat(monkeypatch)
    mock.return_value = _text_response("ok")
    monkeypatch.setattr(brain, "_MAX_TURNS_IN_HISTORY", 3)

    for i in range(5):
        brain.handle_message(f"msg {i}", user_id=99)

    history = brain._history[99]
    user_texts = [m for m in history if m["role"] == "user" and isinstance(m.get("content"), str)]
    assert len(user_texts) == 3
    assert user_texts[0]["content"] == "msg 2"
    assert user_texts[-1]["content"] == "msg 4"


def test_system_prompt_includes_motivator_tone():
    prompt = brain._system_prompt()
    lower = prompt.lower()
    assert "coach" in lower or "motivador" in lower
    assert "tutea" in lower or "tuteas" in lower


def test_system_prompt_includes_html_formatting():
    prompt = brain._system_prompt()
    assert "<b>" in prompt or "HTML" in prompt


def test_system_prompt_includes_emoji_guidance():
    prompt = brain._system_prompt()
    assert "📅" in prompt
    assert "📝" in prompt
    assert "🎯" in prompt


def test_system_prompt_preserves_critical_rules():
    """Las reglas críticas anteriores deben seguir ahí."""
    prompt = brain._system_prompt()
    lower = prompt.lower()
    assert "consulta" in lower or "consúltala" in lower
    assert "borrar" in lower
    assert "confirma" in lower or "confirmaci" in lower


def test_system_prompt_includes_rutinas_section():
    prompt = brain._system_prompt()
    assert "🔁" in prompt
    assert "RUTINAS" in prompt


def test_system_prompt_mentions_streak_emoji():
    prompt = brain._system_prompt()
    assert "🔥" in prompt


def test_pending_calendar_button_starts_empty():
    import brain
    brain.reset_calendar_button(42)
    assert brain.pop_pending_calendar_button(42) is None


def test_record_then_pop_calendar_button():
    import brain
    brain.reset_calendar_button(42)
    brain.record_pending_calendar_button(42, event_id=7)
    assert brain.pop_pending_calendar_button(42) == 7
    # tras pop, queda vacío
    assert brain.pop_pending_calendar_button(42) is None


def test_push_event_to_calendar_clears_pending():
    import brain
    brain.reset_calendar_button(42)
    brain.record_pending_calendar_button(42, event_id=7)
    brain.clear_pending_calendar_button(42)
    assert brain.pop_pending_calendar_button(42) is None


def test_system_prompt_mentions_calendar_tools():
    import brain
    prompt = brain._system_prompt()
    assert "push_event_to_calendar" in prompt
    assert "connect_calendar" in prompt
    # Frases-trigger esperadas
    assert "calendar" in prompt.lower()


def test_record_and_pop_level_up():
    """record_level_up persiste hasta pop."""
    import brain
    brain.record_level_up(42, 4, 5)
    res = brain.pop_level_up(42)
    assert res == (4, 5)
    # Segunda llamada → None
    assert brain.pop_level_up(42) is None


def test_record_and_pop_immediate_reminders():
    import brain
    brain.record_immediate_reminder(42, event_id=7, offset_minutes=30, title="Cita")
    brain.record_immediate_reminder(42, event_id=9, offset_minutes=60, title="Médico")
    res = brain.pop_immediate_reminders(42)
    assert len(res) == 2
    titles = {r["title"] for r in res}
    assert titles == {"Cita", "Médico"}
    # Segunda llamada → lista vacía
    assert brain.pop_immediate_reminders(42) == []


def test_pop_immediate_reminders_unknown_user_returns_empty():
    import brain
    assert brain.pop_immediate_reminders(99999) == []


def test_system_prompt_personalizes_user_name(monkeypatch):
    monkeypatch.setattr(brain, "USER_NAME", "Ana")
    prompt = brain._system_prompt()
    assert "Ana" in prompt
    assert "Pablo" not in prompt


def test_system_prompt_default_name_pablo(monkeypatch):
    monkeypatch.setattr(brain, "USER_NAME", "Pablo")
    prompt = brain._system_prompt()
    assert "Pablo" in prompt


def test_system_prompt_mentions_delete_task_and_objective():
    prompt = brain._system_prompt()
    assert "delete_task" in prompt
    assert "delete_objective" in prompt


def test_system_prompt_mentions_update_task_and_objective():
    prompt = brain._system_prompt()
    assert "update_task" in prompt
    assert "update_objective" in prompt


def test_system_prompt_mentions_semana_que_viene_mapping():
    """Claude tiene que saber traducir 'la que viene' → próximo lunes."""
    prompt = brain._system_prompt().lower()
    assert "la que viene" in prompt or "próxima semana" in prompt


def test_system_prompt_size_under_budget():
    """Regresión: el prompt no debe volver a inflar sin justificación.
    Tras el recorte de junio 2026 quedó en ~7800 chars. Umbral 8200 da
    margen para añadir 1-2 reglas futuras sin alerta espuria."""
    prompt = brain._system_prompt()
    assert len(prompt) < 8200, (
        f"system prompt ha crecido a {len(prompt)} chars. "
        f"Revisa qué añadiste; cada turno cuesta tokens en cada llamada."
    )

import os
import tempfile
from types import SimpleNamespace
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
    return SimpleNamespace(
        stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text=text)],
    )


def _tool_use_then_text(tool_name: str, tool_input: dict, final_text: str):
    """Simula dos turnos: primero tool_use, luego end_turn con texto."""
    first = SimpleNamespace(
        stop_reason="tool_use",
        content=[
            SimpleNamespace(type="text", text=""),
            SimpleNamespace(
                type="tool_use", id="toolu_1", name=tool_name, input=tool_input
            ),
        ],
    )
    second = _text_response(final_text)
    return [first, second]


def test_handle_message_text_only(monkeypatch):
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _text_response("Hola, ¿en qué te ayudo?")
    monkeypatch.setattr(brain, "_client", mock_client)

    reply = brain.handle_message("hola")
    assert "Hola" in reply


def test_handle_message_with_tool_use(monkeypatch):
    responses = _tool_use_then_text(
        "add_task", {"text": "comprar pan"}, "Hecho, añadida."
    )
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = responses
    monkeypatch.setattr(brain, "_client", mock_client)

    reply = brain.handle_message("añade comprar pan")
    assert "Hecho" in reply

    import tools
    rows = tools.list_tasks()
    assert len(rows) == 1
    assert rows[0]["text"] == "comprar pan"


def test_history_persists_across_calls(monkeypatch):
    snapshots = []

    def fake_create(**kwargs):
        # Capturamos una copia superficial de messages en el momento de la llamada
        snapshots.append(list(kwargs["messages"]))
        return _text_response("respuesta")

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = fake_create
    monkeypatch.setattr(brain, "_client", mock_client)

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
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _text_response("ok")
    monkeypatch.setattr(brain, "_client", mock_client)

    brain.handle_message("hola", user_id=7)
    assert 7 in brain._history
    brain.reset_history(7)
    assert 7 not in brain._history


def test_trim_history_keeps_last_n_turns(monkeypatch):
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _text_response("ok")
    monkeypatch.setattr(brain, "_client", mock_client)
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

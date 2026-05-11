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

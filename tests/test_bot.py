from unittest.mock import patch

import bot


def test_handle_unauthorized_user_returns_none():
    reply = bot.process_incoming(text="hola", from_user_id=999)
    assert reply is None


def test_handle_authorized_user_calls_brain(monkeypatch):
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)

    with patch("bot.brain.handle_message", return_value="respuesta de prueba") as mock:
        reply = bot.process_incoming(text="hola", from_user_id=42)

    mock.assert_called_once_with("hola", user_id=42)
    assert reply == "respuesta de prueba"


def test_handle_brain_exception_returns_friendly_message(monkeypatch):
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)

    def explode(_, user_id=0):
        raise RuntimeError("boom")

    monkeypatch.setattr(bot.brain, "handle_message", explode)
    reply = bot.process_incoming(text="hola", from_user_id=42)
    assert "no puedo procesar" in reply.lower()


def test_nueva_command_resets_history(monkeypatch):
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    called = {}

    def fake_reset(user_id):
        called["user_id"] = user_id

    monkeypatch.setattr(bot.brain, "reset_history", fake_reset)

    reply = bot.process_incoming(text="/nueva", from_user_id=42)
    assert called["user_id"] == 42
    assert "reiniciada" in reply.lower()

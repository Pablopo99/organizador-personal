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


def test_process_voice_transcription_unauthorized_returns_none(monkeypatch):
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    reply = bot.process_voice_transcription("hola", from_user_id=999)
    assert reply is None


def test_process_voice_transcription_empty_returns_friendly_message(monkeypatch):
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    reply = bot.process_voice_transcription("", from_user_id=42)
    assert "no he entendido" in reply.lower()


def test_process_voice_transcription_whitespace_only_returns_friendly_message(monkeypatch):
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    reply = bot.process_voice_transcription("   \n  ", from_user_id=42)
    assert "no he entendido" in reply.lower()


def test_process_voice_transcription_composes_prefix(monkeypatch):
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)

    def fake_brain(text, user_id=0):
        return f"respuesta a: {text}"

    monkeypatch.setattr(bot.brain, "handle_message", fake_brain)

    reply = bot.process_voice_transcription("añade comprar pan", from_user_id=42)

    assert reply.startswith("📝 He entendido: «añade comprar pan»\n\n")
    assert "respuesta a: añade comprar pan" in reply


def test_process_voice_transcription_brain_exception_returns_friendly(monkeypatch):
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)

    def explode(text, user_id=0):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(bot.brain, "handle_message", explode)

    reply = bot.process_voice_transcription("hola", from_user_id=42)
    assert "no puedo procesar" in reply.lower()


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


def test_markdown_bold_converted_to_html_in_process_incoming(monkeypatch):
    """Si Claude se le escapa **bold**, se convierte a <b>bold</b> antes de salir."""
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    monkeypatch.setattr(bot.brain, "handle_message",
                        lambda text, user_id=0: "Opción **uno** y **dos**")

    reply = bot.process_incoming(text="hola", from_user_id=42)
    assert "<b>uno</b>" in reply
    assert "<b>dos</b>" in reply
    assert "**" not in reply


def test_markdown_to_html_helper_handles_multiline():
    text = "Esto es **negrita\ncon salto** de línea"
    out = bot._markdown_to_html(text)
    assert "<b>negrita\ncon salto</b>" in out


def test_markdown_to_html_helper_leaves_plain_text_alone():
    assert bot._markdown_to_html("texto sin formato") == "texto sin formato"


def test_markdown_bold_converted_in_slash_command(monkeypatch):
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    monkeypatch.setattr(bot.brain, "handle_message",
                        lambda text, user_id=0: "Sección **HOY**")

    reply = bot.process_slash_command("/hoy", from_user_id=42)
    assert "<b>HOY</b>" in reply
    assert "**" not in reply


def test_markdown_bold_converted_in_voice_transcription(monkeypatch):
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    monkeypatch.setattr(bot.brain, "handle_message",
                        lambda text, user_id=0: "Hecho, **listo**")

    reply = bot.process_voice_transcription("ok", from_user_id=42)
    assert "<b>listo</b>" in reply
    assert "**listo**" not in reply


def test_process_incoming_routes_known_slash_to_command_handler(monkeypatch):
    """process_incoming debe enrutar /hoy al handler de comandos, no al cerebro con '/hoy' literal."""
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    called = {}

    def fake_brain(text, user_id=0):
        called["brain"] = text
        return "from brain"

    monkeypatch.setattr(bot.brain, "handle_message", fake_brain)

    reply = bot.process_incoming(text="/hoy", from_user_id=42)
    assert "/hoy" not in called["brain"]
    assert reply == "from brain"

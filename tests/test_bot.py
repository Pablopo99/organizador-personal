from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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
    out = bot.markdown_to_html(text)
    assert "<b>negrita\ncon salto</b>" in out


def test_markdown_to_html_helper_leaves_plain_text_alone():
    assert bot.markdown_to_html("texto sin formato") == "texto sin formato"


def test_markdown_bold_converted_in_voice_transcription(monkeypatch):
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    monkeypatch.setattr(bot.brain, "handle_message",
                        lambda text, user_id=0: "Hecho, **listo**")

    reply = bot.process_voice_transcription("ok", from_user_id=42)
    assert "<b>listo</b>" in reply
    assert "**listo**" not in reply


def test_hoy_no_longer_in_slash_prompts():
    """/hoy ya no se procesa via Claude — tiene handler dedicado."""
    assert "/hoy" not in bot._SLASH_PROMPTS


def test_semana_prompt_uses_routine_summary():
    prompt = bot._SLASH_PROMPTS["/semana"]
    assert "RUTINAS" in prompt
    assert "routine_summary" in prompt


def test_rachas_prompt_registered():
    prompt = bot._SLASH_PROMPTS["/rachas"]
    assert "RACHAS" in prompt
    assert "routine_summary" in prompt
    assert "current_streak" in prompt
    assert "best_streak" in prompt


def test_rachas_prompt_uses_emoji_and_format():
    prompt = bot._SLASH_PROMPTS["/rachas"]
    assert "🔥" in prompt
    assert "🏆" in prompt


def test_semana_prompt_mentions_streak_threshold():
    prompt = bot._SLASH_PROMPTS["/semana"]
    assert "current_streak" in prompt
    assert "🔥" in prompt
    assert "seguidos" in prompt


@pytest.fixture
def temp_db_for_bot(monkeypatch):
    import os
    import tempfile

    import db as db_mod

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    monkeypatch.setattr(db_mod, "DB_PATH", path)
    db_mod.init_schema()
    yield path
    os.unlink(path)


def _make_callback_query(data: str, user_id: int = 42):
    query = MagicMock()
    query.data = data
    query.from_user = MagicMock()
    query.from_user.id = user_id
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    return query


def _make_update_with_callback(query):
    update = MagicMock()
    update.callback_query = query
    update.effective_user = query.from_user
    return update


def _make_context_with_bot():
    context = MagicMock()
    context.bot = MagicMock()
    context.bot.send_message = AsyncMock()
    return context


@pytest.mark.asyncio
async def test_callback_mark_event_done(temp_db_for_bot, monkeypatch):
    import tools
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    e = tools.add_event("Reunión", "2026-05-19T10:00:00", "work")

    query = _make_callback_query(f"mE:{e['id']}")
    await bot._on_callback_query(_make_update_with_callback(query), _make_context_with_bot())

    import db as db_mod
    with db_mod.connect() as conn:
        row = conn.execute("SELECT done FROM events WHERE id = ?", (e["id"],)).fetchone()
    assert row[0] == 1
    query.edit_message_text.assert_called_once()
    query.answer.assert_called()


@pytest.mark.asyncio
async def test_callback_unmark_event_done(temp_db_for_bot, monkeypatch):
    import tools
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    e = tools.add_event("Reunión", "2026-05-19T10:00:00", "work")
    tools.mark_event_done(e["id"])

    query = _make_callback_query(f"uE:{e['id']}")
    await bot._on_callback_query(_make_update_with_callback(query), _make_context_with_bot())

    import db as db_mod
    with db_mod.connect() as conn:
        row = conn.execute("SELECT done FROM events WHERE id = ?", (e["id"],)).fetchone()
    assert row[0] == 0


@pytest.mark.asyncio
async def test_callback_mark_routine_inserts_completion(temp_db_for_bot, monkeypatch):
    import tools
    import date_utils
    from datetime import date
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 19))
    e = tools.add_event("Flexiones", "2026-05-19T08:00:00", "personal", recurring_rule="DAILY")

    query = _make_callback_query(f"mR:{e['id']}")
    await bot._on_callback_query(_make_update_with_callback(query), _make_context_with_bot())

    import db as db_mod
    with db_mod.connect() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM routine_completions WHERE event_id = ? AND completion_date = ?",
            (e["id"], "2026-05-19"),
        ).fetchone()[0]
    assert count == 1


@pytest.mark.asyncio
async def test_callback_unmark_routine_deletes_completion(temp_db_for_bot, monkeypatch):
    import tools
    import date_utils
    from datetime import date
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 19))
    e = tools.add_event("Flexiones", "2026-05-19T08:00:00", "personal", recurring_rule="DAILY")
    tools.mark_event_done(e["id"])

    query = _make_callback_query(f"uR:{e['id']}")
    await bot._on_callback_query(_make_update_with_callback(query), _make_context_with_bot())

    import db as db_mod
    with db_mod.connect() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM routine_completions WHERE event_id = ?",
            (e["id"],),
        ).fetchone()[0]
    assert count == 0


@pytest.mark.asyncio
async def test_callback_mark_task(temp_db_for_bot, monkeypatch):
    import tools
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    t = tools.add_task("comprar pan")

    query = _make_callback_query(f"mT:{t['id']}")
    await bot._on_callback_query(_make_update_with_callback(query), _make_context_with_bot())

    import db as db_mod
    with db_mod.connect() as conn:
        row = conn.execute("SELECT done FROM tasks WHERE id = ?", (t["id"],)).fetchone()
    assert row[0] == 1


@pytest.mark.asyncio
async def test_callback_unmark_task(temp_db_for_bot, monkeypatch):
    import tools
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    t = tools.add_task("comprar pan")
    tools.complete_task(t["id"])

    query = _make_callback_query(f"uT:{t['id']}")
    await bot._on_callback_query(_make_update_with_callback(query), _make_context_with_bot())

    import db as db_mod
    with db_mod.connect() as conn:
        row = conn.execute("SELECT done, done_at FROM tasks WHERE id = ?", (t["id"],)).fetchone()
    assert row[0] == 0
    assert row[1] is None


@pytest.mark.asyncio
async def test_callback_unauthorized_user_no_mutation(temp_db_for_bot, monkeypatch):
    import tools
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    e = tools.add_event("Reunión", "2026-05-19T10:00:00", "work")

    query = _make_callback_query(f"mE:{e['id']}", user_id=999)
    await bot._on_callback_query(_make_update_with_callback(query), _make_context_with_bot())

    import db as db_mod
    with db_mod.connect() as conn:
        row = conn.execute("SELECT done FROM events WHERE id = ?", (e["id"],)).fetchone()
    assert row[0] == 0
    query.edit_message_text.assert_not_called()


@pytest.mark.asyncio
async def test_callback_malformed_data_does_not_crash(temp_db_for_bot, monkeypatch):
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)

    query = _make_callback_query("garbage")
    await bot._on_callback_query(_make_update_with_callback(query), _make_context_with_bot())

    query.answer.assert_called()
    query.edit_message_text.assert_not_called()


@pytest.mark.asyncio
async def test_callback_edit_failure_sends_new_message(temp_db_for_bot, monkeypatch):
    from telegram.error import BadRequest
    import tools
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    e = tools.add_event("Reunión", "2026-05-19T10:00:00", "work")

    query = _make_callback_query(f"mE:{e['id']}")
    query.edit_message_text.side_effect = BadRequest("Message to edit not found")

    context = _make_context_with_bot()
    await bot._on_callback_query(_make_update_with_callback(query), context)

    context.bot.send_message.assert_called_once()

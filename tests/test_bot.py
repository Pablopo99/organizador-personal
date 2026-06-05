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


def test_process_voice_transcription_returns_brain_reply_without_prefix(monkeypatch):
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)

    def fake_brain(text, user_id=0):
        return f"respuesta a: {text}"

    monkeypatch.setattr(bot.brain, "handle_message", fake_brain)

    reply = bot.process_voice_transcription("añade comprar pan", from_user_id=42)

    assert reply == "respuesta a: añade comprar pan"
    assert "He entendido" not in reply


def test_process_voice_transcription_brain_exception_returns_friendly(monkeypatch):
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)

    def explode(text, user_id=0):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(bot.brain, "handle_message", explode)

    reply = bot.process_voice_transcription("hola", from_user_id=42)
    assert "no puedo procesar" in reply.lower()


def test_slash_rachas_ya_no_pasa_por_claude(monkeypatch):
    """/rachas ahora es determinista (handler directo), ya no va al brain."""
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    assert bot.process_slash_command("/rachas", from_user_id=42) is None


def test_slash_objetivos_ya_no_pasa_por_claude(monkeypatch):
    """/objetivos ahora es determinista (handler directo), ya no va al brain."""
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    assert bot.process_slash_command("/objetivos", from_user_id=42) is None


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
    import date_utils
    from datetime import date
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 19))
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


def test_pendientes_no_longer_in_slash_prompts():
    assert "/pendientes" not in bot._SLASH_PROMPTS


def test_semana_no_longer_in_slash_prompts():
    assert "/semana" not in bot._SLASH_PROMPTS


@pytest.mark.asyncio
async def test_callback_mark_objective_in_week_view(temp_db_for_bot, monkeypatch):
    import tools
    import date_utils
    from datetime import date
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 19))
    o = tools.add_objective("Terminar pres", "2026-05-18")

    query = _make_callback_query(f"mO:{o['id']}:W")
    await bot._on_callback_query(_make_update_with_callback(query), _make_context_with_bot())

    import db as db_mod
    with db_mod.connect() as conn:
        row = conn.execute(
            "SELECT done FROM objectives WHERE id = ?", (o["id"],)
        ).fetchone()
    assert row[0] == 1
    query.edit_message_text.assert_called_once()


@pytest.mark.asyncio
async def test_callback_unmark_objective_in_week_view(temp_db_for_bot, monkeypatch):
    import tools
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    o = tools.add_objective("Subir vídeos", "2026-05-18")
    tools.mark_objective_done(o["id"])

    query = _make_callback_query(f"uO:{o['id']}:W")
    await bot._on_callback_query(_make_update_with_callback(query), _make_context_with_bot())

    import db as db_mod
    with db_mod.connect() as conn:
        row = conn.execute(
            "SELECT done FROM objectives WHERE id = ?", (o["id"],)
        ).fetchone()
    assert row[0] == 0


@pytest.mark.asyncio
async def test_callback_mark_task_in_pending_view(temp_db_for_bot, monkeypatch):
    import tools
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    t = tools.add_task("comprar pan")

    query = _make_callback_query(f"mT:{t['id']}:P")
    await bot._on_callback_query(_make_update_with_callback(query), _make_context_with_bot())

    import db as db_mod
    with db_mod.connect() as conn:
        row = conn.execute("SELECT done FROM tasks WHERE id = ?", (t["id"],)).fetchone()
    assert row[0] == 1
    edit_kwargs = query.edit_message_text.call_args.kwargs
    text = edit_kwargs.get("text") or query.edit_message_text.call_args.args[0]
    assert "No tienes tareas pendientes" in text


@pytest.mark.asyncio
async def test_callback_old_format_no_view_suffix_defaults_to_hoy(temp_db_for_bot, monkeypatch):
    """callback_data sin sufijo de vista (mE:42) se trata como H."""
    import tools
    import date_utils
    from datetime import date
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 19))
    e = tools.add_event("Reunión", "2026-05-19T10:00:00", "work")

    query = _make_callback_query(f"mE:{e['id']}")
    await bot._on_callback_query(_make_update_with_callback(query), _make_context_with_bot())

    import db as db_mod
    with db_mod.connect() as conn:
        row = conn.execute("SELECT done FROM events WHERE id = ?", (e["id"],)).fetchone()
    assert row[0] == 1
    query.edit_message_text.assert_called_once()


def test_callback_action_gc_calls_push_event_to_calendar(monkeypatch):
    import bot
    called = {}
    def fake_push(event_id):
        called["event_id"] = event_id
        return {"event_id": event_id, "synced": True, "gcal_event_id": "g1"}
    monkeypatch.setattr(bot.tools, "push_event_to_calendar", fake_push)
    handler = bot._CALLBACK_ACTIONS["gc"]
    result = handler(99)
    assert called["event_id"] == 99
    assert result["synced"] is True


@pytest.mark.asyncio
async def test_on_metricas_sends_text(temp_db_for_bot, monkeypatch):
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)

    reply_mock = AsyncMock()
    update = MagicMock()
    update.message.reply_text = reply_mock
    update.effective_user.id = 42

    await bot._on_metricas(update, MagicMock())

    reply_mock.assert_called_once()
    args, kwargs = reply_mock.call_args
    text = args[0] if args else kwargs.get("text")
    assert "métricas" in text.lower() or "datos" in text.lower()


@pytest.mark.asyncio
async def test_on_metricas_unauthorized_user_ignored(temp_db_for_bot, monkeypatch):
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    reply_mock = AsyncMock()
    update = MagicMock()
    update.message.reply_text = reply_mock
    update.effective_user.id = 999

    await bot._on_metricas(update, MagicMock())

    reply_mock.assert_not_called()


@pytest.mark.asyncio
async def test_callback_rT_recreates_task(monkeypatch, temp_db_for_bot):
    import db
    import tools
    import date_utils
    from datetime import date

    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 30))

    orig = tools.add_task("Llamar dentista", due_date="2026-05-20")

    query = MagicMock()
    query.from_user.id = 42
    query.data = f"rT:{orig['id']}"
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    query.message = MagicMock()
    query.message.text_html = "Tarea perdida: Llamar dentista"
    update = MagicMock()
    update.callback_query = query

    await bot._on_callback_query(update, MagicMock())

    with db.connect() as conn:
        rows = conn.execute("SELECT outcome FROM tasks ORDER BY id").fetchall()
    assert rows[0]["outcome"] == "missed"
    assert rows[1]["outcome"] is None
    query.edit_message_text.assert_called_once()


@pytest.mark.asyncio
async def test_callback_dT_discards_task(monkeypatch, temp_db_for_bot):
    import db
    import tools

    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)

    orig = tools.add_task("X", due_date="2026-05-20")

    query = MagicMock()
    query.from_user.id = 42
    query.data = f"dT:{orig['id']}"
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    query.message = MagicMock()
    query.message.text_html = "Tarea perdida: X"
    update = MagicMock()
    update.callback_query = query

    await bot._on_callback_query(update, MagicMock())

    with db.connect() as conn:
        row = conn.execute(
            "SELECT outcome FROM tasks WHERE id = ?", (orig["id"],)
        ).fetchone()
    assert row["outcome"] == "missed"
    query.edit_message_text.assert_called_once()


@pytest.mark.asyncio
async def test_on_nivel_sends_text(temp_db_for_bot, monkeypatch):
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    reply_mock = AsyncMock()
    update = MagicMock()
    update.message.reply_text = reply_mock
    update.effective_user.id = 42

    await bot._on_nivel(update, MagicMock())

    reply_mock.assert_called_once()
    args, kwargs = reply_mock.call_args
    text = args[0] if args else kwargs.get("text")
    assert "Nivel" in text


@pytest.mark.asyncio
async def test_on_nivel_unauthorized_ignored(monkeypatch):
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    reply_mock = AsyncMock()
    update = MagicMock()
    update.message.reply_text = reply_mock
    update.effective_user.id = 999

    await bot._on_nivel(update, MagicMock())

    reply_mock.assert_not_called()


@pytest.mark.asyncio
async def test_callback_marks_task_and_sends_level_up(monkeypatch, temp_db_for_bot):
    """Cuando una acción sube de nivel, se manda mensaje aparte."""
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    from datetime import date
    import date_utils
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 19))

    import db
    import tools
    # Preparar: 20 XP previos
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO xp_log "
            "(item_type, item_id, outcome, xp_amount, awarded_at) "
            "VALUES ('task', 999, 'on_time', 20, '2026-05-19T10:00:00')"
        )
    # Crear tarea de hoy
    t = tools.add_task("Hoy", due_date="2026-05-19")

    query = MagicMock()
    query.from_user.id = 42
    query.data = f"mT:{t['id']}:P"
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    query.message = MagicMock()
    update = MagicMock()
    update.callback_query = query
    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock()

    await bot._on_callback_query(update, ctx)

    # XP total ahora 30 = nivel 1. Antes 20 = nivel 0. Debió mandar level-up.
    ctx.bot.send_message.assert_called()
    sent_text = ctx.bot.send_message.call_args.kwargs["text"]
    assert "Nivel 1" in sent_text


@pytest.mark.asyncio
async def test_brain_level_up_triggers_message(monkeypatch):
    """Si brain registra subida, _on_message la envía aparte."""
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    import brain
    brain.record_level_up(42, 0, 1)

    update = MagicMock()
    update.message.text = "hola"
    update.message.reply_text = AsyncMock()
    update.effective_user.id = 42

    ctx = MagicMock()
    ctx.bot.send_message = AsyncMock()

    # Hacer que el path del mensaje no llame a Claude real
    monkeypatch.setattr(bot.brain, "handle_message", lambda text, user_id=0: "ok")

    await bot._on_message(update, ctx)

    ctx.bot.send_message.assert_called_once()
    assert "Nivel 1" in ctx.bot.send_message.call_args.kwargs["text"]


@pytest.mark.asyncio
async def test_on_message_sends_immediate_reminders(monkeypatch):
    """Si brain registró inmediatos, _on_message los manda aparte tras la
    respuesta normal."""
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    import brain
    brain.record_immediate_reminder(
        42, event_id=1, offset_minutes=30, title="Dentista"
    )

    update = MagicMock()
    update.message.text = "hola"
    update.message.reply_text = AsyncMock()
    update.effective_user.id = 42

    ctx = MagicMock()
    ctx.bot.send_message = AsyncMock()

    monkeypatch.setattr(
        bot, "process_incoming", lambda text, from_user_id: "ok"
    )

    await bot._on_message(update, ctx)

    sends = [c.kwargs["text"] for c in ctx.bot.send_message.call_args_list]
    matches = [t for t in sends if "Dentista" in t and "30 min" in t]
    assert len(matches) == 1


@pytest.mark.asyncio
async def test_on_start_sends_welcome(monkeypatch):
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    reply_mock = AsyncMock()
    update = MagicMock()
    update.message.reply_text = reply_mock
    update.effective_user.id = 42

    await bot._on_start(update, MagicMock())

    reply_mock.assert_called_once()
    text = reply_mock.call_args.args[0] if reply_mock.call_args.args else reply_mock.call_args.kwargs.get("text")
    assert "secretaria" in text.lower()
    assert "/hoy" in text


@pytest.mark.asyncio
async def test_on_start_unauthorized_ignored(monkeypatch):
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    reply_mock = AsyncMock()
    update = MagicMock()
    update.message.reply_text = reply_mock
    update.effective_user.id = 999

    await bot._on_start(update, MagicMock())

    reply_mock.assert_not_called()

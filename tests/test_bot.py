from unittest.mock import AsyncMock, MagicMock, patch

import anthropic
import httpx
import pytest

import bot


def _rate_limit_error() -> anthropic.RateLimitError:
    """Construye un RateLimitError tal como lo lanza el SDK tras agotar reintentos."""
    response = httpx.Response(429, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))
    return anthropic.RateLimitError(
        message="rate_limit_error",
        response=response,
        body={"error": {"type": "rate_limit_error"}},
    )


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


def test_handle_rate_limit_error_returns_specific_message(monkeypatch):
    """Cuando Anthropic devuelve 429 (rate limit), el bot debe explicar que es
    un límite temporal y pedir reintento en ~1 minuto. NO el mensaje genérico
    'no puedo procesar' que es confuso."""
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)

    def rate_limited(_, user_id=0):
        raise _rate_limit_error()

    monkeypatch.setattr(bot.brain, "handle_message", rate_limited)
    reply = bot.process_incoming(text="hola", from_user_id=42)
    low = reply.lower()
    assert "límite" in low or "saturado" in low or "demasiados" in low, (
        f"esperaba mención de límite/saturación, got: {reply}"
    )
    assert "minuto" in low or "segundos" in low or "espera" in low, (
        f"esperaba indicación de cuánto esperar, got: {reply}"
    )


def test_voice_rate_limit_error_returns_specific_message(monkeypatch):
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)

    def rate_limited(_, user_id=0):
        raise _rate_limit_error()

    monkeypatch.setattr(bot.brain, "handle_message", rate_limited)
    reply = bot.process_voice_transcription("hola", from_user_id=42)
    low = reply.lower()
    assert "límite" in low or "saturado" in low or "demasiados" in low
    assert "minuto" in low or "segundos" in low or "espera" in low


def test_slash_rate_limit_error_returns_specific_message(monkeypatch):
    """Aunque hoy _SLASH_PROMPTS está vacío, dejamos el camino blindado por si
    se vuelve a enchufar algún slash al brain."""
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    monkeypatch.setattr(bot, "_SLASH_PROMPTS", {"/foo": "qué hay de foo"})

    def rate_limited(_, user_id=0):
        raise _rate_limit_error()

    monkeypatch.setattr(bot.brain, "handle_message", rate_limited)
    reply = bot.process_slash_command("/foo", from_user_id=42)
    low = reply.lower()
    assert "límite" in low or "saturado" in low or "demasiados" in low
    assert "minuto" in low or "segundos" in low or "espera" in low


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


# ---- Deshacer borrado en /duplicados ----

def test_undo_store_push_and_pop():
    bot._undo_store.clear()
    tok = bot._push_undo({"kind": "task", "data": {"text": "x", "due_date": None}})
    assert isinstance(tok, int)
    snap = bot._pop_undo(tok)
    assert snap["data"]["text"] == "x"
    # tras pop, queda vacío
    assert bot._pop_undo(tok) is None


def test_undo_store_tokens_are_unique():
    bot._undo_store.clear()
    t1 = bot._push_undo({"kind": "task", "data": {"text": "a", "due_date": None}})
    t2 = bot._push_undo({"kind": "task", "data": {"text": "b", "due_date": None}})
    assert t1 != t2


@pytest.mark.asyncio
async def test_callback_delete_in_duplicados_sends_undo_button(temp_db_for_bot, monkeypatch):
    import tools
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    bot._undo_store.clear()
    # Dos tareas duplicadas para que /duplicados las agrupe
    a = tools.add_task("Reservar cita peluquería")
    tools.add_task("Reservar cita peluquería")

    query = _make_callback_query(f"xT:{a['id']}:D")
    context = _make_context_with_bot()
    await bot._on_callback_query(_make_update_with_callback(query), context)

    # Solo se borró una
    assert len(tools.list_tasks()) == 1
    # Se mandó un mensaje aparte con botón Deshacer (callback zD:*)
    context.bot.send_message.assert_called_once()
    kwargs = context.bot.send_message.call_args.kwargs
    assert "Borrado" in kwargs["text"]
    markup = kwargs["reply_markup"]
    btn = markup.inline_keyboard[0][0]
    assert btn.callback_data.startswith("zD:")
    assert "Deshacer" in btn.text


@pytest.mark.asyncio
async def test_callback_undo_restores_deleted_task(temp_db_for_bot, monkeypatch):
    import tools
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    bot._undo_store.clear()
    a = tools.add_task("Reservar cita peluquería", due_date="2026-06-20")
    tools.add_task("Reservar cita peluquería")

    # Borra una desde /duplicados
    q1 = _make_callback_query(f"xT:{a['id']}:D")
    ctx = _make_context_with_bot()
    await bot._on_callback_query(_make_update_with_callback(q1), ctx)
    assert len(tools.list_tasks()) == 1

    # Extrae el token del botón Deshacer y púlsalo
    token_data = ctx.bot.send_message.call_args.kwargs["reply_markup"].inline_keyboard[0][0].callback_data
    q2 = _make_callback_query(token_data)
    await bot._on_callback_query(_make_update_with_callback(q2), _make_context_with_bot())

    # La tarea volvió (con su due_date)
    rows = tools.list_tasks()
    assert len(rows) == 2
    restored = [r for r in rows if r["due_date"] == "2026-06-20"]
    assert len(restored) == 1


@pytest.mark.asyncio
async def test_callback_undo_expired_token_is_graceful(temp_db_for_bot, monkeypatch):
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    bot._undo_store.clear()
    q = _make_callback_query("zD:99999")
    await bot._on_callback_query(_make_update_with_callback(q), _make_context_with_bot())
    # No crashea; responde algo al usuario
    q.answer.assert_called()


# ---- Botón ✏️ editar texto: estado e intercepción ----

def test_pending_edit_store_set_peek_pop():
    bot._pending_edit.clear()
    bot._set_pending_edit(42, "task", 7)
    assert bot._peek_pending_edit(42) == {"kind": "task", "id": 7}
    # peek no elimina
    assert bot._peek_pending_edit(42) == {"kind": "task", "id": 7}
    popped = bot._pop_pending_edit(42)
    assert popped == {"kind": "task", "id": 7}
    assert bot._peek_pending_edit(42) is None


def test_pop_pending_edit_unknown_user_returns_none():
    bot._pending_edit.clear()
    assert bot._pop_pending_edit(99999) is None


def test_process_incoming_applies_text_edit_to_task(temp_db_for_bot, monkeypatch):
    import tools
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    bot._pending_edit.clear()
    t = tools.add_task("Comprar pan", due_date="2026-06-25")
    bot._set_pending_edit(42, "task", t["id"])

    reply = bot.process_incoming(text="Comprar pan integral", from_user_id=42)

    assert "integral" in reply.lower()
    rows = tools.list_tasks()
    row = next(r for r in rows if r["id"] == t["id"])
    assert row["text"] == "Comprar pan integral"
    assert row["due_date"] == "2026-06-25"  # fecha intacta
    # el modo se consumió
    assert bot._peek_pending_edit(42) is None


def test_process_incoming_applies_text_edit_to_objective(temp_db_for_bot, monkeypatch):
    import tools
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    bot._pending_edit.clear()
    o = tools.add_objective("Leer 2 libros", "2026-06-22")
    bot._set_pending_edit(42, "objective", o["id"])

    reply = bot.process_incoming(text="Leer 3 libros", from_user_id=42)

    assert "3 libros" in reply.lower()
    rows = tools.query_objectives(None)
    row = next(r for r in rows if r["id"] == o["id"])
    assert row["text"] == "Leer 3 libros"
    assert bot._peek_pending_edit(42) is None


def test_process_incoming_edit_cancelar_aborts(temp_db_for_bot, monkeypatch):
    import tools
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    bot._pending_edit.clear()
    t = tools.add_task("Comprar pan")
    bot._set_pending_edit(42, "task", t["id"])

    reply = bot.process_incoming(text="/cancelar", from_user_id=42)

    assert "cancel" in reply.lower()
    assert tools.list_tasks()[0]["text"] == "Comprar pan"  # intacto
    assert bot._peek_pending_edit(42) is None


def test_process_incoming_edit_slash_command_aborts_and_falls_through(temp_db_for_bot, monkeypatch):
    """Un comando (p.ej. /nueva) en modo edición cancela el modo y se procesa
    como comando, no como texto nuevo de la tarea."""
    import tools
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    bot._pending_edit.clear()
    t = tools.add_task("Comprar pan")
    bot._set_pending_edit(42, "task", t["id"])

    reset_called = {}
    monkeypatch.setattr(bot.brain, "reset_history", lambda uid: reset_called.setdefault("uid", uid))

    reply = bot.process_incoming(text="/nueva", from_user_id=42)

    # /nueva se ejecutó (no se usó como texto de la tarea)
    assert reset_called.get("uid") == 42
    assert tools.list_tasks()[0]["text"] == "Comprar pan"  # intacto
    assert bot._peek_pending_edit(42) is None


def test_process_incoming_edit_empty_text_keeps_mode(temp_db_for_bot, monkeypatch):
    import tools
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    bot._pending_edit.clear()
    t = tools.add_task("Comprar pan")
    bot._set_pending_edit(42, "task", t["id"])

    reply = bot.process_incoming(text="   ", from_user_id=42)

    # sigue en modo edición
    assert bot._peek_pending_edit(42) == {"kind": "task", "id": t["id"]}
    assert tools.list_tasks()[0]["text"] == "Comprar pan"


def test_process_incoming_edit_deleted_item_graceful(temp_db_for_bot, monkeypatch):
    import tools
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    bot._pending_edit.clear()
    t = tools.add_task("Comprar pan")
    bot._set_pending_edit(42, "task", t["id"])
    tools.delete_task(t["id"])  # borrada mientras editabas

    reply = bot.process_incoming(text="Comprar pan integral", from_user_id=42)

    assert "ya no existe" in reply.lower()
    assert bot._peek_pending_edit(42) is None


def test_process_incoming_no_pending_edit_goes_to_brain(temp_db_for_bot, monkeypatch):
    """Regresión: sin modo edición, el texto va a brain como siempre."""
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    bot._pending_edit.clear()
    called = {}
    monkeypatch.setattr(bot.brain, "handle_message", lambda text, user_id=0: called.setdefault("text", text) or "ok")

    reply = bot.process_incoming(text="hola qué tal", from_user_id=42)

    assert called.get("text") == "hola qué tal"


# ---- Botón ✏️ editar texto: callbacks ----

@pytest.mark.asyncio
async def test_callback_eT_enters_edit_mode(temp_db_for_bot, monkeypatch):
    import tools
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    bot._pending_edit.clear()
    t = tools.add_task("Comprar pan")

    query = _make_callback_query(f"eT:{t['id']}:P")
    ctx = _make_context_with_bot()
    await bot._on_callback_query(_make_update_with_callback(query), ctx)

    # Entró en modo edición para esa tarea
    assert bot._peek_pending_edit(42) == {"kind": "task", "id": t["id"]}
    # Mandó un mensaje pidiendo el nuevo texto
    ctx.bot.send_message.assert_called_once()
    sent = ctx.bot.send_message.call_args.kwargs["text"]
    assert "nuevo texto" in sent.lower()
    assert "Comprar pan" in sent


@pytest.mark.asyncio
async def test_callback_eO_enters_edit_mode(temp_db_for_bot, monkeypatch):
    import tools
    import date_utils
    from datetime import date
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 19))
    bot._pending_edit.clear()
    o = tools.add_objective("Leer 2 libros", "2026-05-18")

    query = _make_callback_query(f"eO:{o['id']}:O")
    ctx = _make_context_with_bot()
    await bot._on_callback_query(_make_update_with_callback(query), ctx)

    assert bot._peek_pending_edit(42) == {"kind": "objective", "id": o["id"]}
    ctx.bot.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_callback_eT_missing_item_no_edit_mode(temp_db_for_bot, monkeypatch):
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    bot._pending_edit.clear()

    query = _make_callback_query("eT:99999:P")
    ctx = _make_context_with_bot()
    await bot._on_callback_query(_make_update_with_callback(query), ctx)

    # No entra en modo edición si el item no existe
    assert bot._peek_pending_edit(42) is None
    query.answer.assert_called()


@pytest.mark.asyncio
async def test_cancel_edit_on_command_clears_state(monkeypatch):
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    bot._pending_edit.clear()
    bot._set_pending_edit(42, "task", 7)

    update = MagicMock()
    update.effective_user = MagicMock()
    update.effective_user.id = 42
    await bot._cancel_edit_on_command(update, MagicMock())

    assert bot._peek_pending_edit(42) is None


def test_process_incoming_edit_escapes_html_in_confirmation(temp_db_for_bot, monkeypatch):
    """Si el nuevo texto tiene <, > o &, la confirmación debe escaparlos
    (el reply se manda con parse_mode HTML y rompería si no)."""
    import tools
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    bot._pending_edit.clear()
    t = tools.add_task("Cosa")
    bot._set_pending_edit(42, "task", t["id"])

    reply = bot.process_incoming(text="Comprar pan & <leche>", from_user_id=42)

    assert "&amp;" in reply
    assert "&lt;leche&gt;" in reply
    # el texto crudo SÍ se guarda sin escapar en la BD
    assert tools.list_tasks()[0]["text"] == "Comprar pan & <leche>"


# ---- Fixes de revisión: /cancelar, voz en edición, cap del undo store ----

@pytest.mark.asyncio
async def test_cancel_edit_on_command_ignores_cancelar(monkeypatch):
    """El handler grupo -1 NO debe limpiar para /cancelar: deja que
    process_incoming dé el mensaje 'Edición cancelada'."""
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    bot._pending_edit.clear()
    bot._set_pending_edit(42, "task", 7)

    update = MagicMock()
    update.effective_user = MagicMock()
    update.effective_user.id = 42
    update.message = MagicMock()
    update.message.text = "/cancelar"
    await bot._cancel_edit_on_command(update, MagicMock())

    # Sigue pendiente (lo cancelará process_incoming, no el grupo -1)
    assert bot._peek_pending_edit(42) == {"kind": "task", "id": 7}


@pytest.mark.asyncio
async def test_cancel_edit_on_command_clears_for_registered_command(monkeypatch):
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    bot._pending_edit.clear()
    bot._set_pending_edit(42, "task", 7)

    update = MagicMock()
    update.effective_user = MagicMock()
    update.effective_user.id = 42
    update.message = MagicMock()
    update.message.text = "/hoy"
    await bot._cancel_edit_on_command(update, MagicMock())

    assert bot._peek_pending_edit(42) is None


def test_voice_transcription_applies_pending_edit(temp_db_for_bot, monkeypatch):
    """En modo edición, un audio aplica la transcripción como nuevo texto
    (no queda el estado colgado)."""
    import tools
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    bot._pending_edit.clear()
    t = tools.add_task("Comprar pan")
    bot._set_pending_edit(42, "task", t["id"])

    reply = bot.process_voice_transcription("Comprar pan integral", from_user_id=42)

    assert "integral" in reply.lower()
    assert tools.list_tasks()[0]["text"] == "Comprar pan integral"
    assert bot._peek_pending_edit(42) is None


def test_undo_store_is_capped(monkeypatch):
    """El store de deshacer no crece sin límite."""
    bot._undo_store.clear()
    for i in range(bot._UNDO_MAX + 20):
        bot._push_undo({"kind": "task", "data": {"text": f"t{i}", "due_date": None}})
    assert len(bot._undo_store) <= bot._UNDO_MAX


# ---- Consultas en lenguaje natural → vista determinista (detección) ----

def test_match_summary_view_hoy():
    for t in ["qué tengo hoy", "que tengo hoy", "qué hay hoy",
              "qué tengo para hoy", "mi día", "agenda de hoy", "hoy",
              "¿qué tengo hoy?", "muéstrame hoy"]:
        assert bot.match_summary_view(t) == "hoy", t


def test_match_summary_view_manana():
    for t in ["qué tengo mañana", "mañana", "qué hay mañana", "agenda de mañana"]:
        assert bot.match_summary_view(t) == "manana", t


def test_match_summary_view_semana():
    for t in ["qué tengo esta semana", "mi semana", "qué hay esta semana",
              "esta semana"]:
        assert bot.match_summary_view(t) == "semana", t


def test_match_summary_view_pendientes():
    for t in ["qué tengo pendiente", "mis tareas", "pendientes",
              "qué tareas tengo", "mis pendientes"]:
        assert bot.match_summary_view(t) == "pendientes", t


def test_match_summary_view_objetivos():
    for t in ["mis objetivos", "objetivos de la semana", "qué objetivos tengo",
              "mis metas", "objetivos"]:
        assert bot.match_summary_view(t) == "objetivos", t


def test_match_summary_view_ignores_create_actions():
    for t in ["apunta reunión hoy a las 5", "mañana tengo dentista",
              "recuérdame comprar pan hoy", "marca leer como hecho",
              "tengo que hacer los objetivos", "añade tarea para hoy",
              "pon una cita mañana", "borra la tarea de hoy"]:
        assert bot.match_summary_view(t) is None, t


def test_match_summary_view_unrelated():
    for t in ["hola", "gracias", "cuánto es 2+2", "ponme una alarma",
              "cuéntame un chiste", ""]:
        assert bot.match_summary_view(t) is None, t


# ---- Consultas en lenguaje natural → vista determinista (integración) ----

@pytest.mark.asyncio
async def test_on_message_natural_hoy_renders_view_with_keyboard(temp_db_for_bot, monkeypatch):
    """"qué tengo hoy" en texto libre debe servir la vista de /hoy CON botones,
    sin pasar por la IA."""
    import tools, date_utils
    from datetime import date
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 6, 24))
    tools.add_task("Comprar pan", due_date="2026-06-24")

    brain_called = {}
    def fake_brain(text, user_id=0):
        brain_called["hit"] = True
        return "x"
    monkeypatch.setattr(bot.brain, "handle_message", fake_brain)

    reply_mock = AsyncMock()
    update = MagicMock()
    update.message.text = "qué tengo hoy"
    update.message.reply_text = reply_mock
    update.effective_user.id = 42

    await bot._on_message(update, _make_context_with_bot())

    # No pasó por la IA
    assert "hit" not in brain_called
    # Respondió con teclado (botones de la vista)
    reply_mock.assert_called_once()
    assert reply_mock.call_args.kwargs.get("reply_markup") is not None


@pytest.mark.asyncio
async def test_on_message_normal_text_still_goes_to_brain(temp_db_for_bot, monkeypatch):
    """Regresión: un mensaje normal sigue yendo a la IA."""
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    brain_called = {}
    def fake_brain(text, user_id=0):
        brain_called["text"] = text
        return "respuesta IA"
    monkeypatch.setattr(bot.brain, "handle_message", fake_brain)

    reply_mock = AsyncMock()
    update = MagicMock()
    update.message.text = "cuéntame un chiste"
    update.message.reply_text = reply_mock
    update.effective_user.id = 42

    await bot._on_message(update, _make_context_with_bot())

    assert brain_called.get("text") == "cuéntame un chiste"


@pytest.mark.asyncio
async def test_on_message_natural_query_unauthorized_ignored(temp_db_for_bot, monkeypatch):
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", 42)
    reply_mock = AsyncMock()
    update = MagicMock()
    update.message.text = "qué tengo hoy"
    update.message.reply_text = reply_mock
    update.effective_user.id = 999  # no autorizado

    await bot._on_message(update, _make_context_with_bot())
    reply_mock.assert_not_called()

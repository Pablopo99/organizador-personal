import os
import tempfile
from datetime import date

import pytest

import db
import tools
import views


@pytest.fixture(autouse=True)
def temp_db(monkeypatch):
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init_schema()
    yield path
    os.unlink(path)


def _render(today=None):
    today = today or date(2026, 5, 19)
    with db.connect() as conn:
        return views.render_today_view(today, conn)


def test_render_empty_db_returns_day_libre():
    text, keyboard = _render()
    assert "Día libre" in text
    assert keyboard is None


def test_render_one_event_pending_creates_one_button():
    tools.add_event("Reunión", "2026-05-19T10:00:00", "work")

    text, keyboard = _render()

    assert "📅" in text
    assert "HOY" in text
    assert "10:00 — Reunión" in text
    assert keyboard is not None
    assert len(keyboard.inline_keyboard) == 1
    btn = keyboard.inline_keyboard[0][0]
    assert btn.text.startswith("🔲")
    assert "Reunión" in btn.text
    assert btn.callback_data.startswith("mE:")


def test_render_event_done_appears_in_completado_with_check_button():
    e = tools.add_event("Reunión", "2026-05-19T10:00:00", "work")
    tools.mark_event_done(e["id"])

    text, keyboard = _render()

    assert "COMPLETADO HOY" in text
    assert "<s>10:00 — Reunión</s>" in text
    assert len(keyboard.inline_keyboard) == 1
    btn = keyboard.inline_keyboard[0][0]
    assert btn.text.startswith("✅")
    assert btn.callback_data == f"uE:{e['id']}"


def test_render_routine_pending_in_rutinas_section(monkeypatch):
    import date_utils
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 19))
    e = tools.add_event("Flexiones", "2026-05-19T08:00:00", "personal", recurring_rule="DAILY")

    text, keyboard = _render()

    assert "🔁" in text
    assert "RUTINAS" in text
    assert "Flexiones" in text
    btn = keyboard.inline_keyboard[0][0]
    assert btn.callback_data == f"mR:{e['id']}"


def test_render_routine_done_today_in_completado_section(monkeypatch):
    import date_utils
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 19))
    e = tools.add_event("Flexiones", "2026-05-19T08:00:00", "personal", recurring_rule="DAILY")
    tools.mark_event_done(e["id"])

    text, keyboard = _render()

    assert "COMPLETADO HOY" in text
    assert "<s>Flexiones" in text
    btn = keyboard.inline_keyboard[0][0]
    assert btn.text.startswith("✅")
    assert btn.callback_data == f"uR:{e['id']}"


def test_render_routine_with_streak_shows_fire(monkeypatch):
    import date_utils
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 19))
    e = tools.add_event("Flexiones", "2026-05-17T08:00:00", "personal", recurring_rule="DAILY")
    with db.connect() as conn:
        for d in ("2026-05-17", "2026-05-18"):
            conn.execute(
                "INSERT INTO routine_completions (event_id, completion_date, created_at) VALUES (?, ?, ?)",
                (e["id"], d, "2026-05-19T08:00:00"),
            )

    text, _ = _render()

    assert "🔥 2" in text


def test_render_task_pending_with_button():
    t = tools.add_task("comprar pan")

    text, keyboard = _render()

    assert "PENDIENTES" in text
    assert "comprar pan" in text
    btn = keyboard.inline_keyboard[0][0]
    assert btn.callback_data == f"mT:{t['id']}"


def test_render_task_done_today_in_completado(monkeypatch):
    import date_utils
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 19))
    monkeypatch.setattr(date_utils, "now_iso", lambda: "2026-05-19T10:00:00")
    t = tools.add_task("comprar pan")
    tools.complete_task(t["id"])

    text, keyboard = _render()

    assert "COMPLETADO HOY" in text
    assert "<s>comprar pan</s>" in text
    btn = keyboard.inline_keyboard[0][0]
    assert btn.callback_data == f"uT:{t['id']}"


def test_render_task_done_yesterday_not_shown(monkeypatch):
    import date_utils
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 19))
    t = tools.add_task("comprar pan")
    with db.connect() as conn:
        conn.execute(
            "UPDATE tasks SET done=1, done_at=? WHERE id=?",
            ("2026-05-18T10:00:00", t["id"]),
        )

    text, keyboard = _render()

    assert "COMPLETADO HOY" not in text
    assert "PENDIENTES" not in text
    if keyboard is not None:
        for row in keyboard.inline_keyboard:
            for btn in row:
                assert "comprar pan" not in btn.text


def test_render_pending_view_empty_returns_celebration():
    with db.connect() as conn:
        text, keyboard = views.render_pending_view(conn)

    assert "No tienes tareas pendientes" in text
    assert "🎉" in text
    assert keyboard is None


def test_render_pending_view_lists_tasks_with_buttons():
    t1 = tools.add_task("Solucionar Spotify")
    t2 = tools.add_task("Comprar pan")

    with db.connect() as conn:
        text, keyboard = views.render_pending_view(conn)

    assert "PENDIENTES" in text
    assert "Solucionar Spotify" in text
    assert "Comprar pan" in text
    assert keyboard is not None
    assert len(keyboard.inline_keyboard) == 2

    datas = [row[0].callback_data for row in keyboard.inline_keyboard]
    assert f"mT:{t1['id']}:P" in datas
    assert f"mT:{t2['id']}:P" in datas

    for row in keyboard.inline_keyboard:
        assert row[0].text.startswith("🔲")


def test_render_pending_view_skips_done_tasks():
    t = tools.add_task("Ya hecha")
    tools.complete_task(t["id"])
    tools.add_task("Pendiente")

    with db.connect() as conn:
        text, keyboard = views.render_pending_view(conn)

    assert "Ya hecha" not in text
    assert "Pendiente" in text
    assert len(keyboard.inline_keyboard) == 1


def _render_week(today=None):
    today = today or date(2026, 5, 18)
    with db.connect() as conn:
        return views.render_week_view(today, conn)


def test_render_week_view_empty_returns_semana_tranquila():
    text, keyboard = _render_week()
    assert "Semana tranquila" in text
    assert keyboard is None


def test_render_week_view_only_objective_has_button():
    tools.add_event("Reunión Marta", "2026-05-19T10:00:00", "work")
    o = tools.add_objective("Terminar pres Spotify", "2026-05-18")
    tools.add_event("Flexiones", "2026-05-18T08:00:00", "personal", recurring_rule="DAILY")

    text, keyboard = _render_week()

    assert "ESTA SEMANA" in text
    assert "Reunión Marta" in text
    assert "OBJETIVOS" in text
    assert "Terminar pres Spotify" in text
    assert "RUTINAS" in text
    assert "Flexiones" in text

    assert keyboard is not None
    assert len(keyboard.inline_keyboard) == 1
    btn = keyboard.inline_keyboard[0][0]
    assert btn.text == "🔲 Terminar pres Spotify"
    assert btn.callback_data == f"mO:{o['id']}:W"


def test_render_week_view_done_objective_has_undo_button():
    o = tools.add_objective("Subir vídeos", "2026-05-18")
    tools.mark_objective_done(o["id"])

    text, keyboard = _render_week()

    assert "OBJETIVOS" in text
    assert "✅" in text
    assert keyboard is not None
    btn = keyboard.inline_keyboard[0][0]
    assert btn.text == "✅ Subir vídeos"
    assert btn.callback_data == f"uO:{o['id']}:W"


def test_render_week_view_pending_and_done_objectives_both_get_buttons():
    o1 = tools.add_objective("Pendiente", "2026-05-18")
    o2 = tools.add_objective("Hecho", "2026-05-18")
    tools.mark_objective_done(o2["id"])

    text, keyboard = _render_week()

    assert keyboard is not None
    datas = [row[0].callback_data for row in keyboard.inline_keyboard]
    assert f"mO:{o1['id']}:W" in datas
    assert f"uO:{o2['id']}:W" in datas


def test_render_week_view_completed_task_in_completado_section_without_button(monkeypatch):
    import date_utils
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 19))
    t = tools.add_task("Comprar pan")
    with db.connect() as conn:
        conn.execute(
            "UPDATE tasks SET done=1, done_at=? WHERE id=?",
            ("2026-05-19T10:00:00", t["id"]),
        )

    text, keyboard = _render_week()

    assert "COMPLETADO" in text
    assert "<s>Comprar pan</s>" in text
    if keyboard is not None:
        for row in keyboard.inline_keyboard:
            for btn in row:
                assert "Comprar pan" not in btn.text


def test_render_week_view_objectives_filtered_by_current_week():
    today = date(2026, 5, 18)
    tools.add_objective("De esta semana", "2026-05-18")
    tools.add_objective("De la pasada", "2026-05-11")

    with db.connect() as conn:
        text, keyboard = views.render_week_view(today, conn)

    assert "De esta semana" in text
    assert "De la pasada" not in text


def test_render_full_mix_keyboard_order():
    """Orden: pendientes primero (events, rutinas, tareas), luego completados."""
    tools.add_event("Reunión", "2026-05-19T10:00:00", "work")
    e_done = tools.add_event("Cita", "2026-05-19T11:00:00", "work")
    tools.mark_event_done(e_done["id"])

    text, keyboard = _render()

    btn_texts = [row[0].text for row in keyboard.inline_keyboard]

    assert btn_texts[0].startswith("🔲")
    assert "Reunión" in btn_texts[0]
    assert btn_texts[-1].startswith("✅")
    assert "Cita" in btn_texts[-1]

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


def _render_tomorrow(tomorrow=None):
    tomorrow = tomorrow or date(2026, 5, 20)
    with db.connect() as conn:
        return views.render_tomorrow_view(tomorrow, conn)


def _render_with_completed(today=None):
    today = today or date(2026, 5, 19)
    with db.connect() as conn:
        return views.render_today_view(today, conn, show_completed=True)


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

    text, keyboard = _render_with_completed()

    assert "COMPLETADO HOY" in text
    assert "<s>10:00 — Reunión</s>" in text
    btn_texts = [row[0].text for row in keyboard.inline_keyboard]
    assert any(t.startswith("✅") and "Reunión" in t for t in btn_texts)
    datas = [row[0].callback_data for row in keyboard.inline_keyboard]
    assert f"uE:{e['id']}:Hc" in datas


def test_render_routine_pending_in_rutinas_section(monkeypatch):
    import date_utils
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 19))
    e = tools.add_event("Flexiones", "2026-05-19T08:00:00", "personal", recurring_rule="DAILY")

    text, keyboard = _render()

    assert "🔁" in text
    assert "RUTINAS" in text
    assert "Flexiones" in text
    btn = keyboard.inline_keyboard[0][0]
    assert btn.callback_data == f"mR:{e['id']}:H"


def test_render_routine_done_today_in_completado_section(monkeypatch):
    import date_utils
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 19))
    e = tools.add_event("Flexiones", "2026-05-19T08:00:00", "personal", recurring_rule="DAILY")
    tools.mark_event_done(e["id"])

    text, keyboard = _render_with_completed()

    assert "COMPLETADO HOY" in text
    assert "<s>Flexiones" in text
    datas = [row[0].callback_data for row in keyboard.inline_keyboard]
    assert f"uR:{e['id']}:Hc" in datas


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
    assert btn.callback_data == f"mT:{t['id']}:H"


def test_render_task_done_today_in_completado(monkeypatch):
    import date_utils
    monkeypatch.setattr(date_utils, "today_madrid", lambda: date(2026, 5, 19))
    t = tools.add_task("comprar pan")
    with db.connect() as conn:
        conn.execute(
            "UPDATE tasks SET done=1, done_at=? WHERE id=?",
            ("2026-05-19T10:00:00", t["id"]),
        )

    text, keyboard = _render_with_completed()

    assert "COMPLETADO HOY" in text
    assert "<s>comprar pan</s>" in text
    datas = [row[0].callback_data for row in keyboard.inline_keyboard]
    assert f"uT:{t['id']}:Hc" in datas


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


def test_render_week_view_done_objective_appears_in_completado_tachado():
    """Un objetivo hecho aparece en COMPLETADO tachado, NO en OBJETIVOS."""
    o = tools.add_objective("Subir vídeos", "2026-05-18")
    tools.mark_objective_done(o["id"])

    text, keyboard = _render_week()

    assert "COMPLETADO" in text
    assert "<s>Subir vídeos</s>" in text
    # No aparece en sección OBJETIVOS (que se omite porque no hay pendientes)
    assert "OBJETIVOS" not in text

    # Botón ✅ presente para deshacer
    assert keyboard is not None
    btn = keyboard.inline_keyboard[0][0]
    assert btn.text == "✅ Subir vídeos"
    assert btn.callback_data == f"uO:{o['id']}:W"


def test_render_week_view_pending_in_objectives_done_in_completado():
    """Pendiente en OBJETIVOS, hecho en COMPLETADO. Ambos con botón."""
    o1 = tools.add_objective("Pendiente", "2026-05-18")
    o2 = tools.add_objective("Hecho", "2026-05-18")
    tools.mark_objective_done(o2["id"])

    text, keyboard = _render_week()

    assert "OBJETIVOS" in text
    assert "• Pendiente" in text
    assert "Hecho" not in text.split("OBJETIVOS")[1].split("COMPLETADO")[0]  # Hecho NO está en OBJETIVOS
    assert "COMPLETADO" in text
    assert "<s>Hecho</s>" in text

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
    """Con COMPLETADO mostrado, orden: pendientes primero, luego completados, luego toggle."""
    tools.add_event("Reunión", "2026-05-19T10:00:00", "work")
    e_done = tools.add_event("Cita", "2026-05-19T11:00:00", "work")
    tools.mark_event_done(e_done["id"])

    text, keyboard = _render_with_completed()

    btn_texts = [row[0].text for row in keyboard.inline_keyboard]

    # Primero el pendiente
    assert btn_texts[0].startswith("🔲")
    assert "Reunión" in btn_texts[0]
    # En medio el completado
    assert any(t.startswith("✅") and "Cita" in t for t in btn_texts)
    # Al final el toggle "Ocultar completados"
    assert "Ocultar completados" in btn_texts[-1]


def test_render_tomorrow_view_empty_returns_libre():
    text, keyboard = _render_tomorrow()
    assert "Mañana lo tienes libre" in text
    assert keyboard is None


def test_render_tomorrow_view_event_tomorrow_appears_in_manana():
    tools.add_event("Dentista", "2026-05-20T17:00:00", "medical")

    text, keyboard = _render_tomorrow()

    assert "📅" in text
    assert "MAÑANA" in text
    assert "17:00 — Dentista" in text
    assert keyboard is None


def test_render_tomorrow_view_event_today_not_shown():
    tools.add_event("Hoy a las 10", "2026-05-19T10:00:00", "work")

    text, keyboard = _render_tomorrow()

    assert "Mañana lo tienes libre" in text
    assert "Hoy a las 10" not in text


def test_render_tomorrow_view_daily_routine_appears():
    tools.add_event("Flexiones", "2026-05-19T08:00:00", "personal", recurring_rule="DAILY")

    text, keyboard = _render_tomorrow()

    assert "🔁" in text
    assert "RUTINAS" in text
    assert "Flexiones" in text


def test_render_tomorrow_view_does_not_show_pendientes():
    """Tareas sin fecha no aparecen en /mañana."""
    tools.add_task("comprar pan")

    text, keyboard = _render_tomorrow()

    assert "Mañana lo tienes libre" in text
    assert "comprar pan" not in text
    assert "PENDIENTES" not in text


def test_render_today_view_default_hides_completado_section():
    """Por defecto la sección COMPLETADO no se muestra; en su lugar, un botón."""
    e = tools.add_event("Reunión", "2026-05-19T10:00:00", "work")
    tools.mark_event_done(e["id"])
    tools.add_event("Cita", "2026-05-19T15:00:00", "work")  # pendiente

    text, keyboard = _render()

    assert "COMPLETADO" not in text
    # Sí está la sección HOY con la pendiente
    assert "Cita" in text
    # Hay botón de "Ver completados"
    btn_texts = [row[0].text for row in keyboard.inline_keyboard]
    assert any("Ver completados" in t for t in btn_texts)
    # Y no hay botón ✅ del item completado (porque la sección está oculta)
    assert not any(b.startswith("✅") for b in btn_texts)


def test_render_today_view_show_completed_true_shows_section_and_undo_buttons():
    e_done = tools.add_event("Reunión", "2026-05-19T10:00:00", "work")
    tools.mark_event_done(e_done["id"])

    today = date(2026, 5, 19)
    with db.connect() as conn:
        text, keyboard = views.render_today_view(today, conn, show_completed=True)

    assert "COMPLETADO HOY" in text
    assert "<s>10:00 — Reunión</s>" in text
    btn_texts = [row[0].text for row in keyboard.inline_keyboard]
    # Botón ✅ presente para deshacer
    assert any(t.startswith("✅") and "Reunión" in t for t in btn_texts)
    # Y botón "Ocultar completados"
    assert any("Ocultar completados" in t for t in btn_texts)


def test_render_today_view_no_completed_items_no_toggle_button():
    """Si no hay nada hecho, el botón de toggle no aparece."""
    tools.add_event("Pendiente", "2026-05-19T10:00:00", "work")

    text, keyboard = _render()

    btn_texts = [row[0].text for row in keyboard.inline_keyboard]
    assert not any("completados" in t.lower() for t in btn_texts)


def test_render_today_view_toggle_button_callback_data():
    """El callback del toggle codifica el siguiente estado (Hc para mostrar)."""
    tools.add_event("Pendiente", "2026-05-19T09:00:00", "work")  # para que haya botones
    e = tools.add_event("Reunión", "2026-05-19T10:00:00", "work")
    tools.mark_event_done(e["id"])

    text, keyboard = _render()  # show_completed=False por defecto

    toggle_btn = None
    for row in keyboard.inline_keyboard:
        if "Ver completados" in row[0].text:
            toggle_btn = row[0]
            break
    assert toggle_btn is not None
    assert toggle_btn.callback_data == "tg:0:Hc"


def test_render_today_view_show_completed_action_buttons_use_Hc_view_letter():
    """Cuando COMPLETADO está visible, los botones de acción usan vista Hc."""
    e_pending = tools.add_event("Pendiente", "2026-05-19T15:00:00", "work")
    e_done = tools.add_event("Hecho", "2026-05-19T10:00:00", "work")
    tools.mark_event_done(e_done["id"])

    today = date(2026, 5, 19)
    with db.connect() as conn:
        _, keyboard = views.render_today_view(today, conn, show_completed=True)

    datas = [row[0].callback_data for row in keyboard.inline_keyboard]
    # El botón de la pendiente usa Hc
    assert f"mE:{e_pending['id']}:Hc" in datas
    # El botón de la hecha también usa Hc
    assert f"uE:{e_done['id']}:Hc" in datas


def test_render_tomorrow_view_weekly_routine_only_shows_when_matches():
    """WEEKLY:WED solo aparece si mañana es miércoles."""
    tools.add_event(
        "Gimnasio", "2026-05-20T19:00:00", "personal", recurring_rule="WEEKLY:WED"
    )

    # 2026-05-20 es miércoles → debe aparecer
    text_wed, _ = _render_tomorrow(tomorrow=date(2026, 5, 20))
    assert "Gimnasio" in text_wed

    # Mañana = jueves 21 → no debe aparecer
    text_thu, _ = _render_tomorrow(tomorrow=date(2026, 5, 21))
    assert "Gimnasio" not in text_thu

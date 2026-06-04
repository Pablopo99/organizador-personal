"""Render determinístico de la vista /hoy y el saludo matutino.

Devuelve texto HTML + InlineKeyboardMarkup para Telegram. Sin Claude
en el camino, así un tap edita el mensaje en sitio sin latencia.
"""
from datetime import date, datetime
from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

import tools


def _render_level_header(conn) -> str:
    """Devuelve la línea de cabecera del nivel actual con doble salto."""
    total = conn.execute(
        "SELECT COALESCE(SUM(xp_amount), 0) AS t FROM xp_log"
    ).fetchone()["t"] or 0
    level = tools.compute_level(total)
    if level == 0:
        return "<b>Nivel 0</b>\n\n"
    medal = tools.medal_for_level(level)
    return f"{medal} <b>Nivel {level}</b>\n\n"


def render_today_view(
    today: date, conn, show_completed: bool = False
) -> tuple[str, Optional[InlineKeyboardMarkup]]:
    from datetime import timedelta

    header = _render_level_header(conn)
    today_iso = today.isoformat()
    yesterday = today - timedelta(days=1)
    yesterday_iso = yesterday.isoformat()
    today_start = f"{today_iso}T00:00:00"
    today_end = f"{today_iso}T23:59:59"

    events = tools.query_events(
        today_start, today_end, include_done=True, include_grace=True
    )
    tasks_all = tools.list_tasks(include_done=True)
    routines = tools.routine_summary(today_iso, today_iso)
    streak_by_id = {r["event_id"]: r["current_streak"] for r in routines}

    hoy_pending: list[dict] = []
    grace_pending: list[dict] = []
    hoy_done: list[dict] = []
    for e in events:
        if e.get("recurring_rule"):
            continue
        ev_day = e["datetime"][:10]
        if ev_day == today_iso:
            if e["done"] == 1:
                hoy_done.append(e)
            else:
                hoy_pending.append(e)
        elif ev_day == yesterday_iso and e["done"] == 0:
            grace_pending.append(e)

    rutina_pending = [e for e in events if e.get("recurring_rule") and e["done"] == 0]
    rutina_done = [e for e in events if e.get("recurring_rule") and e["done"] == 1]

    task_pending_today = [
        t for t in tasks_all
        if t["done"] == 0 and t.get("due_date") == today_iso
        and t.get("outcome") != "missed"
    ]
    task_grace = [
        t for t in tasks_all
        if t["done"] == 0 and t.get("due_date") == yesterday_iso
        and t.get("outcome") != "missed"
    ]
    task_done_today = [
        t for t in tasks_all
        if t["done"] == 1 and (t.get("done_at") or "").startswith(today_iso)
    ]

    has_completed = bool(hoy_done or rutina_done or task_done_today)
    completed_count = len(hoy_done) + len(rutina_done) + len(task_done_today)
    view_letter = "Hc" if show_completed else "H"

    sections: list[str] = []

    if grace_pending or task_grace:
        lines = []
        for e in grace_pending:
            dt = datetime.fromisoformat(e["datetime"])
            lines.append(f"• {dt.strftime('%H:%M')} — {e['title']}")
        for t in task_grace:
            lines.append(f"• {t['text']}")
        sections.append("🟡 <b>AYER (último día)</b>\n" + "\n".join(lines))

    if hoy_pending:
        lines = []
        for e in hoy_pending:
            dt = datetime.fromisoformat(e["datetime"])
            lines.append(f"• {dt.strftime('%H:%M')} — {e['title']}")
        sections.append("📅 <b>HOY</b>\n" + "\n".join(lines))

    if rutina_pending:
        lines = []
        for e in rutina_pending:
            streak = streak_by_id.get(e["id"], 0)
            suffix = f" 🔥 {streak}" if streak >= 2 else ""
            lines.append(f"• {e['title']}{suffix}")
        sections.append("🔁 <b>RUTINAS</b>\n" + "\n".join(lines))

    if task_pending_today:
        lines = [f"• {t['text']}" for t in task_pending_today]
        sections.append("📝 <b>PENDIENTES</b>\n" + "\n".join(lines))

    if show_completed and has_completed:
        lines = []
        for e in hoy_done:
            dt = datetime.fromisoformat(e["datetime"])
            lines.append(f"• <s>{dt.strftime('%H:%M')} — {e['title']}</s>")
        for e in rutina_done:
            streak = streak_by_id.get(e["id"], 0)
            suffix = f" 🔥 {streak}" if streak >= 2 else ""
            lines.append(f"• <s>{e['title']}{suffix}</s>")
        for t in task_done_today:
            lines.append(f"• <s>{t['text']}</s>")
        sections.append("✅ <b>COMPLETADO HOY</b>\n" + "\n".join(lines))

    if not sections:
        return header + "Día libre, disfrútalo 💪", None

    text = header + "\n\n".join(sections)

    buttons: list[list[InlineKeyboardButton]] = []
    for e in grace_pending:
        buttons.append([InlineKeyboardButton(
            f"🟡 {e['title']} (ayer)", callback_data=f"mE:{e['id']}:{view_letter}"
        )])
    for t in task_grace:
        buttons.append([InlineKeyboardButton(
            f"🟡 {t['text']} (ayer)", callback_data=f"mT:{t['id']}:{view_letter}"
        )])
    for e in hoy_pending:
        buttons.append([InlineKeyboardButton(
            f"🔲 {e['title']}", callback_data=f"mE:{e['id']}:{view_letter}"
        )])
    for e in rutina_pending:
        buttons.append([InlineKeyboardButton(
            f"🔲 {e['title']}", callback_data=f"mR:{e['id']}:{view_letter}"
        )])
    for t in task_pending_today:
        buttons.append([InlineKeyboardButton(
            f"🔲 {t['text']}", callback_data=f"mT:{t['id']}:{view_letter}"
        )])

    if show_completed:
        for e in hoy_done:
            buttons.append([InlineKeyboardButton(
                f"✅ {e['title']}", callback_data=f"uE:{e['id']}:{view_letter}"
            )])
        for e in rutina_done:
            buttons.append([InlineKeyboardButton(
                f"✅ {e['title']}", callback_data=f"uR:{e['id']}:{view_letter}"
            )])
        for t in task_done_today:
            buttons.append([InlineKeyboardButton(
                f"✅ {t['text']}", callback_data=f"uT:{t['id']}:{view_letter}"
            )])

    if has_completed:
        if show_completed:
            buttons.append([InlineKeyboardButton(
                "▲ Ocultar completados", callback_data="tg:0:H"
            )])
        else:
            buttons.append([InlineKeyboardButton(
                f"🏆 Ver completados ({completed_count})", callback_data="tg:0:Hc"
            )])

    keyboard = InlineKeyboardMarkup(buttons) if buttons else None
    return text, keyboard


def render_tomorrow_view(tomorrow: date, conn) -> tuple[str, Optional[InlineKeyboardMarkup]]:
    """Vista de /mañana: eventos y rutinas que tocan mañana. Solo lectura."""
    header = _render_level_header(conn)
    day_start = f"{tomorrow.isoformat()}T00:00:00"
    day_end = f"{tomorrow.isoformat()}T23:59:59"

    events = tools.query_events(day_start, day_end, include_done=True)
    routines = tools.routine_summary(tomorrow.isoformat(), tomorrow.isoformat())
    streak_by_id = {r["event_id"]: r["current_streak"] for r in routines}

    one_off = [e for e in events if not e.get("recurring_rule") and e["done"] == 0]
    recurring = [e for e in events if e.get("recurring_rule") and e["done"] == 0]

    sections: list[str] = []

    if one_off:
        lines = []
        for e in one_off:
            dt = datetime.fromisoformat(e["datetime"])
            lines.append(f"• {dt.strftime('%H:%M')} — {e['title']}")
        sections.append("📅 <b>MAÑANA</b>\n" + "\n".join(lines))

    if recurring:
        lines = []
        for e in recurring:
            streak = streak_by_id.get(e["id"], 0)
            suffix = f" 🔥 {streak}" if streak >= 2 else ""
            lines.append(f"• {e['title']}{suffix}")
        sections.append("🔁 <b>RUTINAS</b>\n" + "\n".join(lines))

    if not sections:
        return header + "Mañana lo tienes libre 🌞", None

    return header + "\n\n".join(sections), None


def render_pending_view(conn) -> tuple[str, Optional[InlineKeyboardMarkup]]:
    """Vista de /pendientes: tres secciones (gracia, con fecha, flotantes)."""
    from datetime import timedelta

    import date_utils

    header = _render_level_header(conn)
    today = date_utils.today_madrid()
    yesterday = today - timedelta(days=1)
    today_iso = today.isoformat()
    yesterday_iso = yesterday.isoformat()

    all_tasks = tools.list_tasks(include_done=False)
    pending = [t for t in all_tasks if t.get("outcome") != "missed"]

    grace = [t for t in pending if t.get("due_date") == yesterday_iso]
    with_date = sorted(
        [t for t in pending
         if t.get("due_date") and t["due_date"] >= today_iso],
        key=lambda t: t["due_date"],
    )
    floating = [t for t in pending if not t.get("due_date")]

    if not (grace or with_date or floating):
        return header + "No tienes tareas pendientes. 🎉", None

    sections: list[str] = []
    if grace:
        lines = [f"• {t['text']}" for t in grace]
        sections.append("🟡 <b>EN GRACIA</b>\n" + "\n".join(lines))
    if with_date:
        lines = []
        weekdays_es = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
        for t in with_date:
            d = date.fromisoformat(t["due_date"])
            wd = weekdays_es[d.weekday()]
            lines.append(f"• {wd} {d.day}/{d.month:02d} — {t['text']}")
        sections.append("📅 <b>CON FECHA</b>\n" + "\n".join(lines))
    if floating:
        lines = [f"• {t['text']}" for t in floating]
        sections.append("🌊 <b>FLOTANTES</b>\n" + "\n".join(lines))

    text = header + "\n\n".join(sections)

    buttons: list[list[InlineKeyboardButton]] = []
    for t in grace + with_date + floating:
        buttons.append([InlineKeyboardButton(
            f"🔲 {t['text']}", callback_data=f"mT:{t['id']}:P"
        )])

    return text, InlineKeyboardMarkup(buttons)


def render_week_view(today: date, conn) -> tuple[str, Optional[InlineKeyboardMarkup]]:
    """Vista de /semana: 4 secciones, botones solo en objetivos."""
    from datetime import timedelta

    from date_utils import monday_of_week

    header = _render_level_header(conn)
    monday = monday_of_week(today)
    sunday = monday + timedelta(days=6)
    week_start_iso = f"{monday.isoformat()}T00:00:00"
    week_end_iso = f"{sunday.isoformat()}T23:59:59"

    events = tools.query_events(week_start_iso, week_end_iso, include_done=True)
    objectives = tools.query_objectives(monday.isoformat())
    tasks_all = tools.list_tasks(include_done=True)
    routines = tools.routine_summary(monday.isoformat(), sunday.isoformat())

    week_pending = [e for e in events if not e.get("recurring_rule") and e["done"] == 0]
    week_done = [e for e in events if not e.get("recurring_rule") and e["done"] == 1]

    task_done_week = []
    for t in tasks_all:
        if t["done"] != 1:
            continue
        done_at = t.get("done_at") or ""
        if not done_at:
            continue
        try:
            done_date = date.fromisoformat(done_at.split("T")[0])
        except ValueError:
            continue
        if monday <= done_date <= sunday:
            task_done_week.append(t)

    weekdays_es_full = [
        "Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo",
    ]

    sections: list[str] = []

    if week_pending:
        by_day: dict[int, list[dict]] = {}
        for e in week_pending:
            dt = datetime.fromisoformat(e["datetime"])
            by_day.setdefault(dt.weekday(), []).append({"dt": dt, "title": e["title"]})

        chunks: list[str] = []
        for wd in sorted(by_day):
            day_items = sorted(by_day[wd], key=lambda x: x["dt"])
            day_lines = [
                f"• {item['dt'].strftime('%H:%M')} — {item['title']}"
                for item in day_items
            ]
            chunks.append(f"<b>{weekdays_es_full[wd]}</b>\n" + "\n".join(day_lines))

        sections.append("📅 <b>ESTA SEMANA</b>\n\n" + "\n\n".join(chunks))

    pending_objectives = [o for o in objectives if not o["done"] and o.get("outcome") != "missed"]
    done_objectives = [o for o in objectives if o["done"] and o.get("outcome") != "missed"]

    if pending_objectives:
        lines = [f"• {o['text']}" for o in pending_objectives]
        sections.append("🎯 <b>OBJETIVOS</b>\n" + "\n".join(lines))

    if routines:
        lines = []
        for r in routines:
            base = f"• {r['title']} ({r['completed_days']}/{r['scheduled_days']} días)"
            if r["current_streak"] >= 2:
                base += f" 🔥 {r['current_streak']} seguidos"
            lines.append(base)
        sections.append("🔁 <b>RUTINAS</b>\n" + "\n".join(lines))

    if week_done or task_done_week or done_objectives:
        lines = []
        for e in week_done:
            dt = datetime.fromisoformat(e["datetime"])
            wd = weekdays_es_full[dt.weekday()]
            lines.append(f"• <s>{wd} {dt.strftime('%H:%M')} — {e['title']}</s>")
        for o in done_objectives:
            lines.append(f"• <s>{o['text']}</s>")
        for t in task_done_week:
            lines.append(f"• <s>{t['text']}</s>")
        sections.append("✅ <b>COMPLETADO</b>\n" + "\n".join(lines))

    if not sections:
        return header + "Semana tranquila 💆", None

    text = header + "\n\n".join(sections)

    buttons: list[list[InlineKeyboardButton]] = []
    for o in pending_objectives:
        buttons.append([InlineKeyboardButton(
            f"🔲 {o['text']}", callback_data=f"mO:{o['id']}:W"
        )])
    for o in done_objectives:
        buttons.append([InlineKeyboardButton(
            f"✅ {o['text']}", callback_data=f"uO:{o['id']}:W"
        )])

    keyboard = InlineKeyboardMarkup(buttons) if buttons else None
    return text, keyboard


def render_metrics_view(
    today: date, conn
) -> tuple[str, Optional[InlineKeyboardMarkup]]:
    """Panel de métricas de los últimos 30 días."""
    from datetime import timedelta

    header = _render_level_header(conn)
    date_from = (today - timedelta(days=29)).isoformat()
    date_to = today.isoformat()
    m = tools.metrics_summary(date_from, date_to)

    routine_totals = m["routines"]["totals"]
    has_any = (
        sum(routine_totals.values()) > 0
        or sum(m["events"].values()) > 0
        or sum(m["tasks"].values()) > 0
        or sum(m["objectives"].values()) > 0
    )
    if not has_any:
        return header + "Todavía no hay datos suficientes para mostrar métricas.", None

    sections: list[str] = [
        f"📊 <b>Métricas — últimos 30 días</b>"
    ]

    if m["routines"]["per_event"]:
        lines = []
        for r in m["routines"]["per_event"]:
            lines.append(
                f"• {r['title']}: 🟢 {r['on_time']}  🟡 {r['grace']}  🔴 {r['missed']}"
            )
        lines.append(
            f"  <b>Total</b>: 🟢 {routine_totals['on_time']}  "
            f"🟡 {routine_totals['grace']}  🔴 {routine_totals['missed']}"
        )
        sections.append("🔁 <b>Rutinas</b>\n" + "\n".join(lines))

    ev = m["events"]
    if sum(ev.values()) > 0:
        sections.append(
            "📅 <b>Eventos puntuales</b>\n"
            f"🟢 {ev['on_time']}  🟡 {ev['grace']}  🔴 {ev['missed']}"
        )

    tk = m["tasks"]
    if sum(tk.values()) > 0:
        sections.append(
            "✅ <b>Tareas</b>\n"
            f"🟢 {tk['on_time']}  🟡 {tk['grace']}  🔴 {tk['missed']}"
        )

    ob = m["objectives"]
    if sum(ob.values()) > 0:
        sections.append(
            "🎯 <b>Objetivos semanales</b>\n"
            f"🟢 {ob['on_time']}  🟡 {ob['grace']}  🔴 {ob['missed']}"
        )

    return header + "\n\n".join(sections), None


def render_nivel_view(
    today: date, conn
) -> tuple[str, Optional[InlineKeyboardMarkup]]:
    """Panel de nivel con XP total, progreso, faltan y breakdown 30d."""
    from datetime import timedelta

    total = conn.execute(
        "SELECT COALESCE(SUM(xp_amount), 0) AS t FROM xp_log"
    ).fetchone()["t"] or 0
    level = tools.compute_level(total)
    medal = tools.medal_for_level(level)
    medal_prefix = f"{medal} " if medal else ""

    # XP del nivel actual y del siguiente
    xp_for_current = 0 if level == 0 else 10 * level * (level + 2)
    xp_for_next = 10 * (level + 1) * (level + 3)
    needed = xp_for_next - total
    progress_in_level = total - xp_for_current
    range_in_level = xp_for_next - xp_for_current
    pct = int(100 * progress_in_level / range_in_level) if range_in_level else 0

    # Barra de 10 bloques
    blocks_filled = int(pct / 10)
    blocks_empty = 10 - blocks_filled
    bar = "▓" * blocks_filled + "▒" * blocks_empty

    sections = [
        f"{medal_prefix}<b>Nivel {level}</b> — {total} XP",
        f"Para nivel {level + 1} faltan: <b>{needed} XP</b>\n"
        f"Progreso: {bar} {pct}%",
    ]

    # Breakdown últimos 30 días
    cutoff = (today - timedelta(days=29)).isoformat()
    rows = conn.execute(
        "SELECT item_type, COALESCE(SUM(xp_amount), 0) AS sum_xp "
        "FROM xp_log "
        "WHERE substr(awarded_at, 1, 10) >= ? "
        "GROUP BY item_type",
        (cutoff,),
    ).fetchall()
    breakdown = {r["item_type"]: r["sum_xp"] for r in rows}
    total_30d = sum(breakdown.values())

    if total_30d > 0:
        breakdown_lines = [
            f"📊 <b>Últimos 30 días</b>: {total_30d} XP ganados"
        ]
        labels = [
            ("routine", "Rutinas"),
            ("task", "Tareas"),
            ("event", "Eventos"),
            ("objective", "Objetivos"),
            ("perfect_day", "Días perfectos"),
            ("perfect_week", "Semanas perfectas"),
        ]
        for key, label in labels:
            value = breakdown.get(key, 0)
            if value:
                breakdown_lines.append(f"  {label}: {value} XP")
        sections.append("\n".join(breakdown_lines))

    return "\n\n".join(sections), None

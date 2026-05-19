"""Render determinístico de la vista /hoy y el saludo matutino.

Devuelve texto HTML + InlineKeyboardMarkup para Telegram. Sin Claude
en el camino, así un tap edita el mensaje en sitio sin latencia.
"""
from datetime import date, datetime
from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

import tools


def render_today_view(today: date, conn) -> tuple[str, Optional[InlineKeyboardMarkup]]:
    today_start = f"{today.isoformat()}T00:00:00"
    today_end = f"{today.isoformat()}T23:59:59"

    events = tools.query_events(today_start, today_end, include_done=True)
    tasks_all = tools.list_tasks(include_done=True)
    routines = tools.routine_summary(today.isoformat(), today.isoformat())
    streak_by_id = {r["event_id"]: r["current_streak"] for r in routines}

    hoy_pending = [e for e in events if not e.get("recurring_rule") and e["done"] == 0]
    hoy_done = [e for e in events if not e.get("recurring_rule") and e["done"] == 1]
    rutina_pending = [e for e in events if e.get("recurring_rule") and e["done"] == 0]
    rutina_done = [e for e in events if e.get("recurring_rule") and e["done"] == 1]

    task_pending = [t for t in tasks_all if t["done"] == 0]
    today_prefix = today.isoformat()
    task_done_today = [
        t for t in tasks_all
        if t["done"] == 1 and (t.get("done_at") or "").startswith(today_prefix)
    ]

    sections: list[str] = []

    if hoy_pending:
        lines = []
        for e in hoy_pending:
            dt = datetime.fromisoformat(e["datetime"])
            lines.append(f"• {dt.strftime('%H:%M')} — {e['title']}")
        sections.append("📅 <b>HOY</b>\n\n" + "\n".join(lines))

    if rutina_pending:
        lines = []
        for e in rutina_pending:
            streak = streak_by_id.get(e["id"], 0)
            suffix = f" 🔥 {streak}" if streak >= 2 else ""
            lines.append(f"• {e['title']}{suffix}")
        sections.append("🔁 <b>RUTINAS</b>\n\n" + "\n".join(lines))

    if task_pending:
        lines = [f"• {t['text']}" for t in task_pending]
        sections.append("📝 <b>PENDIENTES</b>\n\n" + "\n".join(lines))

    if hoy_done or rutina_done or task_done_today:
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
        sections.append("✅ <b>COMPLETADO HOY</b>\n\n" + "\n".join(lines))

    if not sections:
        return "Día libre, disfrútalo 💪", None

    text = "\n\n".join(sections)

    buttons: list[list[InlineKeyboardButton]] = []
    for e in hoy_pending:
        buttons.append([InlineKeyboardButton(
            f"🔲 {e['title']}", callback_data=f"mE:{e['id']}"
        )])
    for e in rutina_pending:
        buttons.append([InlineKeyboardButton(
            f"🔲 {e['title']}", callback_data=f"mR:{e['id']}"
        )])
    for t in task_pending:
        buttons.append([InlineKeyboardButton(
            f"🔲 {t['text']}", callback_data=f"mT:{t['id']}"
        )])
    for e in hoy_done:
        buttons.append([InlineKeyboardButton(
            f"✅ {e['title']}", callback_data=f"uE:{e['id']}"
        )])
    for e in rutina_done:
        buttons.append([InlineKeyboardButton(
            f"✅ {e['title']}", callback_data=f"uR:{e['id']}"
        )])
    for t in task_done_today:
        buttons.append([InlineKeyboardButton(
            f"✅ {t['text']}", callback_data=f"uT:{t['id']}"
        )])

    keyboard = InlineKeyboardMarkup(buttons)
    return text, keyboard

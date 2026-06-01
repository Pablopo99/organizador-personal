"""Jobs programados: mensaje matutino y recordatorios proactivos."""
import logging
from datetime import datetime, timedelta

from telegram.constants import ParseMode
from telegram.ext import ContextTypes

import db
from config import ALLOWED_USER_ID

log = logging.getLogger("scheduler")

_WEEKDAYS_ES = [
    "lunes", "martes", "miércoles", "jueves",
    "viernes", "sábado", "domingo",
]

_ES_MONTHS = [
    "ene", "feb", "mar", "abr", "may", "jun",
    "jul", "ago", "sep", "oct", "nov", "dic",
]


async def morning_summary(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Envía el saludo matutino con la vista de hoy. Los lunes incluye bloque semanal."""
    import date_utils
    import tools as _tools
    import views
    from datetime import timedelta as _td

    today = date_utils.today_madrid()
    weekday = _WEEKDAYS_ES[today.weekday()]
    date_str = f"{today.day} {_ES_MONTHS[today.month - 1]}"
    greeting = f"Buenos días Pablo 🌅 — <b>{weekday}, {date_str}</b>\n\n"

    weekly_block = ""
    if today.weekday() == 0:
        last_monday = today - _td(days=7)
        last_sunday = today - _td(days=1)
        try:
            with db.connect() as conn:
                perfect_week_awarded = _tools._check_and_award_perfect_week(
                    conn, today
                )
            m = _tools.metrics_summary(
                last_monday.isoformat(), last_sunday.isoformat()
            )
            weekly_block = _format_weekly_block(m)
            if perfect_week_awarded > 0:
                weekly_block += "   🏆 ¡Semana perfecta! +100 XP\n\n"
        except Exception:
            log.exception("Error generando bloque semanal del lunes")
            weekly_block = ""

    try:
        with db.connect() as conn:
            body, keyboard = views.render_today_view(today, conn)
    except Exception:
        log.exception("Error generando el saludo matutino")
        return

    text = greeting + weekly_block + body

    try:
        await context.bot.send_message(
            chat_id=ALLOWED_USER_ID,
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )
    except Exception:
        log.exception("Error enviando el saludo matutino")


def _format_weekly_block(m: dict) -> str:
    """Render del bloque semanal de lunes. Vacío si no hay datos."""
    routine_totals = m["routines"]["totals"]
    routine_total = sum(routine_totals.values())
    tasks_total = sum(m["tasks"].values())
    obj_total = sum(m["objectives"].values())

    if routine_total == 0 and tasks_total == 0 and obj_total == 0:
        return ""

    def _pct_line(label: str, d: dict) -> str:
        total = d["on_time"] + d["grace"] + d["missed"]
        if total == 0:
            return ""
        ot = round(100 * d["on_time"] / total)
        gr = round(100 * d["grace"] / total)
        ms = round(100 * d["missed"] / total)
        return f"   {label}:   🟢 {ot}% 🟡 {gr}% 🔴 {ms}%"

    lines = ["📊 <b>Tu semana pasada</b>"]
    if routine_total > 0:
        line = _pct_line("Rutinas", routine_totals)
        if line:
            lines.append(line)
    if tasks_total > 0:
        line = _pct_line("Tareas", m["tasks"])
        if line:
            lines.append(line)
    if obj_total > 0:
        done = m["objectives"]["on_time"] + m["objectives"]["grace"]
        total = obj_total
        lines.append(f"   Objetivos: {done} de {total} cumplidos")

    return "\n".join(lines) + "\n\n"


async def weekly_objectives_reminder(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Domingo a las 13:00 Madrid: pídele a Pablo pensar los 3 objetivos de la semana que entra."""
    text = (
        "🎯 <b>Domingo de objetivos</b>\n\n"
        "Para la semana que empieza mañana, párate y piensa tus <b>3 objetivos</b>. "
        "Cuéntamelos cuando los tengas claros y los apunto."
    )
    try:
        await context.bot.send_message(
            chat_id=ALLOWED_USER_ID,
            text=text,
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        log.exception("Error enviando recordatorio semanal de objetivos")


_DAY_REMINDER_MIN_HOURS = 23.0
_DAY_REMINDER_MAX_HOURS = 25.0
_HOUR_REMINDER_MIN_MIN = 50.0
_HOUR_REMINDER_MAX_MIN = 70.0


def _format_offset(minutes: int) -> str:
    """Formatea un offset en minutos a una cadena legible en español.

    < 60 → "30 min", 60 → "1 h", 60-1439 → "X h", 1440 → "1 día",
    múltiplos de 1440 → "N días", 10080 → "1 semana", resto → "N días".
    """
    if minutes < 60:
        return f"{minutes} min"
    if minutes == 60:
        return "1 h"
    if minutes < 1440:
        hours = minutes // 60
        return f"{hours} h"
    if minutes == 1440:
        return "1 día"
    if minutes == 10080:
        return "1 semana"
    days = minutes // 1440
    return f"{days} días"


async def check_reminders(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Cada 5 min: revisa eventos próximos y manda recordatorios pendientes."""
    now = datetime.now()
    upper = now + timedelta(hours=26)

    with db.connect() as conn:
        rows = conn.execute(
            """
            SELECT id, title, datetime, reminder_1d_sent, reminder_1h_sent
            FROM events
            WHERE done = 0
              AND recurring_rule IS NULL
              AND datetime >= ?
              AND datetime <= ?
              AND NOT EXISTS (
                  SELECT 1 FROM event_reminders
                  WHERE event_reminders.event_id = events.id
              )
            """,
            (now.isoformat(timespec="seconds"), upper.isoformat(timespec="seconds")),
        ).fetchall()

    for row in rows:
        try:
            event_dt = datetime.fromisoformat(row["datetime"])
        except ValueError:
            log.warning("Evento %s con datetime inválido: %r", row["id"], row["datetime"])
            continue

        delta = event_dt - now
        hours = delta.total_seconds() / 3600.0
        minutes = delta.total_seconds() / 60.0

        if (_DAY_REMINDER_MIN_HOURS <= hours <= _DAY_REMINDER_MAX_HOURS
                and row["reminder_1d_sent"] == 0):
            time_str = event_dt.strftime("%H:%M")
            text = f"📅 Mañana a las {time_str} tienes: <b>{row['title']}</b>"
            await _safe_send_and_mark(context, text, row["id"], "reminder_1d_sent")

        if (_HOUR_REMINDER_MIN_MIN <= minutes <= _HOUR_REMINDER_MAX_MIN
                and row["reminder_1h_sent"] == 0):
            text = f"⏰ En 1h tienes: <b>{row['title']}</b>"
            await _safe_send_and_mark(context, text, row["id"], "reminder_1h_sent")

    # Recordatorios custom dentro de la ventana ±5 min
    with db.connect() as conn:
        custom_rows = conn.execute(
            """
            SELECT er.id AS reminder_id, er.event_id, er.offset_minutes,
                   e.title, e.datetime
            FROM event_reminders er
            JOIN events e ON e.id = er.event_id
            WHERE er.sent = 0
              AND e.done = 0
              AND e.recurring_rule IS NULL
            """
        ).fetchall()

    for r in custom_rows:
        try:
            event_dt = datetime.fromisoformat(r["datetime"])
        except ValueError:
            log.warning(
                "Evento %s con datetime inválido: %r",
                r["event_id"], r["datetime"],
            )
            continue
        fire_time = event_dt - timedelta(minutes=r["offset_minutes"])
        diff_sec = abs((fire_time - now).total_seconds())
        if diff_sec <= 5 * 60:
            pretty = _format_offset(r["offset_minutes"])
            text = f"⏰ En {pretty} tienes: <b>{r['title']}</b>"
            try:
                await context.bot.send_message(
                    chat_id=ALLOWED_USER_ID,
                    text=text,
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                log.exception(
                    "Error enviando recordatorio custom %s",
                    r["reminder_id"],
                )
                continue
            with db.connect() as conn:
                conn.execute(
                    "UPDATE event_reminders SET sent = 1 WHERE id = ?",
                    (r["reminder_id"],),
                )


async def _safe_send_and_mark(context, text: str, event_id: int, flag_column: str) -> None:
    """Envía el recordatorio y marca el flag. Si falla, loguea pero no levanta."""
    try:
        await context.bot.send_message(
            chat_id=ALLOWED_USER_ID,
            text=text,
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        log.exception("Error enviando recordatorio para evento %s", event_id)
        return

    with db.connect() as conn:
        conn.execute(
            f"UPDATE events SET {flag_column} = 1 WHERE id = ?",
            (event_id,),
        )


async def detect_missed_items(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Detecta ítems que cruzaron a 'perdido' y notifica al usuario."""
    import date_utils
    import tools as _tools
    from datetime import timedelta as _td

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    today = date_utils.today_madrid()
    yesterday = today - _td(days=1)
    notify_iso = date_utils.now_iso()

    async def _notify_with_buttons(item_kind: str, item_id: int, title: str) -> None:
        prefix_recreate = {"event": "rE", "task": "rT", "objective": "rO"}[item_kind]
        prefix_discard = {"event": "dE", "task": "dT", "objective": "dO"}[item_kind]
        markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("📌 Pasar a hoy",
                                 callback_data=f"{prefix_recreate}:{item_id}"),
            InlineKeyboardButton("🗑️ Descartar",
                                 callback_data=f"{prefix_discard}:{item_id}"),
        ]])
        try:
            await context.bot.send_message(
                chat_id=ALLOWED_USER_ID,
                text=f"⚠️ Se te ha pasado: <b>{title}</b>",
                parse_mode=ParseMode.HTML,
                reply_markup=markup,
            )
        except Exception:
            log.exception("Error notificando perdido %s/%s", item_kind, item_id)

    async def _notify_routine(event_id: int, title: str, streak_before: int) -> None:
        text = (
            f"⚠️ Se rompió tu racha de <b>{title}</b>"
            + (f" (llevabas {streak_before} días)." if streak_before > 0 else ".")
            + "\nLa rutina sigue activa, vuelve a empezar cuando quieras."
        )
        try:
            await context.bot.send_message(
                chat_id=ALLOWED_USER_ID,
                text=text,
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            log.exception("Error notificando rotura de racha %s", event_id)

    with db.connect() as conn:
        # Tareas perdidas
        rows = conn.execute(
            """
            SELECT id, text FROM tasks
            WHERE done = 0 AND outcome IS NULL
              AND due_date IS NOT NULL
              AND due_date < ?
            """,
            (yesterday.isoformat(),),
        ).fetchall()
        for r in rows:
            try:
                conn.execute(
                    "INSERT INTO missed_notifications "
                    "(item_type, item_id, notified_at) VALUES ('task', ?, ?)",
                    (r["id"], notify_iso),
                )
            except Exception:
                continue
            await _notify_with_buttons("task", r["id"], r["text"])

        # Eventos puntuales perdidos
        rows = conn.execute(
            """
            SELECT id, title FROM events
            WHERE done = 0 AND outcome IS NULL
              AND recurring_rule IS NULL
              AND substr(datetime, 1, 10) < ?
            """,
            (yesterday.isoformat(),),
        ).fetchall()
        for r in rows:
            try:
                conn.execute(
                    "INSERT INTO missed_notifications "
                    "(item_type, item_id, notified_at) VALUES ('event', ?, ?)",
                    (r["id"], notify_iso),
                )
            except Exception:
                continue
            await _notify_with_buttons("event", r["id"], r["title"])

        # Objetivos perdidos
        from date_utils import monday_of_week
        cutoff_obj = monday_of_week(today) - _td(days=14)
        rows = conn.execute(
            """
            SELECT id, text, week_start FROM objectives
            WHERE done = 0 AND outcome IS NULL
              AND week_start <= ?
            """,
            (cutoff_obj.isoformat(),),
        ).fetchall()
        for r in rows:
            try:
                conn.execute(
                    "INSERT INTO missed_notifications "
                    "(item_type, item_id, notified_at) VALUES ('objective', ?, ?)",
                    (r["id"], notify_iso),
                )
            except Exception:
                continue
            await _notify_with_buttons("objective", r["id"], r["text"])

        # Rutinas: notificar rotura de racha
        routine_rows = conn.execute(
            "SELECT id, title, recurring_rule, datetime FROM events "
            "WHERE recurring_rule IS NOT NULL"
        ).fetchall()
        for r in routine_rows:
            rule = r["recurring_rule"]
            lost_date = _tools._previous_expected_date(rule, yesterday)
            if lost_date is None:
                continue
            done_row = conn.execute(
                "SELECT 1 FROM routine_completions "
                "WHERE event_id = ? AND completion_date = ?",
                (r["id"], lost_date.isoformat()),
            ).fetchone()
            if done_row:
                continue
            prior = _tools._previous_expected_date(rule, lost_date)
            if prior is None:
                continue
            prior_done = conn.execute(
                "SELECT 1 FROM routine_completions "
                "WHERE event_id = ? AND completion_date = ?",
                (r["id"], prior.isoformat()),
            ).fetchone()
            if not prior_done:
                continue
            try:
                conn.execute(
                    "INSERT INTO missed_notifications "
                    "(item_type, item_id, occurrence_date, notified_at) "
                    "VALUES ('routine', ?, ?, ?)",
                    (r["id"], lost_date.isoformat(), notify_iso),
                )
            except Exception:
                continue
            streak_before = _tools._current_streak(r["id"], rule, prior, conn)
            await _notify_routine(r["id"], r["title"], streak_before)

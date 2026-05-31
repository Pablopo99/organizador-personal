"""Herramientas que Claude puede invocar. Operan sobre SQLite."""
import logging
from datetime import date, datetime, timedelta
from typing import Optional

import db
import gcal_sync
from config import CATEGORIES
from date_utils import now_iso

log = logging.getLogger("tools")

_WEEKDAY_MAP = {
    "MON": 0, "TUE": 1, "WED": 2, "THU": 3,
    "FRI": 4, "SAT": 5, "SUN": 6,
}


def _calculate_outcome(assigned: Optional[date], today: date) -> Optional[str]:
    """Devuelve 'on_time', 'grace' o None (fuera de ventana / sin fecha).

    Regla:
    - today <= assigned     -> 'on_time'
    - today == assigned + 1 -> 'grace'
    - today >= assigned + 2 -> None (cliente debe rechazar el mark)
    - assigned is None      -> None (item sin fecha; outcome se deja NULL)
    """
    if assigned is None:
        return None
    delta = (today - assigned).days
    if delta <= 0:
        return "on_time"
    if delta == 1:
        return "grace"
    return None


# ----------------------------------------------------------------- xp ----

_XP_BASE = {
    "task":      {"on_time": 10, "grace":  5},
    "event":     {"on_time": 10, "grace":  5},
    "routine":   {"on_time":  5, "grace":  2},
    "objective": {"on_time": 50, "grace": 25},
}

_STREAK_BONUS_CAP = 7


def _calculate_xp(
    item_type: str,
    outcome: str,
    streak_after: int = 0,
) -> tuple[int, int]:
    """Devuelve (xp_amount, streak_bonus_component).

    Para rutinas, el bonus de racha = min(streak_after, 7).
    Para otros tipos, bonus = 0.
    """
    base = _XP_BASE[item_type][outcome]
    streak_bonus = 0
    if item_type == "routine":
        streak_bonus = min(max(streak_after, 0), _STREAK_BONUS_CAP)
    return base + streak_bonus, streak_bonus


def compute_level(xp_total: int) -> int:
    """Devuelve el nivel actual para un total de XP.

    Fórmula: XP_total_para_nivel_N = 10 * N * (N + 2).
    Nivel 0 = < 30 XP.
    """
    if xp_total < 30:
        return 0
    n = 1
    while 10 * (n + 1) * (n + 3) <= xp_total:
        n += 1
    return n


_MEDAL_RANGES = [
    (1, 5, "🥉"),
    (6, 15, "🥈"),
    (16, 30, "🥇"),
    (31, 60, "💎"),
]


def medal_for_level(level: int) -> str:
    """Devuelve el emoji de medalla para el nivel (vacío si nivel 0)."""
    if level <= 0:
        return ""
    for lo, hi, medal in _MEDAL_RANGES:
        if lo <= level <= hi:
            return medal
    return "👑"


def _insert_xp_log(
    conn,
    item_type: str,
    item_id: int,
    outcome: str,
    xp_amount: int,
    streak_bonus: int = 0,
) -> None:
    """Inserta una fila en xp_log. Usar la misma `conn` que la operación
    principal para que todo esté en la misma transacción."""
    import date_utils
    conn.execute(
        """
        INSERT INTO xp_log
            (item_type, item_id, outcome, xp_amount, streak_bonus, awarded_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (item_type, item_id, outcome, xp_amount, streak_bonus, date_utils.now_iso()),
    )


def _get_xp_total() -> int:
    """Suma todos los xp_amount registrados (incluye reversiones)."""
    with db.connect() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(xp_amount), 0) AS total FROM xp_log"
        ).fetchone()
    return row["total"] or 0


def _get_xp_total_with_conn(conn) -> int:
    """Versión de _get_xp_total que usa una conn existente (para
    operaciones dentro de la misma transacción)."""
    row = conn.execute(
        "SELECT COALESCE(SUM(xp_amount), 0) AS total FROM xp_log"
    ).fetchone()
    return row["total"] or 0


# ---------------------------------------------------------------- events ----

def add_event(
    title: str,
    datetime_iso: str,
    category: str,
    recurring_rule: Optional[str] = None,
    notes: Optional[str] = None,
    sync_to_calendar: bool = False,
) -> dict:
    if category not in CATEGORIES:
        raise ValueError(
            f"categoría inválida '{category}'. Permitidas: {CATEGORIES}"
        )
    with db.connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO events (title, datetime, category, recurring_rule, notes, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (title, datetime_iso, category, recurring_rule, notes, now_iso()),
        )
        new_id = cur.lastrowid

    result = {"id": new_id, "title": title, "datetime": datetime_iso}

    if sync_to_calendar:
        try:
            gcal_id = gcal_sync.push_event({
                "title": title,
                "datetime": datetime_iso,
                "category": category,
                "notes": notes,
            })
        except gcal_sync.NotConnected:
            result["sync_error"] = "not_connected"
            return result
        except Exception:
            log.exception("Error en sync_to_calendar para add_event %s", new_id)
            result["sync_error"] = "api_error"
            return result

        with db.connect() as conn:
            conn.execute(
                "UPDATE events SET gcal_event_id = ? WHERE id = ?",
                (gcal_id, new_id),
            )
        result["gcal_event_id"] = gcal_id

    return result


def query_events(
    date_from: str,
    date_to: str,
    category: Optional[str] = None,
    include_done: bool = False,
    include_grace: bool = False,
) -> list[dict]:
    dt_from = datetime.fromisoformat(date_from)
    dt_to = datetime.fromisoformat(date_to)

    grace_from: Optional[datetime] = None
    grace_to: Optional[datetime] = None
    if include_grace:
        grace_day = (dt_from.date() - timedelta(days=1))
        grace_from = datetime.combine(grace_day, datetime.min.time())
        grace_to = datetime.combine(grace_day, datetime.max.time().replace(microsecond=0))

    with db.connect() as conn:
        params: list = []
        sql = "SELECT * FROM events WHERE 1=1"
        if not include_done:
            sql += " AND COALESCE(done, 0) = 0"
        sql += " AND (outcome IS NULL OR outcome != 'missed')"
        if category:
            sql += " AND category = ?"
            params.append(category)
        rows = [dict(r) for r in conn.execute(sql, params).fetchall()]

        occurrences: list[dict] = []
        for row in rows:
            rule = row.get("recurring_rule")
            if not rule:
                row_dt = datetime.fromisoformat(row["datetime"])
                if dt_from <= row_dt <= dt_to:
                    occurrences.append(row)
                elif (
                    include_grace
                    and grace_from is not None
                    and grace_from <= row_dt <= grace_to
                ):
                    occurrences.append(row)
            else:
                occurrences.extend(_expand_recurring(row, rule, dt_from, dt_to, conn))

    occurrences.sort(key=lambda r: r["datetime"])
    return occurrences


def _expand_recurring(
    row: dict,
    rule: str,
    dt_from: datetime,
    dt_to: datetime,
    conn,
) -> list[dict]:
    base_dt = datetime.fromisoformat(row["datetime"])
    results: list[dict] = []

    if rule == "DAILY":
        step = timedelta(days=1)
    elif rule.startswith("WEEKLY:"):
        weekday_code = rule.split(":", 1)[1]
        if weekday_code not in _WEEKDAY_MAP:
            return []
        target_weekday = _WEEKDAY_MAP[weekday_code]
        while base_dt.weekday() != target_weekday:
            base_dt += timedelta(days=1)
        step = timedelta(days=7)
    else:
        return []

    cur_dt = base_dt
    while cur_dt < dt_from:
        cur_dt += step
    while cur_dt <= dt_to:
        clone = dict(row)
        clone["datetime"] = cur_dt.isoformat()
        completion = conn.execute(
            """
            SELECT 1 FROM routine_completions
            WHERE event_id = ? AND completion_date = ?
            """,
            (row["id"], cur_dt.date().isoformat()),
        ).fetchone()
        clone["done"] = 1 if completion else 0
        results.append(clone)
        cur_dt += step
    return results


def update_event(event_id: int, fields: dict) -> dict:
    allowed = {"title", "datetime", "category", "recurring_rule", "notes"}
    sets = []
    params: list = []
    for key, value in fields.items():
        if key not in allowed:
            raise ValueError(f"campo no actualizable: {key}")
        if key == "category" and value not in CATEGORIES:
            raise ValueError(f"categoría inválida '{value}'")
        sets.append(f"{key} = ?")
        params.append(value)
    if not sets:
        return {"id": event_id, "updated": 0}

    if "datetime" in fields:
        sets.append("reminder_1d_sent = 0")
        sets.append("reminder_1h_sent = 0")

    params.append(event_id)
    with db.connect() as conn:
        cur = conn.execute(
            f"UPDATE events SET {', '.join(sets)} WHERE id = ?", params
        )
        gcal_id_row = conn.execute(
            "SELECT gcal_event_id FROM events WHERE id = ?", (event_id,)
        ).fetchone()

    result = {"id": event_id, "updated": cur.rowcount}

    gcal_event_id = gcal_id_row["gcal_event_id"] if gcal_id_row else None
    if gcal_event_id:
        try:
            gcal_sync.update_event(gcal_event_id, fields)
        except Exception:
            log.exception("Error propagando update_event a Calendar (event_id=%s)", event_id)

    return result


def delete_event(event_id: int) -> dict:
    with db.connect() as conn:
        gcal_id_row = conn.execute(
            "SELECT gcal_event_id FROM events WHERE id = ?", (event_id,)
        ).fetchone()
        cur = conn.execute("DELETE FROM events WHERE id = ?", (event_id,))

    gcal_event_id = gcal_id_row["gcal_event_id"] if gcal_id_row else None
    if gcal_event_id:
        try:
            gcal_sync.delete_event(gcal_event_id)
        except Exception:
            log.exception("Error propagando delete_event a Calendar (event_id=%s)", event_id)

    return {"id": event_id, "deleted": cur.rowcount}


def push_event_to_calendar(event_id: int) -> dict:
    """Sincroniza un evento existente con Google Calendar.

    - Si ya está sincronizado, no hace nada (idempotente).
    - Si Pablo no ha autorizado todavía, devuelve error 'not_connected'.
    - Guarda el gcal_event_id en la fila.
    """
    with db.connect() as conn:
        row = conn.execute(
            "SELECT id, title, datetime, category, notes, gcal_event_id"
            " FROM events WHERE id = ?",
            (event_id,),
        ).fetchone()

    if row is None:
        return {"event_id": event_id, "synced": False, "error": "not_found"}

    if row["gcal_event_id"]:
        return {
            "event_id": event_id,
            "synced": True,
            "already_synced": True,
            "gcal_event_id": row["gcal_event_id"],
        }

    try:
        gcal_id = gcal_sync.push_event({
            "title": row["title"],
            "datetime": row["datetime"],
            "category": row["category"],
            "notes": row["notes"],
        })
    except gcal_sync.NotConnected:
        return {"event_id": event_id, "synced": False, "error": "not_connected"}
    except Exception:
        log.exception("Error pushing event %s a Calendar", event_id)
        return {"event_id": event_id, "synced": False, "error": "api_error"}

    with db.connect() as conn:
        conn.execute(
            "UPDATE events SET gcal_event_id = ? WHERE id = ?",
            (gcal_id, event_id),
        )

    return {"event_id": event_id, "gcal_event_id": gcal_id, "synced": True}


def connect_calendar() -> dict:
    """Devuelve la URL OAuth para que el usuario autorice."""
    return {"auth_url": gcal_sync.oauth_start_url()}


def mark_event_done(event_id: int) -> dict:
    """Marca un evento como hecho con XP.

    Eventos puntuales -> done=1 + outcome + xp.
    Eventos recurrentes -> inserta routine_completions con status + xp.
    """
    import sqlite3
    import date_utils

    today = date_utils.today_madrid()

    with db.connect() as conn:
        row = conn.execute(
            "SELECT recurring_rule, datetime FROM events WHERE id = ?", (event_id,)
        ).fetchone()
        if row is None:
            return {"id": event_id, "updated": 0, "error": "not_found"}

        level_before = compute_level(_get_xp_total_with_conn(conn))

        if row["recurring_rule"]:
            rule = row["recurring_rule"]
            most_recent_expected = _most_recent_expected_date(rule, today)
            previous_expected = _previous_expected_date(rule, today)

            target_date = None
            status = None
            if most_recent_expected == today:
                target_date = today
                status = "on_time"
            elif (
                previous_expected is not None
                and (today - previous_expected).days == 1
            ):
                target_date = previous_expected
                status = "grace"
            else:
                return {"id": event_id, "updated": 0, "error": "out_of_window"}

            target_iso = target_date.isoformat()
            try:
                conn.execute(
                    """
                    INSERT INTO routine_completions (event_id, completion_date, created_at, status)
                    VALUES (?, ?, ?, ?)
                    """,
                    (event_id, target_iso, date_utils.now_iso(), status),
                )
            except sqlite3.IntegrityError:
                return {
                    "event_id": event_id,
                    "completion_date": target_iso,
                    "already_done": True,
                    "updated": 0,
                }

            # Calcular racha tras insertar (incluye la actual)
            streak_after = _current_streak(event_id, rule, today, conn)
            xp_amount, streak_bonus = _calculate_xp(
                "routine", status, streak_after=streak_after
            )
            _insert_xp_log(
                conn, "routine", event_id, status,
                xp_amount=xp_amount, streak_bonus=streak_bonus,
            )
            level_after = compute_level(_get_xp_total_with_conn(conn))

            return {
                "event_id": event_id,
                "completion_date": target_iso,
                "status": status,
                "updated": 1,
                "xp_awarded": xp_amount,
                "streak_bonus": streak_bonus,
                "level_before": level_before,
                "level_after": level_after,
            }

        # Evento puntual
        try:
            assigned = date.fromisoformat(row["datetime"][:10])
        except ValueError:
            return {"id": event_id, "updated": 0, "error": "bad_datetime"}

        outcome = _calculate_outcome(assigned, today)
        if outcome is None:
            return {"id": event_id, "updated": 0, "error": "out_of_window"}

        cur = conn.execute(
            "UPDATE events SET done = 1, outcome = ? WHERE id = ?",
            (outcome, event_id),
        )

        xp_amount, _ = _calculate_xp("event", outcome)
        _insert_xp_log(conn, "event", event_id, outcome, xp_amount)
        level_after = compute_level(_get_xp_total_with_conn(conn))

        return {
            "id": event_id,
            "updated": cur.rowcount,
            "outcome": outcome,
            "xp_awarded": xp_amount,
            "level_before": level_before,
            "level_after": level_after,
        }


def unmark_event_done(event_id: int) -> dict:
    """Quita el done=1 + outcome=NULL de un evento puntual. Revierte XP."""
    with db.connect() as conn:
        cur = conn.execute(
            "UPDATE events SET done = 0, outcome = NULL WHERE id = ?",
            (event_id,),
        )
        original = conn.execute(
            "SELECT xp_amount FROM xp_log "
            "WHERE item_type = 'event' AND item_id = ? AND outcome != 'reversal' "
            "ORDER BY id DESC LIMIT 1",
            (event_id,),
        ).fetchone()
        if original and original["xp_amount"] > 0:
            _insert_xp_log(
                conn, "event", event_id, "reversal",
                xp_amount=-original["xp_amount"], streak_bonus=0,
            )
    return {"id": event_id, "updated": cur.rowcount}


def uncomplete_routine_today(event_id: int) -> dict:
    """Borra la completion de hoy (Madrid) para una rutina y revierte XP."""
    import date_utils
    today = date_utils.today_madrid().isoformat()
    with db.connect() as conn:
        cur = conn.execute(
            "DELETE FROM routine_completions "
            "WHERE event_id = ? AND completion_date = ?",
            (event_id, today),
        )
        if cur.rowcount > 0:
            # Revertir el XP de la última fila xp_log de esta rutina
            original = conn.execute(
                "SELECT xp_amount FROM xp_log "
                "WHERE item_type = 'routine' AND item_id = ? "
                "AND outcome != 'reversal' "
                "ORDER BY id DESC LIMIT 1",
                (event_id,),
            ).fetchone()
            if original and original["xp_amount"] > 0:
                _insert_xp_log(
                    conn, "routine", event_id, "reversal",
                    xp_amount=-original["xp_amount"], streak_bonus=0,
                )
    return {"event_id": event_id, "completion_date": today, "deleted": cur.rowcount}


def recreate_event(event_id: int) -> dict:
    """Crea evento nuevo con la misma hora pero fecha de hoy.
    Marca el original como outcome='missed'. NO copia gcal_event_id."""
    import date_utils

    today = date_utils.today_madrid()
    with db.connect() as conn:
        orig = conn.execute(
            "SELECT title, datetime, category, recurring_rule, notes "
            "FROM events WHERE id = ?",
            (event_id,),
        ).fetchone()
        if orig is None:
            return {"error": "not_found"}

        time_part = orig["datetime"][11:] if "T" in orig["datetime"] else "09:00:00"
        new_dt = f"{today.isoformat()}T{time_part}"

        cur = conn.execute(
            """
            INSERT INTO events (title, datetime, category, recurring_rule, notes, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (orig["title"], new_dt, orig["category"], orig["recurring_rule"],
             orig["notes"], date_utils.now_iso()),
        )
        new_id = cur.lastrowid

        conn.execute(
            "UPDATE events SET outcome = 'missed' WHERE id = ?", (event_id,)
        )

    return {"old_id": event_id, "new_id": new_id, "new_datetime": new_dt}


def recreate_task(task_id: int) -> dict:
    """Crea tarea nueva con due_date=hoy. Marca la original como missed."""
    import date_utils

    today = date_utils.today_madrid()
    with db.connect() as conn:
        orig = conn.execute(
            "SELECT text FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if orig is None:
            return {"error": "not_found"}

        cur = conn.execute(
            "INSERT INTO tasks (text, done, created_at, due_date) VALUES (?, 0, ?, ?)",
            (orig["text"], date_utils.now_iso(), today.isoformat()),
        )
        new_id = cur.lastrowid

        conn.execute(
            "UPDATE tasks SET outcome = 'missed' WHERE id = ?", (task_id,)
        )

    return {"old_id": task_id, "new_id": new_id, "due_date": today.isoformat()}


def recreate_objective(objective_id: int) -> dict:
    """Crea objetivo nuevo en la semana actual. Marca el original como missed."""
    from date_utils import monday_of_week
    import date_utils

    today = date_utils.today_madrid()
    week_start = monday_of_week(today).isoformat()
    with db.connect() as conn:
        orig = conn.execute(
            "SELECT text FROM objectives WHERE id = ?", (objective_id,)
        ).fetchone()
        if orig is None:
            return {"error": "not_found"}

        cur = conn.execute(
            "INSERT INTO objectives (text, week_start, done, created_at) VALUES (?, ?, 0, ?)",
            (orig["text"], week_start, date_utils.now_iso()),
        )
        new_id = cur.lastrowid

        conn.execute(
            "UPDATE objectives SET outcome = 'missed' WHERE id = ?", (objective_id,)
        )

    return {"old_id": objective_id, "new_id": new_id, "week_start": week_start}


def discard_event(event_id: int) -> dict:
    """Marca un evento como outcome='missed' sin tocar done."""
    with db.connect() as conn:
        cur = conn.execute(
            "UPDATE events SET outcome = 'missed' WHERE id = ?", (event_id,)
        )
    return {"id": event_id, "updated": cur.rowcount}


def discard_task(task_id: int) -> dict:
    """Marca una tarea como outcome='missed' sin tocar done."""
    with db.connect() as conn:
        cur = conn.execute(
            "UPDATE tasks SET outcome = 'missed' WHERE id = ?", (task_id,)
        )
    return {"id": task_id, "updated": cur.rowcount}


def discard_objective(objective_id: int) -> dict:
    """Marca un objetivo como outcome='missed' sin tocar done."""
    with db.connect() as conn:
        cur = conn.execute(
            "UPDATE objectives SET outcome = 'missed' WHERE id = ?", (objective_id,)
        )
    return {"id": objective_id, "updated": cur.rowcount}


def _completion_dates(event_id: int, conn) -> list:
    """Devuelve las fechas de completion como objetos date, ordenadas asc."""
    rows = conn.execute(
        "SELECT completion_date FROM routine_completions WHERE event_id = ? ORDER BY completion_date ASC",
        (event_id,),
    ).fetchall()
    return [date.fromisoformat(r["completion_date"]) for r in rows]


def _previous_expected_date(rule: str, ref: date) -> Optional[date]:
    """Última fecha esperada estrictamente anterior a ref para la regla dada."""
    if rule == "DAILY":
        return ref - timedelta(days=1)
    if rule.startswith("WEEKLY:"):
        code = rule.split(":", 1)[1]
        if code not in _WEEKDAY_MAP:
            return None
        target = _WEEKDAY_MAP[code]
        d = ref - timedelta(days=1)
        while d.weekday() != target:
            d -= timedelta(days=1)
        return d
    return None


def _most_recent_expected_date(rule: str, today: date) -> Optional[date]:
    """Fecha esperada más reciente <= today.

    Para DAILY siempre es today. Para WEEKLY:X es today si today.weekday()==X,
    si no el último weekday X anterior.
    """
    if rule == "DAILY":
        return today
    if rule.startswith("WEEKLY:"):
        code = rule.split(":", 1)[1]
        if code not in _WEEKDAY_MAP:
            return None
        target = _WEEKDAY_MAP[code]
        d = today
        while d.weekday() != target:
            d -= timedelta(days=1)
        return d
    return None


def _current_streak(event_id: int, rule: str, today: date, conn) -> int:
    """Racha actual hacia atrás desde la fecha esperada más reciente.

    Si hoy es esperada y aún no está hecha, la racha sigue viva contando
    desde la fecha esperada anterior.
    """
    completions = set(_completion_dates(event_id, conn))
    if not completions:
        return 0

    most_recent = _most_recent_expected_date(rule, today)
    if most_recent is None:
        return 0

    if most_recent == today and today not in completions:
        cursor = _previous_expected_date(rule, today)
    else:
        cursor = most_recent

    streak = 0
    while cursor is not None and cursor in completions:
        streak += 1
        cursor = _previous_expected_date(rule, cursor)
    return streak


def _best_streak(event_id: int, rule: str, conn) -> int:
    """Racha máxima histórica para la rutina, sin huecos en el patrón esperado."""
    completions = _completion_dates(event_id, conn)
    if not completions:
        return 0

    best = 1
    current = 1
    for i in range(1, len(completions)):
        expected_prev = _previous_expected_date(rule, completions[i])
        if expected_prev is not None and expected_prev == completions[i - 1]:
            current += 1
            best = max(best, current)
        else:
            current = 1
    return best


def routine_summary(date_from: str, date_to: str) -> list[dict]:
    """Resumen agregado de rutinas (eventos recurrentes) para un rango de fechas.

    Devuelve una fila por rutina con cuántos días tocaba (scheduled_days),
    cuántos se completaron (completed_days) y los streaks actual/mejor.

    Formato fechas: 'YYYY-MM-DD'. El rango es inclusivo por ambos extremos.
    Los streaks son GLOBALES (no dependen del rango).
    """
    import date_utils

    start = date.fromisoformat(date_from)
    end = date.fromisoformat(date_to)
    if end < start:
        return []

    today = date_utils.today_madrid()
    results: list[dict] = []
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM events WHERE recurring_rule IS NOT NULL"
        ).fetchall()

        for row in rows:
            rule = row["recurring_rule"]
            scheduled = _count_scheduled_days(rule, row["datetime"], start, end)
            if scheduled == 0:
                continue
            counts = conn.execute(
                """
                SELECT
                    SUM(CASE WHEN status = 'on_time' THEN 1 ELSE 0 END) as on_time_count,
                    SUM(CASE WHEN status = 'grace'   THEN 1 ELSE 0 END) as grace_count,
                    COUNT(*) as completed_days
                FROM routine_completions
                WHERE event_id = ?
                  AND completion_date >= ?
                  AND completion_date <= ?
                """,
                (row["id"], date_from, date_to),
            ).fetchone()
            on_time_count = counts["on_time_count"] or 0
            grace_count = counts["grace_count"] or 0
            completed = counts["completed_days"] or 0
            current = _current_streak(row["id"], rule, today, conn)
            best = _best_streak(row["id"], rule, conn)
            results.append({
                "event_id": row["id"],
                "title": row["title"],
                "category": row["category"],
                "recurring_rule": rule,
                "scheduled_days": scheduled,
                "completed_days": completed,
                "on_time_count": on_time_count,
                "grace_count": grace_count,
                "current_streak": current,
                "best_streak": best,
            })
    return results


def _count_scheduled_days(rule: str, base_datetime_iso: str, start: date, end: date) -> int:
    """Cuántas instancias programadas tiene una rutina en [start, end].

    Solo cuenta desde la fecha de inicio (`datetime` base) de la rutina:
    si la rutina empezó después de `start`, recortamos el inicio.
    """
    try:
        base_date = date.fromisoformat(base_datetime_iso[:10])
    except (ValueError, TypeError):
        base_date = start
    effective_start = max(start, base_date)
    if effective_start > end:
        return 0
    if rule == "DAILY":
        return (end - effective_start).days + 1
    if rule.startswith("WEEKLY:"):
        weekday_code = rule.split(":", 1)[1]
        if weekday_code not in _WEEKDAY_MAP:
            return 0
        target = _WEEKDAY_MAP[weekday_code]
        count = 0
        cur = effective_start
        while cur <= end:
            if cur.weekday() == target:
                count += 1
            cur += timedelta(days=1)
        return count
    return 0


# ------------------------------------------------------------ objectives ----

def add_objective(text: str, week_start: str) -> dict:
    from date_utils import monday_of_week
    parsed = date.fromisoformat(week_start)
    normalized = monday_of_week(parsed).isoformat()
    with db.connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO objectives (text, week_start, done, created_at)
            VALUES (?, ?, 0, ?)
            """,
            (text, normalized, now_iso()),
        )
        new_id = cur.lastrowid
    return {"id": new_id, "text": text, "week_start": normalized}


def query_objectives(week_start: Optional[str]) -> list[dict]:
    with db.connect() as conn:
        if week_start:
            from date_utils import monday_of_week
            normalized = monday_of_week(date.fromisoformat(week_start)).isoformat()
            rows = conn.execute(
                "SELECT * FROM objectives WHERE week_start = ? ORDER BY id",
                (normalized,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM objectives ORDER BY week_start DESC, id"
            ).fetchall()
    return [dict(r) for r in rows]


def mark_objective_done(objective_id: int) -> dict:
    from date_utils import monday_of_week
    import date_utils

    today = date_utils.today_madrid()
    today_monday = monday_of_week(today)

    with db.connect() as conn:
        row = conn.execute(
            "SELECT week_start FROM objectives WHERE id = ?", (objective_id,)
        ).fetchone()
        if row is None:
            return {"id": objective_id, "updated": 0, "error": "not_found"}

        week_start = date.fromisoformat(row["week_start"])
        weeks_diff = (today_monday - week_start).days // 7

        if weeks_diff <= 0:
            outcome = "on_time"
        elif weeks_diff == 1:
            outcome = "grace"
        else:
            return {"id": objective_id, "updated": 0, "error": "out_of_window"}

        cur = conn.execute(
            "UPDATE objectives SET done = 1, outcome = ? WHERE id = ?",
            (outcome, objective_id),
        )
    return {"id": objective_id, "updated": cur.rowcount, "outcome": outcome}


def unmark_objective_done(objective_id: int) -> dict:
    """Desmarca un objetivo: done=0. Uso interno (callback de /semana)."""
    with db.connect() as conn:
        cur = conn.execute(
            "UPDATE objectives SET done = 0 WHERE id = ?", (objective_id,)
        )
    return {"id": objective_id, "updated": cur.rowcount}


# ----------------------------------------------------------------- tasks ----

def add_task(text: str, due_date: Optional[str] = None) -> dict:
    with db.connect() as conn:
        cur = conn.execute(
            "INSERT INTO tasks (text, done, created_at, due_date) VALUES (?, 0, ?, ?)",
            (text, now_iso(), due_date),
        )
        new_id = cur.lastrowid
    return {"id": new_id, "text": text, "due_date": due_date}


def list_tasks(include_done: bool = False) -> list[dict]:
    with db.connect() as conn:
        if include_done:
            rows = conn.execute(
                "SELECT * FROM tasks ORDER BY done, id"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE done = 0 "
                "AND (outcome IS NULL OR outcome != 'missed') "
                "ORDER BY id"
            ).fetchall()
    return [dict(r) for r in rows]


def complete_task(task_id: int) -> dict:
    import date_utils

    today = date_utils.today_madrid()
    with db.connect() as conn:
        row = conn.execute(
            "SELECT due_date FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if row is None:
            return {"id": task_id, "updated": 0, "error": "not_found"}

        assigned = None
        if row["due_date"]:
            assigned = date.fromisoformat(row["due_date"])
            outcome = _calculate_outcome(assigned, today)
            if outcome is None:
                return {"id": task_id, "updated": 0, "error": "out_of_window"}
        else:
            outcome = None

        cur = conn.execute(
            "UPDATE tasks SET done = 1, done_at = ?, outcome = ? WHERE id = ?",
            (now_iso(), outcome, task_id),
        )

        # XP: solo si hay outcome (tareas flotantes no entran al juego)
        xp_awarded = 0
        level_before = compute_level(_get_xp_total_with_conn(conn))
        if outcome in ("on_time", "grace"):
            xp_awarded, _ = _calculate_xp("task", outcome)
            _insert_xp_log(conn, "task", task_id, outcome, xp_awarded)
        level_after = compute_level(_get_xp_total_with_conn(conn))

    return {
        "id": task_id,
        "updated": cur.rowcount,
        "outcome": outcome,
        "xp_awarded": xp_awarded,
        "level_before": level_before,
        "level_after": level_after,
    }


def uncomplete_task(task_id: int) -> dict:
    """Desmarca una tarea: done=0, done_at=NULL, outcome=NULL.
    Inserta una reversión en xp_log si había una ganancia previa."""
    with db.connect() as conn:
        cur = conn.execute(
            "UPDATE tasks SET done = 0, done_at = NULL, outcome = NULL "
            "WHERE id = ?",
            (task_id,),
        )
        # Buscar última fila xp_log para esta tarea no reversada
        original = conn.execute(
            "SELECT xp_amount FROM xp_log "
            "WHERE item_type = 'task' AND item_id = ? AND outcome != 'reversal' "
            "ORDER BY id DESC LIMIT 1",
            (task_id,),
        ).fetchone()
        if original and original["xp_amount"] > 0:
            _insert_xp_log(
                conn, "task", task_id, "reversal",
                xp_amount=-original["xp_amount"], streak_bonus=0,
            )
    return {"id": task_id, "updated": cur.rowcount}


def metrics_summary(date_from: str, date_to: str) -> dict:
    """Conteos agregados por outcome para el rango [date_from, date_to] inclusive."""
    start = date.fromisoformat(date_from)
    end = date.fromisoformat(date_to)

    def _count_outcomes(rows: list) -> dict:
        return {
            "on_time": sum(1 for r in rows if r["outcome"] == "on_time"),
            "grace":   sum(1 for r in rows if r["outcome"] == "grace"),
            "missed":  sum(1 for r in rows if r["outcome"] == "missed"),
        }

    with db.connect() as conn:
        ev_rows = conn.execute(
            """
            SELECT outcome FROM events
            WHERE recurring_rule IS NULL
              AND outcome IS NOT NULL
              AND substr(datetime, 1, 10) >= ?
              AND substr(datetime, 1, 10) <= ?
            """,
            (date_from, date_to),
        ).fetchall()
        task_rows = conn.execute(
            """
            SELECT outcome FROM tasks
            WHERE due_date IS NOT NULL
              AND outcome IS NOT NULL
              AND due_date >= ?
              AND due_date <= ?
            """,
            (date_from, date_to),
        ).fetchall()
        obj_rows = conn.execute(
            """
            SELECT outcome FROM objectives
            WHERE outcome IS NOT NULL
              AND week_start >= ?
              AND week_start <= ?
            """,
            (date_from, date_to),
        ).fetchall()

    routine_rows = routine_summary(date_from, date_to)

    per_event = []
    routine_totals = {"on_time": 0, "grace": 0, "missed": 0}
    for r in routine_rows:
        on_t = r["on_time_count"]
        gr = r["grace_count"]
        missed = max(0, r["scheduled_days"] - on_t - gr)
        per_event.append({
            "event_id": r["event_id"],
            "title": r["title"],
            "on_time": on_t,
            "grace": gr,
            "missed": missed,
        })
        routine_totals["on_time"] += on_t
        routine_totals["grace"] += gr
        routine_totals["missed"] += missed

    return {
        "events": _count_outcomes(ev_rows),
        "tasks": _count_outcomes(task_rows),
        "objectives": _count_outcomes(obj_rows),
        "routines": {"per_event": per_event, "totals": routine_totals},
    }


# -------------------------------------------------------------- registry ----

TOOL_DEFINITIONS: list[dict] = [
    {
        "name": "add_event",
        "description": (
            "Añade un evento o cita al calendario. Para rutinas recurrentes, "
            "usar recurring_rule con formato 'DAILY' o 'WEEKLY:MON|TUE|WED|THU|FRI|SAT|SUN'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "datetime_iso": {
                    "type": "string",
                    "description": "Fecha y hora ISO 8601 sin zona, ej. 2026-05-22T17:00:00",
                },
                "category": {
                    "type": "string",
                    "enum": list(CATEGORIES),
                },
                "recurring_rule": {"type": ["string", "null"]},
                "notes": {"type": ["string", "null"]},
                "sync_to_calendar": {
                    "type": "boolean",
                    "default": False,
                    "description": (
                        "Si es true, además de añadir el evento al bot, lo manda a "
                        "Google Calendar. Úsala SOLO cuando el usuario lo pida "
                        "explícitamente ('mételo en el calendario' y similares)."
                    ),
                },
            },
            "required": ["title", "datetime_iso", "category"],
        },
    },
    {
        "name": "query_events",
        "description": (
            "Lista eventos entre dos fechas. Expande recurrentes. "
            "Por defecto solo devuelve eventos pendientes (done=0). "
            "Para incluir también los marcados como hechos, usa include_done=true."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date_from": {"type": "string", "description": "ISO 8601, ej. 2026-05-15T00:00:00"},
                "date_to": {"type": "string"},
                "category": {"type": ["string", "null"]},
                "include_done": {
                    "type": "boolean",
                    "default": False,
                    "description": "Si es true, incluye también eventos con done=1.",
                },
                "include_grace": {
                    "type": "boolean",
                    "default": False,
                    "description": "Si es true, también devuelve eventos puntuales del día anterior con done=0 (día de gracia).",
                },
            },
            "required": ["date_from", "date_to"],
        },
    },
    {
        "name": "update_event",
        "description": "Modifica campos de un evento existente.",
        "input_schema": {
            "type": "object",
            "properties": {
                "event_id": {"type": "integer"},
                "fields": {"type": "object"},
            },
            "required": ["event_id", "fields"],
        },
    },
    {
        "name": "delete_event",
        "description": "Borra un evento por su id. Confirmar con el usuario antes.",
        "input_schema": {
            "type": "object",
            "properties": {"event_id": {"type": "integer"}},
            "required": ["event_id"],
        },
    },
    {
        "name": "mark_event_done",
        "description": (
            "Marca un evento como hecho/pasado. Úsala cuando el usuario diga "
            "'ya pasó X', 'ya he ido al Y', 'ya hice la reunión Z'. Los eventos "
            "marcados como hechos no salen en query_events por defecto."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"event_id": {"type": "integer"}},
            "required": ["event_id"],
        },
    },
    {
        "name": "routine_summary",
        "description": (
            "Resumen agregado de rutinas (eventos recurrentes) para un rango de "
            "fechas. Devuelve por cada rutina cuántos días tocaba (scheduled_days) "
            "y cuántos se completaron (completed_days). Útil para /semana."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date_from": {"type": "string", "description": "ISO date YYYY-MM-DD"},
                "date_to": {"type": "string", "description": "ISO date YYYY-MM-DD"},
            },
            "required": ["date_from", "date_to"],
        },
    },
    {
        "name": "add_objective",
        "description": (
            "Añade un objetivo semanal. week_start puede ser cualquier fecha de la semana; "
            "se normaliza al lunes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "week_start": {"type": "string", "description": "ISO date YYYY-MM-DD"},
            },
            "required": ["text", "week_start"],
        },
    },
    {
        "name": "query_objectives",
        "description": "Lista objetivos. Si week_start es null, devuelve todos.",
        "input_schema": {
            "type": "object",
            "properties": {
                "week_start": {"type": ["string", "null"]},
            },
            "required": ["week_start"],
        },
    },
    {
        "name": "mark_objective_done",
        "description": "Marca un objetivo como completado.",
        "input_schema": {
            "type": "object",
            "properties": {"objective_id": {"type": "integer"}},
            "required": ["objective_id"],
        },
    },
    {
        "name": "add_task",
        "description": (
            "Añade una tarea. due_date es opcional ('YYYY-MM-DD'); úsala SOLO si "
            "el usuario indica un día concreto. Si no la indica, no inventes fecha."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "due_date": {
                    "type": ["string", "null"],
                    "description": "Fecha objetivo en formato YYYY-MM-DD. NULL si no la hay.",
                },
            },
            "required": ["text"],
        },
    },
    {
        "name": "list_tasks",
        "description": "Lista tareas. Por defecto solo pendientes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "include_done": {"type": "boolean", "default": False},
            },
        },
    },
    {
        "name": "complete_task",
        "description": "Marca una tarea como hecha.",
        "input_schema": {
            "type": "object",
            "properties": {"task_id": {"type": "integer"}},
            "required": ["task_id"],
        },
    },
    {
        "name": "push_event_to_calendar",
        "description": (
            "Sincroniza un evento existente con Google Calendar. Úsala cuando "
            "Pablo diga 'mételo en el calendario', 'pásalo a Google Calendar', "
            "'manda al calendario' o variantes, o justo después de add_event si "
            "el mismo mensaje pedía sincronizar. Si devuelve error 'not_connected', "
            "avisa al usuario de que ejecute 'conecta con calendar'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"event_id": {"type": "integer"}},
            "required": ["event_id"],
        },
    },
    {
        "name": "connect_calendar",
        "description": (
            "Devuelve la URL de autorización OAuth para conectar el bot con "
            "Google Calendar. Úsala cuando Pablo diga 'conecta con calendar', "
            "'autoriza Google Calendar', o cuando push_event_to_calendar haya "
            "devuelto error 'not_connected'."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "metrics_summary",
        "description": (
            "Conteos agregados por outcome (on_time/grace/missed) para rutinas, "
            "eventos puntuales, tareas y objetivos en un rango de fechas. Útil "
            "cuando el usuario pregunta por sus métricas o porcentajes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date_from": {"type": "string", "description": "ISO date YYYY-MM-DD"},
                "date_to":   {"type": "string", "description": "ISO date YYYY-MM-DD"},
            },
            "required": ["date_from", "date_to"],
        },
    },
]


_DISPATCH = {
    "add_event": add_event,
    "query_events": query_events,
    "update_event": update_event,
    "delete_event": delete_event,
    "mark_event_done": mark_event_done,
    "routine_summary": routine_summary,
    "add_objective": add_objective,
    "query_objectives": query_objectives,
    "mark_objective_done": mark_objective_done,
    "add_task": add_task,
    "list_tasks": list_tasks,
    "complete_task": complete_task,
    "push_event_to_calendar": push_event_to_calendar,
    "connect_calendar": connect_calendar,
    "metrics_summary": metrics_summary,
}


def dispatch(name: str, arguments: dict):
    if name not in _DISPATCH:
        raise ValueError(f"herramienta desconocida: {name}")
    return _DISPATCH[name](**arguments)

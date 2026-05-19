"""Herramientas que Claude puede invocar. Operan sobre SQLite."""
from datetime import date, datetime, timedelta
from typing import Optional

import db
from config import CATEGORIES
from date_utils import now_iso

_WEEKDAY_MAP = {
    "MON": 0, "TUE": 1, "WED": 2, "THU": 3,
    "FRI": 4, "SAT": 5, "SUN": 6,
}


# ---------------------------------------------------------------- events ----

def add_event(
    title: str,
    datetime_iso: str,
    category: str,
    recurring_rule: Optional[str] = None,
    notes: Optional[str] = None,
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
    return {"id": new_id, "title": title, "datetime": datetime_iso}


def query_events(
    date_from: str,
    date_to: str,
    category: Optional[str] = None,
    include_done: bool = False,
) -> list[dict]:
    dt_from = datetime.fromisoformat(date_from)
    dt_to = datetime.fromisoformat(date_to)

    with db.connect() as conn:
        params: list = []
        sql = "SELECT * FROM events WHERE 1=1"
        if not include_done:
            sql += " AND COALESCE(done, 0) = 0"
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
        return {"id": event_id, "updated": cur.rowcount}


def delete_event(event_id: int) -> dict:
    with db.connect() as conn:
        cur = conn.execute("DELETE FROM events WHERE id = ?", (event_id,))
    return {"id": event_id, "deleted": cur.rowcount}


def mark_event_done(event_id: int) -> dict:
    """Marca un evento como hecho.

    Eventos puntuales -> done=1 (permanente).
    Eventos recurrentes (rutinas) -> inserta fila en routine_completions
    con la fecha de hoy en Madrid (no toca done).
    """
    import sqlite3

    import date_utils

    with db.connect() as conn:
        row = conn.execute(
            "SELECT recurring_rule FROM events WHERE id = ?", (event_id,)
        ).fetchone()
        if row is None:
            return {"id": event_id, "updated": 0}

        if row["recurring_rule"]:
            today = date_utils.today_madrid().isoformat()
            try:
                conn.execute(
                    """
                    INSERT INTO routine_completions (event_id, completion_date, created_at)
                    VALUES (?, ?, ?)
                    """,
                    (event_id, today, date_utils.now_iso()),
                )
                return {
                    "event_id": event_id,
                    "completion_date": today,
                    "updated": 1,
                }
            except sqlite3.IntegrityError:
                return {
                    "event_id": event_id,
                    "completion_date": today,
                    "already_done_today": True,
                    "updated": 0,
                }

        cur = conn.execute(
            "UPDATE events SET done = 1 WHERE id = ?", (event_id,)
        )
        return {"id": event_id, "updated": cur.rowcount}


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

    Devuelve una fila por rutina con cuántos días tocaba (scheduled_days)
    y cuántos se completaron (completed_days) dentro del rango inclusivo.

    Formato fechas: 'YYYY-MM-DD'.
    """
    start = date.fromisoformat(date_from)
    end = date.fromisoformat(date_to)
    if end < start:
        return []

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
            completed = conn.execute(
                """
                SELECT COUNT(*) FROM routine_completions
                WHERE event_id = ?
                  AND completion_date >= ?
                  AND completion_date <= ?
                """,
                (row["id"], date_from, date_to),
            ).fetchone()[0]
            results.append({
                "event_id": row["id"],
                "title": row["title"],
                "category": row["category"],
                "recurring_rule": rule,
                "scheduled_days": scheduled,
                "completed_days": completed,
            })
    return results


def _count_scheduled_days(rule: str, base_datetime_iso: str, start: date, end: date) -> int:
    """Cuántas instancias programadas tiene una rutina en [start, end]."""
    if rule == "DAILY":
        return (end - start).days + 1
    if rule.startswith("WEEKLY:"):
        weekday_code = rule.split(":", 1)[1]
        if weekday_code not in _WEEKDAY_MAP:
            return 0
        target = _WEEKDAY_MAP[weekday_code]
        count = 0
        cur = start
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
    with db.connect() as conn:
        cur = conn.execute(
            "UPDATE objectives SET done = 1 WHERE id = ?", (objective_id,)
        )
    return {"id": objective_id, "updated": cur.rowcount}


# ----------------------------------------------------------------- tasks ----

def add_task(text: str) -> dict:
    with db.connect() as conn:
        cur = conn.execute(
            "INSERT INTO tasks (text, done, created_at) VALUES (?, 0, ?)",
            (text, now_iso()),
        )
        new_id = cur.lastrowid
    return {"id": new_id, "text": text}


def list_tasks(include_done: bool = False) -> list[dict]:
    with db.connect() as conn:
        if include_done:
            rows = conn.execute(
                "SELECT * FROM tasks ORDER BY done, id"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE done = 0 ORDER BY id"
            ).fetchall()
    return [dict(r) for r in rows]


def complete_task(task_id: int) -> dict:
    with db.connect() as conn:
        cur = conn.execute(
            "UPDATE tasks SET done = 1, done_at = ? WHERE id = ?",
            (now_iso(), task_id),
        )
    return {"id": task_id, "updated": cur.rowcount}


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
        "description": "Añade una tarea suelta sin fecha.",
        "input_schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
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
}


def dispatch(name: str, arguments: dict):
    if name not in _DISPATCH:
        raise ValueError(f"herramienta desconocida: {name}")
    return _DISPATCH[name](**arguments)

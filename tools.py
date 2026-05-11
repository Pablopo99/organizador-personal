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
) -> list[dict]:
    dt_from = datetime.fromisoformat(date_from)
    dt_to = datetime.fromisoformat(date_to)

    with db.connect() as conn:
        params: list = []
        sql = "SELECT * FROM events WHERE 1=1"
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
            occurrences.extend(_expand_recurring(row, rule, dt_from, dt_to))

    occurrences.sort(key=lambda r: r["datetime"])
    return occurrences


def _expand_recurring(row: dict, rule: str, dt_from: datetime, dt_to: datetime) -> list[dict]:
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
            "UPDATE tasks SET done = 1 WHERE id = ?", (task_id,)
        )
    return {"id": task_id, "updated": cur.rowcount}

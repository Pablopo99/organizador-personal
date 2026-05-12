"""Acceso a SQLite: esquema y conexiones."""
import sqlite3
from contextlib import contextmanager
from typing import Iterator

from config import DB_PATH

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    title             TEXT NOT NULL,
    datetime          TEXT NOT NULL,
    category          TEXT NOT NULL DEFAULT 'other',
    recurring_rule    TEXT,
    notes             TEXT,
    created_at        TEXT NOT NULL,
    done              INTEGER NOT NULL DEFAULT 0,
    reminder_1d_sent  INTEGER NOT NULL DEFAULT 0,
    reminder_1h_sent  INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_events_datetime ON events(datetime);

CREATE TABLE IF NOT EXISTS objectives (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    text        TEXT NOT NULL,
    week_start  TEXT NOT NULL,
    done        INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_objectives_week ON objectives(week_start);

CREATE TABLE IF NOT EXISTS tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    text        TEXT NOT NULL,
    done        INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    done_at     TEXT
);
"""


def init_schema() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(_SCHEMA)
        _migrate(conn)


def _migrate(conn: sqlite3.Connection) -> None:
    """Migraciones idempotentes para tablas ya creadas en versiones anteriores."""
    events_cols = [row[1] for row in conn.execute("PRAGMA table_info(events)").fetchall()]
    if "done" not in events_cols:
        conn.execute("ALTER TABLE events ADD COLUMN done INTEGER NOT NULL DEFAULT 0")
    if "reminder_1d_sent" not in events_cols:
        conn.execute("ALTER TABLE events ADD COLUMN reminder_1d_sent INTEGER NOT NULL DEFAULT 0")
    if "reminder_1h_sent" not in events_cols:
        conn.execute("ALTER TABLE events ADD COLUMN reminder_1h_sent INTEGER NOT NULL DEFAULT 0")

    tasks_cols = [row[1] for row in conn.execute("PRAGMA table_info(tasks)").fetchall()]
    if "done_at" not in tasks_cols:
        conn.execute("ALTER TABLE tasks ADD COLUMN done_at TEXT")


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

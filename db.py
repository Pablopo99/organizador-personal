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

CREATE TABLE IF NOT EXISTS routine_completions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id         INTEGER NOT NULL,
    completion_date  TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    UNIQUE(event_id, completion_date),
    FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_routine_completions_date
    ON routine_completions(completion_date);

CREATE TABLE IF NOT EXISTS oauth_tokens (
    provider      TEXT PRIMARY KEY,
    access_token  TEXT NOT NULL,
    refresh_token TEXT NOT NULL,
    expires_at    TEXT NOT NULL,
    created_at    TEXT NOT NULL
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


    if "gcal_event_id" not in events_cols:
        conn.execute("ALTER TABLE events ADD COLUMN gcal_event_id TEXT")

    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()]
    if "routine_completions" not in tables:
        conn.execute("""
            CREATE TABLE routine_completions (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id         INTEGER NOT NULL,
                completion_date  TEXT NOT NULL,
                created_at       TEXT NOT NULL,
                UNIQUE(event_id, completion_date),
                FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_routine_completions_date
                ON routine_completions(completion_date)
        """)


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

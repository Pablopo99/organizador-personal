"""Acceso a SQLite: esquema y conexiones."""
import sqlite3
from contextlib import contextmanager
from typing import Iterator

from config import DB_PATH

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT NOT NULL,
    datetime        TEXT NOT NULL,
    category        TEXT NOT NULL DEFAULT 'other',
    recurring_rule  TEXT,
    notes           TEXT,
    created_at      TEXT NOT NULL
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
    created_at  TEXT NOT NULL
);
"""


def init_schema() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(_SCHEMA)


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

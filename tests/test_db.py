import os
import sqlite3
import tempfile

import pytest

import db


@pytest.fixture
def temp_db(monkeypatch):
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init_schema()
    yield path
    os.unlink(path)


def test_init_creates_tables(temp_db):
    with sqlite3.connect(temp_db) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
    names = [r[0] for r in rows]
    assert "events" in names
    assert "objectives" in names
    assert "tasks" in names


def test_init_is_idempotent(temp_db):
    db.init_schema()
    db.init_schema()
    with sqlite3.connect(temp_db) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
        ).fetchone()[0]
    assert count >= 3


def test_connection_context_manager_commits(temp_db):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO tasks (text, done, created_at) VALUES (?, 0, ?)",
            ("comprar pan", "2026-05-11T10:00:00"),
        )
    with sqlite3.connect(temp_db) as conn:
        row = conn.execute("SELECT text FROM tasks").fetchone()
    assert row[0] == "comprar pan"


def test_migration_adds_done_at_to_tasks_in_old_db(monkeypatch):
    """BD vieja sin done_at en tasks: init_schema la añade."""
    import os
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    monkeypatch.setattr(db, "DB_PATH", path)
    with sqlite3.connect(path) as conn:
        conn.execute("""
            CREATE TABLE tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                done INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
        """)
        conn.commit()

    db.init_schema()

    with sqlite3.connect(path) as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(tasks)").fetchall()]
    assert "done_at" in cols
    os.unlink(path)


def test_migration_adds_done_to_events_in_old_db(monkeypatch):
    """Si existe una BD vieja sin columna 'done' en events, init_schema la añade."""
    import os
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    monkeypatch.setattr(db, "DB_PATH", path)
    # Simulamos una BD vieja: creamos events sin 'done'
    with sqlite3.connect(path) as conn:
        conn.execute("""
            CREATE TABLE events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                datetime TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'other',
                recurring_rule TEXT,
                notes TEXT,
                created_at TEXT NOT NULL
            )
        """)
        conn.commit()

    db.init_schema()

    with sqlite3.connect(path) as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(events)").fetchall()]
    assert "done" in cols
    os.unlink(path)


def test_init_schema_is_idempotent_with_existing_done_column(temp_db):
    """Llamar init_schema dos veces no falla si la columna ya existe."""
    db.init_schema()  # ya se llamó una vez en el fixture
    db.init_schema()  # segunda llamada
    with sqlite3.connect(temp_db) as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(events)").fetchall()]
    assert cols.count("done") == 1

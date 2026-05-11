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

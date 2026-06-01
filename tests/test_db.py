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


def test_migration_adds_reminder_flags_to_events(monkeypatch):
    """BD vieja sin flags de recordatorio: init_schema los añade."""
    import os
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    monkeypatch.setattr(db, "DB_PATH", path)
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
    assert "reminder_1d_sent" in cols
    assert "reminder_1h_sent" in cols
    os.unlink(path)


def test_init_schema_is_idempotent_with_existing_done_column(temp_db):
    """Llamar init_schema dos veces no falla si la columna ya existe."""
    db.init_schema()  # ya se llamó una vez en el fixture
    db.init_schema()  # segunda llamada
    with sqlite3.connect(temp_db) as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(events)").fetchall()]
    assert cols.count("done") == 1


def test_migration_creates_routine_completions_table(monkeypatch):
    """BD vieja sin la tabla: init_schema la crea."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    monkeypatch.setattr(db, "DB_PATH", path)
    with sqlite3.connect(path) as conn:
        conn.execute("""
            CREATE TABLE events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                datetime TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'other',
                recurring_rule TEXT,
                notes TEXT,
                created_at TEXT NOT NULL,
                done INTEGER NOT NULL DEFAULT 0,
                reminder_1d_sent INTEGER NOT NULL DEFAULT 0,
                reminder_1h_sent INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.commit()

    db.init_schema()

    with sqlite3.connect(path) as conn:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
    assert "routine_completions" in tables
    os.unlink(path)


def test_connect_enables_foreign_keys(temp_db):
    """db.connect() debe activar PRAGMA foreign_keys=ON."""
    with db.connect() as conn:
        cur = conn.execute("PRAGMA foreign_keys")
        assert cur.fetchone()[0] == 1


def test_delete_event_cascades_to_routine_completions(temp_db):
    """Borrar un evento elimina sus filas de routine_completions."""
    with db.connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO events (title, datetime, category, created_at, recurring_rule)
            VALUES ('Flexiones', '2026-05-19T08:00:00', 'personal', '2026-05-19T08:00:00', 'DAILY')
            """
        )
        event_id = cur.lastrowid
        conn.execute(
            """
            INSERT INTO routine_completions (event_id, completion_date, created_at)
            VALUES (?, '2026-05-19', '2026-05-19T08:00:00')
            """,
            (event_id,),
        )

    with db.connect() as conn:
        conn.execute("DELETE FROM events WHERE id = ?", (event_id,))

    with db.connect() as conn:
        rows = conn.execute(
            "SELECT COUNT(*) FROM routine_completions WHERE event_id = ?",
            (event_id,),
        ).fetchone()
    assert rows[0] == 0


def test_routine_completions_unique_per_event_per_date(temp_db):
    """No se puede insertar dos filas con el mismo event_id y completion_date."""
    with db.connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO events (title, datetime, category, created_at, recurring_rule)
            VALUES ('Flexiones', '2026-05-19T08:00:00', 'personal', '2026-05-19T08:00:00', 'DAILY')
            """
        )
        event_id = cur.lastrowid
        conn.execute(
            "INSERT INTO routine_completions (event_id, completion_date, created_at) VALUES (?, '2026-05-19', '2026-05-19T08:00:00')",
            (event_id,),
        )

    with pytest.raises(sqlite3.IntegrityError):
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO routine_completions (event_id, completion_date, created_at) VALUES (?, '2026-05-19', '2026-05-19T08:30:00')",
                (event_id,),
            )

def test_init_schema_adds_gcal_event_id_column(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "x.db"))
    db.init_schema()
    with db.connect() as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(events)").fetchall()]
    assert "gcal_event_id" in cols


def test_init_schema_creates_oauth_tokens_table(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "x.db"))
    db.init_schema()
    with db.connect() as conn:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
    assert "oauth_tokens" in tables


def test_oauth_tokens_provider_is_primary_key(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "x.db"))
    db.init_schema()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO oauth_tokens (provider, access_token, refresh_token, expires_at, created_at)"
            " VALUES ('google', 'a', 'r', '2026-01-01T00:00:00', '2026-01-01T00:00:00')"
        )
        with pytest.raises(Exception):
            conn.execute(
                "INSERT INTO oauth_tokens (provider, access_token, refresh_token, expires_at, created_at)"
                " VALUES ('google', 'b', 'r2', '2026-01-01T00:00:00', '2026-01-01T00:00:00')"
            )


@pytest.fixture
def fresh_db(monkeypatch):
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init_schema()
    yield path
    os.unlink(path)


def test_events_has_outcome_column(fresh_db):
    with db.connect() as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(events)").fetchall()]
    assert "outcome" in cols


def test_tasks_has_due_date_and_outcome_columns(fresh_db):
    with db.connect() as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(tasks)").fetchall()]
    assert "due_date" in cols
    assert "outcome" in cols


def test_objectives_has_outcome_column(fresh_db):
    with db.connect() as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(objectives)").fetchall()]
    assert "outcome" in cols


def test_routine_completions_has_status_column(fresh_db):
    with db.connect() as conn:
        cols = [r[1] for r in conn.execute(
            "PRAGMA table_info(routine_completions)"
        ).fetchall()]
    assert "status" in cols


def test_missed_notifications_table_exists(fresh_db):
    with db.connect() as conn:
        cols = [r[1] for r in conn.execute(
            "PRAGMA table_info(missed_notifications)"
        ).fetchall()]
    assert "item_type" in cols
    assert "item_id" in cols
    assert "occurrence_date" in cols
    assert "notified_at" in cols
    assert "decision" in cols


def test_missed_notifications_unique_routine_per_occurrence(fresh_db):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO missed_notifications (item_type, item_id, occurrence_date, notified_at) "
            "VALUES ('routine', 1, '2026-05-28', '2026-05-29T00:05:00')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO missed_notifications (item_type, item_id, occurrence_date, notified_at) "
                "VALUES ('routine', 1, '2026-05-28', '2026-05-29T00:05:00')"
            )


def test_missed_notifications_unique_task_one_per_item(fresh_db):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO missed_notifications (item_type, item_id, notified_at) "
            "VALUES ('task', 5, '2026-05-29T00:05:00')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO missed_notifications (item_type, item_id, notified_at) "
                "VALUES ('task', 5, '2026-05-30T00:05:00')"
            )


def test_xp_log_table_exists(fresh_db):
    with db.connect() as conn:
        cols = [r[1] for r in conn.execute(
            "PRAGMA table_info(xp_log)"
        ).fetchall()]
    assert "item_type" in cols
    assert "item_id" in cols
    assert "outcome" in cols
    assert "xp_amount" in cols
    assert "streak_bonus" in cols
    assert "awarded_at" in cols


def test_xp_log_default_item_id_is_zero(fresh_db):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO xp_log (item_type, outcome, xp_amount, awarded_at) "
            "VALUES ('perfect_day', 'bonus', 20, '2026-05-31T22:00:00')"
        )
        row = conn.execute(
            "SELECT item_id FROM xp_log WHERE item_type='perfect_day'"
        ).fetchone()
    assert row["item_id"] == 0


def test_event_reminders_table_exists(fresh_db):
    with db.connect() as conn:
        cols = [r[1] for r in conn.execute(
            "PRAGMA table_info(event_reminders)"
        ).fetchall()]
    assert "event_id" in cols
    assert "offset_minutes" in cols
    assert "sent" in cols
    assert "created_at" in cols


def test_event_reminders_cascades_on_event_delete(fresh_db):
    with db.connect() as conn:
        cur = conn.execute(
            "INSERT INTO events (title, datetime, category, created_at) "
            "VALUES ('Test', '2026-06-10T10:00:00', 'personal', '2026-06-01T08:00:00')"
        )
        event_id = cur.lastrowid
        conn.execute(
            "INSERT INTO event_reminders "
            "(event_id, offset_minutes, sent, created_at) "
            "VALUES (?, 30, 0, '2026-06-01T08:00:00')",
            (event_id,),
        )
        conn.execute("DELETE FROM events WHERE id = ?", (event_id,))
        count = conn.execute(
            "SELECT COUNT(*) FROM event_reminders WHERE event_id = ?",
            (event_id,),
        ).fetchone()[0]
    assert count == 0

"""Tests de detección de duplicados y borrado."""
import os
import tempfile

import pytest

import db
import tools


@pytest.fixture(autouse=True)
def temp_db(monkeypatch):
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init_schema()
    yield path
    os.unlink(path)


# ---- helpers puros ----

def test_normalize_title_strips_accents_case_punct():
    assert tools._normalize_title("Comprar  Pan!") == "comprar pan"
    assert tools._normalize_title("Médico") == "medico"


def test_titles_similar_exact_normalized():
    assert tools._titles_similar("Comprar pan", "comprar  PAN") is True


def test_titles_similar_substring():
    assert tools._titles_similar("Llamar al fontanero", "Llamar fontanero") is True


def test_titles_similar_token_overlap_reordered():
    # Mismos tokens en distinto orden → Jaccard alto → duplicado.
    assert tools._titles_similar("Reunión Marta equipo", "equipo Marta Reunión") is True


def test_titles_not_similar():
    assert tools._titles_similar("Comprar pan", "Ir al gimnasio") is False


# ---- find_duplicate_groups ----

def test_find_duplicate_groups_tasks():
    tools.add_task("Comprar pan")
    tools.add_task("comprar PAN")
    tools.add_task("Ir al gym")  # sin pareja

    groups = tools.find_duplicate_groups()
    assert len(groups) == 1
    labels = {g["label"] for g in groups[0]}
    assert labels == {"Comprar pan", "comprar PAN"}
    assert all(g["kind"] == "task" for g in groups[0])


def test_find_duplicate_groups_events():
    tools.add_event("Dentista", "2026-06-10T10:00:00", "personal")
    tools.add_event("dentista", "2026-06-11T09:00:00", "personal")

    groups = tools.find_duplicate_groups()
    assert len(groups) == 1
    assert all(g["kind"] == "event" for g in groups[0])


def test_find_duplicate_groups_none_when_unique():
    tools.add_task("Comprar pan")
    tools.add_task("Ir al gym")
    assert tools.find_duplicate_groups() == []


# ---- auto-warning en add_task / add_event ----

def test_add_task_flags_possible_duplicate():
    tools.add_task("Comprar pan")
    res = tools.add_task("comprar pan")
    assert "possible_duplicates" in res
    assert res["possible_duplicates"][0]["text"] == "Comprar pan"


def test_add_task_no_duplicate_flag_when_unique():
    res = tools.add_task("Comprar pan")
    assert "possible_duplicates" not in res


def test_add_event_flags_possible_duplicate():
    tools.add_event("Dentista", "2026-06-10T10:00:00", "personal")
    res = tools.add_event("dentista", "2026-06-11T09:00:00", "personal")
    assert "possible_duplicates" in res


def test_add_event_recurring_not_flagged():
    tools.add_event("Meditar", "2026-06-10T08:00:00", "personal")
    res = tools.add_event(
        "meditar", "2026-06-10T08:00:00", "personal", recurring_rule="DAILY"
    )
    assert "possible_duplicates" not in res


# ---- delete_task ----

def test_delete_task_removes_it():
    t = tools.add_task("Borrar esto")
    out = tools.delete_task(t["id"])
    assert out["deleted"] == 1
    assert all(x["id"] != t["id"] for x in tools.list_tasks(include_done=True))


# ---- snapshot / restore para deshacer borrado ----

def test_snapshot_for_undo_task_captures_fields():
    t = tools.add_task("Comprar pan", due_date="2026-06-20")
    snap = tools.snapshot_for_undo("task", t["id"])
    assert snap["kind"] == "task"
    assert snap["data"]["text"] == "Comprar pan"
    assert snap["data"]["due_date"] == "2026-06-20"


def test_snapshot_for_undo_event_captures_fields():
    e = tools.add_event("Dentista", "2026-06-20T10:00:00", "personal", notes="muela")
    snap = tools.snapshot_for_undo("event", e["id"])
    assert snap["kind"] == "event"
    assert snap["data"]["title"] == "Dentista"
    assert snap["data"]["datetime"] == "2026-06-20T10:00:00"
    assert snap["data"]["category"] == "personal"
    assert snap["data"]["notes"] == "muela"


def test_snapshot_for_undo_not_found_returns_none():
    assert tools.snapshot_for_undo("task", 99999) is None
    assert tools.snapshot_for_undo("event", 99999) is None


def test_restore_from_snapshot_task_recreates_it():
    t = tools.add_task("Comprar pan", due_date="2026-06-20")
    snap = tools.snapshot_for_undo("task", t["id"])
    tools.delete_task(t["id"])
    assert tools.list_tasks() == []
    restored = tools.restore_from_snapshot(snap)
    rows = tools.list_tasks()
    assert len(rows) == 1
    assert rows[0]["text"] == "Comprar pan"
    assert rows[0]["due_date"] == "2026-06-20"
    assert restored["id"] == rows[0]["id"]


def test_restore_from_snapshot_event_recreates_it():
    e = tools.add_event("Dentista", "2026-06-20T10:00:00", "personal", notes="muela")
    snap = tools.snapshot_for_undo("event", e["id"])
    tools.delete_event(e["id"])
    restored = tools.restore_from_snapshot(snap)
    with db.connect() as conn:
        row = conn.execute(
            "SELECT title, datetime, category, notes FROM events WHERE id = ?",
            (restored["id"],),
        ).fetchone()
    assert row["title"] == "Dentista"
    assert row["datetime"] == "2026-06-20T10:00:00"
    assert row["category"] == "personal"
    assert row["notes"] == "muela"


def test_restore_from_snapshot_event_does_not_resync_calendar():
    """Restaurar NO debe re-sincronizar a Google Calendar automáticamente."""
    e = tools.add_event("Dentista", "2026-06-20T10:00:00", "personal")
    snap = tools.snapshot_for_undo("event", e["id"])
    tools.delete_event(e["id"])
    restored = tools.restore_from_snapshot(snap)
    with db.connect() as conn:
        row = conn.execute(
            "SELECT gcal_event_id FROM events WHERE id = ?", (restored["id"],)
        ).fetchone()
    assert row["gcal_event_id"] is None

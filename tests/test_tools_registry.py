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


def test_tool_definitions_shape():
    defs = tools.TOOL_DEFINITIONS
    assert isinstance(defs, list)
    names = {d["name"] for d in defs}
    expected = {
        "add_event", "query_events", "update_event", "delete_event", "mark_event_done",
        "add_objective", "query_objectives", "mark_objective_done",
        "add_task", "list_tasks", "complete_task",
    }
    assert expected.issubset(names)
    for d in defs:
        assert "description" in d
        assert "input_schema" in d
        assert d["input_schema"]["type"] == "object"


def test_dispatch_add_task():
    result = tools.dispatch("add_task", {"text": "comprar pan"})
    assert result["text"] == "comprar pan"


def test_dispatch_unknown_tool():
    with pytest.raises(ValueError, match="desconocida"):
        tools.dispatch("nope", {})


def test_routine_summary_is_registered():
    names = [t["name"] for t in tools.TOOL_DEFINITIONS]
    assert "routine_summary" in names
    assert "routine_summary" in tools._DISPATCH


def test_dispatch_includes_calendar_tools():
    import tools
    assert "push_event_to_calendar" in tools._DISPATCH
    assert "connect_calendar" in tools._DISPATCH


def test_tool_definitions_include_calendar_tools():
    import tools
    names = [t["name"] for t in tools.TOOL_DEFINITIONS]
    assert "push_event_to_calendar" in names
    assert "connect_calendar" in names


def test_delete_task_registered():
    names = [t["name"] for t in tools.TOOL_DEFINITIONS]
    assert "delete_task" in names


def test_delete_task_dispatches_to_helper(monkeypatch):
    called = {}
    def fake(task_id):
        called["id"] = task_id
        return {"id": task_id, "deleted": 1}
    monkeypatch.setattr(tools, "delete_task", fake)
    # _DISPATCH guarda referencia capturada en módulo; reconstruir entrada
    monkeypatch.setitem(tools._DISPATCH, "delete_task", fake)
    result = tools.dispatch("delete_task", {"task_id": 42})
    assert called["id"] == 42
    assert result["deleted"] == 1


def test_delete_objective_registered():
    names = [t["name"] for t in tools.TOOL_DEFINITIONS]
    assert "delete_objective" in names


def test_update_task_registered():
    names = [t["name"] for t in tools.TOOL_DEFINITIONS]
    assert "update_task" in names


def test_update_objective_registered():
    names = [t["name"] for t in tools.TOOL_DEFINITIONS]
    assert "update_objective" in names

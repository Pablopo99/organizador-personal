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

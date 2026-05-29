import os
import tempfile

import pytest

import db
import gcal_sync


@pytest.fixture(autouse=True)
def temp_db(monkeypatch):
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init_schema()
    yield path
    os.unlink(path)


def test_get_tokens_returns_none_when_empty():
    assert gcal_sync.get_tokens() is None


def test_save_and_get_tokens_roundtrip():
    gcal_sync.save_tokens(
        access_token="at-1",
        refresh_token="rt-1",
        expires_at="2026-05-29T12:00:00",
    )
    tokens = gcal_sync.get_tokens()
    assert tokens is not None
    assert tokens["access_token"] == "at-1"
    assert tokens["refresh_token"] == "rt-1"
    assert tokens["expires_at"] == "2026-05-29T12:00:00"


def test_save_tokens_upserts():
    gcal_sync.save_tokens("at-1", "rt-1", "2026-05-29T12:00:00")
    gcal_sync.save_tokens("at-2", "rt-2", "2026-05-29T13:00:00")
    tokens = gcal_sync.get_tokens()
    assert tokens["access_token"] == "at-2"
    assert tokens["refresh_token"] == "rt-2"


def test_clear_tokens():
    gcal_sync.save_tokens("at-1", "rt-1", "2026-05-29T12:00:00")
    gcal_sync.clear_tokens()
    assert gcal_sync.get_tokens() is None

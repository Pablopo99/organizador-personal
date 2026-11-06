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


from unittest.mock import patch
from urllib.parse import parse_qs, urlparse


def test_oauth_start_url_contains_required_params(monkeypatch):
    monkeypatch.setattr(gcal_sync, "GOOGLE_CLIENT_ID", "abc.apps.googleusercontent.com")
    monkeypatch.setattr(gcal_sync, "GOOGLE_REDIRECT_URI", "https://example.com/cb")
    url = gcal_sync.oauth_start_url()
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    assert parsed.netloc == "accounts.google.com"
    assert qs["client_id"] == ["abc.apps.googleusercontent.com"]
    assert qs["redirect_uri"] == ["https://example.com/cb"]
    assert qs["response_type"] == ["code"]
    assert "https://www.googleapis.com/auth/calendar.events" in qs["scope"][0]
    assert qs["access_type"] == ["offline"]
    assert qs["prompt"] == ["consent"]


def test_exchange_code_persists_tokens(monkeypatch):
    monkeypatch.setattr(gcal_sync, "GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setattr(gcal_sync, "GOOGLE_CLIENT_SECRET", "csecret")
    monkeypatch.setattr(gcal_sync, "GOOGLE_REDIRECT_URI", "https://example.com/cb")

    fake_response = {
        "access_token": "at-abc",
        "refresh_token": "rt-abc",
        "expires_in": 3599,
    }

    captured = {}
    def fake_post(url, data, timeout):
        captured["url"] = url
        captured["data"] = data
        class R:
            status_code = 200
            def json(self_inner):
                return fake_response
            def raise_for_status(self_inner):
                pass
        return R()

    with patch("gcal_sync.requests.post", side_effect=fake_post):
        gcal_sync.exchange_code("the-code")

    assert captured["url"] == "https://oauth2.googleapis.com/token"
    assert captured["data"]["code"] == "the-code"
    assert captured["data"]["client_id"] == "cid"
    assert captured["data"]["client_secret"] == "csecret"
    assert captured["data"]["redirect_uri"] == "https://example.com/cb"
    assert captured["data"]["grant_type"] == "authorization_code"

    saved = gcal_sync.get_tokens()
    assert saved["access_token"] == "at-abc"
    assert saved["refresh_token"] == "rt-abc"


from datetime import timedelta


def test_ensure_valid_token_returns_existing_when_fresh(monkeypatch):
    monkeypatch.setattr(gcal_sync, "GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setattr(gcal_sync, "GOOGLE_CLIENT_SECRET", "csecret")
    future = (gcal_sync.now_madrid_naive() + timedelta(hours=1)).isoformat(timespec="seconds")
    gcal_sync.save_tokens("at-current", "rt-current", future)

    with patch("gcal_sync.requests.post") as post:
        token = gcal_sync.ensure_valid_token()

    assert token == "at-current"
    post.assert_not_called()


def test_ensure_valid_token_refreshes_when_near_expiry(monkeypatch):
    monkeypatch.setattr(gcal_sync, "GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setattr(gcal_sync, "GOOGLE_CLIENT_SECRET", "csecret")
    past = (gcal_sync.now_madrid_naive() + timedelta(minutes=2)).isoformat(timespec="seconds")
    gcal_sync.save_tokens("at-old", "rt-keep", past)

    fake_payload = {"access_token": "at-new", "expires_in": 3600}

    def fake_post(url, data, timeout):
        assert data["refresh_token"] == "rt-keep"
        assert data["grant_type"] == "refresh_token"
        class R:
            def json(self_inner):
                return fake_payload
            def raise_for_status(self_inner):
                pass
        return R()

    with patch("gcal_sync.requests.post", side_effect=fake_post):
        token = gcal_sync.ensure_valid_token()

    assert token == "at-new"
    saved = gcal_sync.get_tokens()
    assert saved["access_token"] == "at-new"
    assert saved["refresh_token"] == "rt-keep"  # se conserva


def test_ensure_valid_token_raises_when_no_tokens():
    with pytest.raises(gcal_sync.NotConnected):
        gcal_sync.ensure_valid_token()


def _fresh_token(monkeypatch):
    monkeypatch.setattr(gcal_sync, "GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setattr(gcal_sync, "GOOGLE_CLIENT_SECRET", "csecret")
    future = (gcal_sync.now_madrid_naive() + timedelta(hours=1)).isoformat(timespec="seconds")
    gcal_sync.save_tokens("at-fresh", "rt-fresh", future)


def test_push_event_posts_correct_body(monkeypatch):
    _fresh_token(monkeypatch)
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        class R:
            status_code = 200
            def json(self_inner):
                return {"id": "gcal-evt-1"}
            def raise_for_status(self_inner):
                pass
        return R()

    with patch("gcal_sync.requests.post", side_effect=fake_post):
        gcal_event_id = gcal_sync.push_event({
            "title": "Dentista",
            "datetime": "2026-05-29T10:00:00",
            "notes": "C/ Doctor San Juan 26",
            "category": "medical",
        })

    assert gcal_event_id == "gcal-evt-1"
    assert captured["url"] == "https://www.googleapis.com/calendar/v3/calendars/primary/events"
    assert captured["headers"]["Authorization"] == "Bearer at-fresh"
    body = captured["json"]
    assert body["summary"] == "Dentista"
    assert body["description"] == "C/ Doctor San Juan 26"
    assert body["start"] == {"dateTime": "2026-05-29T10:00:00", "timeZone": "Europe/Madrid"}
    assert body["end"] == {"dateTime": "2026-05-29T11:00:00", "timeZone": "Europe/Madrid"}


def test_push_event_handles_missing_notes(monkeypatch):
    _fresh_token(monkeypatch)
    def fake_post(url, json=None, headers=None, timeout=None):
        class R:
            def json(self_inner):
                return {"id": "x"}
            def raise_for_status(self_inner):
                pass
        return R()
    with patch("gcal_sync.requests.post", side_effect=fake_post) as p:
        gcal_sync.push_event({
            "title": "T", "datetime": "2026-05-29T10:00:00", "category": "other",
        })
    body = p.call_args.kwargs["json"]
    assert "description" not in body or body["description"] == ""


def test_update_event_patches_changed_fields(monkeypatch):
    _fresh_token(monkeypatch)
    captured = {}
    def fake_patch(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        class R:
            def raise_for_status(self_inner):
                pass
        return R()
    with patch("gcal_sync.requests.patch", side_effect=fake_patch):
        gcal_sync.update_event("gcal-evt-1", {"title": "Nuevo", "datetime": "2026-05-29T15:30:00"})
    assert captured["url"].endswith("/primary/events/gcal-evt-1")
    assert captured["json"]["summary"] == "Nuevo"
    assert captured["json"]["start"]["dateTime"] == "2026-05-29T15:30:00"
    assert captured["json"]["end"]["dateTime"] == "2026-05-29T16:30:00"


def test_delete_event_treats_404_as_success(monkeypatch):
    _fresh_token(monkeypatch)
    class R:
        status_code = 404
        def raise_for_status(self_inner):
            import requests as r
            raise r.HTTPError(response=self_inner)
    with patch("gcal_sync.requests.delete", return_value=R()):
        gcal_sync.delete_event("gcal-evt-gone")  # no debe levantar


def test_delete_event_success_204(monkeypatch):
    _fresh_token(monkeypatch)
    class R:
        status_code = 204
        def raise_for_status(self_inner):
            pass
    with patch("gcal_sync.requests.delete", return_value=R()):
        gcal_sync.delete_event("gcal-evt-1")


def test_ensure_valid_token_clears_tokens_when_refresh_revoked(monkeypatch):
    """Si Google responde invalid_grant (token caducado/revocado, típico con la
    app OAuth en modo Testing: caduca a los 7 días), borramos los tokens y
    lanzamos NotConnected para que el bot ofrezca reconectar en vez de fallar
    en silencio con 'api_error' para siempre."""
    monkeypatch.setattr(gcal_sync, "GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setattr(gcal_sync, "GOOGLE_CLIENT_SECRET", "csecret")
    gcal_sync.save_tokens("old-at", "dead-rt", "2000-01-01T00:00:00")

    class R:
        status_code = 400

        def json(self):
            return {"error": "invalid_grant", "error_description": "Token has been expired or revoked."}

        def raise_for_status(self):
            import requests as r
            raise r.HTTPError("400")

    with patch("gcal_sync.requests.post", return_value=R()):
        with pytest.raises(gcal_sync.NotConnected):
            gcal_sync.ensure_valid_token()

    assert gcal_sync.get_tokens() is None

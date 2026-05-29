import config


def test_config_loads_env_vars():
    # conftest.py garantiza valores por defecto para tests
    assert config.TELEGRAM_TOKEN
    assert config.ANTHROPIC_API_KEY
    assert isinstance(config.ALLOWED_USER_ID, int)


def test_config_constants():
    assert config.TIMEZONE == "Europe/Madrid"
    assert config.DB_PATH.endswith("organizador.db")
    assert "medical" in config.CATEGORIES
    assert "work" in config.CATEGORIES
    assert "personal" in config.CATEGORIES
    assert "other" in config.CATEGORIES


def test_require_raises_for_missing(monkeypatch):
    monkeypatch.delenv("MISSING_VAR", raising=False)
    import pytest
    with pytest.raises(RuntimeError, match="MISSING_VAR"):
        config._require("MISSING_VAR")


def test_groq_api_key_loads_optionally():
    # conftest fija un valor de test; debe existir y ser string
    assert isinstance(config.GROQ_API_KEY, str)


def test_google_credentials_default_to_empty_when_unset(monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    import importlib
    import config
    importlib.reload(config)
    assert config.GOOGLE_CLIENT_ID == ""
    assert config.GOOGLE_CLIENT_SECRET == ""


def test_google_credentials_read_from_env(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "abc.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "GOCSPX-secret")
    import importlib
    import config
    importlib.reload(config)
    assert config.GOOGLE_CLIENT_ID == "abc.apps.googleusercontent.com"
    assert config.GOOGLE_CLIENT_SECRET == "GOCSPX-secret"

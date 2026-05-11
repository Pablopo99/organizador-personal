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

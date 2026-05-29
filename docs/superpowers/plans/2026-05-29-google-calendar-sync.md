# Google Calendar Sync — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permitir a Pablo enviar (y propagar updates/deletes de) eventos del bot a su Google Calendar de forma explícita — lenguaje natural o botón inline.

**Architecture:** Módulo aislado `gcal_sync.py` con toda la lógica OAuth + Calendar API. `tools.py` propaga automáticamente si la fila del evento tiene `gcal_event_id`. Endpoint `/oauth/callback` se monta en el aiohttp ya existente (el de Siri). El bot sigue siendo la fuente de verdad: si Calendar falla, se loguea pero el bot no degrada.

**Tech Stack:** Python 3.11, `google-auth`, `google-auth-oauthlib`, `google-api-python-client`, aiohttp (ya en uso), SQLite, python-telegram-bot.

---

## Estructura de archivos

- **Crear** `gcal_sync.py` — todo lo de Calendar: storage de tokens, OAuth (URL, exchange, refresh), llamadas a la API (push/update/delete), registro de la ruta `/oauth/callback` en aiohttp.
- **Crear** `tests/test_gcal_sync.py` — tests con HTTP mockeado.
- **Modificar** `db.py` — migración: añadir columna `gcal_event_id` a `events` y crear tabla `oauth_tokens`.
- **Modificar** `config.py` — leer `GOOGLE_CLIENT_ID` y `GOOGLE_CLIENT_SECRET` como opcionales.
- **Modificar** `tools.py` — `add_event` admite `sync_to_calendar`; `update_event`/`delete_event` propagan si hay `gcal_event_id`; añade tools `push_event_to_calendar` y `connect_calendar`.
- **Modificar** `brain.py` — registry de "último evento creado sin sync" para que `bot.py` adjunte el botón; cambios en el system prompt.
- **Modificar** `bot.py` — registrar `/oauth/callback` en el aiohttp app; callback handler `gcs` para el botón inline; adjuntar el botón cuando `brain` reporte un evento recién creado sin sync.
- **Modificar** `requirements.txt` — añadir las tres librerías de Google.
- **Modificar** `.env.example` — documentar `GOOGLE_CLIENT_ID` y `GOOGLE_CLIENT_SECRET`.

---

## Convenciones del repo (no inventar)

- Test runner: `./.venv/bin/python -m pytest …` (no `pytest` pelado — falla con el venv).
- Toda fecha "hoy" se obtiene con `date_utils.today_madrid()`; "ahora ISO" con `date_utils.now_iso()`.
- `db.connect()` ya hace `PRAGMA foreign_keys = ON`.
- Conventional Commits con el trailer:
  ```
  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  ```
- Commit al final de cada tarea, una tarea = un commit.

---

## Task 1: Dependencias y secrets

**Files:**
- Modify: `requirements.txt`
- Modify: `.env.example`

- [ ] **Step 1: Añadir las tres librerías a `requirements.txt`**

Tras la línea `pytest-aiohttp>=1.0`, añade:

```
google-auth>=2.0
google-auth-oauthlib>=1.0
google-api-python-client>=2.0
```

- [ ] **Step 2: Documentar variables en `.env.example`**

Añadir al final del archivo:

```
# Credenciales OAuth de Google Calendar. Crear en console.cloud.google.com.
# OPCIONAL: si no se rellenan, el bot funciona normal pero la sincronización con
# Google Calendar queda deshabilitada.
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
```

- [ ] **Step 3: Instalar dependencias localmente**

Run: `./.venv/bin/pip install -r requirements.txt`
Expected: instalación correcta de las tres librerías.

- [ ] **Step 4: Commit**

```bash
git add requirements.txt .env.example
git commit -m "$(cat <<'EOF'
build: add google-api-python-client deps for Calendar sync

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Migración de BD — `gcal_event_id` y `oauth_tokens`

**Files:**
- Modify: `db.py`
- Test: `tests/test_db.py`

- [ ] **Step 1: Escribir test que comprueba que la columna y la tabla existen tras init_schema**

Añadir al final de `tests/test_db.py`:

```python
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
```

Si `tests/test_db.py` no tiene `import pytest` en cabecera, añádelo.

- [ ] **Step 2: Verificar que los tests fallan**

Run: `./.venv/bin/python -m pytest tests/test_db.py -v`
Expected: FAIL en los tres tests nuevos (`gcal_event_id` no existe, `oauth_tokens` no existe).

- [ ] **Step 3: Añadir migración y schema en `db.py`**

En `db.py`, dentro del string `_SCHEMA`, añadir el bloque de `oauth_tokens` antes del cierre de las comillas triples, justo después de la tabla `routine_completions` y su índice:

```sql
CREATE TABLE IF NOT EXISTS oauth_tokens (
    provider      TEXT PRIMARY KEY,
    access_token  TEXT NOT NULL,
    refresh_token TEXT NOT NULL,
    expires_at    TEXT NOT NULL,
    created_at    TEXT NOT NULL
);
```

En la función `_migrate`, justo después del bloque que añade `done_at` a `tasks` y antes del bloque que crea `routine_completions`, añadir:

```python
    if "gcal_event_id" not in events_cols:
        conn.execute("ALTER TABLE events ADD COLUMN gcal_event_id TEXT")
```

(Nota: `events_cols` ya está calculado más arriba en la función; no recalcules.)

- [ ] **Step 4: Verificar que los tests pasan**

Run: `./.venv/bin/python -m pytest tests/test_db.py -v`
Expected: PASS en los tres tests nuevos.

- [ ] **Step 5: Pasar la suite completa**

Run: `./.venv/bin/python -m pytest`
Expected: todos los tests pasan.

- [ ] **Step 6: Commit**

```bash
git add db.py tests/test_db.py
git commit -m "$(cat <<'EOF'
feat(db): add gcal_event_id column and oauth_tokens table

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Config opcional para credenciales de Google

**Files:**
- Modify: `config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Escribir tests**

Añadir al final de `tests/test_config.py`:

```python
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
```

- [ ] **Step 2: Verificar que fallan**

Run: `./.venv/bin/python -m pytest tests/test_config.py -v`
Expected: FAIL (`AttributeError: module 'config' has no attribute 'GOOGLE_CLIENT_ID'`).

- [ ] **Step 3: Añadir lectura en `config.py`**

En `config.py`, después de la línea de `SIRI_TOKEN = _require("SIRI_TOKEN")`, añadir:

```python
# Credenciales OAuth de Google Calendar. Si están vacías, la sincronización
# con Calendar queda deshabilitada (el bot sigue funcionando normal).
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.environ.get(
    "GOOGLE_REDIRECT_URI",
    "https://mi-secretaria-pablo.fly.dev/oauth/callback",
)
```

- [ ] **Step 4: Verificar tests**

Run: `./.venv/bin/python -m pytest tests/test_config.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add config.py tests/test_config.py
git commit -m "$(cat <<'EOF'
feat(config): optional GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `gcal_sync.py` — token storage

**Files:**
- Create: `gcal_sync.py`
- Create: `tests/test_gcal_sync.py`

- [ ] **Step 1: Escribir tests de almacenamiento**

Crear `tests/test_gcal_sync.py` con:

```python
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
```

- [ ] **Step 2: Verificar que fallan**

Run: `./.venv/bin/python -m pytest tests/test_gcal_sync.py -v`
Expected: FAIL (`ModuleNotFoundError: gcal_sync`).

- [ ] **Step 3: Crear `gcal_sync.py` con storage**

Crear `gcal_sync.py`:

```python
"""Sincronización con Google Calendar.

Storage de tokens OAuth + llamadas a la API + endpoint /oauth/callback.
El bot es la fuente de verdad: si Google falla, se loguea y se sigue.
"""
import logging
from typing import Optional

import db
from date_utils import now_iso

log = logging.getLogger("gcal_sync")

_PROVIDER = "google"


def get_tokens() -> Optional[dict]:
    """Devuelve el dict de tokens guardados o None si no hay."""
    with db.connect() as conn:
        row = conn.execute(
            "SELECT access_token, refresh_token, expires_at FROM oauth_tokens"
            " WHERE provider = ?",
            (_PROVIDER,),
        ).fetchone()
    if row is None:
        return None
    return {
        "access_token": row["access_token"],
        "refresh_token": row["refresh_token"],
        "expires_at": row["expires_at"],
    }


def save_tokens(access_token: str, refresh_token: str, expires_at: str) -> None:
    """Inserta o reemplaza los tokens. `expires_at` en ISO 8601 (naive Madrid)."""
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO oauth_tokens (provider, access_token, refresh_token, expires_at, created_at)"
            " VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT(provider) DO UPDATE SET"
            "   access_token = excluded.access_token,"
            "   refresh_token = excluded.refresh_token,"
            "   expires_at = excluded.expires_at",
            (_PROVIDER, access_token, refresh_token, expires_at, now_iso()),
        )


def clear_tokens() -> None:
    """Borra los tokens guardados (uso: token revocado en Google)."""
    with db.connect() as conn:
        conn.execute("DELETE FROM oauth_tokens WHERE provider = ?", (_PROVIDER,))
```

- [ ] **Step 4: Verificar tests**

Run: `./.venv/bin/python -m pytest tests/test_gcal_sync.py -v`
Expected: PASS los 4 tests.

- [ ] **Step 5: Commit**

```bash
git add gcal_sync.py tests/test_gcal_sync.py
git commit -m "$(cat <<'EOF'
feat(gcal): token storage in SQLite (get/save/clear)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `gcal_sync` — generación de URL OAuth y exchange de código

**Files:**
- Modify: `gcal_sync.py`
- Modify: `tests/test_gcal_sync.py`

- [ ] **Step 1: Escribir tests**

Añadir al final de `tests/test_gcal_sync.py`:

```python
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
```

- [ ] **Step 2: Verificar que fallan**

Run: `./.venv/bin/python -m pytest tests/test_gcal_sync.py -v`
Expected: FAIL (`oauth_start_url`, `exchange_code` no existen).

- [ ] **Step 3: Implementar `oauth_start_url` y `exchange_code` en `gcal_sync.py`**

Al inicio de `gcal_sync.py`, completar imports y añadir las constantes leídas de config (con re-export para que los tests puedan monkeypatchear el módulo). Reemplazar la cabecera del archivo por:

```python
"""Sincronización con Google Calendar.

Storage de tokens OAuth + llamadas a la API + endpoint /oauth/callback.
El bot es la fuente de verdad: si Google falla, se loguea y se sigue.
"""
import logging
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlencode

import requests

import db
from config import (
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    GOOGLE_REDIRECT_URI,
)
from date_utils import now_iso, now_madrid_naive

log = logging.getLogger("gcal_sync")

_PROVIDER = "google"
_SCOPE = "https://www.googleapis.com/auth/calendar.events"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_API_BASE = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
```

Y al final del archivo, después de `clear_tokens()`, añadir:

```python
def oauth_start_url() -> str:
    """Devuelve la URL a la que el usuario debe ir para autorizar el bot."""
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": _SCOPE,
        "access_type": "offline",
        "prompt": "consent",
    }
    return f"{_AUTH_URL}?{urlencode(params)}"


def exchange_code(code: str) -> None:
    """Intercambia el authorization code por tokens y los guarda.

    Lanza excepción si Google devuelve error (la captura quien llame).
    """
    response = requests.post(
        _TOKEN_URL,
        data={
            "code": code,
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri": GOOGLE_REDIRECT_URI,
            "grant_type": "authorization_code",
        },
        timeout=15,
    )
    response.raise_for_status()
    payload = response.json()
    expires_at = (
        now_madrid_naive() + timedelta(seconds=int(payload["expires_in"]))
    ).isoformat(timespec="seconds")
    save_tokens(
        access_token=payload["access_token"],
        refresh_token=payload["refresh_token"],
        expires_at=expires_at,
    )
```

Nota: `requests` aún no está explícitamente en `requirements.txt`, pero es dependencia transitiva de `google-auth-oauthlib`. Verifícalo con `./.venv/bin/pip show requests` — si no está, añade `requests>=2.31` al `requirements.txt` en este paso.

- [ ] **Step 4: Verificar tests**

Run: `./.venv/bin/python -m pytest tests/test_gcal_sync.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add gcal_sync.py tests/test_gcal_sync.py requirements.txt
git commit -m "$(cat <<'EOF'
feat(gcal): oauth_start_url and exchange_code with token persistence

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: `gcal_sync.ensure_valid_token` — refresh automático

**Files:**
- Modify: `gcal_sync.py`
- Modify: `tests/test_gcal_sync.py`

- [ ] **Step 1: Escribir tests**

Añadir al final de `tests/test_gcal_sync.py`:

```python
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
```

Añadir `from datetime import timedelta` arriba en el archivo si falta.

- [ ] **Step 2: Verificar que fallan**

Run: `./.venv/bin/python -m pytest tests/test_gcal_sync.py -v -k ensure_valid_token`
Expected: FAIL (`NotConnected`, `ensure_valid_token` no existen).

- [ ] **Step 3: Implementar `NotConnected` y `ensure_valid_token`**

Justo después de las constantes en `gcal_sync.py` añadir:

```python
class NotConnected(Exception):
    """No hay tokens guardados — el usuario debe autorizar."""
```

Y al final del archivo:

```python
def ensure_valid_token() -> str:
    """Devuelve un access_token válido. Renueva con refresh_token si toca."""
    tokens = get_tokens()
    if tokens is None:
        raise NotConnected("No hay tokens guardados.")

    expires_at = datetime.fromisoformat(tokens["expires_at"])
    if expires_at - now_madrid_naive() > timedelta(minutes=5):
        return tokens["access_token"]

    response = requests.post(
        _TOKEN_URL,
        data={
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "refresh_token": tokens["refresh_token"],
            "grant_type": "refresh_token",
        },
        timeout=15,
    )
    response.raise_for_status()
    payload = response.json()
    new_expires = (
        now_madrid_naive() + timedelta(seconds=int(payload["expires_in"]))
    ).isoformat(timespec="seconds")
    save_tokens(
        access_token=payload["access_token"],
        refresh_token=tokens["refresh_token"],  # Google no devuelve refresh nuevo en este flow
        expires_at=new_expires,
    )
    return payload["access_token"]
```

- [ ] **Step 4: Verificar tests**

Run: `./.venv/bin/python -m pytest tests/test_gcal_sync.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add gcal_sync.py tests/test_gcal_sync.py
git commit -m "$(cat <<'EOF'
feat(gcal): ensure_valid_token refreshes when expiring soon

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: `gcal_sync` — push/update/delete event

**Files:**
- Modify: `gcal_sync.py`
- Modify: `tests/test_gcal_sync.py`

- [ ] **Step 1: Escribir tests**

Añadir al final de `tests/test_gcal_sync.py`:

```python
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
```

- [ ] **Step 2: Verificar que fallan**

Run: `./.venv/bin/python -m pytest tests/test_gcal_sync.py -v -k "push_event or update_event or delete_event"`
Expected: FAIL (las tres funciones no existen).

- [ ] **Step 3: Implementar las tres funciones**

Añadir al final de `gcal_sync.py`:

```python
def _build_event_body(fields: dict) -> dict:
    """Traduce campos del bot al JSON body de Google Calendar.

    Solo incluye las claves que vienen en `fields` para que sirva tanto para
    POST (create) como para PATCH (update).
    """
    body: dict = {}
    if "title" in fields:
        body["summary"] = fields["title"]
    if "notes" in fields and fields["notes"]:
        body["description"] = fields["notes"]
    if "datetime" in fields:
        start = datetime.fromisoformat(fields["datetime"])
        end = start + timedelta(hours=1)
        body["start"] = {"dateTime": start.isoformat(timespec="seconds"), "timeZone": "Europe/Madrid"}
        body["end"] = {"dateTime": end.isoformat(timespec="seconds"), "timeZone": "Europe/Madrid"}
    return body


def push_event(event: dict) -> str:
    """Crea un evento en Calendar. Devuelve el id de Google."""
    access_token = ensure_valid_token()
    body = _build_event_body(event)
    response = requests.post(
        _API_BASE,
        json=body,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=15,
    )
    response.raise_for_status()
    return response.json()["id"]


def update_event(gcal_event_id: str, fields: dict) -> None:
    """PATCH a Calendar con los campos cambiados."""
    access_token = ensure_valid_token()
    body = _build_event_body(fields)
    if not body:
        return
    response = requests.patch(
        f"{_API_BASE}/{gcal_event_id}",
        json=body,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=15,
    )
    response.raise_for_status()


def delete_event(gcal_event_id: str) -> None:
    """DELETE en Calendar. 404 se trata como éxito (ya no existe)."""
    access_token = ensure_valid_token()
    response = requests.delete(
        f"{_API_BASE}/{gcal_event_id}",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=15,
    )
    if response.status_code == 404:
        log.warning("Evento %s ya no existe en Calendar, asumimos éxito", gcal_event_id)
        return
    response.raise_for_status()
```

- [ ] **Step 4: Verificar tests**

Run: `./.venv/bin/python -m pytest tests/test_gcal_sync.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add gcal_sync.py tests/test_gcal_sync.py
git commit -m "$(cat <<'EOF'
feat(gcal): push/update/delete event API calls

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Propagar a Calendar desde `tools.update_event` y `tools.delete_event`

**Files:**
- Modify: `tools.py`
- Modify: `tests/test_tools_events.py`

- [ ] **Step 1: Escribir tests**

Añadir al final de `tests/test_tools_events.py`:

```python
from unittest.mock import patch


def test_update_event_propagates_to_calendar_when_synced():
    created = tools.add_event("Reu", "2026-05-29T10:00:00", "work")
    # Marcar la fila como sincronizada (simula que pasó por push_event_to_calendar)
    with db.connect() as conn:
        conn.execute(
            "UPDATE events SET gcal_event_id = ? WHERE id = ?",
            ("gcal-1", created["id"]),
        )

    with patch("tools.gcal_sync.update_event") as upd:
        tools.update_event(created["id"], {"title": "Reu nueva"})

    upd.assert_called_once_with("gcal-1", {"title": "Reu nueva"})


def test_update_event_does_not_call_gcal_when_not_synced():
    created = tools.add_event("Sin sync", "2026-05-29T10:00:00", "work")
    with patch("tools.gcal_sync.update_event") as upd:
        tools.update_event(created["id"], {"title": "Otro"})
    upd.assert_not_called()


def test_update_event_swallows_gcal_errors():
    created = tools.add_event("Reu", "2026-05-29T10:00:00", "work")
    with db.connect() as conn:
        conn.execute(
            "UPDATE events SET gcal_event_id = ? WHERE id = ?",
            ("gcal-x", created["id"]),
        )
    with patch("tools.gcal_sync.update_event", side_effect=RuntimeError("boom")):
        result = tools.update_event(created["id"], {"title": "Reu2"})
    assert result["updated"] == 1  # update local sí funcionó


def test_delete_event_propagates_to_calendar_when_synced():
    created = tools.add_event("Borrar", "2026-05-29T10:00:00", "work")
    with db.connect() as conn:
        conn.execute(
            "UPDATE events SET gcal_event_id = ? WHERE id = ?",
            ("gcal-d", created["id"]),
        )
    with patch("tools.gcal_sync.delete_event") as dl:
        tools.delete_event(created["id"])
    dl.assert_called_once_with("gcal-d")


def test_delete_event_does_not_call_gcal_when_not_synced():
    created = tools.add_event("X", "2026-05-29T10:00:00", "work")
    with patch("tools.gcal_sync.delete_event") as dl:
        tools.delete_event(created["id"])
    dl.assert_not_called()
```

- [ ] **Step 2: Verificar que fallan**

Run: `./.venv/bin/python -m pytest tests/test_tools_events.py -v -k "propagates or swallow or not_call_gcal"`
Expected: FAIL (importación `tools.gcal_sync` falla, o la propagación no se hace).

- [ ] **Step 3: Modificar `tools.py`**

En `tools.py`, debajo del `import db`, añadir:

```python
import gcal_sync
import logging

log = logging.getLogger("tools")
```

Sustituir la función `update_event` actual (líneas ~115-138) por:

```python
def update_event(event_id: int, fields: dict) -> dict:
    allowed = {"title", "datetime", "category", "recurring_rule", "notes"}
    sets = []
    params: list = []
    for key, value in fields.items():
        if key not in allowed:
            raise ValueError(f"campo no actualizable: {key}")
        if key == "category" and value not in CATEGORIES:
            raise ValueError(f"categoría inválida '{value}'")
        sets.append(f"{key} = ?")
        params.append(value)
    if not sets:
        return {"id": event_id, "updated": 0}

    if "datetime" in fields:
        sets.append("reminder_1d_sent = 0")
        sets.append("reminder_1h_sent = 0")

    params.append(event_id)
    with db.connect() as conn:
        cur = conn.execute(
            f"UPDATE events SET {', '.join(sets)} WHERE id = ?", params
        )
        gcal_id_row = conn.execute(
            "SELECT gcal_event_id FROM events WHERE id = ?", (event_id,)
        ).fetchone()

    result = {"id": event_id, "updated": cur.rowcount}

    gcal_event_id = gcal_id_row["gcal_event_id"] if gcal_id_row else None
    if gcal_event_id:
        try:
            gcal_sync.update_event(gcal_event_id, fields)
        except Exception:
            log.exception("Error propagando update_event a Calendar (event_id=%s)", event_id)

    return result
```

Sustituir la función `delete_event` actual (líneas ~141-144) por:

```python
def delete_event(event_id: int) -> dict:
    with db.connect() as conn:
        gcal_id_row = conn.execute(
            "SELECT gcal_event_id FROM events WHERE id = ?", (event_id,)
        ).fetchone()
        cur = conn.execute("DELETE FROM events WHERE id = ?", (event_id,))

    gcal_event_id = gcal_id_row["gcal_event_id"] if gcal_id_row else None
    if gcal_event_id:
        try:
            gcal_sync.delete_event(gcal_event_id)
        except Exception:
            log.exception("Error propagando delete_event a Calendar (event_id=%s)", event_id)

    return {"id": event_id, "deleted": cur.rowcount}
```

- [ ] **Step 4: Verificar tests**

Run: `./.venv/bin/python -m pytest tests/test_tools_events.py -v`
Expected: PASS (incluyendo los preexistentes).

- [ ] **Step 5: Commit**

```bash
git add tools.py tests/test_tools_events.py
git commit -m "$(cat <<'EOF'
feat(tools): propagate update_event and delete_event to Calendar

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: `tools.add_event(sync_to_calendar=True)`, `push_event_to_calendar` y `connect_calendar`

**Files:**
- Modify: `tools.py`
- Modify: `tests/test_tools_events.py`
- Modify: `tests/test_tools_registry.py`

- [ ] **Step 1: Escribir tests**

Añadir al final de `tests/test_tools_events.py`:

```python
def test_add_event_with_sync_to_calendar_true_pushes_and_stores_gcal_id():
    with patch("tools.gcal_sync.push_event", return_value="gcal-sync-1") as p:
        result = tools.add_event(
            "Reu", "2026-05-29T10:00:00", "work", sync_to_calendar=True
        )
    p.assert_called_once()
    assert result["gcal_event_id"] == "gcal-sync-1"
    with db.connect() as conn:
        row = conn.execute(
            "SELECT gcal_event_id FROM events WHERE id = ?", (result["id"],)
        ).fetchone()
    assert row["gcal_event_id"] == "gcal-sync-1"


def test_add_event_default_does_not_call_calendar():
    with patch("tools.gcal_sync.push_event") as p:
        tools.add_event("Reu", "2026-05-29T10:00:00", "work")
    p.assert_not_called()


def test_add_event_with_sync_not_connected_returns_unsynced_but_keeps_event():
    import gcal_sync
    with patch("tools.gcal_sync.push_event", side_effect=gcal_sync.NotConnected()):
        result = tools.add_event(
            "Reu", "2026-05-29T10:00:00", "work", sync_to_calendar=True
        )
    assert "id" in result
    assert result.get("sync_error") == "not_connected"


def test_push_event_to_calendar_writes_gcal_id_and_returns_ok():
    created = tools.add_event("Cena", "2026-05-29T21:00:00", "personal")

    with patch("tools.gcal_sync.push_event", return_value="gcal-cena-1"):
        result = tools.push_event_to_calendar(created["id"])

    assert result == {"event_id": created["id"], "gcal_event_id": "gcal-cena-1", "synced": True}
    with db.connect() as conn:
        row = conn.execute(
            "SELECT gcal_event_id FROM events WHERE id = ?", (created["id"],)
        ).fetchone()
    assert row["gcal_event_id"] == "gcal-cena-1"


def test_push_event_to_calendar_is_idempotent_when_already_synced():
    created = tools.add_event("Cita", "2026-05-29T10:00:00", "medical")
    with db.connect() as conn:
        conn.execute(
            "UPDATE events SET gcal_event_id = ? WHERE id = ?",
            ("gcal-already", created["id"]),
        )

    with patch("tools.gcal_sync.push_event") as p:
        result = tools.push_event_to_calendar(created["id"])

    p.assert_not_called()
    assert result["already_synced"] is True
    assert result["gcal_event_id"] == "gcal-already"


def test_push_event_to_calendar_raises_friendly_when_not_connected():
    created = tools.add_event("Cita", "2026-05-29T10:00:00", "medical")
    import gcal_sync
    with patch("tools.gcal_sync.push_event", side_effect=gcal_sync.NotConnected()):
        result = tools.push_event_to_calendar(created["id"])
    assert result == {"event_id": created["id"], "synced": False, "error": "not_connected"}


def test_push_event_to_calendar_unknown_event_id():
    result = tools.push_event_to_calendar(99999)
    assert result == {"event_id": 99999, "synced": False, "error": "not_found"}


def test_connect_calendar_returns_auth_url():
    with patch("tools.gcal_sync.oauth_start_url", return_value="https://example/auth?x=1"):
        result = tools.connect_calendar()
    assert result == {"auth_url": "https://example/auth?x=1"}
```

Y en `tests/test_tools_registry.py`, verificar que las dos tools nuevas están registradas. Buscar el test existente que enumera nombres (si no existe uno así, añade):

```python
def test_dispatch_includes_calendar_tools():
    import tools
    assert "push_event_to_calendar" in tools._DISPATCH
    assert "connect_calendar" in tools._DISPATCH


def test_tool_definitions_include_calendar_tools():
    import tools
    names = [t["name"] for t in tools.TOOL_DEFINITIONS]
    assert "push_event_to_calendar" in names
    assert "connect_calendar" in names
```

- [ ] **Step 2: Verificar que fallan**

Run: `./.venv/bin/python -m pytest tests/test_tools_events.py tests/test_tools_registry.py -v`
Expected: FAIL (`push_event_to_calendar`, `connect_calendar` no existen).

- [ ] **Step 3: Modificar `tools.add_event` para aceptar `sync_to_calendar`**

Sustituir la función `add_event` actual por:

```python
def add_event(
    title: str,
    datetime_iso: str,
    category: str,
    recurring_rule: Optional[str] = None,
    notes: Optional[str] = None,
    sync_to_calendar: bool = False,
) -> dict:
    if category not in CATEGORIES:
        raise ValueError(
            f"categoría inválida '{category}'. Permitidas: {CATEGORIES}"
        )
    with db.connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO events (title, datetime, category, recurring_rule, notes, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (title, datetime_iso, category, recurring_rule, notes, now_iso()),
        )
        new_id = cur.lastrowid

    result = {"id": new_id, "title": title, "datetime": datetime_iso}

    if sync_to_calendar:
        try:
            gcal_id = gcal_sync.push_event({
                "title": title,
                "datetime": datetime_iso,
                "category": category,
                "notes": notes,
            })
        except gcal_sync.NotConnected:
            result["sync_error"] = "not_connected"
            return result
        except Exception:
            log.exception("Error en sync_to_calendar para add_event %s", new_id)
            result["sync_error"] = "api_error"
            return result

        with db.connect() as conn:
            conn.execute(
                "UPDATE events SET gcal_event_id = ? WHERE id = ?",
                (gcal_id, new_id),
            )
        result["gcal_event_id"] = gcal_id

    return result
```

Y actualizar la entrada de `add_event` en `TOOL_DEFINITIONS` para incluir el nuevo flag. Reemplazar el bloque actual del schema de `add_event`:

```python
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "datetime_iso": {
                    "type": "string",
                    "description": "Fecha y hora ISO 8601 sin zona, ej. 2026-05-22T17:00:00",
                },
                "category": {
                    "type": "string",
                    "enum": list(CATEGORIES),
                },
                "recurring_rule": {"type": ["string", "null"]},
                "notes": {"type": ["string", "null"]},
                "sync_to_calendar": {
                    "type": "boolean",
                    "default": False,
                    "description": (
                        "Si es true, además de añadir el evento al bot, lo manda a "
                        "Google Calendar. Úsala SOLO cuando el usuario lo pida "
                        "explícitamente ('mételo en el calendario' y similares)."
                    ),
                },
            },
            "required": ["title", "datetime_iso", "category"],
        },
```

- [ ] **Step 4: Implementar `push_event_to_calendar` y `connect_calendar` en `tools.py`**

Añadir después de `delete_event`:

```python
def push_event_to_calendar(event_id: int) -> dict:
    """Sincroniza un evento existente con Google Calendar.

    - Si ya está sincronizado, no hace nada (idempotente).
    - Si Pablo no ha autorizado todavía, devuelve error 'not_connected'.
    - Guarda el gcal_event_id en la fila.
    """
    with db.connect() as conn:
        row = conn.execute(
            "SELECT id, title, datetime, category, notes, gcal_event_id"
            " FROM events WHERE id = ?",
            (event_id,),
        ).fetchone()

    if row is None:
        return {"event_id": event_id, "synced": False, "error": "not_found"}

    if row["gcal_event_id"]:
        return {
            "event_id": event_id,
            "synced": True,
            "already_synced": True,
            "gcal_event_id": row["gcal_event_id"],
        }

    try:
        gcal_id = gcal_sync.push_event({
            "title": row["title"],
            "datetime": row["datetime"],
            "category": row["category"],
            "notes": row["notes"],
        })
    except gcal_sync.NotConnected:
        return {"event_id": event_id, "synced": False, "error": "not_connected"}
    except Exception:
        log.exception("Error pushing event %s a Calendar", event_id)
        return {"event_id": event_id, "synced": False, "error": "api_error"}

    with db.connect() as conn:
        conn.execute(
            "UPDATE events SET gcal_event_id = ? WHERE id = ?",
            (gcal_id, event_id),
        )

    return {"event_id": event_id, "gcal_event_id": gcal_id, "synced": True}


def connect_calendar() -> dict:
    """Devuelve la URL OAuth para que el usuario autorice."""
    return {"auth_url": gcal_sync.oauth_start_url()}
```

En el dict `_DISPATCH` al final del archivo, añadir:

```python
    "push_event_to_calendar": push_event_to_calendar,
    "connect_calendar": connect_calendar,
```

En la lista `TOOL_DEFINITIONS`, añadir (al final, antes del cierre `]`):

```python
    {
        "name": "push_event_to_calendar",
        "description": (
            "Sincroniza un evento existente con Google Calendar. Úsala cuando "
            "Pablo diga 'mételo en el calendario', 'pásalo a Google Calendar', "
            "'manda al calendario' o variantes, o justo después de add_event si "
            "el mismo mensaje pedía sincronizar. Si devuelve error 'not_connected', "
            "avisa al usuario de que ejecute 'conecta con calendar'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"event_id": {"type": "integer"}},
            "required": ["event_id"],
        },
    },
    {
        "name": "connect_calendar",
        "description": (
            "Devuelve la URL de autorización OAuth para conectar el bot con "
            "Google Calendar. Úsala cuando Pablo diga 'conecta con calendar', "
            "'autoriza Google Calendar', o cuando push_event_to_calendar haya "
            "devuelto error 'not_connected'."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
```

- [ ] **Step 5: Verificar tests**

Run: `./.venv/bin/python -m pytest tests/test_tools_events.py tests/test_tools_registry.py -v`
Expected: PASS.

- [ ] **Step 6: Suite completa**

Run: `./.venv/bin/python -m pytest`
Expected: todo pasa.

- [ ] **Step 7: Commit**

```bash
git add tools.py tests/test_tools_events.py tests/test_tools_registry.py
git commit -m "$(cat <<'EOF'
feat(tools): add sync_to_calendar flag, push_event_to_calendar, connect_calendar

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Endpoint `/oauth/callback` y notificación por Telegram

**Files:**
- Modify: `gcal_sync.py`
- Create: tests `tests/test_gcal_oauth_endpoint.py`
- Modify: `bot.py`

- [ ] **Step 1: Escribir test del endpoint**

Crear `tests/test_gcal_oauth_endpoint.py`:

```python
import os
import tempfile
from unittest.mock import AsyncMock, patch

import pytest
from aiohttp import web

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


def _make_app(telegram_bot, allowed_user_id):
    app = web.Application()
    gcal_sync.register_oauth_routes(app, telegram_bot=telegram_bot, allowed_user_id=allowed_user_id)
    return app


async def test_callback_with_valid_code_saves_tokens_and_pings_telegram(aiohttp_client):
    tg_bot = AsyncMock()
    client = await aiohttp_client(_make_app(tg_bot, 42))

    with patch("gcal_sync.exchange_code") as ex:
        resp = await client.get("/oauth/callback?code=THE-CODE")

    assert resp.status == 200
    body = await resp.text()
    assert "Calendar conectado" in body
    ex.assert_called_once_with("THE-CODE")
    tg_bot.send_message.assert_awaited_once()
    args = tg_bot.send_message.await_args.kwargs
    assert args["chat_id"] == 42
    assert "Calendar conectado" in args["text"]


async def test_callback_without_code_returns_400(aiohttp_client):
    client = await aiohttp_client(_make_app(AsyncMock(), 42))
    resp = await client.get("/oauth/callback")
    assert resp.status == 400


async def test_callback_with_error_query_returns_400(aiohttp_client):
    client = await aiohttp_client(_make_app(AsyncMock(), 42))
    resp = await client.get("/oauth/callback?error=access_denied")
    assert resp.status == 400
    body = await resp.text()
    assert "denegada" in body.lower() or "error" in body.lower()


async def test_callback_exchange_fails_returns_500(aiohttp_client):
    tg_bot = AsyncMock()
    client = await aiohttp_client(_make_app(tg_bot, 42))
    with patch("gcal_sync.exchange_code", side_effect=RuntimeError("boom")):
        resp = await client.get("/oauth/callback?code=BAD")
    assert resp.status == 500
```

- [ ] **Step 2: Verificar que falla**

Run: `./.venv/bin/python -m pytest tests/test_gcal_oauth_endpoint.py -v`
Expected: FAIL (`register_oauth_routes` no existe).

- [ ] **Step 3: Implementar `register_oauth_routes` en `gcal_sync.py`**

Al final de `gcal_sync.py` añadir:

```python
def register_oauth_routes(app, *, telegram_bot, allowed_user_id: int) -> None:
    """Monta `/oauth/callback` en la aiohttp Application dada.

    `telegram_bot` debe tener un método async `send_message(chat_id, text, parse_mode)`.
    `allowed_user_id` es el único user al que le notificamos el éxito.
    """
    from aiohttp import web

    async def _on_callback(request):
        if "error" in request.query:
            log.warning("OAuth callback con error: %s", request.query["error"])
            return web.Response(
                text="<h1>Autorización denegada</h1><p>Vuelve a Telegram y prueba otra vez.</p>",
                status=400,
                content_type="text/html",
            )
        code = request.query.get("code")
        if not code:
            return web.Response(
                text="<h1>Falta el código</h1>",
                status=400,
                content_type="text/html",
            )
        try:
            exchange_code(code)
        except Exception:
            log.exception("Error intercambiando código OAuth")
            return web.Response(
                text="<h1>Algo ha fallado</h1><p>Vuelve a Telegram e inténtalo en un momento.</p>",
                status=500,
                content_type="text/html",
            )

        try:
            await telegram_bot.send_message(
                chat_id=allowed_user_id,
                text="✅ Calendar conectado. Ya puedo mandar tus eventos a Google Calendar.",
                parse_mode="HTML",
            )
        except Exception:
            log.exception("Error notificando éxito de OAuth en Telegram")

        return web.Response(
            text="<h1>✅ Calendar conectado</h1><p>Vuelve a Telegram.</p>",
            status=200,
            content_type="text/html",
        )

    app.router.add_get("/oauth/callback", _on_callback)
```

- [ ] **Step 4: Verificar tests**

Run: `./.venv/bin/python -m pytest tests/test_gcal_oauth_endpoint.py -v`
Expected: PASS los 4 tests.

- [ ] **Step 5: Registrar el endpoint en `bot.py`**

En `bot.py`, dentro de `_async_main`, justo después de:

```python
    siri_app = siri_server.build_app(
        telegram_bot=app.bot,
        brain_fn=brain.handle_message,
        siri_token=SIRI_TOKEN,
        allowed_user_id=ALLOWED_USER_ID,
    )
```

Añadir:

```python
    import gcal_sync
    gcal_sync.register_oauth_routes(
        siri_app,
        telegram_bot=app.bot,
        allowed_user_id=ALLOWED_USER_ID,
    )
```

- [ ] **Step 6: Suite completa**

Run: `./.venv/bin/python -m pytest`
Expected: todo pasa.

- [ ] **Step 7: Commit**

```bash
git add gcal_sync.py bot.py tests/test_gcal_oauth_endpoint.py
git commit -m "$(cat <<'EOF'
feat(gcal): /oauth/callback endpoint with Telegram notification

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: Botón inline "📅 Mandar a Calendar" en la confirmación

Este task tiene la complicación de que `brain.handle_message` devuelve texto, pero el botón requiere `InlineKeyboardMarkup`. Estrategia: `brain.py` mantiene un dict `_pending_calendar_button[user_id] = event_id` que se rellena cuando Claude llama a `add_event` y vacía cuando llama a `push_event_to_calendar`. `bot.py` lee este registro tras `handle_message` y, si tiene un `event_id`, adjunta el botón al `reply_text`.

**Files:**
- Modify: `brain.py`
- Modify: `bot.py`
- Modify: `tests/test_brain.py`
- Modify: `tests/test_bot.py`

- [ ] **Step 1: Tests para el registro en brain**

Añadir al final de `tests/test_brain.py`:

```python
def test_pending_calendar_button_starts_empty():
    import brain
    brain.reset_calendar_button(42)
    assert brain.pop_pending_calendar_button(42) is None


def test_record_then_pop_calendar_button():
    import brain
    brain.reset_calendar_button(42)
    brain.record_pending_calendar_button(42, event_id=7)
    assert brain.pop_pending_calendar_button(42) == 7
    # tras pop, queda vacío
    assert brain.pop_pending_calendar_button(42) is None


def test_push_event_to_calendar_clears_pending():
    import brain
    brain.reset_calendar_button(42)
    brain.record_pending_calendar_button(42, event_id=7)
    brain.clear_pending_calendar_button(42)
    assert brain.pop_pending_calendar_button(42) is None
```

- [ ] **Step 2: Verificar que fallan**

Run: `./.venv/bin/python -m pytest tests/test_brain.py -v -k calendar_button`
Expected: FAIL.

- [ ] **Step 3: Implementar el registro en `brain.py`**

En `brain.py`, después del bloque `_history: dict[int, list[dict]] = {}`, añadir:

```python
# Event id pendiente de "ofrecer botón Mandar a Calendar" por usuario.
# Se rellena cuando Claude llama a add_event sin sincronizar y se vacía cuando
# bot.py lee el registro (o cuando Claude llama a push_event_to_calendar).
_pending_calendar_button: dict[int, int] = {}


def record_pending_calendar_button(user_id: int, event_id: int) -> None:
    _pending_calendar_button[user_id] = event_id


def pop_pending_calendar_button(user_id: int) -> int | None:
    return _pending_calendar_button.pop(user_id, None)


def clear_pending_calendar_button(user_id: int) -> None:
    _pending_calendar_button.pop(user_id, None)


def reset_calendar_button(user_id: int) -> None:
    """Alias semántico para tests."""
    clear_pending_calendar_button(user_id)
```

En el loop de tool_use dentro de `handle_message`, justo antes de `result = tools.dispatch(...)`, capturar el id del usuario para registrar el botón cuando se cree un evento sin push inmediato. Reemplazar:

```python
                try:
                    result = tools.dispatch(block.name, dict(block.input))
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": str(result),
                    })
```

por:

```python
                try:
                    result = tools.dispatch(block.name, dict(block.input))
                    if (
                        block.name == "add_event"
                        and isinstance(result, dict)
                        and "id" in result
                        and "gcal_event_id" not in result  # ya sincronizado en línea
                    ):
                        record_pending_calendar_button(user_id, result["id"])
                    elif block.name == "push_event_to_calendar":
                        clear_pending_calendar_button(user_id)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": str(result),
                    })
```

- [ ] **Step 4: Verificar tests del registro**

Run: `./.venv/bin/python -m pytest tests/test_brain.py -v -k calendar_button`
Expected: PASS.

- [ ] **Step 5: Tests del callback `gcs` y del botón en bot.py**

Añadir al final de `tests/test_bot.py`:

```python
def test_callback_action_gcs_calls_push_event_to_calendar(monkeypatch):
    import bot
    called = {}
    def fake_push(event_id):
        called["event_id"] = event_id
        return {"event_id": event_id, "synced": True, "gcal_event_id": "g1"}
    monkeypatch.setattr(bot.tools, "push_event_to_calendar", fake_push)
    handler = bot._CALLBACK_ACTIONS["gcs"]
    result = handler(99)
    assert called["event_id"] == 99
    assert result["synced"] is True
```

- [ ] **Step 6: Verificar que falla**

Run: `./.venv/bin/python -m pytest tests/test_bot.py -v -k gcs`
Expected: FAIL (no existe la acción `gcs`).

- [ ] **Step 7: Añadir el callback `gcs` en `bot.py`**

En `_CALLBACK_ACTIONS` (línea ~249), añadir:

```python
    "gcs": lambda i: tools.push_event_to_calendar(i),
```

En `_on_callback_query`, hay que asegurarse de que al re-renderizar tras `gcs` no se rompe — la lógica actual asume que tras el handler hay que re-renderizar una vista (H/P/W). Para `gcs` no procede re-renderizar `/hoy` ni nada similar: simplemente editamos el mensaje quitando el teclado y añadiendo "✅ Enviado a Calendar".

Justo después del bloque `try: handler(item_id)` y antes del bloque `today = date_utils.today_madrid()`, añadir:

```python
    if action_type == "gcs":
        try:
            # Quitamos el teclado y mantenemos el texto original con un sufijo.
            original = query.message.text_html if query.message else ""
            await query.edit_message_text(
                f"{original}\n\n✅ Enviado a Calendar",
                parse_mode=ParseMode.HTML,
                reply_markup=None,
            )
        except BadRequest:
            log.warning("No pude editar el mensaje del botón Calendar")
        await query.answer("Enviado a Calendar")
        return
```

- [ ] **Step 8: Adjuntar el botón en el reply de mensajes**

En `bot.py`, modificar `_on_message` para que, si tras `process_incoming` `brain.pop_pending_calendar_button(user_id)` devuelve un id, adjunte un `InlineKeyboardMarkup`.

Reemplazar:

```python
async def _on_message(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return
    reply = process_incoming(
        text=update.message.text,
        from_user_id=update.effective_user.id,
    )
    if reply is not None:
        await update.message.reply_text(reply, parse_mode=ParseMode.HTML)
```

por:

```python
async def _on_message(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return
    user_id = update.effective_user.id
    reply = process_incoming(text=update.message.text, from_user_id=user_id)
    if reply is None:
        return
    keyboard = _calendar_button_keyboard(user_id)
    await update.message.reply_text(reply, parse_mode=ParseMode.HTML, reply_markup=keyboard)
```

Y hacer lo mismo en `_on_voice` (el bloque final que llama a `reply_text`):

```python
    reply = process_voice_transcription(transcription, from_user_id=from_user_id)
    if reply is None:
        return
    keyboard = _calendar_button_keyboard(from_user_id)
    await update.message.reply_text(reply, parse_mode=ParseMode.HTML, reply_markup=keyboard)
```

Definir `_calendar_button_keyboard` justo antes de `_on_message`:

```python
from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def _calendar_button_keyboard(user_id: int):
    """Si brain dejó un event_id pendiente, devuelve un teclado con el botón.
    Si no, None.
    """
    event_id = brain.pop_pending_calendar_button(user_id)
    if event_id is None:
        return None
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("📅 Mandar a Calendar", callback_data=f"gcs:{event_id}"),
    ]])
```

- [ ] **Step 9: Suite completa**

Run: `./.venv/bin/python -m pytest`
Expected: todo pasa.

- [ ] **Step 10: Commit**

```bash
git add brain.py bot.py tests/test_brain.py tests/test_bot.py
git commit -m "$(cat <<'EOF'
feat(bot): inline button to push event to Calendar on confirmation

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: System prompt — Claude aprende los triggers de Calendar

**Files:**
- Modify: `brain.py`
- Modify: `tests/test_brain.py`

- [ ] **Step 1: Test que verifica que el prompt menciona las tools**

Añadir a `tests/test_brain.py`:

```python
def test_system_prompt_mentions_calendar_tools():
    import brain
    prompt = brain._system_prompt()
    assert "push_event_to_calendar" in prompt
    assert "connect_calendar" in prompt
    # Frases-trigger esperadas
    assert "calendar" in prompt.lower()
```

- [ ] **Step 2: Verificar que falla**

Run: `./.venv/bin/python -m pytest tests/test_brain.py -v -k system_prompt_mentions_calendar`
Expected: FAIL.

- [ ] **Step 3: Añadir la sección al system prompt**

En `brain.py`, dentro de la f-string de `_system_prompt()`, añadir un bloque nuevo después del bloque "Marcar cosas como hechas (TRES herramientas distintas según el tipo):" y antes de "Formato de las respuestas (Telegram HTML):":

```
Sincronización con Google Calendar:
- Cuando Pablo añada un evento Y pida sincronizarlo en el mismo mensaje ("y mételo en el calendario", "y al calendario", "y pásalo a Google Calendar", "y súbelo al calendar" o variantes), llama a add_event con sync_to_calendar=true. Confirma con UNA frase corta (ej. "Apuntado y mandado al calendario").
- Cuando Pablo pida sincronizar un evento ya existente ("manda la reunión de Marta al calendario", "sube esa cita a Google"), busca el evento con query_events y llama a push_event_to_calendar(event_id).
- Cuando Pablo diga "conecta con calendar", "autoriza Google Calendar" o equivalente, llama a connect_calendar y devuélvele el auth_url como enlace clicable, p.ej.: «Autoriza el bot aquí: <a href="URL">conectar Calendar</a>».
- Si add_event devuelve sync_error="not_connected" o push_event_to_calendar devuelve {"error": "not_connected"}, responde: «Primero tienes que conectar Calendar. Dime "conecta con calendar" y te paso el enlace.»
- Si add_event NO incluye sync explícito por parte de Pablo, NO uses sync_to_calendar — el bot mostrará un botón inline para que Pablo decida.
```

- [ ] **Step 4: Verificar tests**

Run: `./.venv/bin/python -m pytest tests/test_brain.py -v`
Expected: PASS.

- [ ] **Step 5: Suite completa**

Run: `./.venv/bin/python -m pytest`
Expected: todo pasa.

- [ ] **Step 6: Commit**

```bash
git add brain.py tests/test_brain.py
git commit -m "$(cat <<'EOF'
feat(brain): system prompt learns Calendar sync triggers

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 13: Deploy y prueba en producción

Este task no es TDD — son acciones de despliegue. Ejecútalo solo cuando los 12 anteriores estén cerrados y la suite verde.

**Files:** ninguno

- [ ] **Step 1: Confirmar suite verde y working tree limpio**

Run: `./.venv/bin/python -m pytest && git status`
Expected: tests verdes y working tree clean (todos los commits hechos).

- [ ] **Step 2: Avisar a Pablo y desplegar**

Decir a Pablo: "Voy a desplegar Google Calendar. Si tienes el bot corriendo en local con `./start.sh`, párelo antes (Ctrl+C) — el deploy va a tomar el polling y daría 409."

Cuando confirme:

```bash
flyctl deploy --app mi-secretaria-pablo
```

- [ ] **Step 3: Verificar logs**

```bash
flyctl logs --app mi-secretaria-pablo --no-tail
```

Expected: ver `"Bot arrancando (polling + HTTP en :8080)…"` sin trazas de error.

- [ ] **Step 4: Probar el flujo de autorización**

Pedir a Pablo:
1. Escribir al bot: *"conecta con calendar"*.
2. Bot debe responder con un enlace.
3. Tocar el enlace → consent screen de Google → autorizar.
4. Browser debe mostrar "✅ Calendar conectado".
5. En Telegram debe llegar el mensaje "✅ Calendar conectado…".

- [ ] **Step 5: Probar push, update, delete**

1. *"apunta dentista el viernes a las 10 y mételo en el calendario"* → debe aparecer en Google Calendar.
2. *"cambia el dentista al sábado a las 11"* → la fecha cambia en Google Calendar.
3. *"borra el dentista"* (con confirmación) → desaparece de Google Calendar.

- [ ] **Step 6: Probar el botón inline**

1. *"apunta cena con Marta el sábado a las 21"* (sin pedir sync).
2. Mensaje de confirmación debe traer un botón `📅 Mandar a Calendar`.
3. Tap → mensaje se edita a `✅ Enviado a Calendar` y el evento aparece en Google Calendar.

- [ ] **Step 7: Actualizar memoria**

Reemplazar el archivo `gcal-state-2026-05-28.md` por uno nuevo o editarlo: cambiar `Estado` de "diseño aprobado, pendiente plan + implementación" a "implementado y desplegado el 2026-05-29".

---

## Notas operativas

- **Tokens en SQLite**: van sin cifrar. Aceptado en el diseño porque solo Pablo accede a la BD y el bot es personal.
- **Errores de Calendar nunca rompen el bot**: están envueltos en `try/except` y solo loguean.
- **El bot ignora Calendar si no hay credenciales**: `GOOGLE_CLIENT_ID` vacío hace que `oauth_start_url()` genere una URL inválida; la solución preferida es que la pantalla de conexión no se pida si no están — Pablo ya tiene los secrets en Fly, así que no es un problema real, pero conviene tenerlo en mente para futuras instancias.
- **No se sincronizan rutinas**: si en el futuro queremos, hay que decidir cómo expresar `recurring_rule` en Calendar (`RRULE`). Está fuera del MVP.

---

## Fuera del alcance (recordatorio)

Listado en la spec, no implementamos nada de esto:

- Lectura de Calendar al bot.
- Sync automático sin que Pablo lo pida.
- Sincronizar rutinas, tareas u objetivos.
- Elegir calendario distinto al principal.
- Duración configurable (siempre 1h).
- Invitados.
- Webhooks de Calendar al bot.
- Multi-cuenta.
- Tokens cifrados.

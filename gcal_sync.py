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

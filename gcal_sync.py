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


class NotConnected(Exception):
    """No hay tokens guardados — el usuario debe autorizar."""


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

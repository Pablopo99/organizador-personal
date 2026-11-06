"""Carga de configuración y constantes globales."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

_PROJECT_ROOT = Path(__file__).parent.resolve()


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"Falta la variable de entorno {name}. "
            f"Revisa tu archivo .env (puedes copiar .env.example)."
        )
    return value


TELEGRAM_TOKEN = _require("TELEGRAM_TOKEN")
AIKIT_API_KEY = _require("AIKIT_API_KEY")
# Modelo de AiKit: "fast" (2-6 s) o "expert" (más lento). Ver docs de AiKit.
AIKIT_MODEL = os.environ.get("AIKIT_MODEL", "fast")
ALLOWED_USER_ID = int(_require("ALLOWED_USER_ID"))

# Opcional: si está vacía, el bot ignorará mensajes de voz con respuesta de "no configurado".
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

SIRI_TOKEN = _require("SIRI_TOKEN")

# Credenciales OAuth de Google Calendar. Si están vacías, la sincronización
# con Calendar queda deshabilitada (el bot sigue funcionando normal).
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.environ.get(
    "GOOGLE_REDIRECT_URI",
    "https://mi-secretaria-pablo.fly.dev/oauth/callback",
)

# Nombre del usuario (para personalizar el tono del bot y el saludo matutino).
# Por defecto "Pablo"; cada persona que despliegue su copia puede ponerlo en su .env.
USER_NAME = os.environ.get("USER_NAME", "Pablo")

TIMEZONE = "Europe/Madrid"
DB_PATH = os.environ.get("DB_PATH") or str(_PROJECT_ROOT / "organizador.db")
CATEGORIES = ("medical", "work", "personal", "other")

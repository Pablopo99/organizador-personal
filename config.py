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
ANTHROPIC_API_KEY = _require("ANTHROPIC_API_KEY")
ALLOWED_USER_ID = int(_require("ALLOWED_USER_ID"))

# Opcional: si está vacía, el bot ignorará mensajes de voz con respuesta de "no configurado".
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

TIMEZONE = "Europe/Madrid"
DB_PATH = os.environ.get("DB_PATH") or str(_PROJECT_ROOT / "organizador.db")
CATEGORIES = ("medical", "work", "personal", "other")
CLAUDE_MODEL = "claude-sonnet-4-6"

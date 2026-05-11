"""Fixtures globales y entorno mínimo para todos los tests."""
import os

os.environ.setdefault("TELEGRAM_TOKEN", "test-telegram-token")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-anthropic-key")
os.environ.setdefault("ALLOWED_USER_ID", "42")

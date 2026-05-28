"""Fixtures globales y entorno mínimo para todos los tests."""
import os

os.environ.setdefault("TELEGRAM_TOKEN", "test-telegram-token")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-anthropic-key")
os.environ.setdefault("ALLOWED_USER_ID", "42")
os.environ.setdefault("GROQ_API_KEY", "test-groq-key")
os.environ.setdefault("SIRI_TOKEN", "test-siri-token")

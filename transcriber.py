"""Transcripción de audio a texto usando Groq Whisper API."""
from typing import Optional

from groq import Groq

from config import GROQ_API_KEY


class TranscriptionUnavailable(Exception):
    """Se lanza cuando no hay clave de Groq configurada."""


_client: Optional[Groq] = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None


def transcribe(audio_bytes: bytes) -> str:
    """Transcribe audio a texto en español usando Groq Whisper.

    Devuelve el texto transcrito (limpio de espacios al inicio/final).
    Lanza TranscriptionUnavailable si no hay API key configurada.
    Propaga cualquier otra excepción de la SDK de Groq al caller.
    """
    if _client is None:
        raise TranscriptionUnavailable(
            "GROQ_API_KEY no está configurada en .env"
        )

    result = _client.audio.transcriptions.create(
        file=("audio.ogg", audio_bytes),
        model="whisper-large-v3",
        language="es",
        response_format="text",
    )

    if isinstance(result, str):
        return result.strip()
    return getattr(result, "text", "").strip()

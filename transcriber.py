"""Transcripción de audio a texto usando Groq Whisper API."""
import re
from typing import Optional

from groq import Groq

from config import GROQ_API_KEY


class TranscriptionUnavailable(Exception):
    """Se lanza cuando no hay clave de Groq configurada."""


# Frases que Whisper alucina cuando el audio es silencio/ruido en español.
# Vienen de su corpus de entrenamiento (YouTube, subtítulos comunitarios).
_HALLUCINATION_MARKERS = (
    "gracias por ver",
    "subtitulos por",
    "subtítulos por",
    "subtitulado por",
    "amara.org",
    "suscribete al canal",
    "suscríbete al canal",
    "subtítulos realizados por la comunidad",
    "subtitulos realizados por la comunidad",
    "subtítulos hechos por la comunidad",
    "subtitulos hechos por la comunidad",
)

_PUNCT_RE = re.compile(r"[^\w\s]")


def _is_likely_hallucination(text: str) -> bool:
    """True si la transcripción parece una alucinación típica de Whisper sobre silencio."""
    normalized = _PUNCT_RE.sub("", text.lower()).strip()
    if not normalized:
        return True
    return any(marker in normalized for marker in _HALLUCINATION_MARKERS)


_client: Optional[Groq] = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None


def transcribe(audio_bytes: bytes) -> str:
    """Transcribe audio a texto en español usando Groq Whisper.

    Devuelve el texto transcrito (limpio de espacios al inicio/final).
    Si la transcripción coincide con una alucinación típica sobre silencio, devuelve "".
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
        text = result.strip()
    else:
        text = getattr(result, "text", "").strip()

    if _is_likely_hallucination(text):
        return ""
    return text

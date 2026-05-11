from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import transcriber


def test_transcribe_returns_text_from_string_response(monkeypatch):
    """Cuando Groq devuelve directamente un string (response_format='text')."""
    mock_client = MagicMock()
    mock_client.audio.transcriptions.create.return_value = "Hola, esto es una prueba"
    monkeypatch.setattr(transcriber, "_client", mock_client)

    result = transcriber.transcribe(b"fake-audio-bytes")
    assert result == "Hola, esto es una prueba"


def test_transcribe_returns_text_from_object_response(monkeypatch):
    """Cuando Groq devuelve un objeto con atributo .text."""
    mock_client = MagicMock()
    mock_client.audio.transcriptions.create.return_value = SimpleNamespace(text="con objeto")
    monkeypatch.setattr(transcriber, "_client", mock_client)

    result = transcriber.transcribe(b"fake-audio-bytes")
    assert result == "con objeto"


def test_transcribe_strips_whitespace(monkeypatch):
    mock_client = MagicMock()
    mock_client.audio.transcriptions.create.return_value = "  texto con espacios  \n"
    monkeypatch.setattr(transcriber, "_client", mock_client)

    result = transcriber.transcribe(b"fake")
    assert result == "texto con espacios"


def test_transcribe_passes_spanish_language(monkeypatch):
    """Debe forzar language='es' para evitar transcripciones falsas en inglés."""
    mock_client = MagicMock()
    mock_client.audio.transcriptions.create.return_value = "ok"
    monkeypatch.setattr(transcriber, "_client", mock_client)

    transcriber.transcribe(b"fake")

    call_kwargs = mock_client.audio.transcriptions.create.call_args.kwargs
    assert call_kwargs["language"] == "es"
    assert call_kwargs["model"] == "whisper-large-v3"


def test_transcribe_raises_when_no_client(monkeypatch):
    monkeypatch.setattr(transcriber, "_client", None)

    with pytest.raises(transcriber.TranscriptionUnavailable):
        transcriber.transcribe(b"fake")


def test_transcribe_propagates_groq_exception(monkeypatch):
    mock_client = MagicMock()
    mock_client.audio.transcriptions.create.side_effect = RuntimeError("groq down")
    monkeypatch.setattr(transcriber, "_client", mock_client)

    with pytest.raises(RuntimeError, match="groq down"):
        transcriber.transcribe(b"fake")

"""Cliente de AiKit (API compatible con OpenAI Chat Completions).

Es la única pieza del bot que habla con el proveedor de IA. Si algún día se
cambia de proveedor, solo hay que tocar este archivo.
"""
import logging
import time

import requests

from config import AIKIT_API_KEY, AIKIT_MODEL

log = logging.getLogger("llm_client")

_URL = "https://cms.aikit.es/api/inference/chat/completions"
_TIMEOUT_S = 60
_RETRY_DELAY_S = 2


class LLMError(Exception):
    """Fallo al hablar con la IA (red, servidor, respuesta inválida)."""


class RateLimitError(LLMError):
    """429: límite de peticiones o presupuesto de AiKit agotado."""


def to_openai_tools(tool_definitions: list[dict]) -> list[dict]:
    """Convierte las tools del formato Anthropic (`input_schema`) al de OpenAI."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t["input_schema"],
            },
        }
        for t in tool_definitions
    ]


def chat(system: str, messages: list[dict], tools: list[dict]) -> dict:
    """Manda la conversación a AiKit y devuelve el `message` de la respuesta.

    `tools` va en formato Anthropic (tools.TOOL_DEFINITIONS); se convierte aquí.
    Un reintento ante 5xx o fallo de red. 429 → RateLimitError; resto → LLMError.
    """
    body = {
        "model": AIKIT_MODEL,
        "messages": [{"role": "system", "content": system}, *messages],
    }
    if tools:
        body["tools"] = to_openai_tools(tools)

    last_error: Exception | None = None
    for attempt in range(2):
        if attempt:
            time.sleep(_RETRY_DELAY_S)
        try:
            response = requests.post(
                _URL,
                json=body,
                headers={"Authorization": f"Bearer {AIKIT_API_KEY}"},
                timeout=_TIMEOUT_S,
            )
        except requests.RequestException as exc:
            log.warning("Fallo de red con AiKit (intento %d): %s", attempt + 1, exc)
            last_error = exc
            continue

        if response.status_code == 429:
            raise RateLimitError(response.text[:300])
        if response.status_code >= 500:
            log.warning("AiKit devolvió %s (intento %d)", response.status_code, attempt + 1)
            last_error = LLMError(f"HTTP {response.status_code}")
            continue
        if response.status_code != 200:
            raise LLMError(f"HTTP {response.status_code}: {response.text[:300]}")

        fallback = response.headers.get("X-AiKit-Model-Fallback")
        if fallback:
            log.warning("AiKit no reconoce el modelo %r; ha usado %s", AIKIT_MODEL, fallback)
        try:
            return response.json()["choices"][0]["message"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"Respuesta inesperada de AiKit: {response.text[:300]}") from exc

    raise LLMError(f"AiKit no responde tras reintentar: {last_error}")

# Migración del cerebro de Anthropic a AiKit — diseño

**Fecha:** 2026-11-06
**Decisiones de Pablo:** modelo `fast`; solo AiKit (sin respaldo de Claude); probar en el bot real.

## Contexto

AiKit (`POST https://cms.aikit.es/api/inference/chat/completions`) es compatible con
OpenAI Chat Completions. Verificado el 2026-11-06 con la clave real:

- `tools` + `tool_calls` funcionan (ida y vuelta completa con mensajes `role: "tool"`).
- `fast` responde en ~4 s. Los nombres `claude/fast` y `gpt/fast` no existen en la
  cuenta → AiKit cae a `aikit/fast` (cabecera `X-AiKit-Model-Fallback`).
- Límite: 100 req/min por clave; presupuesto agotado → 429 `ORG_BUDGET_EXCEEDED`.
- No garantiza JSON válido → los `arguments` de cada tool call se validan.

## Diseño

1. **`llm_client.py` (nuevo)** — única pieza que habla con AiKit.
   - `chat(system, messages, tools) -> dict` devuelve el `message` del primer choice.
   - Convierte `tools.TOOL_DEFINITIONS` (formato Anthropic: `input_schema`) a formato
     OpenAI (`{"type":"function","function":{name, description, parameters}}`).
   - Errores: 429 → `RateLimitError`; resto → `LLMError`. Un reintento en 5xx/timeout.
   - Si llega `X-AiKit-Model-Fallback`, se loguea un warning.
2. **`brain.py`** — el bucle de herramientas pasa a formato OpenAI:
   `assistant.tool_calls[]` → ejecutar → `{"role":"tool","tool_call_id","content"}`.
   Argumentos con JSON inválido → resultado de error a la IA (no crash).
   Se elimina el prompt caching (específico de Anthropic). Toda la lógica de efectos
   secundarios (botón Calendar, subida de nivel, recordatorios inmediatos) se conserva.
3. **`bot.py`** — captura `llm_client.RateLimitError` en vez de `anthropic.RateLimitError`;
   el mensaje deja de nombrar a Anthropic.
4. **Config** — `AIKIT_API_KEY` obligatoria, `AIKIT_MODEL` (default `fast`).
   Se retira `ANTHROPIC_API_KEY` y la dependencia `anthropic`.

## Fuera de alcance

Respaldo automático a Claude, modo mixto fast/expert, historial persistente.

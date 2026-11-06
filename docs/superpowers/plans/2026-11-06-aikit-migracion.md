# Plan — migración a AiKit

Spec: `docs/superpowers/specs/2026-11-06-aikit-migracion-design.md`

1. **llm_client** — tests (`tests/test_llm_client.py`): conversión de tools, payload
   enviado (system primero, model, tools), 429 → RateLimitError, 5xx → reintento y
   luego LLMError. Implementar `llm_client.py` + config `AIKIT_API_KEY`/`AIKIT_MODEL`.
   Commit `feat(llm): cliente AiKit compatible OpenAI`.
2. **brain** — reescribir los tests de `test_brain.py` que simulan el SDK de Anthropic
   para simular `llm_client.chat`; añadir test de argumentos JSON inválidos.
   Reescribir el bucle de `handle_message`. Commit `feat(brain): usar AiKit`.
3. **bot + limpieza** — `bot.py` captura `llm_client.RateLimitError`; quitar
   `anthropic` de requirements/config/conftest/.env.example/CLAUDE.md.
   Commit `refactor: retirar Anthropic`.
4. **Deploy** — `flyctl secrets set AIKIT_API_KEY=…`, deploy, prueba real en Telegram.

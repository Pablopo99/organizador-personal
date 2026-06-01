# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

A personal Telegram bot ("Mi Secretaria") that helps Pablo (single authorized user) manage events, tasks, weekly objectives and daily routines. It's deployed to Fly.io as `mi-secretaria-pablo` (region `cdg`, Paris) and talks to him in Spanish.

## Common commands

```bash
# Run the full test suite (use absolute venv path — chained `source activate && python` is unreliable)
./.venv/bin/python -m pytest

# Run a single test file or pattern
./.venv/bin/python -m pytest tests/test_views.py -v
./.venv/bin/python -m pytest -k "streak"

# Start the bot locally (keeps Mac awake via caffeinate)
./start.sh

# Deploy to Fly
flyctl deploy --app mi-secretaria-pablo

# Tail Fly logs
flyctl logs --app mi-secretaria-pablo --no-tail

# Set/update Fly secrets
flyctl secrets set --app mi-secretaria-pablo KEY=value
```

**Never run the local bot and the Fly deployment at the same time** — they share the same `TELEGRAM_TOKEN` and Telegram returns 409 Conflict if two pollers compete.

## Architecture in three layers

```
Telegram ─► bot.py ─► brain.py ─► tools.py ─► db.py ─► SQLite
                │                     ▲
                └────► views.py ──────┘  (for /hoy, /pendientes, /semana, morning)
```

- **`bot.py`** — Telegram listener. Auth-gates every entry point with `ALLOWED_USER_ID`. Routes:
  - Slash commands `/semana`, `/objetivos`, `/rachas` → `_SLASH_PROMPTS` dict → `brain.handle_message` (Claude does the work).
  - Slash command `/hoy` → dedicated `_on_hoy` handler that calls `views.render_today_view` directly (bypasses Claude for instant tap response). Same pattern likely for `/pendientes` and `/semana` over time.
  - Free text and voice → `brain.handle_message` (Claude with tool use).
  - Button taps → `_on_callback_query`. Callback data format `{action}{type}:{id}[:{view}]` (e.g. `mE:42`, `mR:5`, `uT:7`). View letter (H/P/W) selects which render function re-paints the message; default H for backward compatibility with old messages.

- **`brain.py`** — Claude tool-use loop. One `_history` dict per `user_id` (in-memory, lost on restart). The system prompt is the source of truth for tone, formatting rules (HTML for Telegram), section templates and the strict rules for slash-command summaries.

- **`tools.py`** — All Claude-callable functions plus a few **internal** helpers not registered in `TOOL_DEFINITIONS` (the `unmark_*` / `uncomplete_*` family, used only by callback handlers). `mark_event_done` is **smart-routed**: for non-recurring events it sets `done=1`; for events with `recurring_rule` it inserts a row in `routine_completions` for today's Madrid date (idempotent via UNIQUE).

- **`views.py`** — Deterministic renderers used by `/hoy` and `morning_summary`. Return `(html_text, InlineKeyboardMarkup | None)`. The keyboard has one row per item: `🔲 {title}` for pending, `✅ {title}` for done-today (tap toggles).

- **`scheduler.py`** — Two APScheduler jobs registered in `bot.main()`:
  - `morning_summary` daily at 09:00 Madrid → sends greeting + `views.render_today_view` output.
  - `check_reminders` every 5 min → para eventos puntuales ≤26h, manda los avisos por defecto ⏰ 1h-before y 📅 1d-before. **Los eventos con cualquier fila en `event_reminders` quedan excluidos de los defaults** (custom = control total, ver feature de recordatorios personalizados). En la misma pasada también revisa `event_reminders` con `sent=0` y dispara los customs cuya antelación cae en la ventana ±5 min (`"⏰ En {pretty} tienes: …"`). Excluye eventos recurrentes (gap pendiente, ver [[pending-recurring-reminders]]).

- **`db.py`** — SQLite schema and `connect()` context manager. **Every connection enables `PRAGMA foreign_keys = ON`** so `ON DELETE CASCADE` actually fires (not default in SQLite). Migrations are idempotent additive only.

- **`date_utils.py`** — `today_madrid()` and `now_madrid_naive()` are the source of truth for "today/now" because the Fly container runs UTC by default. `now_iso()` returns Madrid wall time. **Gotcha**: `tools.py` imports `now_iso` *by name* at module load, so `monkeypatch.setattr(date_utils, "now_iso", ...)` does NOT affect `tools.now_iso`. `today_madrid` is referenced as `date_utils.today_madrid()` in `tools.py`, so patching the module attribute works.

## Data model (SQLite)

- `events(id, title, datetime, category, recurring_rule, notes, created_at, done, reminder_1d_sent, reminder_1h_sent)` — `recurring_rule` is `'DAILY'`, `'WEEKLY:MON'`..`'WEEKLY:SUN'`, or NULL.
- `tasks(id, text, done, created_at, done_at)` — no date.
- `objectives(id, text, week_start, done, created_at)` — `week_start` always normalized to Monday.
- `routine_completions(id, event_id, completion_date, created_at)` — UNIQUE(event_id, completion_date), FK to `events.id` ON DELETE CASCADE. Records that a recurring event was done on a specific date. Powers RUTINAS section, streaks and per-instance "done today" rendering.
- `xp_log(id, item_type, item_id, outcome, xp_amount, streak_bonus, awarded_at)` — append-only ledger del sistema de niveles/XP. Cada acción que da XP (tarea/evento/rutina/objetivo on_time o grace, día perfecto, semana perfecta) inserta una fila positiva. Las reversiones (`uncomplete_*`, `unmark_*`) insertan una fila negativa con `outcome='reversal'`. `compute_level(SUM(xp_amount))` da el nivel actual. NO tiene FK a events/tasks/objectives a propósito (conserva historial aunque el item original se borre).

## Workflow conventions

This project follows the **superpowers** methodology strictly. For every non-trivial change:

1. **Brainstorming** — clarify with the user, propose options. (Skip only for pure deploys/infra.)
2. **Spec** in `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md` — committed.
3. **Plan** in `docs/superpowers/plans/YYYY-MM-DD-<feature>.md` — committed.
4. **TDD execution**: failing test → minimal implementation → test passes → commit. Each task in the plan ends in its own commit.
5. **Commit messages** use Conventional Commits (`feat(scope): …`, `fix(scope): …`, `docs: …`, `refactor: …`) with this trailer:

   ```
   Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
   ```

The user is non-technical — explain the *why*, not just the *what*. Present option lists with `AskUserQuestion` for decisions. Don't decide for him on UX or product calls.

## Deploy notes

- App: `mi-secretaria-pablo`. Region `cdg` (Madrid is not in Fly's catalog).
- Persistent volume `data` mounted at `/data` — SQLite lives at `/data/organizador.db`.
- `Dockerfile` sets `TZ=Europe/Madrid` so naive `datetime.now()` returns wall-clock Madrid time. Tests still patch `date_utils.today_madrid` for reproducibility.
- Polling, not webhook — bot makes outbound calls to Telegram. No HTTP service exposed.
- Secrets in Fly: `TELEGRAM_TOKEN`, `ANTHROPIC_API_KEY`, `ALLOWED_USER_ID`, `GROQ_API_KEY` (optional, for voice), `DB_PATH=/data/organizador.db`.

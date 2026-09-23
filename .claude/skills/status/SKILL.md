---
name: status
description: Quick bot health check - is it running, today's posts, recent errors
allowed-tools: Bash Read
---

Quick health check, read-only:

1. Running? `pgrep -if "python.*main\.py"` and `cat bot.lock` (PID of the
   running `main.py`).
2. Toronto time: `TZ=America/Toronto date "+%F %T %Z"`, and Waking hours:
   `uv run python -c "from src.active_hours import is_active; print(is_active())"`.
   Silence Overnight is normal.
3. Today's Profile publications against the ceiling of seven:
   `uv run python -c "from src import action_guard; print(action_guard.profile_count_today())"`
4. Editorial slots: `jq '{date, slots, attempts}' editorial_state.json`.
   A `pending` slot is never retried: see `docs/OPERATIONS.md#recovery`.
5. Last 30 lines of `bot.log`: last `[EDITORIAL]`/`[POST]` and `[REPLY]`
   lines, errors, `[HEALTH]` Safari restarts.

Report:
- Bot running? (yes/no + PID), Waking hours or Overnight
- Today: Profile publications X/7, slots published / pending
- Last activity timestamp
- Any errors in recent logs

---
name: engage
description: Trigger one engage cycle by hand - follow and like accounts from the feed-discovered pool
disable-model-invocation: true
allowed-tools: Bash Read
---

Trigger one engage cycle, the same one `engage_job` runs every 8 minutes.
Only on an explicit operator request: it follows and likes on the real account.

1. The bot must be stopped: `pgrep -if "python.*main\.py"` returns nothing.
   The Safari lock only serialises writes inside one process. If it runs,
   suggest `/stop` first.
2. Only during active hours (04:30–22:00 Toronto); the chokepoints refuse
   writes outside them.
3. Run `uv run python -c "from src.engage_bot import safe_run_engage_cycle; safe_run_engage_cycle()"`
4. Report from the `[ENGAGE]`, `[FOLLOW]` and `[LIKE]` lines of `bot.log`:
   profiles visited, follows made or refused by the follow policy, likes.

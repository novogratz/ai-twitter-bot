---
name: engage
description: Trigger one engage cycle by hand - follow and like accounts from the feed-discovered pool
disable-model-invocation: true
allowed-tools: Bash Read
---

Trigger one engage cycle, the same one `engage_job` runs every 8 minutes.
Only on an explicit operator request: it follows and likes on the real account.

1. Preconditions in `docs/OPERATIONS.md#manual-writes`. Check:
   `pgrep -if "python.*main\.py"` prints nothing and
   `uv run python -c "from src.guards.active_hours import is_active; print(is_active())"`
   prints `True`. If the bot runs, suggest `/stop` first.
2. Run `uv run python -c "from src.core import health; from src.account.engage_bot import run_engage_cycle; health.wrap_job(run_engage_cycle, 'engage')()"`
3. Report from the `[ENGAGE]`, `[FOLLOW]` and `[LIKE]` lines of `bot.log`:
   profiles visited, follows made or refused by the follow policy, likes
   (the `[LIKE] @handle: …` summary counts liked, already liked, blocked
   and failed). A failed cycle logs `[engage] Cycle failed.` with its
   traceback, and an unreadable state file `[HEALTH] engage halted`, in
   `bot.log` only: report those too.

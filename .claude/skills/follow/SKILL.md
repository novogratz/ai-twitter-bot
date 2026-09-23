---
name: follow
description: Follow a specific account through the follow policy
arguments: [username]
disable-model-invocation: true
allowed-tools: Bash Read Write
---

Follow @$username. Only on an explicit operator request.

1. Strip @ if present
2. Preconditions in `docs/OPERATIONS.md#manual-writes`. Check:
   `pgrep -if "python.*main\.py"` prints nothing and
   `uv run python -c "from src.guards.active_hours import is_active; print(is_active())"`
   prints `True`.
3. Run `uv run python -c "from src.x.twitter_client import follow_account; print(follow_account('$username'))"`
   - `follow_account` applies the follow policy: whitelist-only, daily cap,
     spacing, total-following ceiling, 30-day anti-churn, quality gate. A
     refusal is logged as `[FOLLOW] policy refuses …` in `bot.log`.
4. Only if it printed `True`, add the handle to `followed_accounts.json`
   if not already there. `False` or `DRY_RUN_RECORDED` means nothing
   shipped: write nothing.
5. Report the result and, on refusal, the reason from `bot.log`.

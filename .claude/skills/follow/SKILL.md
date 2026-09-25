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
4. Write nothing yourself: `follow_account` adds the handle to
   `followed_accounts.json` on `FollowOutcome.FOLLOWED` and
   `FollowOutcome.ALREADY_FOLLOWED`. Only `FOLLOWED` shipped a follow.
5. Report the result and, on a refusal (`TOO_SOON`, `CAP_REACHED`,
   `QUALITY_REJECTED`, `REFUSED`), the reason from `bot.log`.

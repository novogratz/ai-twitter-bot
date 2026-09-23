---
name: unfollow
description: Mass-unfollow from the /following page in Safari (ratio repair) — skips the protected keep-set, records to the action ledger
arguments: [max]
disable-model-invocation: true
allowed-tools: Bash Read
---

Mass-unfollow accounts directly on https://x.com/$BOT_HANDLE/following in Safari.
Only on an explicit operator request.

The script refuses to start Overnight, stops before its next unfollow at
22:00 Toronto or on SIGTERM, and stops after `--max` unfollows (150 by
default).

1. Preconditions in `docs/OPERATIONS.md#manual-writes`. Check:
   `pgrep -if "python.*main\.py"` prints nothing and
   `uv run python -c "from src.active_hours import is_active; print(is_active())"`
   prints `True`. Never pass `--force`.
2. `--max`: `$max` if the operator gave it, capped at 150, the default,
   which stays under X's unfollow quota of about 190 per window (the
   script's help). Keep pace `normal` (the default): about 5–9 s per
   unfollow and a 20–40 s breather every 25 (≈480/h), so 150 take about
   27 minutes. A run started close to 22:00 stops short of `--max`.
   ```bash
   nohup .venv/bin/python bin/mass_unfollow.py --max N >/tmp/mass_unfollow.log 2>&1 &
   tail -f /tmp/mass_unfollow.log
   ```
3. To stop it early: `pkill -f bin/mass_unfollow.py`. It stops before its
   next unfollow and prints `TOTAL unfollowed:`.
4. What it does per unfollow: pick the first visible `Following` button not
   in the keep-set, click it, confirm the `confirmationSheetConfirm` modal,
   record to `action_ledger.json` (30-day anti-churn) and decrement
   `following_count.json`. It stops at `--max`, at 22:00 Toronto, on
   SIGTERM, when the list is exhausted (empty after 3 reloads) or on
   repeated JS errors. A rate-limit toast or 5 failed confirms trigger a
   cooldown, never an abort: if the log shows repeated `COOLDOWN` lines, X
   is blocking the action; tell the operator.
5. Keep-set (`--keep`): default `whitelist` = current `whitelist.json` tiers +
   `seeds[]` (the curated follow list; never unfollow what the follow policy
   may follow, or the 30-day anti-churn record would block the re-follow).
   `--keep legacy` adds respect_list + engage/early-bird/mega target lists
   (gentle prune).
6. Report the final `TOTAL unfollowed:` count, the `STOP:` line if any, and
   the new ratio if available. Unfollowed handles are in
   `mass_unfollow_results.json`, rewritten after every unfollow.

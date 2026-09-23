---
name: unfollow
description: Mass-unfollow from the /following page in Safari (ratio repair) — skips the protected keep-set, records to the action ledger
arguments: [max]
disable-model-invocation: true
allowed-tools: Bash Read
---

Mass-unfollow accounts directly on https://x.com/$BOT_HANDLE/following in Safari.
Only on an explicit operator request.

Until issue #122 ships, `bin/mass_unfollow.py` checks no Waking hours,
defaults `--max` to 10**6 and never aborts on a rate limit: a run started
late keeps unfollowing Overnight. This skill bounds it by hand.

1. Preconditions in `docs/OPERATIONS.md#manual-writes`. Check:
   `pgrep -if "python.*main\.py"` prints nothing and
   `uv run python -c "from src.active_hours import is_active; print(is_active())"`
   prints `True`. Never pass `--force`.
2. Start cutoff: `TZ=America/Toronto date +%H:%M` must be 21:00 or earlier;
   otherwise stop and tell the operator. Pace `normal` (the default, keep it)
   spends per unfollow 1.2 s before the confirm plus a 3.5–7 s jittered gap
   plus two `osascript` calls, about 5–9 s, and a 20–40 s breather every 25
   (≈480/h, the script's help). `--max 150` then ends within about 27
   minutes; the hour before 22:00 leaves about 30 minutes for rate-limit
   cooldowns (2 min, +50% per consecutive hit, capped at 8 min) and page
   reloads.
3. `--max` is mandatory: `$max` if the operator gave it, capped at 150,
   which also stays under X's unfollow quota of about 190 per window (the
   script's help).
   ```bash
   nohup .venv/bin/python bin/mass_unfollow.py --max N >/tmp/mass_unfollow.log 2>&1 &
   tail -f /tmp/mass_unfollow.log
   ```
4. If it still runs at 21:55 Toronto, stop it: `pkill -f bin/mass_unfollow.py`.
   Each unfollow is already in the ledger; report the last `[n] unfollowed`
   line, since `mass_unfollow_results.json` is written only at the end.
5. What it does per unfollow: pick the first visible `Following` button not
   in the keep-set, click it, confirm the `confirmationSheetConfirm` modal,
   record to `action_ledger.json` (30-day anti-churn) and decrement
   `following_count.json`. It stops at `--max`, when the list is exhausted
   (empty after 3 reloads) or on repeated JS errors. A rate-limit toast or 5
   failed confirms trigger a cooldown, never an abort: if the log shows
   repeated `COOLDOWN` lines, X is blocking the action; tell the operator.
6. Keep-set (`--keep`): default `whitelist` = current `whitelist.json` tiers +
   `seeds[]` (the curated follow list; never unfollow what the follow policy
   may follow, or the 30-day anti-churn record would block the re-follow).
   `--keep legacy` adds respect_list + engage/early-bird/mega target lists
   (gentle prune).
7. Report the final `TOTAL unfollowed:` count and the new ratio if available.
   Unfollowed handles are saved to `mass_unfollow_results.json`.

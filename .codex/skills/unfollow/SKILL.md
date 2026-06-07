---
name: unfollow
description: Mass-unfollow from the /following page in Safari (ratio repair) — skips the protected keep-set, records to the action ledger
arguments: [max]
allowed-tools: Bash Read
---

Mass-unfollow accounts directly on https://x.com/$BOT_HANDLE/following in Safari.

1. Check the bot is stopped (`pgrep -f "python.*main.py"`) — it shares Safari.
   If running, suggest `/stop` first (the script also refuses on its own).
2. Run in the background and tail progress:
   ```bash
   .venv/bin/python bin/mass_unfollow.py 2>&1 | tee /tmp/mass_unfollow.log
   ```
   Optional: `--max N` to cap the run, `--force` to bypass the bot-running check.
3. What it does per cycle: pick the first visible `Following` button not in the
   protected keep-set, click it, confirm the `confirmationSheetConfirm` modal,
   record to `action_ledger.json` (30-day anti-churn) and decrement
   `following_count.json`, then sleep 3.5–7s jittered with a 20–40s breather
   every 25. Scrolls when no buttons left; stops after 6 empty scroll rounds
   (list exhausted) or 5 consecutive failed confirms (likely X action block —
   tell the operator).
4. Keep-set (`--keep`): default `whitelist` = current `whitelist.json` tiers +
   `seeds[]` (the 2026-06-07 curated follow list — full purge; never unfollow
   what `marquee_follow_bot` must follow, or the 30d anti-churn record would
   block the re-follow). `--keep legacy` adds respect_list +
   engage/early-bird/mega target lists (gentle prune).
5. Report the final `TOTAL unfollowed:` count and the new ratio if available.
   Unfollowed handles are saved to `mass_unfollow_results.json`.

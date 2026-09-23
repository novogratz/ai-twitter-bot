---
name: reply
description: Trigger one direct reply cycle by hand - scan the feeds and searches, reply through Reply admission
disable-model-invocation: true
allowed-tools: Bash Read
---

Trigger one reply scan, the same one `direct_reply_job` runs every 2 minutes.
Only on an explicit operator request: it replies on the real account.

1. The bot must be stopped: `pgrep -if "python.*main\.py"` returns nothing.
   The Safari lock only serialises writes inside one process. If it runs,
   suggest `/stop` first.
2. Only during active hours (04:30–22:00 Toronto); the chokepoints refuse
   writes outside them.
3. Run `uv run python -c "from src.direct_reply import safe_run_direct_reply_cycle; safe_run_direct_reply_cycle(max_replies=3)"`
   - `max_replies` bounds the search pass only; the VIP scan runs whole.
   - Each candidate goes through `reply_admission.judge_parent` before
     generation; `reply_to_tweet` checks and marks `replied_tweets.json`.
     Never pre-mark that store by hand.
4. Report from the `[DIRECT]` and `[REPLY]` lines of `bot.log`: how many
   replies shipped and to which status URLs.

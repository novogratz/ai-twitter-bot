---
name: reply
description: Prepare Reply drafts by hand through the shared admission and ranked queue
disable-model-invocation: true
allowed-tools: Bash Read
---

Trigger one reply scan, the same one `direct_reply_job` runs every 2 minutes.
Only on an explicit operator request: it scans the real account and uses models.
For the ranked live Account this prepares drafts only. The scheduler's separate
selector compares and publishes at most one approved draft after the shared
75–95 second cooldown. This skill does not start that scheduler or bypass review.

1. Preconditions in `docs/OPERATIONS.md#manual-writes`. Check:
   `pgrep -if "python.*main\.py"` prints nothing and
   `uv run python -c "from src.guards.active_hours import is_active; print(is_active())"`
   prints `True`. If the bot runs, suggest `/stop` first.
2. Run `uv run python -c "from src.core import health; from src.replies.direct_reply import run_direct_reply_cycle; health.wrap_job(lambda: run_direct_reply_cycle(max_replies=3), 'direct_reply')()"`
   - `max_replies` bounds the search pass only; the VIP scan runs whole.
   - Each candidate goes through `reply_admission.judge_parent` before
     generation; `reply_to_tweet` checks and marks `replied_tweets.json`.
     Never pre-mark that store by hand.
3. Report from the `[DIRECT]` and `[REPLY]` lines of `bot.log`: how many
   drafts were prepared and their status URLs. Do not report a queued draft as
   published; the collector returns zero shipped Replies in ranked mode. A failed cycle logs
   `[direct_reply] Cycle failed.` with its traceback, and an unreadable
   state file `[HEALTH] direct_reply halted`, in `bot.log` only: report
   those too.

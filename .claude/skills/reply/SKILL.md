---
name: reply
description: Collect posts, compare the saved Reply pool, and send at most one selected Reply
disable-model-invocation: true
allowed-tools: Bash Read
---

Collect one reply scan, wait for comparison eligibility, then run the shared
Reply selector. Only on an explicit operator request: the selector can reply
on the real account. Scanning alone saves posts and never sends Replies.

1. Preconditions in `docs/OPERATIONS.md#manual-writes`. Check:
   `pgrep -if "python.*main\.py"` prints nothing and
   `uv run python -c "from src.guards.active_hours import is_active; print(is_active())"`
   prints `True`. If the bot runs, suggest `/stop` first.
2. Run the direct scan with `run_direct_reply_cycle()` wrapped by
   `health.wrap_job(..., 'direct_reply')`. This archives every discovered
   status and queues eligible standalone posts. Never pre-mark the Replied store.
3. Wait at least sixty seconds after new discoveries, then run
   `uv run python -c "from src.core import health; from src.replies.reply_selector import run_reply_selection_cycle; health.wrap_job(run_reply_selection_cycle, 'reply_selection', safari_health=False)()"`.
   The selector compares saved candidates and drafts at most one scoring
   85/100 or higher; it can reject them all. Hourly allowances, active windows,
   the ten-per-day cap including ambiguous submissions, and all Reply
   admission/write guards still apply. An allowance is never a quota to fill.
4. Report the saved count and the `[SELECTION]`, `[SELECTED]` and `[REPLY]`
   log lines: selected URL, score/reason, and confirmed shipment only.
   An unreadable pool or unsavable archive stops the work; report the halt
   rather than replacing or deleting guarded state. Pool and archive live
   through `reply_pool.POOL` and `reply_pool.ARCHIVE` under `state_store.root()`.

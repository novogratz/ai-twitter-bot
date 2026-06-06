---
name: approve
description: Review and publish posts waiting in the human-approval queue (REVIEW_MODE)
allowed-tools: Bash Read
---

Review-queue approval flow (only relevant when `REVIEW_MODE=1` in `.env`):

1. Read `review_queue.json`. If empty/missing → "queue is empty", done.
2. Show each pending item: kind (post / post_gif / quote / quote_gif), text,
   gif query and/or target URL, queued_at.
3. Ask the operator which items to approve (all / by index / none).
4. For each approved item, publish with REVIEW_MODE off for the call:
   ```bash
   REVIEW_MODE=0 uv run python -c "
   from src.twitter_client import post_tweet, post_tweet_with_gif, quote_tweet, quote_tweet_with_gif
   # dispatch on item['kind'] with the stored payload fields
   "
   ```
5. Remove published (and operator-rejected) items from `review_queue.json`.
6. Report what shipped and what was discarded.

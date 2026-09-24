---
name: stats
description: Show the engagement stats dashboard - originals, replies, follows, reach
allowed-tools: Bash Read Glob
---

Show engagement stats, read-only:

1. `action_ledger.json` - counted writes (`post`, `reply`, `follow`, `like`, `pin`,
   `debate_turn`…) with Toronto timestamps, one JSON object per line (`jq -c`
   filters it row by row, `jq -s` reads it as one list); skip rows with
   `dry_run: true`
2. `editorial_state.json` - today's slots and the recent `published` originals
3. `editorial_review.jsonl` - approvals and rejection reasons of recent drafts
4. `editorial_reach.md` - observed views of the last seven days of originals
   against the 500,000 target
5. `engagement_log.csv` - append-only action log
6. `replied_tweets.json` - tweets already answered, by status ID
7. `followed_accounts.json` - accounts followed

Present a clean summary:
- Today: originals published against the target of six (Profile
  publications against the ceiling of eight), replies sent, follows, likes
- Last 7 days per day
- Last 5 originals and last 5 replies
- Reach against target, with the missing coverage the report states
- Patterns (review rejection reasons, most active hour)

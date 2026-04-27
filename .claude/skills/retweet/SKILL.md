---
name: retweet
description: Trigger one selective retweet cycle - scrapes trusted news outlets, picks the best candidate, retweets if score >= 9/10, logs picks >= 8/10 to daily_news_picks.md
allowed-tools: Bash
---

Run one retweet cycle:

1. Run `python3 -c "from src.retweet_bot import run_retweet_cycle; run_retweet_cycle()"`
2. Show the picked tweet (if any) and the score
3. If anything was logged, surface the new entries in `daily_news_picks.md`

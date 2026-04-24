---
name: stats
description: Show full engagement stats dashboard - posts, replies, follows, history
allowed-tools: Bash Read Glob
---

Show engagement stats:

1. Read `engagement_log.csv` - count posts, replies, hot takes, quote tweets by day
2. Read `daily_state.json` - today's counters
3. Read `replied_tweets.json` - total unique tweets replied to
4. Read `followed_accounts.json` - accounts followed
5. Read `tweet_history.json` - recent tweet topics

Present a clean summary:
- Today: news posted, hot takes posted, replies sent
- All-time totals
- Last 5 tweets and last 5 replies
- Patterns or insights (posting rate, most active hour, etc.)

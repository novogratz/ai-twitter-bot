Show engagement stats for the bot. Analyze all available data:

1. Read `engagement_log.csv` to get posting history - count posts, replies, hot takes, quote tweets by day
2. Read `daily_state.json` to get today's counters
3. Read `replied_tweets.json` to count total unique tweets replied to
4. Read `followed_accounts.json` to count accounts followed
5. Read `tweet_history.json` to check recent tweet topics
6. Present a clean summary:
   - Today's numbers: news posted, hot takes posted, replies sent
   - Total all-time: posts, replies, follows
   - Last 5 tweets posted (with timestamps if available)
   - Last 5 replies sent (with target URLs)
   - Any patterns or insights (e.g. "posting rate is X/hour", "most active hour", etc.)

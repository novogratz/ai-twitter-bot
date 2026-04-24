---
name: thread
description: Post a multi-tweet thread manually
disable-model-invocation: true
arguments: [tweets]
allowed-tools: Bash
---

Post a thread:

1. Parse "$tweets" - split by "---" to get individual tweets
2. Validate each is under 280 chars
3. Show preview with tweet numbers
4. Ask for confirmation
5. Post: `python3 -c "from src.twitter_client import post_thread; post_thread($TWEET_LIST)"`

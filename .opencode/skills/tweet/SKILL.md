---
name: tweet
description: Post a specific tweet right now
arguments: [text]
allowed-tools: Bash
---

Post a tweet with the provided text:

1. Validate the text "$text" is under 280 characters
2. Post it: `python3 -c "from src.twitter_client import post_tweet; post_tweet('''$text''')"`
3. Confirm posted

If no text provided, ask what to tweet.

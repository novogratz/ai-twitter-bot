Post a specific tweet right now. The user provides the tweet text as an argument.

Usage: /tweet "your tweet text here"

1. Take the argument text as the tweet content
2. Validate it's under 280 characters
3. Run `python -c "from src.twitter_client import post_tweet; post_tweet('$ARGUMENTS')"` to post it
4. Confirm the tweet was posted

If no argument provided, ask the user what they want to tweet.

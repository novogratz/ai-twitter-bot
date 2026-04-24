Post a thread right now. The user provides the tweets separated by newlines or "---".

Usage: /thread "tweet 1 --- tweet 2 --- tweet 3"

1. Parse the argument - split by "---" or newlines to get individual tweets
2. Validate each tweet is under 280 characters
3. Show the thread preview to the user with tweet numbers
4. Ask for confirmation
5. Run: `python -c "from src.twitter_client import post_thread; post_thread(['tweet1', 'tweet2', ...])"` to post
6. Confirm the thread was posted

"""Generate a single tweet, print it, and post it."""
from src.agent import generate_tweet
from src.twitter_client import post_tweet
from src.history import save_tweet

print("Searching for AI news and generating tweet...\n")
tweet = generate_tweet()
if tweet is None:
    print("No fresh news found - nothing to post.")
else:
    print(f"Tweet ({len(tweet)} chars):\n")
    print(tweet)
    print("\nPosting to Twitter...")
    post_tweet(tweet)
    save_tweet(tweet)
    print("Done!")

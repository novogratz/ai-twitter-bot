import traceback
from .agent import generate_tweet
from .twitter_client import post_tweet, post_thread
from .history import save_tweet

THREAD_SEPARATOR = "---THREAD---"


def run_bot_cycle():
    """Search for AI news and post a tweet (or thread)."""
    print("Searching for AI news...")
    tweet = generate_tweet()
    if tweet is None:
        print("No fresh news - skipping this cycle.")
        return

    # Check if it's a thread
    if THREAD_SEPARATOR in tweet:
        parts = [p.strip() for p in tweet.split(THREAD_SEPARATOR) if p.strip()]
        print(f"[THREAD] Got {len(parts)}-tweet thread:")
        for i, part in enumerate(parts, 1):
            print(f"  [{i}] ({len(part)} chars): {part[:80]}...")
        post_thread(parts)
        # Save the full thread as one entry for dedup
        save_tweet(tweet)
    else:
        print(f"Tweet ({len(tweet)} chars):\n{tweet}")
        post_tweet(tweet)
        save_tweet(tweet)


def safe_run_bot_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    try:
        run_bot_cycle()
    except Exception:
        print("Error during bot cycle:")
        traceback.print_exc()

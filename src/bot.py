import traceback
from .agent import generate_tweet
from .twitter_client import post_tweet
from .history import save_tweet


def run_bot_cycle():
    """Let Claude search the web, generate a French AI tweet, and post it."""
    print("Agent searching for AI news and generating tweet...")
    tweet = generate_tweet()
    if tweet is None:
        print("No fresh news found — skipping this cycle.")
        return
    print(f"Generated tweet ({len(tweet)} chars):\n{tweet}")
    post_tweet(tweet)
    save_tweet(tweet)


def safe_run_bot_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    try:
        run_bot_cycle()
    except Exception:
        print("Error during bot cycle:")
        traceback.print_exc()

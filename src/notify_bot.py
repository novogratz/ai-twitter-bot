import traceback
from .twitter_client import like_own_tweet_replies


def run_notify_cycle():
    """Visit own latest tweet, like replies, and build loyalty."""
    print("[NOTIFY] Checking replies on latest tweet...")
    like_own_tweet_replies()
    print("[NOTIFY] Done.")


def safe_run_notify_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    try:
        run_notify_cycle()
    except Exception:
        print("[NOTIFY] Error during notify cycle:")
        traceback.print_exc()

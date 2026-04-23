import random
import traceback
from .agent import generate_tweet
from .hotake_agent import generate_hotake
from .twitter_client import post_tweet, post_thread
from .history import save_tweet
from .engagement_log import log_post, log_hotake

THREAD_SEPARATOR = "---THREAD---"

# Track last post type to alternate
_last_was_hotake = False


def run_bot_cycle():
    """Post either a news tweet or a hot take (alternating)."""
    global _last_was_hotake

    # 50/50 news and hot takes for maximum volume
    # Never two hot takes in a row
    do_hotake = not _last_was_hotake and random.random() < 0.5

    if do_hotake:
        print("[HOTAKE] Generating hot take (no web search)...")
        tweet = generate_hotake()
        if tweet is None:
            print("[HOTAKE] Failed, falling back to news...")
            tweet = generate_tweet()
        else:
            _last_was_hotake = True
            print(f"[HOTAKE] ({len(tweet)} chars):\n{tweet}")
            post_tweet(tweet)
            save_tweet(tweet)
            log_hotake(tweet)
            return
    else:
        _last_was_hotake = False

    print("Searching for AI news...")
    tweet = generate_tweet()
    if tweet is None:
        # No news? Post a hot take instead
        print("No fresh news - trying a hot take instead...")
        tweet = generate_hotake()
        if tweet is None:
            print("Nothing to post - skipping this cycle.")
            return
        _last_was_hotake = True

    # Check if it's a thread
    if THREAD_SEPARATOR in tweet:
        parts = [p.strip() for p in tweet.split(THREAD_SEPARATOR) if p.strip()]
        print(f"[THREAD] Got {len(parts)}-tweet thread:")
        for i, part in enumerate(parts, 1):
            print(f"  [{i}] ({len(part)} chars): {part[:80]}...")
        post_thread(parts)
        save_tweet(tweet)
        log_post(tweet)
    else:
        print(f"Tweet ({len(tweet)} chars):\n{tweet}")
        post_tweet(tweet)
        save_tweet(tweet)
        log_post(tweet)


def safe_run_bot_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    try:
        run_bot_cycle()
    except Exception:
        print("Error during bot cycle:")
        traceback.print_exc()

import random
import traceback
from datetime import date
from .agent import generate_tweet
from .hotake_agent import generate_hotake
from .twitter_client import post_tweet, post_thread
from .history import save_tweet
from .engagement_log import log_post, log_hotake

THREAD_SEPARATOR = "---THREAD---"

# Daily counters - reset each day
_today = None
_news_count = 0
_hotake_count = 0

MAX_NEWS_PER_DAY = 70      # ~3-4 per hour across 18 active hours
MAX_HOTAKES_PER_DAY = 20   # ~1 per hour


def _reset_if_new_day():
    """Reset counters at midnight."""
    global _today, _news_count, _hotake_count
    today = date.today()
    if _today != today:
        _today = today
        _news_count = 0
        _hotake_count = 0


def run_bot_cycle():
    """Post a news tweet or hot take, respecting daily limits."""
    global _news_count, _hotake_count
    _reset_if_new_day()

    print(f"[POST] Today: {_news_count}/{MAX_NEWS_PER_DAY} news, {_hotake_count}/{MAX_HOTAKES_PER_DAY} hot takes")

    # Check if we've hit both limits
    if _news_count >= MAX_NEWS_PER_DAY and _hotake_count >= MAX_HOTAKES_PER_DAY:
        print("[POST] Daily limits reached. Skipping.")
        return

    # Decide what to post
    can_hotake = _hotake_count < MAX_HOTAKES_PER_DAY
    can_news = _news_count < MAX_NEWS_PER_DAY

    # ~22% hot takes (1 per hour out of ~4-5 posts per hour)
    do_hotake = can_hotake and (not can_news or random.random() < 0.22)

    if do_hotake:
        print("[HOTAKE] Generating AI philosophy hot take...")
        tweet = generate_hotake()
        if tweet is None:
            print("[HOTAKE] Failed, falling back to news...")
            if can_news:
                tweet = generate_tweet()
                if tweet:
                    _news_count += 1
        else:
            _hotake_count += 1
            print(f"[HOTAKE] ({len(tweet)} chars):\n{tweet}")
            post_tweet(tweet)
            save_tweet(tweet)
            log_hotake(tweet)
            return
    else:
        print("Searching for AI news...")
        tweet = generate_tweet()
        if tweet:
            _news_count += 1
        elif can_hotake:
            print("No fresh news - trying a hot take instead...")
            tweet = generate_hotake()
            if tweet:
                _hotake_count += 1

    if tweet is None:
        print("Nothing to post - skipping this cycle.")
        return

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

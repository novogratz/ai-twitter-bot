"""Pin-boost bot — un-retweet then re-retweet the pinned tweet every hour.

Cycling the pinned tweet (undo RT → re-RT) makes it appear fresh in
followers' feeds and picks up new reach without posting anything new.
Runs on startup and every 1h via the scheduler.
"""
import traceback

from .config import BOT_HANDLE
from .logger import log
from .twitter_client import scrape_profile_tweets, reboost_tweet


def run_pin_boost_cycle() -> None:
    log.info(f"[PIN_BOOST] Scraping @{BOT_HANDLE} to find pinned tweet...")
    try:
        tweets = scrape_profile_tweets(BOT_HANDLE, max_tweets=1)
    except Exception:
        log.info("[PIN_BOOST] Failed to scrape profile:")
        traceback.print_exc()
        return

    if not tweets:
        log.info("[PIN_BOOST] No tweets found on profile. Skipping.")
        return

    pinned_url = tweets[0].get("url", "")
    if not pinned_url:
        log.info("[PIN_BOOST] Could not extract URL from first tweet. Skipping.")
        return

    log.info(f"[PIN_BOOST] Pinned tweet: {pinned_url}")
    try:
        reboost_tweet(pinned_url)
    except Exception:
        log.info("[PIN_BOOST] Reboost failed:")
        traceback.print_exc()


def safe_run_pin_boost_cycle() -> None:
    from . import health
    try:
        run_pin_boost_cycle()
        health.record_success("pin_boost")
    except Exception:
        log.info("[PIN_BOOST] Unhandled error:")
        traceback.print_exc()
        health.record_failure("pin_boost")

"""Notify bot: likes replies on own tweets and replies back to build loyalty."""
import traceback
from .logger import log
from .twitter_client import like_own_tweet_replies, retweet_own_latest


def run_notify_cycle():
    """Visit own latest tweet, like replies, and build loyalty."""
    log.info("[NOTIFY] Checking replies on latest tweet...")
    like_own_tweet_replies()
    log.info("[NOTIFY] Done.")


def run_boost_cycle():
    """Retweet own latest tweet for extra exposure in followers' feeds."""
    log.info("[BOOST] Boosting latest tweet...")
    retweet_own_latest()
    log.info("[BOOST] Done.")


def safe_run_notify_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    try:
        run_notify_cycle()
    except Exception:
        log.info("[NOTIFY] Error during notify cycle:")
        traceback.print_exc()


def safe_run_boost_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    try:
        run_boost_cycle()
    except Exception:
        log.info("[BOOST] Error during boost cycle:")
        traceback.print_exc()

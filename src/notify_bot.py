"""Notify bot: likes replies on own tweets and replies back to build loyalty."""
import json
import os
import traceback
from .config import _PROJECT_ROOT
from .logger import log
from .twitter_client import (
    like_own_tweet_replies,
    retweet_own_latest,
    scrape_own_tweet_and_replies,
    reply_to_tweet,
)
from .replyback_agent import generate_replyback
from .humanizer import humanize

REPLIED_BACK_FILE = os.path.join(_PROJECT_ROOT, "replied_back.json")


def _load_replied_back() -> set:
    if os.path.exists(REPLIED_BACK_FILE):
        try:
            with open(REPLIED_BACK_FILE, "r") as f:
                return set(json.load(f))
        except (json.JSONDecodeError, IOError):
            pass
    return set()


def _save_replied_back(replied: set):
    with open(REPLIED_BACK_FILE, "w") as f:
        json.dump(list(replied)[-200:], f, indent=2)


def run_notify_cycle():
    """Visit own latest tweet, like replies, and build loyalty."""
    log.info("[NOTIFY] Checking replies on latest tweet...")
    like_own_tweet_replies()
    log.info("[NOTIFY] Done.")


def run_replyback_cycle():
    """Scrape replies on own tweets and reply back to create conversation threads.
    Threads boost both tweets in the algorithm."""
    log.info("[REPLYBACK] Scanning for replies to engage with...")

    data = scrape_own_tweet_and_replies()
    if not data or not data.get("replies"):
        log.info("[REPLYBACK] No replies found.")
        return

    own_tweet = data["own_tweet"]
    replies = data["replies"]
    replied_back = _load_replied_back()
    count = 0

    for reply_info in replies[:3]:  # Max 3 reply-backs per cycle
        user = reply_info.get("user", "")
        text = reply_info.get("text", "")

        # Dedup key: first 50 chars of their reply
        dedup_key = text[:50]
        if dedup_key in replied_back:
            continue

        # Skip our own replies
        if "kzer_ai" in user.lower():
            continue

        # Skip very short or empty replies
        if len(text) < 5:
            continue

        log.info(f"[REPLYBACK] Replying to: {user}: {text[:60]}...")
        reply = generate_replyback(own_tweet, text)
        if not reply:
            continue

        reply = humanize(reply)
        log.info(f"[REPLYBACK] Reply ({len(reply)} chars): {reply}")

        # We can't easily reply to a specific reply via URL, so we post as a
        # new reply on our own tweet. This still creates a thread effect.
        # The reply-back shows up in the conversation.
        try:
            # Post as a reply-style tweet mentioning the user
            from .twitter_client import post_tweet
            # Include @mention so they get notified
            handle = user.split("@")[-1].strip() if "@" in user else ""
            if handle:
                full_reply = f"@{handle} {reply}"
            else:
                full_reply = reply
            post_tweet(full_reply)
            replied_back.add(dedup_key)
            count += 1
        except Exception:
            log.info(f"[REPLYBACK] Failed to reply back:")
            traceback.print_exc()

    _save_replied_back(replied_back)
    log.info(f"[REPLYBACK] Replied back to {count} people.")


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


def safe_run_replyback_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    try:
        run_replyback_cycle()
    except Exception:
        log.info("[REPLYBACK] Error during replyback cycle:")
        traceback.print_exc()


def safe_run_boost_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    try:
        run_boost_cycle()
    except Exception:
        log.info("[BOOST] Error during boost cycle:")
        traceback.print_exc()

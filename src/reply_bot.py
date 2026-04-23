import json
import os
import time
import traceback
from .reply_agent import generate_replies
from .twitter_client import reply_to_tweet, quote_tweet, refresh_feed
from .history import get_recent_tweets

REPLIED_FILE = os.path.join(os.path.dirname(__file__), "..", "replied_tweets.json")


def load_replied() -> set:
    """Load set of tweet URLs we already replied to."""
    if os.path.exists(REPLIED_FILE):
        with open(REPLIED_FILE, "r") as f:
            return set(json.load(f))
    return set()


def save_replied(urls: set):
    """Save the set of replied tweet URLs."""
    # Keep only the last 500 to avoid file bloat
    url_list = list(urls)[-500:]
    with open(REPLIED_FILE, "w") as f:
        json.dump(url_list, f, indent=2)


def run_reply_cycle():
    """Search for popular AI tweets and reply with a sharp one-liner."""
    refresh_feed()
    print("[REPLY] Scanning for tweets to reply to...")

    # Load already-replied URLs so the agent avoids them
    replied = load_replied()

    # Cross-dedup: pass recent post topics so replies don't overlap
    recent_posts = get_recent_tweets(hours=6)
    replies = generate_replies(
        recent_topics=recent_posts if recent_posts else None,
        already_replied=replied,
    )

    if replies is None:
        print("[REPLY] No good tweets found - skipping this cycle.")
        return
    posted_count = 0

    for data in replies:
        url = data["tweet_url"]
        action_type = data.get("type", "reply")

        # Skip tweets we already replied to
        if url in replied:
            print(f"[REPLY] Already replied to {url} - skipping.")
            continue

        print(f"[REPLY] Target: {url}")
        print(f"[REPLY] {action_type.upper()} ({len(data['reply'])} chars): {data['reply']}")

        try:
            if action_type == "quote":
                quote_tweet(url, data["reply"])
            else:
                reply_to_tweet(url, data["reply"])
            replied.add(url)
            posted_count += 1
            # Wait between replies so browser can catch up
            if posted_count < len(replies):
                print("[REPLY] Waiting 15 seconds before next action...")
                time.sleep(15)
        except Exception:
            print(f"[REPLY] Failed to {action_type} {url}:")
            traceback.print_exc()

    save_replied(replied)
    print(f"[REPLY] Posted {posted_count} replies/quotes this cycle.")


def safe_run_reply_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    try:
        run_reply_cycle()
    except Exception:
        print("[REPLY] Error during reply cycle:")
        traceback.print_exc()

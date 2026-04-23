import json
import os
import time
import traceback
from .reply_agent import generate_replies
from .twitter_client import reply_to_tweet, refresh_feed

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
    """Search for popular AI tweets and reply to 2-3 with troll one-liners."""
    refresh_feed()
    print("[REPLY] Scanning for tweets to reply to...")
    replies = generate_replies()
    if replies is None:
        print("[REPLY] No good tweets found - skipping this cycle.")
        return

    replied = load_replied()
    posted_count = 0

    for data in replies:
        url = data["tweet_url"]

        # Skip tweets we already replied to
        if url in replied:
            print(f"[REPLY] Already replied to {url} - skipping.")
            continue

        print(f"[REPLY] Target: {url}")
        print(f"[REPLY] Reply ({len(data['reply'])} chars): {data['reply']}")

        try:
            reply_to_tweet(url, data["reply"])
            replied.add(url)
            posted_count += 1
            # Wait between replies so browser can catch up
            if posted_count < len(replies):
                print("[REPLY] Waiting 15 seconds before next reply...")
                time.sleep(15)
        except Exception:
            print(f"[REPLY] Failed to reply to {url}:")
            traceback.print_exc()

    save_replied(replied)
    print(f"[REPLY] Posted {posted_count} replies this cycle.")


def safe_run_reply_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    try:
        run_reply_cycle()
    except Exception:
        print("[REPLY] Error during reply cycle:")
        traceback.print_exc()

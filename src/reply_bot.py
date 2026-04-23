import traceback
from .reply_agent import generate_reply
from .twitter_client import reply_to_tweet


def run_reply_cycle():
    """Search for a popular AI tweet and reply with a troll take."""
    print("[REPLY] Scanning for tweets to reply to...")
    data = generate_reply()
    if data is None:
        print("[REPLY] No good tweet found - skipping this cycle.")
        return
    print(f"[REPLY] Target: {data['tweet_url']}")
    print(f"[REPLY] Reply ({len(data['reply'])} chars): {data['reply']}")
    reply_to_tweet(data["tweet_url"], data["reply"])


def safe_run_reply_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    try:
        run_reply_cycle()
    except Exception:
        print("[REPLY] Error during reply cycle:")
        traceback.print_exc()

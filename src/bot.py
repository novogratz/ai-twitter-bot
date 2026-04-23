import traceback
from .agent import generate_tweet
from .twitter_client import post_tweet
from .history import save_tweet, get_last_topic


def run_bot_cycle():
    """Alternate between AI and Crypto news each cycle."""
    last = get_last_topic()
    topic = "ai" if last == "crypto" else "crypto"
    label = "IA" if topic == "ai" else "Crypto"

    print(f"[{label}] Recherche de news et generation du tweet...")
    tweet = generate_tweet(topic=topic)
    if tweet is None:
        print(f"[{label}] Pas de news fraiche - on skip ce cycle.")
        return
    print(f"[{label}] Tweet ({len(tweet)} chars):\n{tweet}")
    post_tweet(tweet)
    save_tweet(tweet, topic=topic)


def safe_run_bot_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    try:
        run_bot_cycle()
    except Exception:
        print("Error during bot cycle:")
        traceback.print_exc()

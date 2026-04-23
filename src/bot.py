import traceback
from .agent import generate_tweet
from .twitter_client import post_tweet
from .history import save_tweet, get_next_topic

TOPIC_LABELS = {
    "ai": "IA",
    "crypto": "Crypto",
    "invest": "Investissement",
    "gambling": "Gambling",
}


def run_bot_cycle():
    """Rotate through AI, Crypto, Investment, and Gambling each cycle."""
    topic = get_next_topic()
    label = TOPIC_LABELS[topic]

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

import random
import time
import traceback
from .twitter_client import visit_profile_and_like

# AI-focused accounts only for engagement
TARGET_ACCOUNTS = [
    # Big AI companies
    "OpenAI", "AnthropicAI", "GoogleDeepMind", "MetaAI",
    "xAI", "MistralAI", "HuggingFace", "Cohere", "PerplexityAI",
    # AI leaders
    "sama", "ylecun", "karpathy", "DarioAmodei", "demishassabis",
    "elonmusk", "satyanadella", "jeffdean",
    # AI researchers / influencers
    "DrJimFan", "GaryMarcus", "bindureddy", "AravSrinivas",
    "emollison", "swyx", "AndrewYNg", "fchollet",
    # AI media / news
    "TheAIGRID", "ai_breakfast", "AINathaniel",
    # French AI community
    "Numerama", "Capetlevrai", "Siecledigital", "01net",
    "FrenchWeb", "LesEchos",
]


def run_engage_cycle():
    """Visit a few target accounts and like their latest tweet.
    Builds reciprocity and signals activity to the algorithm."""
    count = random.randint(3, 5)
    picks = random.sample(TARGET_ACCOUNTS, min(count, len(TARGET_ACCOUNTS)))

    print(f"[ENGAGE] Engaging with {len(picks)} accounts...")
    for username in picks:
        try:
            print(f"[ENGAGE] Visiting @{username}...")
            visit_profile_and_like(username)
            time.sleep(random.randint(3, 6))
        except Exception:
            print(f"[ENGAGE] Failed to engage with @{username}:")
            traceback.print_exc()

    print(f"[ENGAGE] Done. Engaged with {len(picks)} accounts.")


def safe_run_engage_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    try:
        run_engage_cycle()
    except Exception:
        print("[ENGAGE] Error during engage cycle:")
        traceback.print_exc()

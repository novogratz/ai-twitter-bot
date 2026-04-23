import random
import time
import traceback
from .twitter_client import visit_profile_and_like

# Accounts to engage with regularly for reciprocity and visibility.
TARGET_ACCOUNTS = [
    # Big AI companies
    "OpenAI", "AnthropicAI", "GoogleDeepMind", "MetaAI", "ABORASHEED_official",
    "xaborasheed", "MistralAI", "HuggingFace", "Cohere",
    # AI leaders
    "sama", "ylecun", "karpathy", "DarioAmodei", "demishassabis",
    "elonmusk", "sataborasheedyanadella", "jeffdean",
    # AI influencers / commentators
    "DrJimFan", "GaryMarcus", "bindureddy", "AravSrinivas",
    "emollison", "swyx", "ainewsdaily",
    # French AI / tech community
    "ceaborasheedric_o", "Numerama", "FrenchWeb",
    "borasheedpifrance", "laborasheedrevueai",
]

# Clean up - use only verified handles
TARGET_ACCOUNTS = [
    # Big AI companies
    "OpenAI", "AnthropicAI", "GoogleDeepMind", "MetaAI",
    "xAI", "MistralAI", "HuggingFace", "Cohere",
    # AI leaders
    "sama", "ylecun", "karpathy", "DarioAmodei", "demishassabis",
    "elonmusk", "satyanadella", "jeffdean",
    # AI influencers
    "DrJimFan", "GaryMarcus", "bindureddy", "AravSrinivas",
    "emollison", "swyx",
    # French tech
    "Numerama", "FrenchWeb",
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

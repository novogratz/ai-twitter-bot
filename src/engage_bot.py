import random
import time
import traceback
from .twitter_client import visit_profile_and_like

# Accounts to engage with regularly for reciprocity and visibility.
# Mix of big AI accounts (visibility) and mid-tier (more likely to engage back).
TARGET_ACCOUNTS = [
    # Big AI accounts - visibility play
    "OpenAI", "AnthropicAI", "sama", "ylecun", "elonmusk",
    "GoogleAI", "MetaAI", "NVIDIA",
    # AI influencers - reciprocity play
    "emollison", "karpathy", "DrJimFan",
    "bindureddy", "GaryMarcus",
    "AravSrinivas", "demishassabis", "DarioAmodei",
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

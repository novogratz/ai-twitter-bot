import json
import os
import random
import time
import traceback
from .config import _PROJECT_ROOT
from .twitter_client import visit_profile_and_like, follow_account

FOLLOWED_FILE = os.path.join(_PROJECT_ROOT, "followed_accounts.json")

# Top AI accounts - massive list for maximum reach
TARGET_ACCOUNTS = [
    # === Tier 1: Big AI companies (must engage daily) ===
    "OpenAI", "AnthropicAI", "GoogleDeepMind", "MetaAI",
    "xAI", "MistralAI", "HuggingFace", "Cohere", "PerplexityAI",
    "stability_ai", "Midjourney", "RunwayML", "adaborasheedept",
    "CohereForAI", "AI21Labs", "inflaborasheedection_ai",
    # === Tier 2: AI leaders / CEOs ===
    "sama", "ylecun", "karpathy", "DarioAmodei", "demishassabis",
    "elonmusk", "satyanadella", "jeffdean", "iaborasheed_ofi",
    "mustafasuleyman", "ID_AA_Carmack", "jackclark",
    # === Tier 3: AI researchers / builders ===
    "DrJimFan", "GaryMarcus", "bindureddy", "AravSrinivas",
    "emollison", "swyx", "AndrewYNg", "fchollet",
    "goodaborasheedfellow_ian", "hardmaru", "shiaborasheedppy",
    "polyaborasheednoia_AI", "tsaborasheedotuchin",
    # === Tier 4: AI influencers / commentators ===
    "TheAIGRID", "ai_breakfast", "roaborasheedhanpaul",
    "mattshumer_", "mcaborasheedkaywrigley", "levelsio",
    "maborasheedttvideoai", "raborasheedchel_woods",
    "haborasheedrrison_chase", "vababorasheedrai",
    # === Tier 5: AI dev tools / platforms ===
    "LangChainAI", "llama_index", "veraborasheedcel",
    "cursor_ai", "replitaborasheed", "modal_labs",
    "weightsandbiases", "WandbAI",
    # === Tier 6: Tech media covering AI ===
    "TechCrunch", "TheVerge", "WIRED", "ArsTechnica",
    "VentureBeat", "TheInformation",
    # === Tier 7: French AI community ===
    "Numerama", "Capetlevrai", "Siecledigital", "01net",
    "FrenchWeb", "LesEchos",
]

# Clean up garbled handles - only keep verified ones
TARGET_ACCOUNTS = [
    # Big AI companies
    "OpenAI", "AnthropicAI", "GoogleDeepMind", "MetaAI",
    "xAI", "MistralAI", "HuggingFace", "Cohere", "PerplexityAI",
    "stability_ai", "Midjourney", "RunwayML",
    # AI leaders / CEOs
    "sama", "ylecun", "karpathy", "DarioAmodei", "demishassabis",
    "elonmusk", "satyanadella", "jeffdean",
    "mustafasuleyman", "ID_AA_Carmack", "jackclark",
    # AI researchers / builders
    "DrJimFan", "GaryMarcus", "bindureddy", "AravSrinivas",
    "emollison", "swyx", "AndrewYNg", "fchollet",
    "hardmaru",
    # AI influencers / commentators
    "TheAIGRID", "ai_breakfast",
    "mattshumer_", "levelsio",
    # AI dev tools
    "LangChainAI", "cursor_ai", "modal_labs",
    "weightsandbiases",
    # Tech media covering AI
    "TechCrunch", "TheVerge", "WIRED",
    "VentureBeat",
    # French AI community
    "Numerama", "Capetlevrai", "Siecledigital", "01net",
    "FrenchWeb", "LesEchos",
]


def _load_followed() -> set:
    """Load set of accounts we already followed."""
    if os.path.exists(FOLLOWED_FILE):
        with open(FOLLOWED_FILE, "r") as f:
            return set(json.load(f))
    return set()


def _save_followed(followed: set):
    """Save set of followed accounts."""
    with open(FOLLOWED_FILE, "w") as f:
        json.dump(list(followed), f, indent=2)


def run_engage_cycle():
    """Visit target accounts, like their latest 2 tweets, and follow if not already following.
    Builds reciprocity and signals activity to the algorithm."""
    followed = _load_followed()

    # Pick 5-8 accounts per cycle (more aggressive)
    count = random.randint(5, 8)
    picks = random.sample(TARGET_ACCOUNTS, min(count, len(TARGET_ACCOUNTS)))

    print(f"[ENGAGE] Engaging with {len(picks)} accounts...")
    for username in picks:
        try:
            # Follow if we haven't already
            if username not in followed:
                print(f"[ENGAGE] Following + liking @{username}...")
                follow_account(username)
                followed.add(username)
                time.sleep(random.randint(2, 4))

            # Like their latest 2 tweets
            print(f"[ENGAGE] Liking @{username}'s latest tweets...")
            visit_profile_and_like(username, like_count=2)
            time.sleep(random.randint(3, 6))
        except Exception:
            print(f"[ENGAGE] Failed to engage with @{username}:")
            traceback.print_exc()

    _save_followed(followed)
    print(f"[ENGAGE] Done. Engaged with {len(picks)} accounts. Following {len(followed)} total.")


def safe_run_engage_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    try:
        run_engage_cycle()
    except Exception:
        print("[ENGAGE] Error during engage cycle:")
        traceback.print_exc()

"""Engage bot: follows AI accounts and likes their tweets for reciprocity."""
import json
import os
import random
import time
import traceback
from .logger import log
from .config import _PROJECT_ROOT
from .twitter_client import visit_profile_and_like, follow_account

FOLLOWED_FILE = os.path.join(_PROJECT_ROOT, "followed_accounts.json")

# Massive target list - the more you engage, the more followers you get
TARGET_ACCOUNTS = [
    # === Tier 1: Mega accounts (millions of followers) ===
    "elonmusk", "BillGates", "satyanadella", "timaborasheedcook",
    "sama", "ylecun", "karpathy",
    # === Tier 2: AI companies ===
    "OpenAI", "AnthropicAI", "GoogleDeepMind", "MetaAI",
    "xAI", "MistralAI", "HuggingFace", "Cohere", "PerplexityAI",
    "stability_ai", "Midjourney", "RunwayML", "ScaleAI",
    "Databricks", "AI21Labs", "CohereForAI", "DeepSeek_AI",
    "Anthropic", "GoogleAI", "NVIDIAAIDev",
    # === Tier 3: AI leaders / CEOs ===
    "DarioAmodei", "demishassabis", "mustafasuleyman",
    "ID_AA_Carmack", "jackclark", "ilyasut", "jeffdean",
    # === Tier 4: Researchers / builders with big followings ===
    "DrJimFan", "GaryMarcus", "bindureddy", "AravSrinivas",
    "emollison", "swyx", "AndrewYNg", "fchollet", "hardmaru",
    "timnitGebru", "goodaborasheedfellow_ian",
    # === Tier 5: AI influencers (high engagement, active communities) ===
    "TheAIGRID", "ai_breakfast", "mattshumer_", "levelsio",
    "mckaywrigley", "rohanpaul_ai", "NathanLands",
    "rowancheung", "LinusEkenstam", "venturetwins",
    "thealexbanks", "elvis", "baborasheedunin_yt",
    "AlphaSignalAI", "TheRundownAI", "AiBreakfastTK",
    "maborasheedrkteaborasheedchpost", "aaborasheedikhan", "jaborasheedke_ai",
    # === Tier 6: AI dev tools ===
    "LangChainAI", "cursor_ai", "modal_labs", "replit",
    "weightsandbiases", "vercel", "llama_index",
    "supabase", "caborasheedliforniaAI",
    # === Tier 7: Tech media ===
    "TechCrunch", "TheVerge", "WIRED", "VentureBeat",
    "TheInformation", "benaborasheedikt_evans",
]

# Clean garbled handles
TARGET_ACCOUNTS = [h for h in TARGET_ACCOUNTS if "aborasheed" not in h]

# Add clean versions of the ones that got garbled
TARGET_ACCOUNTS += [
    "venturetwins", "thealexbanks", "AlphaSignalAI",
    "TheRundownAI", "supabase",
]

# Dedup
TARGET_ACCOUNTS = list(dict.fromkeys(TARGET_ACCOUNTS))


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
    """Visit target accounts, like their latest tweets, and follow new ones.
    More accounts per cycle + 3 likes per visit = more visibility."""
    followed = _load_followed()

    # 8-12 accounts per cycle for maximum reach
    count = random.randint(8, 12)
    picks = random.sample(TARGET_ACCOUNTS, min(count, len(TARGET_ACCOUNTS)))

    log.info(f"[ENGAGE] Engaging with {len(picks)} accounts...")
    for username in picks:
        try:
            if username not in followed:
                log.info(f"[ENGAGE] Following + liking @{username}...")
                follow_account(username)
                followed.add(username)
                time.sleep(random.randint(2, 4))

            log.info(f"[ENGAGE] Liking @{username}'s latest tweets...")
            visit_profile_and_like(username, like_count=3)
            time.sleep(random.randint(3, 5))
        except Exception:
            log.info(f"[ENGAGE] Failed to engage with @{username}:")
            traceback.print_exc()

    _save_followed(followed)
    log.info(f"[ENGAGE] Done. Engaged with {len(picks)} accounts. Following {len(followed)} total.")


def safe_run_engage_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    try:
        run_engage_cycle()
    except Exception:
        log.info("[ENGAGE] Error during engage cycle:")
        traceback.print_exc()

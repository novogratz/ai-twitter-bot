"""Engage bot: follows AI accounts and likes their tweets for reciprocity."""
import json
import os
import random
import time
import traceback
from .logger import log
from .config import _PROJECT_ROOT, DISCOVERED_ACCOUNTS_FILE, BLOCKLIST
from .twitter_client import visit_profile_and_like, follow_account

FOLLOWED_FILE = os.path.join(_PROJECT_ROOT, "followed_accounts.json")


def _load_discovered_handles() -> list:
    """Read autonomously-discovered handles, skipping blocklisted ones."""
    if not os.path.exists(DISCOVERED_ACCOUNTS_FILE):
        return []
    try:
        with open(DISCOVERED_ACCOUNTS_FILE, "r") as f:
            data = json.load(f)
        return [d.get("handle") for d in data
                if d.get("handle") and d["handle"].lower() not in BLOCKLIST]
    except (json.JSONDecodeError, IOError):
        return []

# IA + Crypto + Bourse target accounts
TARGET_ACCOUNTS = [
    # === IA: Mega accounts ===
    "elonmusk", "BillGates", "satyanadella",
    "sama", "ylecun", "karpathy",

    # === IA: Companies ===
    "OpenAI", "AnthropicAI", "GoogleDeepMind", "MetaAI",
    "xAI", "MistralAI", "HuggingFace", "Cohere", "PerplexityAI",
    "stability_ai", "Midjourney", "RunwayML", "ScaleAI",

    # === IA: Leaders / CEOs ===
    "DarioAmodei", "demishassabis", "mustafasuleyman",
    "ID_AA_Carmack", "jackclark", "ilyasut",

    # === IA: Researchers / builders ===
    "DrJimFan", "GaryMarcus", "AndrewYNg", "fchollet",
    "swyx", "hardmaru", "AravSrinivas",

    # === IA: Influencers ===
    "TheAIGRID", "mattshumer_", "levelsio",
    "rowancheung", "AlphaSignalAI", "TheRundownAI",
    "thealexbanks", "NathanLands",

    # === Crypto: Mega accounts ===
    "VitalikButerin", "APompliano", "CryptoCapo_",
    "caborashedzaborashedles", "brian_armstrong",

    # === Crypto: Influencers FR ===
    "PowerHasheur", "Capetlevrai", "Dark_Emi_",
    "CryptoMusic_fr", "JournalDuCoin", "powl_d",

    # === Crypto: Media & accounts ===
    "CoinDesk", "Cointelegraph", "coin_bureau",
    "WuBlockchain", "tier10k",

    # === Bourse/Finance: FR ===
    "Graphseo", "ABaradez", "FinTales_",
    "ZonebourseFR", "BFMBourse",
    "NCheron_bourse", "RodolpheSteffan", "IVTrading",
    "DereeperVivre",

    # === Bourse/Finance: US ===
    "chamath", "jimcramer", "unusual_whales",

    # === Tech media ===
    "TechCrunch", "TheVerge", "WIRED",
]

# Append discovered handles, then dedup
TARGET_ACCOUNTS = list(dict.fromkeys(TARGET_ACCOUNTS + _load_discovered_handles()))


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

    # 3-5 accounts per cycle - stay under Twitter's radar
    count = random.randint(3, 5)
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

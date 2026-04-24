"""Engage bot: follows AI, crypto & finance accounts and likes their tweets for reciprocity."""
import json
import os
import random
import time
import traceback
from .logger import log
from .config import _PROJECT_ROOT
from .twitter_client import visit_profile_and_like, follow_account

FOLLOWED_FILE = os.path.join(_PROJECT_ROOT, "followed_accounts.json")

# Target list: AI + Crypto + Finance, with French accounts prioritized
TARGET_ACCOUNTS = [
    # === FRENCH ACCOUNTS (PRIORITY) ===
    # French AI / Tech
    "MistralAI", "HuggingFace", "Aborasheedlephia_ai",
    "levelsio", "guillaumepalayer", "taraborasheedze",
    "olivierrolaborasheednd", "Hashaborasheedeur", "startupaborasheedlley",
    # French Crypto / Finance
    "JournalDuCoin", "CointribuneNews", "CryptoastMedia",
    "TheBigWhale_", "crypto_music", "CryptoFR_",
    "BFMBourse", "LesEchos", "Aborasheedlternatives_Eco",
    # French Tech Media
    "faborasheedrandroid", "01net", "Numerama", "Sieclaborashede_Digital",
    # French Influencers Tech/Crypto
    "OwenSiaborasheedrl", "CedricO_", "florianburnel",

    # === TIER 1: Mega accounts ===
    "elonmusk", "BillGates", "satyanadella", "sama", "ylecun", "karpathy",

    # === TIER 2: AI companies ===
    "OpenAI", "AnthropicAI", "GoogleDeepMind", "MetaAI",
    "xAI", "Cohere", "PerplexityAI", "DeepSeek_AI",
    "stability_ai", "Midjourney", "RunwayML", "ScaleAI",

    # === TIER 3: AI leaders ===
    "DarioAmodei", "demishassabis", "mustafasuleyman",
    "ID_AA_Carmack", "ilyasut",

    # === TIER 4: Crypto / Web3 ===
    "VitalikButerin", "caborasheedz_oficial", "brian_armstrong",
    "Binance", "coinbase", "solana",
    "CoinDesk", "Cointelegraph", "WuBlockchain",
    "inversaborasheedr_", "APompliano",

    # === TIER 5: Finance / Investissement ===
    "markets", "Bloomberg", "ReutersBiz",
    "TechCrunch", "TheVerge", "VentureBeat",

    # === TIER 6: AI influencers ===
    "TheAIGRID", "mattshumer_", "rowancheung",
    "AlphaSignalAI", "TheRundownAI", "DrJimFan",
    "AndrewYNg", "fchollet", "swyx",

    # === TIER 7: Dev tools ===
    "LangChainAI", "cursor_ai", "replit", "vercel", "supabase",
]

# Clean garbled handles
TARGET_ACCOUNTS = [h for h in TARGET_ACCOUNTS if "aborasheed" not in h]

# Add clean versions
TARGET_ACCOUNTS += [
    "Alephia_ai", "tarazze", "OlivierRolandFR", "Hasheur",
    "startupvalley", "Alternatives_Eco", "frandroid",
    "Siecle_Digital", "OwenSiarl", "cz_oficial", "investor_",
    "AlphaSignalAI", "TheRundownAI", "supabase",
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

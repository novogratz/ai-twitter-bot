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

# Massive target list: AI + Crypto + Finance, French accounts FIRST
TARGET_ACCOUNTS = [
    # =============================================================
    # FRENCH INFLUENCERS (PRIORITY - grow francophone base)
    # =============================================================

    # --- French Crypto / Bitcoin influencers ---
    "PowerHasheur",       # Hasheur (Owen Simonin) - #1 crypto FR, 400k+ followers
    "crypto_futur",       # Crypto Futur (Mattéo) - 240k+ followers
    "CryptoMatrix2",      # Crypto Matrix - #1 chaîne crypto FR daily
    "Capetlevrai",        # Crypto influenceur FR majeur
    "Dark_Emi_",          # Dark Emi - crypto influenceur FR
    "FinTales_",          # FinTales - finance/crypto FR
    "CryptoGourmetFR",    # Crypto Gourmet - analyses marché FR
    "FranceCryptos",      # France Cryptos - actu Bitcoin FR
    "BeInCrypto_fr",      # BeInCrypto France
    "cryptofranceFR",     # Crypto Trading France
    "cryptonews_FR",      # Cryptonews FR
    "Paul_Theway",        # Cryptonorth - formation crypto FR
    "BTC_CRYPTO_fr",      # bitcoin-crypto.fr
    "CryptoFR_",          # Communauté crypto FR

    # --- French Finance / Bourse influencers ---
    "ABaradez",           # Alexandre Baradez - analyste macro IG France
    "NCheron_bourse",     # Nicolas Chéron - stratégiste bourse indépendant
    "Graphseo",           # Julien Flot - trader/analyste technique
    "Tradosaure",         # Tradosaure - trader pro, formateur
    "MatthieuLouvet",     # Matthieu Louvet - investissement ETF/bourse
    "ZoneBourse",         # Zonebourse - actu marchés FR
    "CafeDelaBourse",     # Café de la Bourse - média finance FR

    # --- French Crypto Médias ---
    "LeJournalDuCoin",    # Journal du Coin - #1 média crypto FR
    "CointribuneNews",    # Cointribune - actu crypto FR
    "CryptoastMedia",     # Cryptoast - analyses crypto FR
    "TheBigWhale_",       # The Big Whale - crypto/Web3 FR

    # --- French AI / Tech ---
    "MistralAI",          # Mistral AI - startup IA française
    "HuggingFace",        # Hugging Face - fondé en France
    "fchollet",           # François Chollet - créateur de Keras, français
    "tariqkrim",          # Tariq Krim - fondateur Netvibes
    "CedricO_",           # Cédric O - ex-secrétaire d'État au numérique
    "flaborasheedeurpellerin",    # Fleur Pellerin - VC, ex-ministre numérique
    "ActuIA_",            # Actu IA - média IA FR

    # --- French Tech Média ---
    "frandroid",          # Frandroid - tech FR
    "01net",              # 01net - tech FR
    "Numerama",           # Numerama - tech/science FR
    "Siecle_Digital",     # Siècle Digital - tech FR
    "BFMBourse",          # BFM Bourse
    "LesEchos",           # Les Echos
    "LaTribune",          # La Tribune
    "FrenchWeb",          # FrenchWeb - startup/tech FR

    # --- French Tech/Startup influencers ---
    "guillaumepalayer",   # Guillaume Palayer - tech FR
    "OlivierRolandFR",    # Olivier Roland - entrepreneur FR
    "florianburnel",      # Florian Burnel - tech FR
    "levelsio",           # Pieter Levels - indie maker (parle de la France)

    # =============================================================
    # INTERNATIONAL (big accounts for visibility)
    # =============================================================

    # --- Mega accounts ---
    "elonmusk", "BillGates", "satyanadella", "sama", "ylecun", "karpathy",

    # --- AI companies ---
    "OpenAI", "AnthropicAI", "GoogleDeepMind", "MetaAI",
    "xAI", "Cohere", "PerplexityAI", "DeepSeek_AI",
    "stability_ai", "Midjourney", "RunwayML", "ScaleAI",

    # --- AI leaders ---
    "DarioAmodei", "demishassabis", "mustafasuleyman",
    "ID_AA_Carmack", "ilyasut",

    # --- Crypto / Web3 international ---
    "VitalikButerin", "cz_binance", "brian_armstrong",
    "Binance", "coinbase", "solana",
    "CoinDesk", "Cointelegraph", "WuBlockchain",
    "APompliano", "100trillionUSD",

    # --- Finance / Markets ---
    "markets", "Bloomberg", "ReutersBiz",
    "TechCrunch", "TheVerge", "VentureBeat",

    # --- AI influencers ---
    "TheAIGRID", "mattshumer_", "rowancheung",
    "AlphaSignalAI", "TheRundownAI", "DrJimFan",
    "AndrewYNg", "swyx",

    # --- Dev tools ---
    "LangChainAI", "cursor_ai", "replit", "vercel", "supabase",
]

# Clean any garbled handles (Safari keyboard issue)
TARGET_ACCOUNTS = [h for h in TARGET_ACCOUNTS if "aborasheed" not in h]

# Add clean versions of garbled ones
TARGET_ACCOUNTS += ["fleurpellerin"]

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

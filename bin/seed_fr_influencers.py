#!/usr/bin/env python3
"""One-shot seeder: add a curated batch of francophone IA/crypto/bourse
influencers to dynamic_accounts.json AND follow them immediately.

User directive 2026-05-09: "find all the influencers you can that are
francophones on twitter related to ia ai crypto ou bourse investissements,
add them, follow them, and reshare their news + reply to those all day long"

After this runs:
  - All 30+ bots that merge dynamic_accounts.json will see these handles.
  - The bot will follow them once (best-effort via twitter_client).
  - retweet_bot will pull them as candidates (when scout_agent reinforces).
  - direct_reply will visit them as PROFILE-FR cycles.

Run: python3 bin/seed_fr_influencers.py
"""
import json
import os
import sys
import time
import random

# Make src/ importable.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import _PROJECT_ROOT
from src.logger import log
from src.twitter_client import follow_account
from src.engage_bot import _load_followed, _save_followed

# 50+ francophone handles, IA / Crypto / Bourse / Macro / Tech press.
# Curated for likelihood of being active accounts.
SEED_HANDLES = [
    # FR Crypto / DeFi
    "JulienBouteloup", "cryptaa", "crypto_etudiant", "KEvinDOR",
    "CrypTAlphaFR", "BitcoinerFR", "JFR_Crypto", "CryptoSushi_",
    "HackoBoss", "0xCryptoLab", "MaxOpti_", "BastienBronnec",
    "bitcoin_FR", "MisterCrypto_FR", "sentinelcrypt0", "JeromeAtangana",
    "investirsimple", "oui_oui_crypto",

    # FR AI / Tech
    "clemdelangue", "gilles_babinet", "stanislaspolu", "aurelien_geron",
    "mihalgrouv", "lex_lhomme", "datageek_FR", "le_tech_FR",
    "KIVU_AI", "BorisJabes",

    # FR Finance / Bourse / Macro
    "marc_touati", "PatrickArtus", "CMS_Bordier", "CarminFinance",
    "TheoTrader_", "HappyTradingFR", "FrenchMacro", "CafeDeLaBourse",
    "BoursorMa", "Trader_Officiel", "Albizzia", "JoeBoursoFR",
    "Marc_Fiorentino", "thomas_porcher", "Charles_Sannat",

    # FR Media + journalists
    "Le_Figaro_Eco", "OlivierBabeau", "ContexteTech", "BFMTechIA",
    "FrenchWeb", "AgnesLaszczyk",
]

DYNAMIC_FILE = os.path.join(_PROJECT_ROOT, "dynamic_accounts.json")


def _load_dynamic():
    if not os.path.exists(DYNAMIC_FILE):
        return {"fr": [], "en": []}
    try:
        with open(DYNAMIC_FILE, "r") as f:
            d = json.load(f) or {}
        d.setdefault("fr", [])
        d.setdefault("en", [])
        return d
    except Exception:
        return {"fr": [], "en": []}


def _save_dynamic(d):
    with open(DYNAMIC_FILE, "w") as f:
        json.dump(d, f, indent=2, ensure_ascii=False)


def main():
    print(f"[SEED] Loading {DYNAMIC_FILE}...")
    dyn = _load_dynamic()
    existing = {h.lower() for h in dyn["fr"]}

    new = [h for h in SEED_HANDLES if h.lower() not in existing]
    if not new:
        print("[SEED] All seed handles already present. Nothing to add.")
    else:
        dyn["fr"] = sorted(set(dyn["fr"] + new))
        _save_dynamic(dyn)
        print(f"[SEED] Added {len(new)} new handles to dynamic_accounts.fr.")
        for h in new:
            print(f"  + {h}")

    # Now follow them best-effort. Skip already-followed.
    followed = _load_followed()
    targets = [h for h in SEED_HANDLES if h not in followed]

    if not targets:
        print("[SEED] All seed handles already in followed_accounts.json.")
        return

    print(f"\n[SEED] Following {len(targets)} accounts (best-effort)...")
    print("[SEED] Each follow takes ~6-8 sec. Total ~5-7 minutes.\n")

    succeeded = 0
    for h in targets:
        print(f"  → @{h}", end=" ", flush=True)
        try:
            ok = follow_account(h)
            if ok:
                followed.add(h)
                _save_followed(followed)
                succeeded += 1
                print("✓")
            else:
                print("(skipped — invalid handle or already following)")
        except Exception as e:
            print(f"(error: {e})")
        time.sleep(random.randint(3, 6))

    print(f"\n[SEED] Done. Followed: {succeeded}/{len(targets)}")
    print(f"[SEED] dynamic_accounts.json now has {len(dyn['fr'])} FR handles.")
    print("[SEED] All bots that merge dynamic_accounts will see these on next cycle.")


if __name__ == "__main__":
    main()

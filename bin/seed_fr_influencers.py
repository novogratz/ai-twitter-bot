#!/usr/bin/env python3
"""One-shot seeder: add a curated batch of francophone IA/crypto/bourse
influencers to dynamic_accounts.json AND follow them immediately.

User directive 2026-05-09: "find all the influencers you can that are
francophones on twitter related to ia ai crypto ou bourse investissements,
add them, follow them, and reshare their news + reply to those all day long"

After this runs:
  - The bot will follow them once (best-effort via twitter_client).

Run: python3 bin/seed_fr_influencers.py
"""
import json
import os
import sys
import time
import random

# Make src/ importable.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core import state_store
from src.core.logger import log
from src.guards import follow_policy
from src.x.twitter_client import follow_account

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

DYNAMIC_FILE = state_store.StatePath("dynamic_accounts.json")


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
    try:
        state_store.require_migrated()
    except state_store.Unmigrated as exc:
        sys.exit(f"[SEED] ABORT: {exc}")
    state_store.ensure_root()
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

    # Now follow them best-effort. Skip already-followed, and any handle
    # whitelist.json does not list: follow_account also follows a follower
    # or an Engager outside it, with a lighter gate for an Engager, which a
    # seeding script has no business doing (#173).
    followed = follow_policy.followed()
    targets = [h for h in SEED_HANDLES if h not in followed
               and follow_policy.relation(h) is follow_policy.Relation.SEED]

    if not targets:
        print("[SEED] No whitelisted seed handle left to follow.")
        return

    print(f"\n[SEED] Following {len(targets)} accounts (best-effort)...")
    print("[SEED] Each follow takes ~6-8 sec. Total ~5-7 minutes.\n")

    succeeded = 0
    for h in targets:
        print(f"  → @{h}", end=" ", flush=True)
        try:
            result = follow_account(h)
            if result:
                succeeded += 1
                print("✓")
            else:
                print(f"(skipped — {result.value})")
        except Exception as e:
            print(f"(error: {e})")
        time.sleep(random.randint(3, 6))

    print(f"\n[SEED] Done. Followed: {succeeded}/{len(targets)}")
    print(f"[SEED] dynamic_accounts.json now has {len(dyn['fr'])} FR handles.")
    print("[SEED] All bots that merge dynamic_accounts will see these on next cycle.")


if __name__ == "__main__":
    main()

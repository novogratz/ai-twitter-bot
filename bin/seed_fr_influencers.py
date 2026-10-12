#!/usr/bin/env python3
"""Manual seeder for the Account's curated French topic experts.

Run only on an explicit operator request. Follow admission, the whitelist,
active hours and all write caps apply to every follow.
"""
import os
import sys
import time
import random

# Make src/ importable.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core import state_store
from src.core.dynamic_strategy import DYNAMIC_ACCOUNTS
from src.core.logger import log
from src.guards import follow_policy
from src.x.twitter_client import follow_account

# Operator 2026-10-12: only the Account's curated subject experts.
from src.core import account
SEED_HANDLES = list(account.current().network.big_fr)

DYNAMIC_FILE = state_store.StatePath("dynamic_accounts.json")


def _load_dynamic():
    data = DYNAMIC_ACCOUNTS.read()
    data.setdefault("fr", [])
    data.setdefault("en", [])
    return data


def _save_dynamic(data):
    DYNAMIC_ACCOUNTS.write(data)


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

"""Seed-priority follow bot (2026-06-07 agent spec, Part 1 — Following).

Rebuilds the following list from near-zero after the full purge, walking the
curated seed list in whitelist.json in the spec's priority order:

  tier1 (foils / persona ecosystem — follow FIRST, highest ROI)
  → tier2 (niche reply targets) → tier3 (AI signal) → tier4 (crypto/markets).

Pacing and the hard constraints live at the chokepoint
(twitter_client.follow_account → action_guard.can_follow): whitelist-only,
max 20 follows/day, >=10-min randomized gaps, total-following ceiling
(300 hard / ~150 while followers are low), 30-day anti-churn. This bot only
decides WHO is next; it attempts ONE follow per cycle and lets the guard
refuse the rest — so the schedule can run often without ever bursting.

Handles in the seed list are HINTS (handles drift): follow_account visits
the profile and only records a follow when the click actually fired, so an
unresolved/suspended handle simply fails and is logged + retried later.
Idempotent via `followed_accounts.json` (shared with engage_bot).
"""
import json
import os
import traceback

from .config import _PROJECT_ROOT, WHITELIST_FILE
from .logger import log
from .twitter_client import follow_account
from . import engage_bot

# Spec priority order — tier1 first, always.
_TIER_ORDER = ("tier1", "tier2", "tier3", "tier4")


def _seed_handles_in_priority_order() -> list:
    """Ordered handle list from whitelist.json — seeds[] (sorted by priority)
    when present, else tiers in tier1→tier4 order."""
    try:
        with open(WHITELIST_FILE) as f:
            raw = json.load(f) or {}
    except (OSError, json.JSONDecodeError):
        return []
    seeds = raw.get("seeds")
    if isinstance(seeds, list) and seeds:
        rows = [s for s in seeds if isinstance(s, dict) and s.get("handle")]
        rows.sort(key=lambda s: s.get("priority", 999))
        return [str(s["handle"]) for s in rows]
    ordered = []
    tiers = raw.get("tiers") or {}
    for t in _TIER_ORDER:
        ordered.extend(str(h) for h in (tiers.get(t) or []))
    return ordered


def run_marquee_follow_cycle() -> None:
    """Follow the single highest-priority seed not yet followed.

    One attempt per cycle: the action_guard spacing rule (>=10 min between
    follows) would refuse back-to-back follows anyway, and one-at-a-time is
    exactly the "spread with randomized gaps, never burst" behavior the spec
    demands.
    """
    followed = engage_bot._load_followed()
    followed_lc = {f.lower() for f in followed}
    pending = [h for h in _seed_handles_in_priority_order()
               if h.lower() not in followed_lc]
    if not pending:
        log.info("[SEED-FOLLOW] Seed list fully followed — holding (discovery "
                 "candidates go to whitelist suggestions[] for approval).")
        return
    handle = pending[0]
    log.info(f"[SEED-FOLLOW] Next seed (priority order): @{handle} "
             f"({len(pending)} pending).")
    try:
        if follow_account(handle):
            followed.add(handle)
            engage_bot._save_followed(followed)
            log.info(f"[SEED-FOLLOW] Followed @{handle}.")
        else:
            # Guard refusal (cap/spacing/ceiling) or unresolved handle —
            # follow_account already logged the reason; retry next cycle.
            log.info(f"[SEED-FOLLOW] @{handle} not followed this cycle.")
    except Exception:
        log.info(f"[SEED-FOLLOW] follow_account crashed on @{handle}:")
        traceback.print_exc()


def safe_run_marquee_follow_cycle() -> None:
    from . import health
    try:
        run_marquee_follow_cycle()
        health.record_success("marquee_follow")
    except Exception:
        log.info("[SEED-FOLLOW] outer error:")
        traceback.print_exc()
        health.record_failure("marquee_follow")

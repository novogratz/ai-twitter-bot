"""Engage bot — visit active profiles discovered from the live feed, not a static list.

Strategy (2026-06-06 operator mandate):
  - Primary pool: handles captured from For You / Following feed by the feed
    sweeper (dynamic_accounts.json "en"/"fr" buckets) + legacy discovered.json.
  - VIP: the Account's network.engage_vip, included every cycle.
  - Blocked / pruned accounts are filtered out automatically.
  - Only a Seed account of the pool is followed (issue #173): followers
    belong to followback_job and Engagers to follow_engagers_job, each with
    its own cap. The like pass is the same for every pool account.
"""
import random
import time
import traceback
from ..core import account
from ..core.logger import log
from ..core.state_store import StateUnreadable
from ..core.dynamic_strategy import DISCOVERED_ACCOUNTS, get_dynamic_accounts
from ..guards import follow_policy
from ..guards.reply_admission import is_blocked_account
from ..x.scraper import _profile_visit_allowed
from ..x.twitter_client import visit_profile_and_like, follow_account, LikeOutcome


def _vip_accounts() -> tuple:
    """The Account's engage VIPs, always in the rotation (operator 2026-06-06)."""
    return account.current().network.engage_vip


def _load_discovered_handles() -> list:
    """Read autonomously-discovered handles from discovered_accounts.json."""
    return [d.get("handle") for d in DISCOVERED_ACCOUNTS.read()
            if d.get("handle") and not is_blocked_account(d["handle"])]


def _load_dynamic_handles() -> list:
    """Read handles from dynamic_accounts.json (populated by feed sweeper)."""
    data = get_dynamic_accounts()
    handles = []
    for bucket in ("en", "fr"):
        for h in data[bucket]:
            if h and not is_blocked_account(h):
                handles.append(h)
    return handles


def _build_pool() -> list:
    """VIPs + dynamic + discovered, deduped and blocklist-filtered."""
    seen = set()
    pool = []
    for h in [*_vip_accounts(), *_load_dynamic_handles(), *_load_discovered_handles()]:
        h_lower = h.lower() if h else ""
        if h and h_lower not in seen and not is_blocked_account(h):
            pool.append(h)
            seen.add(h_lower)
    return pool


def run_engage_cycle():
    """Visit a sample of feed-discovered profiles, like their latest tweets."""
    from ..core.evolution_store import filter_and_weight
    followed = follow_policy.followed()
    pool = filter_and_weight(_build_pool())

    if not pool:
        log.info("[ENGAGE] Pool empty — no dynamic/discovered handles yet.")
        return

    count = random.randint(8, 12)
    # Always include VIPs if they're in the pool.
    vip = _vip_accounts()
    vip_picks = [h for h in pool if h in vip]
    rest = [h for h in pool if h not in vip]
    random.shuffle(rest)
    picks = (vip_picks + rest)[:count]

    log.info(f"[ENGAGE] Visiting {len(picks)} profiles (pool size: {len(pool)})...")
    liked = 0
    for username in picks:
        try:
            if (username not in followed
                    and follow_policy.relation(username) is follow_policy.Relation.SEED):
                log.info(f"[ENGAGE] Following + liking @{username}...")
                follow_account(username)
                time.sleep(random.randint(2, 4))

            # 2026-06-17: skip the reciprocity-like pass when the handle is
            # outside PROFILE_VISIT_ALLOWLIST (home/search-only mandate).
            # The like primitive returns instantly after logging "blocked",
            # so iterating it just spammed bot.log (~50s of [ENGAGE]/[LIKE]
            # blocked pairs per cycle) without doing any work. Same shape
            # as the trusted-news skip (PR #49). The follow above still
            # ran — follow_account's profile visit is mechanically required
            # and intentionally ungated.
            if not _profile_visit_allowed(username):
                continue
            # Cooled down 5/3→2/1 (operator 2026-06-15: too many likes
            # tripped the automation flag).
            like_count = 2 if username in vip else 1
            log.info(f"[ENGAGE] Liking @{username}'s latest tweets...")
            outcomes = visit_profile_and_like(username, like_count=like_count)
            liked += sum(o is LikeOutcome.LIKED for o in outcomes)
            time.sleep(random.randint(3, 5))
        except StateUnreadable:
            raise  # a guarded file stops the job, not one pick at a time
        except Exception:
            log.info(f"[ENGAGE] Failed to engage with @{username}:")
            traceback.print_exc()

    log.info(f"[ENGAGE] Done. Visited {len(picks)} accounts, liked {liked} posts.")


def safe_run_engage_cycle():
    from ..core import health
    try:
        run_engage_cycle()
        health.record_success("engage")
    except Exception:
        log.info("[ENGAGE] Error during engage cycle:")
        traceback.print_exc()
        health.record_failure("engage")

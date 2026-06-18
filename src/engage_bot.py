"""Engage bot — visit active profiles discovered from the live feed, not a static list.

Strategy (2026-06-06 operator mandate):
  - Primary pool: handles captured from For You / Following feed by the feed
    sweeper (dynamic_accounts.json "en"/"fr" buckets) + legacy discovered.json.
  - VIP: Graphseo always included every cycle.
  - Blocked / pruned accounts are filtered out automatically.
  - No massive hardcoded follow list — we follow who the feed shows us.
"""
import json
import os
import random
import time
import traceback
from .logger import log
from .config import _PROJECT_ROOT, DISCOVERED_ACCOUNTS_FILE, BLOCKLIST
from .twitter_client import visit_profile_and_like, follow_account

FOLLOWED_FILE = os.path.join(_PROJECT_ROOT, "followed_accounts.json")

# Compatibility shim — notify_bot and reply_agent import TARGET_ACCOUNTS.
# Real pool is built dynamically from the feed; this satisfies the import.
# Follow pool: BIG AI accounts only (operator 2026-06-17: "only follow big big
# ai accounts, minimum 100k followers"). The follow chokepoint additionally
# enforces MIN_FOLLOWERS_TO_FOLLOW as a hard gate, so nothing small slips in.
TARGET_ACCOUNTS = [
    "OpenAI", "sama", "AnthropicAI", "GoogleDeepMind", "demishassabis",
    "elonmusk", "xai", "karpathy", "ylecun", "AndrewYNg", "GoogleAI",
    "nvidia", "MistralAI", "perplexity_ai", "OpenAIDevs", "grok",
    "satyanadella", "sundarpichai",
]

# No forced small-account VIP under the big-AI mandate.
VIP_ACCOUNTS = []


def _load_discovered_handles() -> list:
    """Read autonomously-discovered handles from discovered_accounts.json."""
    if not os.path.exists(DISCOVERED_ACCOUNTS_FILE):
        return []
    try:
        with open(DISCOVERED_ACCOUNTS_FILE, "r") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [d.get("handle") for d in data
                    if d.get("handle") and d["handle"].lower() not in BLOCKLIST]
        return []
    except (json.JSONDecodeError, IOError):
        return []


def _load_dynamic_handles() -> list:
    """Read handles from dynamic_accounts.json (populated by feed sweeper)."""
    path = os.path.join(_PROJECT_ROOT, "dynamic_accounts.json")
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r") as f:
            data = json.load(f)
        handles = []
        for bucket in ("en", "fr"):
            for h in data.get(bucket, []):
                if h and h.lower() not in BLOCKLIST:
                    handles.append(h)
        return handles
    except (json.JSONDecodeError, IOError):
        return []


def _build_pool() -> list:
    """VIPs + dynamic + discovered, deduped and blocklist-filtered."""
    seen = set()
    pool = []
    for h in VIP_ACCOUNTS + _load_dynamic_handles() + _load_discovered_handles():
        h_lower = h.lower() if h else ""
        if h and h_lower not in seen and h_lower not in BLOCKLIST:
            pool.append(h)
            seen.add(h_lower)
    return pool


def _load_followed() -> set:
    if os.path.exists(FOLLOWED_FILE):
        try:
            with open(FOLLOWED_FILE, "r") as f:
                return set(json.load(f))
        except (json.JSONDecodeError, IOError):
            pass
    return set()


def _save_followed(followed: set):
    with open(FOLLOWED_FILE, "w") as f:
        json.dump(list(followed), f, indent=2)


def run_engage_cycle():
    """Visit a sample of feed-discovered profiles, like their latest tweets."""
    from .evolution_store import filter_and_weight
    followed = _load_followed()
    pool = filter_and_weight(_build_pool())

    if not pool:
        log.info("[ENGAGE] Pool empty — no dynamic/discovered handles yet.")
        return

    count = random.randint(8, 12)
    # Always include VIPs if they're in the pool.
    vip_picks = [h for h in pool if h in VIP_ACCOUNTS]
    rest = [h for h in pool if h not in VIP_ACCOUNTS]
    random.shuffle(rest)
    picks = (vip_picks + rest)[:count]

    log.info(f"[ENGAGE] Visiting {len(picks)} profiles (pool size: {len(pool)})...")
    for username in picks:
        try:
            if username not in followed:
                log.info(f"[ENGAGE] Following + liking @{username}...")
                if follow_account(username):
                    followed.add(username)
                time.sleep(random.randint(2, 4))

            like_count = 5 if username in VIP_ACCOUNTS else 3
            log.info(f"[ENGAGE] Liking @{username}'s latest tweets...")
            visit_profile_and_like(username, like_count=like_count)
            time.sleep(random.randint(3, 5))
        except Exception:
            log.info(f"[ENGAGE] Failed to engage with @{username}:")
            traceback.print_exc()

    _save_followed(followed)
    log.info(f"[ENGAGE] Done. Engaged with {len(picks)} accounts.")


def safe_run_engage_cycle():
    from . import health
    try:
        run_engage_cycle()
        health.record_success("engage")
    except Exception:
        log.info("[ENGAGE] Error during engage cycle:")
        traceback.print_exc()
        health.record_failure("engage")

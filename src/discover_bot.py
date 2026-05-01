"""Discover bot: find new crypto/AI/bourse influencers and add them to monitoring."""
import json
import os
import random
import re
import traceback
from datetime import datetime
from .config import BLOCKLIST, DISCOVERED_ACCOUNTS_FILE, _PROJECT_ROOT
from .logger import log
from .twitter_client import scrape_x_search, follow_account

# Persisted set of handles we already auto-followed via discovery
FOLLOWED_FILE = os.path.join(_PROJECT_ROOT, "followed_accounts.json")

# Categories that count as "best FR AI/crypto/bourse" — those get auto-followed
AUTO_FOLLOW_CATEGORIES = {"ai", "crypto", "bourse"}


# Search queries — bumped 2026-04-26 on user directive: double the FR
# discovery throughput. Was 7 FR / 8 EN; now 18 FR / 4 EN. Auto-follow
# is already FR-only, so growing the FR query surface directly grows the
# rate of new FR followers.
DISCOVERY_QUERIES = [
    # FR — bourse / trading / finance (was 3, now 7)
    "bourse trading français",
    "CAC 40 analyse",
    "investissement long terme",
    "PEA bourse",
    "trader Paris",
    "ETF français",
    "analyse marché français",
    # FR — crypto (was 2, now 5)
    "crypto français analyse",
    "Bitcoin analyse FR",
    "crypto Paris",
    "DeFi français",
    "stablecoin français",
    # FR — IA (was 2, now 4)
    "intelligence artificielle français",
    "IA actualité",
    "Mistral AI français",
    "LLM français",
    # FR — tech / startup (new bucket, 2)
    "startup française tech",
    "VC français AI",
    # EN — keep just top-signal queries (was 8, now 4)
    "AI founder",
    "AI startup",
    "Bitcoin macro",
    "AGI",
]


def _load_discovered() -> list:
    if not os.path.exists(DISCOVERED_ACCOUNTS_FILE):
        return []
    try:
        with open(DISCOVERED_ACCOUNTS_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def _save_discovered(accounts: list):
    with open(DISCOVERED_ACCOUNTS_FILE, "w") as f:
        json.dump(accounts[-500:], f, indent=2)


def _load_followed() -> set:
    if not os.path.exists(FOLLOWED_FILE):
        return set()
    try:
        with open(FOLLOWED_FILE, "r") as f:
            return set(json.load(f))
    except (json.JSONDecodeError, IOError):
        return set()


def _save_followed(followed: set):
    with open(FOLLOWED_FILE, "w") as f:
        json.dump(list(followed), f, indent=2)


def _auto_follow_best(approved: list, discovered_state: list) -> list:
    """Follow approved FR ai/crypto/bourse handles we haven't followed yet.

    Returns the list of newly-followed handles (also flagged in discovered_state).
    """
    followed = _load_followed()
    newly_followed = []

    for k in approved:
        handle = (k.get("handle") or "").strip().lower()
        category = (k.get("category") or "").lower()
        lang = (k.get("lang") or "").lower()
        if not handle:
            continue
        if lang != "fr":
            continue  # FR-only auto-follow, per request
        if category not in AUTO_FOLLOW_CATEGORIES:
            continue
        if handle in followed:
            continue

        log.info(f"[DISCOVER] Auto-following @{handle} ({category}, fr)...")
        try:
            ok = follow_account(handle)
            if not ok:
                # JS click didn't fire (transient Safari race or stale selector).
                # Don't pollute followed_accounts.json — leave it out so we retry next cycle.
                continue
            followed.add(handle)
            newly_followed.append(handle)
            # Mark in discovered state so the JSON shows we acted on this entry
            for entry in discovered_state:
                if entry.get("handle", "").lower() == handle:
                    entry["followed"] = True
                    break
        except Exception as e:
            log.info(f"[DISCOVER] Follow failed for @{handle}: {e}")

    if newly_followed:
        _save_followed(followed)
    return newly_followed


def _existing_handles() -> set:
    """All handles we already know about (engage + reply targets + blocklist + already-discovered)."""
    from .engage_bot import TARGET_ACCOUNTS as ENGAGE_TARGETS
    from .reply_agent import TARGET_ACCOUNTS as REPLY_TARGETS
    handles = {h.lower() for h in list(ENGAGE_TARGETS) + list(REPLY_TARGETS)}
    handles |= {h.lower() for h in BLOCKLIST}
    handles |= {a.get("handle", "").lower() for a in _load_discovered()}
    handles.discard("")
    return handles


def _score_candidates(candidates: list) -> list:
    """Heuristic account filter. No model call."""
    if not candidates:
        return []

    spam = re.compile(r"signal|formation|promo|airdrop|giveaway|whatsapp|telegram|100x|garanti|coach", re.I)
    buckets = {
        "ai": re.compile(r"\b(ai|ia|llm|gpt|openai|anthropic|mistral|nvidia|agent)\b", re.I),
        "crypto": re.compile(r"\b(crypto|bitcoin|btc|ethereum|eth|solana|defi|blockchain)\b", re.I),
        "bourse": re.compile(r"\b(bourse|finance|trading|invest|actions|marché|sp500|nasdaq|cac40)\b", re.I),
        "tech": re.compile(r"\b(tech|startup|software|saas|cloud|cyber)\b", re.I),
    }
    fr_markers = re.compile(r"\b(le|la|les|des|une|pour|avec|marché|bourse|france|québec|ia)\b", re.I)

    keepers = []
    seen = set()
    for c in candidates[:25]:
        handle = (c.get("handle") or "").strip().lstrip("@")
        sample = c.get("sample") or ""
        if not handle or handle.lower() in seen or spam.search(sample):
            continue
        category = next((name for name, rx in buckets.items() if rx.search(sample)), "")
        if not category:
            continue
        seen.add(handle.lower())
        keepers.append({
            "handle": handle,
            "category": category,
            "lang": "fr" if fr_markers.search(sample) else "en",
        })
    return keepers


def run_discovery_cycle():
    """One discovery pass: search X, dedup, heuristic-filter, persist new handles."""
    log.info("[DISCOVER] Starting discovery cycle...")
    queries = random.sample(DISCOVERY_QUERIES, k=min(3, len(DISCOVERY_QUERIES)))
    known = _existing_handles()
    candidates_by_handle = {}

    for q in queries:
        try:
            tweets = scrape_x_search(q, max_tweets=15)
        except Exception as e:
            log.info(f"[DISCOVER] Search failed for '{q}': {e}")
            continue

        for t in tweets or []:
            handle = (t.get("author") or "").strip().lstrip("@").lower()
            text = t.get("text") or ""
            if not handle or handle == "unknown":
                continue
            # Reject display-name leaks ("btc inflow", "jerome colombain | monde numérique")
            # — the scraper occasionally hands back the rendered name instead of the @handle.
            # A real X handle is [A-Za-z0-9_]{1,15}; anything with whitespace or punctuation
            # other than underscore is a display-name and would just burn follow attempts.
            if any(c not in "abcdefghijklmnopqrstuvwxyz0123456789_" for c in handle) or len(handle) > 15:
                continue
            if handle in known or handle in candidates_by_handle:
                continue
            candidates_by_handle[handle] = {"handle": handle, "sample": text}

    candidates = list(candidates_by_handle.values())
    log.info(f"[DISCOVER] Found {len(candidates)} new candidates after dedup.")

    if not candidates:
        log.info("[DISCOVER] No new candidates this cycle.")
        return

    keepers = _score_candidates(candidates)
    log.info(f"[DISCOVER] Heuristic filter kept {len(keepers)} of {len(candidates)} candidates.")

    if not keepers:
        return

    # Persist with timestamp
    discovered = _load_discovered()
    today = datetime.now().strftime("%Y-%m-%d")
    for k in keepers:
        h = k.get("handle", "").strip().lower()
        if not h or h in known:
            continue
        discovered.append({
            "handle": h,
            "category": k.get("category", "unknown"),
            "added": today,
        })
        known.add(h)

    _save_discovered(discovered)
    new_handles = [k.get("handle") for k in keepers if k.get("handle")]
    log.info(f"[DISCOVER] Added {len(new_handles)} new handles: {', '.join(new_handles)}")

    # Auto-follow the best new FR ai/crypto/bourse accounts so they show up in our feed.
    followed = _auto_follow_best(keepers, discovered)
    if followed:
        _save_discovered(discovered)  # persist `followed: true` flags
        log.info(f"[DISCOVER] Auto-followed {len(followed)} FR account(s): {', '.join(followed)}")


def safe_run_discovery_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    try:
        run_discovery_cycle()
    except Exception:
        log.info("[DISCOVER] Error during discovery cycle:")
        traceback.print_exc()

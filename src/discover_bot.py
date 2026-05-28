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


# Search queries — 2026-05-27 pivot: English-first discovery.
# EN accounts fill our feed with global AI/crypto/markets signal.
# Small FR tail remains for major French stories only.
DISCOVERY_QUERIES = [
    # EN — AI labs / agents / devtools
    "AI founder OR AI startup OR AI developer lang:en",
    "OpenAI OR Anthropic OR Claude OR ChatGPT lang:en",
    "machine learning OR LLM OR agent OR frontier model lang:en",
    "Nvidia OR GPU OR AI chip OR semiconductor lang:en",
    "tech founder OR Y Combinator OR startup builder lang:en",
    "datacenter OR compute OR AI infrastructure lang:en",
    "robotics OR humanoid OR frontier tech lang:en",
    "Mistral OR Hugging Face OR open source AI lang:en",
    # EN — crypto / BTC / DeFi
    "Bitcoin OR BTC OR crypto investment lang:en",
    "Ethereum OR ETH OR DeFi OR stablecoin lang:en",
    "crypto mining OR Bitcoin mining lang:en",
    "CoreWeave OR MARA OR IREN OR CleanSpark lang:en",
    "Solana OR Bittensor OR TAO lang:en",
    "blockchain OR tokenization OR RWA lang:en",
    # EN — markets / macro / investing
    "stock market OR S&P 500 OR NASDAQ lang:en",
    "AI IPO OR tech IPO OR venture capital lang:en",
    "macro OR Fed OR inflation OR interest rates lang:en",
    "energy OR nuclear OR power grid OR natural gas lang:en",
    # EN — space / aerospace
    "SpaceX OR Starship OR Starlink lang:en",
    "space tech OR aerospace OR satellite lang:en",
    # EN — SaaS / tech business
    "SaaS OR B2B OR startup growth OR founder lang:en",
    "tech earnings OR Silicon Valley OR private equity lang:en",
    # FR tail — keep a few for diverse follow pool
    "startup IA France OR French Tech",
    "crypto analyste France OR Bitcoin France",
    "bourse investissement France",
]

DYNAMIC_LIVE_QUERY_SEEDS = [
    "OpenAI OR Anthropic OR Claude OR ChatGPT lang:en",
    "Bitcoin OR BTC OR Ethereum OR crypto lang:en",
    "Nvidia OR GPU OR datacenter OR AI lang:en",
    "CoreWeave OR MARA OR IREN OR Bittensor lang:en",
    "SpaceX OR Starship OR Starlink lang:en",
    "AI startup OR tech IPO OR VC funding lang:en",
    "Mistral OR HuggingFace OR open source AI lang:en",
    "macro OR Fed OR inflation OR stock market lang:en",
]

DYNAMIC_HOT_QUERY_SEEDS = [
    "OpenAI OR ChatGPT OR Claude lang:en min_faves:30",
    "Mistral OR Nvidia OR AI lang:en min_faves:30",
    "Bitcoin OR crypto OR Ethereum lang:en min_faves:30",
    "SpaceX OR Starship OR Starlink lang:en min_faves:15",
    "AI OR startup OR VC OR funding lang:en min_faves:20",
    "stock OR market OR macro OR Fed lang:en min_faves:20",
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
        if not handle:
            continue
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
    queries = random.sample(DISCOVERY_QUERIES, k=min(6, len(DISCOVERY_QUERIES)))
    known = _existing_handles()
    candidates_by_handle = {}

    for q in queries:
        try:
            tweets = scrape_x_search(q, max_tweets=30)
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

    # Feed the reply engine directly. discovery_state is archival; direct_reply
    # consumes dynamic_accounts/dynamic_queries every cycle.
    try:
        from .dynamic_strategy import add_dynamic_accounts, add_dynamic_queries
        en_handles = [k["handle"] for k in keepers if k.get("lang") == "en"]
        fr_handles = [k["handle"] for k in keepers if k.get("lang") == "fr"]
        if en_handles:
            added = add_dynamic_accounts(en=en_handles, known=known)
            log.info(f"[DISCOVER] Added {added} EN handle(s) to dynamic_accounts.json.")
        if fr_handles:
            added = add_dynamic_accounts(fr=fr_handles, known=known)
            log.info(f"[DISCOVER] Added {added} FR handle(s) to dynamic_accounts.json.")
        added_queries = add_dynamic_queries(
            live=random.sample(DYNAMIC_LIVE_QUERY_SEEDS, k=min(3, len(DYNAMIC_LIVE_QUERY_SEEDS))),
            hot=random.sample(DYNAMIC_HOT_QUERY_SEEDS, k=min(2, len(DYNAMIC_HOT_QUERY_SEEDS))),
        )
    except Exception:
        log.info("[DISCOVER] Dynamic strategy handoff failed:")
        traceback.print_exc()


def safe_run_discovery_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    try:
        run_discovery_cycle()
    except Exception:
        log.info("[DISCOVER] Error during discovery cycle:")
        traceback.print_exc()

"""Discover bot: autonomously find new crypto/AI/bourse influencers and add them to monitoring.

Runs every ~6h. Uses the existing X search scraper, then asks Claude to score the
candidates. Approved handles get appended to discovered_accounts.json, which is
merged into both the engage targets and the reply agent's prompt at runtime.
"""
import json
import os
import random
import re
import subprocess
import traceback
from datetime import datetime
from .config import REPLY_MODEL, BLOCKLIST, DISCOVERED_ACCOUNTS_FILE
from .logger import log
from .twitter_client import scrape_x_search


# Search queries — mix niches and languages, FR-leaning
DISCOVERY_QUERIES = [
    # FR — bourse / trading
    "bourse trading français",
    "CAC 40 analyse",
    "investissement long terme",
    # FR — crypto
    "crypto français analyse",
    "Bitcoin analyse FR",
    # FR — IA
    "intelligence artificielle français",
    "IA actualité",
    # EN — AI
    "AI founder",
    "AGI",
    "LLM benchmark",
    "AI startup",
    # EN — crypto
    "crypto trader",
    "Bitcoin macro",
    # EN — markets
    "macro markets",
    "S&P 500 analysis",
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
    """Ask Claude to pick the high-quality crypto/AI/bourse handles.

    candidates: [{"handle": "...", "sample": "..."}]
    Returns a filtered list of dicts with an added "category" key.
    """
    if not candidates:
        return []

    # Truncate samples to keep prompt small
    sample_blob = "\n".join(
        f"- @{c['handle']}: {c['sample'][:140]}" for c in candidates[:25]
    )

    prompt = f"""Tu es un curateur. Voici des comptes X candidats avec un de leurs tweets récents.

Ton job: garder UNIQUEMENT les comptes pertinents pour @kzer_ai (un compte FR qui couvre IA + crypto + bourse avec des analyses sharp et drôles).

CRITÈRES DE SÉLECTION:
- Le compte parle régulièrement de: IA, crypto, bourse/finance/trading, ou tech.
- Le compte a l'air actif et de qualité (pas un bot, pas un spam, pas un compte mort).
- Pas de comptes promo / arnaque / vente de signaux à 99€/mois.
- Pas de comptes politiques.

CANDIDATS:
{sample_blob}

Output UNIQUEMENT un JSON array avec les handles à garder, chacun catégorisé:
[{{"handle": "elonmusk", "category": "ai"}}, ...]

Categories valides: "ai", "crypto", "bourse", "tech".
Output rien d'autre que le JSON."""

    try:
        result = subprocess.run(
            ["claude", "-p", prompt, "--model", REPLY_MODEL],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            log.info(f"[DISCOVER] Scoring CLI error: {result.stderr[:200]}")
            return []

        out = result.stdout.strip()
        # Strip markdown fences if present
        if "```" in out:
            m = re.search(r"```(?:json)?\s*\n?(.*?)```", out, re.DOTALL)
            if m:
                out = m.group(1).strip()
        # Find JSON array
        if not out.startswith("["):
            i = out.find("[")
            j = out.rfind("]")
            if i != -1 and j > i:
                out = out[i:j + 1]

        data = json.loads(out)
        if not isinstance(data, list):
            return []
        return [d for d in data if isinstance(d, dict) and d.get("handle")]
    except Exception as e:
        log.info(f"[DISCOVER] Scoring failed: {e}")
        return []


def run_discovery_cycle():
    """One discovery pass: search X, dedup, score with Claude, persist new handles."""
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
            handle = (t.get("author") or "").strip().lower()
            text = t.get("text") or ""
            if not handle or handle == "unknown":
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
    log.info(f"[DISCOVER] Claude kept {len(keepers)} of {len(candidates)} candidates.")

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


def safe_run_discovery_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    try:
        run_discovery_cycle()
    except Exception:
        log.info("[DISCOVER] Error during discovery cycle:")
        traceback.print_exc()

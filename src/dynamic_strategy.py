"""Append-only stores for the autonomous strategy agent.

The strategy agent (src/strategy_agent.py) reads engagement_log.csv to compute
per-source ROI, then proposes new search queries and accounts to monitor.
Approved additions land in two JSON files that direct_reply / engage / reply
agents merge with their static lists at runtime.

Removals are NEVER auto-applied — only humans should prune. This keeps the
self-improvement loop safe: a bad scoring pass can only ADD noise, never
silently delete a hand-picked target.
"""
import json
import os
from datetime import datetime
from .config import _PROJECT_ROOT

DYNAMIC_QUERIES_FILE = os.path.join(_PROJECT_ROOT, "dynamic_queries.json")
DYNAMIC_ACCOUNTS_FILE = os.path.join(_PROJECT_ROOT, "dynamic_accounts.json")


def _load(path: str, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return default


def _save(path: str, obj):
    with open(path, "w") as f:
        json.dump(obj, f, indent=2)


def get_dynamic_queries() -> dict:
    """Returns {"live": [str], "hot": [str]}."""
    data = _load(DYNAMIC_QUERIES_FILE, {})
    return {"live": data.get("live", []), "hot": data.get("hot", [])}


def get_dynamic_accounts() -> dict:
    """Returns {"fr": [handle], "en": [handle]}."""
    data = _load(DYNAMIC_ACCOUNTS_FILE, {})
    return {"fr": data.get("fr", []), "en": data.get("en", [])}


def add_dynamic_queries(live: list = None, hot: list = None) -> int:
    """Append new queries (dedup). Returns number of new entries written."""
    data = _load(DYNAMIC_QUERIES_FILE, {"live": [], "hot": [], "history": []})
    data.setdefault("live", [])
    data.setdefault("hot", [])
    data.setdefault("history", [])
    added = 0
    today = datetime.now().strftime("%Y-%m-%d")
    for q in (live or []):
        q = q.strip()
        if q and q not in data["live"]:
            data["live"].append(q)
            data["history"].append({"kind": "live", "value": q, "added": today})
            added += 1
    for q in (hot or []):
        q = q.strip()
        if q and q not in data["hot"]:
            data["hot"].append(q)
            data["history"].append({"kind": "hot", "value": q, "added": today})
            added += 1
    if added:
        _save(DYNAMIC_QUERIES_FILE, data)
    return added


def add_dynamic_accounts(fr: list = None, en: list = None, known: set = None) -> int:
    """Append new account handles (dedup against `known` and existing entries)."""
    data = _load(DYNAMIC_ACCOUNTS_FILE, {"fr": [], "en": [], "history": []})
    data.setdefault("fr", [])
    data.setdefault("en", [])
    data.setdefault("history", [])
    known = {h.lower() for h in (known or set())}
    added = 0
    today = datetime.now().strftime("%Y-%m-%d")
    for h in (fr or []):
        h = h.strip().lstrip("@")
        if h and h.lower() not in known and h not in data["fr"]:
            data["fr"].append(h)
            data["history"].append({"lang": "fr", "handle": h, "added": today})
            added += 1
    for h in (en or []):
        h = h.strip().lstrip("@")
        if h and h.lower() not in known and h not in data["en"]:
            data["en"].append(h)
            data["history"].append({"lang": "en", "handle": h, "added": today})
            added += 1
    if added:
        _save(DYNAMIC_ACCOUNTS_FILE, data)
    return added

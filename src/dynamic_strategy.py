"""Append-only store of accounts harvested from the feeds.

`feed_sweeper_bot` appends the accounts it discovers to
`dynamic_accounts.json`. Removals are NEVER auto-applied — only humans should
prune, so a bad pass can only ADD noise, never silently delete a hand-picked
target.
"""
import json
import os
from datetime import datetime
from .config import _PROJECT_ROOT

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


def get_dynamic_accounts() -> dict:
    """Returns {"fr": [handle], "en": [handle]}."""
    data = _load(DYNAMIC_ACCOUNTS_FILE, {})
    return {"fr": data.get("fr", []), "en": data.get("en", [])}


def _is_valid_handle(h: str) -> bool:
    """X handles are [A-Za-z0-9_]{1,15}. Reject display-name leaks
    (e.g. 'la pique', 'jerome colombain | monde numérique', 17-char truncations)
    so strategy / scout agents can't pollute the active follow + reply pools."""
    return bool(h) and len(h) <= 15 and all(c.isascii() and (c.isalnum() or c == "_") for c in h)


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
        if not _is_valid_handle(h):
            continue
        if h.lower() not in known and h not in data["fr"]:
            data["fr"].append(h)
            data["history"].append({"lang": "fr", "handle": h, "added": today})
            added += 1
    for h in (en or []):
        h = h.strip().lstrip("@")
        if not _is_valid_handle(h):
            continue
        if h.lower() not in known and h not in data["en"]:
            data["en"].append(h)
            data["history"].append({"lang": "en", "handle": h, "added": today})
            added += 1
    if added:
        _save(DYNAMIC_ACCOUNTS_FILE, data)
    return added

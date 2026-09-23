"""Stores left by the removed evolution agent, now read-only.

- `directives.md`            — rules `reply_agent` injects into its prompt.
- `pruned_accounts.json`     — handles selectors skip. Each entry has an
                               `until` timestamp; expired entries are dropped
                               on read.
- `reinforced_accounts.json` — handles selectors weight more heavily.

No job writes these files any more: they hold what the evolution agent last
proposed, and the selection code reads them at runtime.
"""
import json
import os
from datetime import datetime
from .config import _PROJECT_ROOT

DIRECTIVES_FILE = os.path.join(_PROJECT_ROOT, "directives.md")
PRUNED_FILE = os.path.join(_PROJECT_ROOT, "pruned_accounts.json")
REINFORCED_FILE = os.path.join(_PROJECT_ROOT, "reinforced_accounts.json")


def _load_json(path: str, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return default


def _save_json(path: str, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


# ---------- DIRECTIVES (loaded by generation agents) ----------

def get_directives_block() -> str:
    """Return a compact block to inject into generation prompts. Empty if
    no directives have been generated yet (first run / clean state)."""
    if not os.path.exists(DIRECTIVES_FILE):
        return ""
    try:
        with open(DIRECTIVES_FILE, "r") as f:
            content = f.read().strip()
        if not content:
            return ""
        # Trim to keep the prompt size reasonable
        return f"\n\n=== DIRECTIVES AUTONOMES (issues de l'analyse de performance) ===\n{content[:1500]}\n=== FIN DIRECTIVES ===\n"
    except IOError:
        return ""


# ---------- PRUNED ACCOUNTS (filtered by selectors) ----------

def get_pruned_handles() -> set:
    """Return lowercase set of currently-pruned handles, with TTL cleanup."""
    data = _load_json(PRUNED_FILE, {"entries": []})
    entries = data.get("entries", [])
    now = datetime.now()

    fresh = []
    pruned = set()
    for e in entries:
        try:
            until = datetime.fromisoformat(e.get("until", ""))
        except (ValueError, TypeError):
            continue
        if until > now:
            fresh.append(e)
            pruned.add(e.get("handle", "").lower())

    # Rewrite if any expired (cheap, keeps file from growing forever)
    if len(fresh) != len(entries):
        _save_json(PRUNED_FILE, {"entries": fresh})

    pruned.discard("")
    return pruned


# ---------- REINFORCED ACCOUNTS (overweighted by selectors) ----------

def get_reinforced_handles() -> set:
    """Return lowercase set of currently-reinforced handles."""
    data = _load_json(REINFORCED_FILE, {"entries": []})
    return {e.get("handle", "").lower() for e in data.get("entries", []) if e.get("handle")}


# ---------- SELECTOR HELPERS (used by engage/early-bird/direct-reply) ----------

def filter_and_weight(accounts: list) -> list:
    """Return a new list with pruned accounts removed and reinforced accounts
    duplicated (so random.sample picks them more often). Case-insensitive.

    Reinforcement = 2x weight, which lifts a winner from ~1.5%/cycle pick
    probability to ~3%/cycle — meaningful without being mechanical.
    """
    pruned = get_pruned_handles()
    reinforced = get_reinforced_handles()
    out = []
    for a in accounts:
        a_lower = a.lower()
        if a_lower in pruned:
            continue
        out.append(a)
        if a_lower in reinforced:
            out.append(a)  # 2x weight via duplication
    return out

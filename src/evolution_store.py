"""Persistent stores for the autonomous evolution agent.

Three artifacts, all append-only / time-bounded so a bad agent run can never
silently destroy hand-curated state:

- `directives.md`   — overwritten each cycle. Short, actionable rules the
                      generation agents (news/reply/hot take) load at runtime.
                      Worst case: directives become noise → next cycle resets.
- `pruned_accounts.json`     — handles to skip in selectors. Each entry has
                               an `until` timestamp; auto-expires after 30 days
                               so accounts that had a slow week aren't lost.
- `reinforced_accounts.json` — handles to weight more heavily. No expiry,
                               additive only.

The evolution agent PROPOSES; this module APPLIES with caps + expiry. The
generation/selection code reads these stores at runtime — no restart needed.
"""
import json
import os
from datetime import datetime, timedelta
from .config import _PROJECT_ROOT

DIRECTIVES_FILE = os.path.join(_PROJECT_ROOT, "directives.md")
PRUNED_FILE = os.path.join(_PROJECT_ROOT, "pruned_accounts.json")
REINFORCED_FILE = os.path.join(_PROJECT_ROOT, "reinforced_accounts.json")
EVOLUTION_LOG_FILE = os.path.join(_PROJECT_ROOT, "evolution_log.json")

PRUNE_TTL_DAYS = 30
MAX_PRUNES_PER_CYCLE = 3   # safety cap so one bad run can't gut the roster
MAX_REINFORCEMENTS_PER_CYCLE = 5
# Fast-feedback path: when a recently-added source produces 0 engagement on
# ≥3 attempts, demote it with a SHORT TTL (7d) so it can come back if the
# situation changes. Distinct from the 30d evolution-agent prune.
FAST_PRUNE_TTL_DAYS = 7
MAX_FAST_PRUNES_PER_CYCLE = 5


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

def write_directives(directives: list, summary: str = ""):
    """Overwrite directives.md with the new directive list. Old directives
    are dropped — the agent re-derives them every cycle from fresh data."""
    if not directives:
        return
    body = "# Directives autonomes (régénérées chaque cycle d'évolution)\n\n"
    body += f"_Dernière mise à jour: {datetime.now().isoformat(timespec='minutes')}_\n\n"
    if summary:
        body += f"**Synthèse:** {summary}\n\n"
    body += "## À appliquer dans tous les tweets/replies/hot takes:\n\n"
    for d in directives:
        body += f"- {d}\n"
    with open(DIRECTIVES_FILE, "w") as f:
        f.write(body)


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

def _now_iso() -> str:
    return datetime.now().isoformat()


def add_pruned_accounts(handles: list, reason: str = ""):
    """Append handles to pruned set with TTL. Returns count of NEW prunes."""
    if not handles:
        return 0
    data = _load_json(PRUNED_FILE, {"entries": []})
    data.setdefault("entries", [])
    existing = {e.get("handle", "").lower() for e in data["entries"]}

    until = (datetime.now() + timedelta(days=PRUNE_TTL_DAYS)).isoformat()
    added = 0
    for h in handles[:MAX_PRUNES_PER_CYCLE]:  # hard cap
        h = h.strip().lstrip("@").lower()
        if not h or h in existing:
            continue
        data["entries"].append({
            "handle": h,
            "reason": reason[:200],
            "added": _now_iso(),
            "until": until,
        })
        existing.add(h)
        added += 1
    if added:
        _save_json(PRUNED_FILE, data)
    return added


def fast_demote(handles: list, reason: str = "") -> int:
    """Short-TTL prune for the fast-feedback path. Same store as the 30d prunes
    but with a 7d expiry so a bad week doesn't blacklist a source forever.
    Returns count of NEW demotions."""
    if not handles:
        return 0
    data = _load_json(PRUNED_FILE, {"entries": []})
    data.setdefault("entries", [])
    existing = {e.get("handle", "").lower() for e in data["entries"]}

    until = (datetime.now() + timedelta(days=FAST_PRUNE_TTL_DAYS)).isoformat()
    added = 0
    for h in handles[:MAX_FAST_PRUNES_PER_CYCLE]:
        h = h.strip().lstrip("@").lower()
        if not h or h in existing:
            continue
        data["entries"].append({
            "handle": h,
            "reason": f"[FAST] {reason}"[:200],
            "added": _now_iso(),
            "until": until,
        })
        existing.add(h)
        added += 1
    if added:
        _save_json(PRUNED_FILE, data)
    return added


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

def add_reinforced_accounts(handles: list, reason: str = ""):
    """Append handles to reinforced set. No TTL — confirmed winners stay."""
    if not handles:
        return 0
    data = _load_json(REINFORCED_FILE, {"entries": []})
    data.setdefault("entries", [])
    existing = {e.get("handle", "").lower() for e in data["entries"]}

    added = 0
    for h in handles[:MAX_REINFORCEMENTS_PER_CYCLE]:
        h = h.strip().lstrip("@").lower()
        if not h or h in existing:
            continue
        data["entries"].append({
            "handle": h,
            "reason": reason[:200],
            "added": _now_iso(),
        })
        existing.add(h)
        added += 1
    if added:
        _save_json(REINFORCED_FILE, data)
    return added


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


# ---------- AUDIT LOG ----------

def append_evolution_log(entry: dict):
    """Persist what was applied this cycle for auditability."""
    history = _load_json(EVOLUTION_LOG_FILE, [])
    if not isinstance(history, list):
        history = []
    history.append(entry)
    _save_json(EVOLUTION_LOG_FILE, history[-100:])

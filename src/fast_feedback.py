"""Fast-feedback dead-source scanner.

Closes the gap between strategy_agent (adds new sources every 6h) and
evolution_agent (audits performance every 12h). Without this module, a
freshly-added strategy source can absorb dozens of replies for a full
12h before any pruning kicks in.

Heuristic (intentionally simple + safe):
- Scan engagement_log.csv for the last 8h.
- Group reply attempts by `source` column (e.g. "PROFILE-FR/handle").
- For each source: if (a) the underlying handle was added by the strategy
  agent (lives in dynamic_accounts.json's history), AND (b) it's been
  attempted >= MIN_ATTEMPTS times in the window, AND (c) it's not already
  reinforced, then fast-demote it with a 7d TTL.

Hand-curated static targets are NEVER touched here. Only the strategy
agent's own additions are subject to fast pruning. This preserves the
"append-only safety boundary" already documented in CLAUDE.md.

Called once per performance cycle (every 2h) so a bad addition gets
killed within 2h of crossing the noise threshold.
"""
import csv
import os
import re
from datetime import datetime, timedelta
from typing import Optional

from .config import ENGAGEMENT_LOG_FILE
from .logger import log
from .dynamic_strategy import get_dynamic_accounts, DYNAMIC_ACCOUNTS_FILE
from .evolution_store import fast_demote, get_pruned_handles, get_reinforced_handles

WINDOW_HOURS = 8
MIN_ATTEMPTS = 5  # cross this in 8h on a strategy-added source = dead

# Source tags look like "PROFILE-FR/Handle", "EARLYBIRD/Handle",
# "SEARCH-FR-HOT/Bitcoin lang:fr", etc. We extract the handle when present.
_HANDLE_FROM_SOURCE = re.compile(r"/([A-Za-z0-9_]{2,20})\b")


def _extract_handle(source: str) -> Optional[str]:
    """Pull a handle out of a source tag if it's a profile-keyed source.
    Search-keyed sources return None (we never demote whole queries here)."""
    if not source:
        return None
    if source.upper().startswith("SEARCH"):
        return None
    m = _HANDLE_FROM_SOURCE.search(source)
    if not m:
        return None
    return m.group(1).lower()


def _strategy_added_handles() -> set:
    """Lowercase set of handles the strategy agent has ever added."""
    accounts = get_dynamic_accounts()
    return {h.lower() for h in (accounts.get("fr", []) + accounts.get("en", []))}


def _recent_source_counts() -> dict:
    """Count reply attempts per source in the last WINDOW_HOURS."""
    if not os.path.exists(ENGAGEMENT_LOG_FILE):
        return {}
    cutoff = datetime.now() - timedelta(hours=WINDOW_HOURS)
    counts: dict = {}
    try:
        with open(ENGAGEMENT_LOG_FILE, "r", newline="") as f:
            reader = csv.reader(f)
            next(reader, None)  # header
            for row in reader:
                if len(row) < 5:
                    continue
                ts_str, _type, _text, _url, source = row[0], row[1], row[2], row[3], row[4]
                if not source:
                    continue
                try:
                    ts = datetime.fromisoformat(ts_str)
                except ValueError:
                    continue
                if ts < cutoff:
                    continue
                counts[source] = counts.get(source, 0) + 1
    except (IOError, OSError) as e:
        log.info(f"[FAST-FB] Could not read engagement log: {e}")
        return {}
    return counts


def scan_and_demote_dead_sources() -> int:
    """Run one fast-feedback pass. Returns count of newly-demoted handles."""
    counts = _recent_source_counts()
    if not counts:
        return 0

    strategy_handles = _strategy_added_handles()
    if not strategy_handles:
        return 0

    already_pruned = get_pruned_handles()
    reinforced = get_reinforced_handles()

    # Aggregate per-handle attempt counts (a handle can appear in multiple
    # source tags, e.g. PROFILE-FR/X and EARLYBIRD/X).
    handle_attempts: dict = {}
    for source, n in counts.items():
        h = _extract_handle(source)
        if not h:
            continue
        if h not in strategy_handles:
            continue  # never touch hand-curated static targets
        if h in already_pruned or h in reinforced:
            continue
        handle_attempts[h] = handle_attempts.get(h, 0) + n

    candidates = [h for h, n in handle_attempts.items() if n >= MIN_ATTEMPTS]
    if not candidates:
        return 0

    # Sort by most-attempted first so the worst offenders go first when the
    # MAX_FAST_PRUNES_PER_CYCLE cap kicks in.
    candidates.sort(key=lambda h: -handle_attempts[h])

    n_demoted = fast_demote(
        candidates,
        reason=f"≥{MIN_ATTEMPTS} attempts in {WINDOW_HOURS}h, no reinforcement",
    )
    if n_demoted:
        log.info(
            f"[FAST-FB] Demoted {n_demoted} dead source(s) (7d TTL): "
            f"{[(h, handle_attempts[h]) for h in candidates[:n_demoted]]}"
        )
    return n_demoted

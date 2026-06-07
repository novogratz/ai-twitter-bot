"""Seed-priority follow bot (2026-06-07 agent spec, Part 1 — Following).

Rebuilds the following list from near-zero after the full purge, walking the
curated seed list in whitelist.json in the spec's priority order:

  tier1 (foils / persona ecosystem — follow FIRST, highest ROI)
  → tier2 (niche reply targets) → tier3 (AI signal) → tier4 (crypto/markets).

Pacing and the hard constraints live at the chokepoint
(twitter_client.follow_account → action_guard.can_follow): whitelist-only,
max 20 follows/day, >=10-min randomized gaps, total-following ceiling
(300 hard / ~150 while followers are low), 30-day anti-churn. This bot only
decides WHO is next; it attempts ONE follow per cycle and lets the guard
refuse the rest — so the schedule can run often without ever bursting.

Handles in the seed list are HINTS (handles drift): follow_account visits
the profile and only records a follow when the click actually fired, so an
unresolved/suspended handle simply fails and is logged + retried later.
Idempotent via `followed_accounts.json` (shared with engage_bot).
"""
import json
import os
import re
import subprocess
import tempfile
import time
import traceback
import webbrowser
from datetime import datetime, timedelta

from .config import _PROJECT_ROOT, WHITELIST_FILE
from .logger import log
from .twitter_client import follow_account, _safari_lock, close_front_tab
from . import engage_bot

# Spec priority order — tier1 first, always. "discovered" (curator-promoted,
# 2026-06-07 operator grant) follows LAST: operator seeds always outrank the
# bot's own finds.
_TIER_ORDER = ("tier1", "tier2", "tier3", "tier4", "discovered")

# Seeds that failed identity resolution (handle squatted/renamed/off-niche).
# Persisted so a mismatch isn't re-scraped every 15 min; retried weekly in
# case the seed list gets corrected or the account comes back.
UNRESOLVED_FILE = os.path.join(_PROJECT_ROOT, "seed_unresolved.json")
_UNRESOLVED_RETRY_DAYS = 7


def _load_seed_rows() -> list:
    """Ordered seed rows from whitelist.json — seeds[] (sorted by priority)
    when present, else bare {handle} rows from tiers in tier1→tier4 order."""
    try:
        with open(WHITELIST_FILE) as f:
            raw = json.load(f) or {}
    except (OSError, json.JSONDecodeError):
        return []
    seeds = raw.get("seeds")
    tiers = raw.get("tiers") or {}
    if isinstance(seeds, list) and seeds:
        rows = [s for s in seeds if isinstance(s, dict) and s.get("handle")]
        rows.sort(key=lambda s: s.get("priority", 999))
        # Curator-promoted handles queue AFTER the operator seeds (they're
        # in tiers["discovered"] only, never in seeds[]).
        seeded = {str(s["handle"]).lower() for s in rows}
        rows.extend({"handle": str(h)} for h in (tiers.get("discovered") or [])
                    if str(h).lower() not in seeded)
        return rows
    rows = []
    for t in _TIER_ORDER:
        rows.extend({"handle": str(h)} for h in (tiers.get(t) or []))
    return rows


def _seed_handles_in_priority_order() -> list:
    return [str(s["handle"]) for s in _load_seed_rows()]


# --- handle resolution (spec: "handles drift — treat each @handle as a
# HINT, not ground truth; never follow a wrong/ambiguous handle") ----------

_NAME_STOPWORDS = {"the", "of", "and", "a", "an", "mr", "dr"}


def _seed_matches_identity(seed: dict, scraped_name: str, scraped_bio: str = "") -> bool:
    """Pure matcher: does the scraped profile look like the seed we expect?

    True when any significant token of the expected display name appears in
    the scraped display name, OR any seed keyword appears in the name+bio.
    A seed with no display_name/keywords metadata always matches (nothing
    to verify against).
    """
    expected = (seed.get("display_name") or "").lower()
    keywords = [str(k).lower() for k in (seed.get("keywords") or [])]
    if not expected and not keywords:
        return True
    hay_name = (scraped_name or "").lower()
    hay_full = hay_name + " " + (scraped_bio or "").lower()
    name_tokens = [t for t in re.split(r"[^a-z0-9]+", expected)
                   if len(t) >= 3 and t not in _NAME_STOPWORDS]
    if any(t in hay_name for t in name_tokens):
        return True
    return any(k in hay_full for k in keywords)


def _scrape_profile_identity(handle: str):
    """Best-effort (display_name, bio) scrape of x.com/<handle>.
    Returns (None, None) on any failure — caller treats that as
    'could not verify, proceed' (follow_account fails safe anyway)."""
    js = """
    (function() {
        var n = document.querySelector('[data-testid="UserName"]');
        var b = document.querySelector('[data-testid="UserDescription"]');
        var name = n ? n.innerText.split('\\n')[0] : '';
        var bio = b ? b.innerText : '';
        return JSON.stringify({name: name, bio: bio});
    })()
    """
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".js", delete=False)
    tmp.write(js)
    tmp.close()
    osa = f'''
    tell application "Safari" to activate
    set jsCode to (read POSIX file "{tmp.name}")
    tell application "Safari"
        set result to do JavaScript jsCode in current tab of front window
    end tell
    '''
    try:
        with _safari_lock:
            webbrowser.open(f"https://x.com/{handle}")
            time.sleep(6)
            r = subprocess.run(["osascript", "-e", osa],
                               capture_output=True, text=True, timeout=30)
            close_front_tab()
        if r.returncode != 0:
            return (None, None)
        doc = json.loads((r.stdout or "").strip() or "{}")
        return (doc.get("name") or None, doc.get("bio") or "")
    except Exception:
        return (None, None)
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


def _load_unresolved() -> dict:
    try:
        with open(UNRESOLVED_FILE) as f:
            return json.load(f) or {}
    except (OSError, json.JSONDecodeError):
        return {}


def _mark_unresolved(handle: str, reason: str) -> None:
    doc = _load_unresolved()
    doc[handle.lower()] = {"ts": datetime.now().isoformat(), "reason": reason}
    try:
        with open(UNRESOLVED_FILE, "w") as f:
            json.dump(doc, f, indent=2)
    except OSError:
        pass


def _recently_unresolved(handle: str) -> bool:
    row = _load_unresolved().get(handle.lower())
    if not row:
        return False
    try:
        ts = datetime.fromisoformat(row.get("ts", ""))
    except ValueError:
        return False
    return datetime.now() - ts < timedelta(days=_UNRESOLVED_RETRY_DAYS)


def run_marquee_follow_cycle() -> None:
    """Follow the single highest-priority seed not yet followed.

    One attempt per cycle: the action_guard spacing rule (>=10 min between
    follows) would refuse back-to-back follows anyway, and one-at-a-time is
    exactly the "spread with randomized gaps, never burst" behavior the spec
    demands.

    Resolution rule (spec): a seed with display_name/keywords metadata is
    VERIFIED before the follow — scrape the profile's name+bio and require a
    match. A confident mismatch (scrape worked, nothing matched) is logged
    to seed_unresolved.json and retried weekly, never followed. A failed
    scrape proceeds — follow_account fails safe on dead profiles anyway.
    """
    followed = engage_bot._load_followed()
    followed_lc = {f.lower() for f in followed}
    pending = [s for s in _load_seed_rows()
               if s["handle"].lower() not in followed_lc
               and not _recently_unresolved(s["handle"])]
    if not pending:
        log.info("[SEED-FOLLOW] Seed list fully followed/resolved — holding "
                 "(discovery candidates go to whitelist suggestions[] for approval).")
        return
    seed = pending[0]
    handle = str(seed["handle"])
    log.info(f"[SEED-FOLLOW] Next seed (priority order): @{handle} "
             f"({len(pending)} pending).")

    # Cheap guard pre-check BEFORE paying the Safari identity visit: if the
    # chokepoint would refuse this follow anyway (daily cap, 10-min spacing,
    # 300/150 total ceiling, churn), skip the whole cycle now. The
    # chokepoint inside follow_account stays the authoritative gate.
    from . import action_guard
    ok, why = action_guard.can_follow(handle)
    if not ok:
        log.info(f"[SEED-FOLLOW] Guard refuses @{handle} right now ({why}) — "
                 f"skipping cycle (no Safari work).")
        return

    # Verify identity when the seed carries resolution metadata.
    if seed.get("display_name") or seed.get("keywords"):
        name, bio = _scrape_profile_identity(handle)
        if name is not None and not _seed_matches_identity(seed, name, bio):
            log.info(f"[SEED-FOLLOW] @{handle} FAILED resolution: scraped "
                     f"name {name!r} doesn't match expected "
                     f"{seed.get('display_name')!r} / keywords "
                     f"{seed.get('keywords')} — skipping for "
                     f"{_UNRESOLVED_RETRY_DAYS}d, never following blind.")
            _mark_unresolved(handle, f"name {name!r} != {seed.get('display_name')!r}")
            return
        if name is None:
            log.info(f"[SEED-FOLLOW] @{handle} identity scrape failed — "
                     f"proceeding (follow_account fails safe).")

    try:
        if follow_account(handle):
            followed.add(handle)
            engage_bot._save_followed(followed)
            log.info(f"[SEED-FOLLOW] Followed @{handle}.")
        else:
            # Guard refusal (cap/spacing/ceiling) or dead profile —
            # follow_account already logged the reason; retry next cycle.
            log.info(f"[SEED-FOLLOW] @{handle} not followed this cycle.")
    except Exception:
        log.info(f"[SEED-FOLLOW] follow_account crashed on @{handle}:")
        traceback.print_exc()


def safe_run_marquee_follow_cycle() -> None:
    from . import health
    try:
        run_marquee_follow_cycle()
        health.record_success("marquee_follow")
    except Exception:
        log.info("[SEED-FOLLOW] outer error:")
        traceback.print_exc()
        health.record_failure("marquee_follow")

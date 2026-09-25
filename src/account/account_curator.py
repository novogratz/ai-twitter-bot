"""Self-curated account tracking (operator mandate 2026-06-07 PM).

"Stop going to the static accounts we discussed in the past and develop
yourself the list of accounts you want to follow and track their posts so
you use it as content. The only ones you should continue: TheBTCTherapist
and Graphseo."

Replaces the hand-curated EARLY_BIRD/MEGA lists with a list the bot earns
from its OWN evidence, recomputed every 4h into `tracked_accounts.json`:

  score(author) = engagements_14d × conversion_weight
    - engagements_14d: how often our reply/quote bots found this author's
      posts worth engaging (engagement_log parent authors, last 14 days) —
      authors who keep producing on-lane, reply-worthy content rise.
    - conversion_weight: engagement_targets_log per-author weight, bumped
      by conversion_attribution_bot when replying to that author actually
      produced followers (cap 3.0). Evidence of ROI, not just activity.

PINNED_TRACKED_HANDLES (always tracked, never decay): TheBTCTherapist, Graphseo.

The curator may also PROMOTE its strongest finds into the whitelist's
"discovered" tier, whitelist_discovered.json (operator-granted 2026-06-07:
"develop yourself the list of accounts you want to follow") — hard-capped at
CURATOR_DISCOVERED_PER_DAY adds/day and CURATOR_DISCOVERED_MAX total, never
touching the Operator's whitelist.json, every add logged. All follow chokepoint rules (20/day,
10-min gaps, 300/150 ceiling, 30d churn) still govern actual follows.
"""
import csv
import re
import traceback
from collections import defaultdict
from datetime import datetime, timedelta

from ..core import config, settings
from ..core.config import ENGAGEMENT_LOG_FILE
from ..core.logger import log
from ..core.state_store import DISPOSABLE, StateFile
from ..guards import active_hours
# A missing or corrupt whitelist stops the cycle before any promotion.
from ..guards.follow_policy import DISCOVERED, WHITELIST
from ..guards.reply_admission import is_blocked_account

# Disposable: recomputed every run from the engagement log.
TRACKED = StateFile("tracked_accounts.json", {}, DISPOSABLE)
TARGETS_LOG = StateFile("engagement_targets_log.json", {}, DISPOSABLE)

_AUTHOR_RE = re.compile(r"x\.com/([A-Za-z0-9_]{1,15})/status/")


def pinned_handles() -> tuple:
    return tuple(h.strip() for h in settings.get("PINNED_TRACKED_HANDLES").split(",") if h.strip())


def _author_engagements(window_days: int | None = None) -> dict:
    """{author_lc: count} of our ON-LANE replies/quotes per parent author.

    Lane gate: only engagements whose outgoing text classified into a real
    pillar count as evidence — rows tagged "other" (which is where FR-era
    replies and off-voice noise land) are ignored. This is what lets the
    curator survive a persona pivot: stale-lane evidence stops scoring the
    moment the voice changed, even though the rows are still in the window.
    """
    from ..core.pillar_tags import classify as _classify_pillar
    if window_days is None:
        window_days = settings.get("CURATOR_WINDOW_DAYS")
    cutoff = (datetime.now() - timedelta(days=window_days)).isoformat()
    counts: dict = defaultdict(int)
    own = (config.BOT_HANDLE or "").lower()
    try:
        with open(ENGAGEMENT_LOG_FILE, newline="") as f:
            for row in csv.reader(f):
                if len(row) < 4 or row[0] < cutoff:
                    continue
                if row[1] not in ("reply", "quote", "quote_gif", "retweet"):
                    continue
                m = _AUTHOR_RE.search(row[3] or "")
                if not m:
                    continue
                a = m.group(1).lower()
                if a == own or is_blocked_account(a):
                    continue
                pillar = (row[6].strip() if len(row) > 6 and row[6] else
                          _classify_pillar(row[2] if len(row) > 2 else "", row[1]))
                if pillar == "other":
                    continue
                counts[a] += 1
    except OSError:
        pass
    return counts


def _conversion_weights() -> dict:
    """{author_lc: weight} from engagement_targets_log (conversion-bumped)."""
    try:
        return {a.lower(): float(v.get("weight", 1.0))
                for a, v in (TARGETS_LOG.read().get("authors") or {}).items()}
    except (AttributeError, ValueError, TypeError):
        return {}


def _load_tracked_doc() -> dict:
    return TRACKED.read()


def tracked_handles(limit: int = 30) -> list:
    """Pinned handles first, then the bot's own earned list. This is THE source the
    early-reply bots scan — no static fallback by operator mandate."""
    doc = _load_tracked_doc()
    rows = doc.get("tracked") or []
    out = list(pinned_handles())
    seen = {h.lower() for h in out}
    for r in rows:
        h = r.get("handle", "")
        if h and h.lower() not in seen:
            out.append(h)
            seen.add(h.lower())
        if len(out) >= limit:
            break
    return out


def _promotable(cand: dict) -> bool:
    """TRACKING an account costs a scan; PROMOTING one means we FOLLOW it —
    the bar is higher. Reject spam-pattern handles (long digit runs are the
    classic burner/airdrop fingerprint) and require deeper engagement
    evidence than the tracking floor."""
    h = cand.get("handle", "")
    if re.search(r"\d{4,}", h):
        return False
    return int(cand.get("engagements", 0)) >= settings.get("CURATOR_PROMOTE_MIN_ENGAGEMENTS")


def _promote_to_whitelist(candidates: list, doc: dict) -> int:
    """Add top candidates to the discovered tier (capped/logged)."""
    candidates = [c for c in candidates if _promotable(c)]
    meta = doc.setdefault("promotion_meta", {})
    if active_hours.is_past_day(meta.get("date")):
        meta["count"] = 0
    meta["date"] = active_hours.today_iso()
    budget = settings.get("CURATOR_DISCOVERED_PER_DAY") - int(meta.get("count", 0))
    if budget <= 0:
        return 0
    tiers = WHITELIST.read().get("tiers") or {}
    operator_handles = {str(h).lower() for t in tiers.values() for h in (t or [])}
    discovered_max = settings.get("CURATOR_DISCOVERED_MAX")
    promoted = []

    def promote(discovered):
        existing = operator_handles | {str(h).lower() for h in discovered}
        for cand in candidates:
            if len(promoted) >= budget or len(discovered) >= discovered_max:
                break
            h = cand["handle"]
            if h.lower() in existing:
                continue
            discovered.append(h)
            existing.add(h.lower())
            promoted.append(cand)
        return discovered if promoted else None
    DISCOVERED.update(promote)
    for cand in promoted:
        log.info(f"[CURATOR] PROMOTED @{cand['handle']} to whitelist discovered tier "
                 f"(score {cand['score']:.1f}, {cand['engagements']} engagements, "
                 f"weight {cand['weight']}).")
    if promoted:
        meta["count"] = int(meta.get("count", 0)) + len(promoted)
    return len(promoted)


def run_curator_cycle() -> None:
    engagements = _author_engagements()
    weights = _conversion_weights()
    pinned = pinned_handles()
    pinned_lc = {h.lower() for h in pinned}
    min_engagements = settings.get("CURATOR_MIN_ENGAGEMENTS")
    scored = []
    for a, n in engagements.items():
        if n < min_engagements or a in pinned_lc:
            continue
        w = weights.get(a, 1.0)
        scored.append({"handle": a, "engagements": n, "weight": w,
                       "score": round(n * w, 2)})
    scored.sort(key=lambda r: r["score"], reverse=True)
    tracked = scored[:settings.get("CURATOR_TRACKED_MAX")]

    doc = _load_tracked_doc()
    doc["tracked"] = tracked
    doc["pinned"] = list(pinned)
    doc["updated"] = datetime.now().isoformat()
    promoted = _promote_to_whitelist(tracked[:10], doc)
    TRACKED.write(doc)
    top = ", ".join(f"@{r['handle']}({r['score']})" for r in tracked[:5])
    log.info(f"[CURATOR] {len(tracked)} tracked (top: {top}); "
             f"{promoted} promoted to whitelist discovered tier.")


def safe_run_curator_cycle() -> None:
    from ..core import health
    try:
        run_curator_cycle()
        health.record_success("account_curator")
    except Exception:
        log.info("[CURATOR] outer error:")
        traceback.print_exc()
        health.record_failure("account_curator")

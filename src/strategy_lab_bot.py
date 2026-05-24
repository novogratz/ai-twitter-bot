"""Autonomous strategy lab — proposes, applies, measures, and reverts
strategic changes to the bot's live config based on what actually moves
followers + likes.

Loop (runs every hour):

  1. AUDIT — if there's an active experiment whose eval window has
     expired (default 4h), compute Δfollowers and Δlikes-per-post vs
     the baseline snapshot taken when the experiment started. Keep if
     it helped, REVERT to the prior value if it didn't. Log the
     decision to strategy_ledger.md.

  2. PROPOSE — if no experiment is active and the cooldown has passed,
     send Claude:
       - the current live_strategy.json
       - the last 24h of follower history
       - the last ~50 posts' likes/views/source
       - the last few experiment outcomes from strategy_ledger.md
     Claude returns ONE JSON patch describing a single targeted change
     (e.g. "bump MAX_REPLIES_PER_CYCLE 40 → 60 because reply-source
     posts averaged 12 likes vs 4 for news"). We apply it, snapshot
     baseline metrics, mark active.

State:
  - strategy_experiments.json  (current active + last 30 history)
  - strategy_ledger.md         (human-readable log of decisions)

Safety:
  - Only ONE experiment active at a time.
  - Only patches a whitelisted set of paths (caps + cadence_factor).
  - Conservative deltas (max ±50% per change).
  - Auto-revert is the default if the metric didn't improve.
"""
import json
import os
import re
import time
import traceback
from datetime import datetime, timedelta
from typing import Optional

from .config import _PROJECT_ROOT, REPLY_MODEL
from .logger import log
from .llm_client import run_llm, unwrap_text

LIVE_STRATEGY_FILE = os.path.join(_PROJECT_ROOT, "live_strategy.json")
EXPERIMENTS_FILE = os.path.join(_PROJECT_ROOT, "strategy_experiments.json")
LEDGER_FILE = os.path.join(_PROJECT_ROOT, "strategy_ledger.md")
FOLLOWER_HISTORY_FILE = os.path.join(_PROJECT_ROOT, "follower_history.json")
ENGAGEMENT_LOG_FILE = os.path.join(_PROJECT_ROOT, "engagement_log.csv")
PERFORMANCE_LOG_FILE = os.path.join(_PROJECT_ROOT, "performance_log.json")

# Paths we're allowed to mutate. Anything else from the LLM gets rejected.
ALLOWED_PATHS = {
    "caps.MAX_NEWS_PER_DAY":      (4, 8),
    "caps.MAX_HOTAKES_PER_DAY":   (2, 5),
    "caps.MAX_BREAKOUTS_PER_DAY": (0, 20),
    "caps.MAX_SPICY_PER_DAY":     (0, 20),
    "caps.MAX_QUOTES_PER_DAY":    (20, 120),
    "caps.MAX_RETWEETS_PER_DAY":  (8, 30),
    "caps.MAX_REPLIES_PER_CYCLE": (1, 5),
    "caps.FOLLOW_BLAST_PER_CYCLE": (20, 200),
    "caps.LIKE_BOT_PER_CYCLE":    (20, 200),
    "cadence_factor":             (0.5, 1.5),
}

EVAL_WINDOW_HOURS = int(os.environ.get("STRATEGY_LAB_EVAL_HOURS", "4"))
COOLDOWN_AFTER_DECISION_MINUTES = 30


def _load_json(path: str, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def _save_json(path: str, data) -> None:
    try:
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
    except OSError:
        log.info(f"[STRATEGY_LAB] save failed for {path}")


def _appendln_ledger(line: str) -> None:
    try:
        with open(LEDGER_FILE, "a") as f:
            f.write(line.rstrip() + "\n")
    except OSError:
        pass


def _get_path(d: dict, path: str):
    cur = d
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _set_path(d: dict, path: str, value) -> None:
    parts = path.split(".")
    cur = d
    for p in parts[:-1]:
        if not isinstance(cur.get(p), dict):
            cur[p] = {}
        cur = cur[p]
    cur[parts[-1]] = value


def _followers_at(snapshot: list, when: datetime) -> Optional[int]:
    """Closest follower count at-or-before `when`."""
    if not isinstance(snapshot, list):
        return None
    best = None
    for entry in snapshot:
        try:
            ts = datetime.fromisoformat(entry["ts"])
            if ts <= when:
                best = entry.get("count")
        except (KeyError, ValueError, TypeError):
            continue
    return best


def _likes_per_post_since(since: datetime) -> Optional[float]:
    """Average likes across our posts in performance_log.json with
    scraped_at >= since. Returns None if no data."""
    data = _load_json(PERFORMANCE_LOG_FILE, [])
    if not isinstance(data, list):
        return None
    likes = []
    for p in data:
        try:
            sa = p.get("scraped_at")
            ts = datetime.fromisoformat(sa) if sa else None
            if ts and ts >= since:
                likes.append(int(p.get("likes") or 0))
        except (ValueError, TypeError):
            continue
    if not likes:
        return None
    return sum(likes) / len(likes)


def _snapshot_metrics(now: datetime) -> dict:
    """Capture current followers + avg likes-per-post baseline."""
    follower_hist = _load_json(FOLLOWER_HISTORY_FILE, [])
    followers = _followers_at(follower_hist, now)
    lpp = _likes_per_post_since(now - timedelta(hours=24))
    return {
        "ts": now.isoformat(timespec="seconds"),
        "followers": followers,
        "likes_per_post_24h": lpp,
    }


def _compute_delta(baseline: dict, current: dict) -> dict:
    df = None
    if baseline.get("followers") is not None and current.get("followers") is not None:
        df = current["followers"] - baseline["followers"]
    dl = None
    if baseline.get("likes_per_post_24h") is not None and current.get("likes_per_post_24h") is not None:
        dl = current["likes_per_post_24h"] - baseline["likes_per_post_24h"]
    return {"d_followers": df, "d_likes_per_post": dl}


def _was_winner(delta: dict) -> bool:
    df = delta.get("d_followers")
    dl = delta.get("d_likes_per_post")
    # Either a meaningful follower bump or a clear likes-per-post bump = keep.
    if df is not None and df >= 3:
        return True
    if dl is not None and dl >= 1.0:
        return True
    return False


def _audit_active_experiment(state: dict, now: datetime) -> bool:
    """Returns True if we resolved (kept or reverted) an experiment this cycle."""
    active = state.get("active")
    if not active:
        return False
    try:
        applied_at = datetime.fromisoformat(active["applied_at"])
    except (KeyError, ValueError):
        log.info("[STRATEGY_LAB] active experiment malformed — clearing.")
        state["active"] = None
        return True
    age_hours = (now - applied_at).total_seconds() / 3600.0
    if age_hours < EVAL_WINDOW_HOURS:
        log.info(f"[STRATEGY_LAB] experiment age {age_hours:.1f}h < {EVAL_WINDOW_HOURS}h — waiting.")
        return False

    current_metrics = _snapshot_metrics(now)
    delta = _compute_delta(active["baseline"], current_metrics)
    won = _was_winner(delta)
    decision = "KEPT" if won else "REVERTED"

    if not won:
        # Revert the change in live_strategy.json
        strat = _load_json(LIVE_STRATEGY_FILE, {}) or {}
        _set_path(strat, active["path"], active["before"])
        strat["updated_at"] = now.isoformat(timespec="seconds")
        strat["last_revert"] = {
            "path": active["path"],
            "from": active["after"],
            "to": active["before"],
            "ts": now.isoformat(timespec="seconds"),
        }
        _save_json(LIVE_STRATEGY_FILE, strat)

    line = (
        f"- [{now.strftime('%Y-%m-%d %H:%M')}] **{decision}** `{active['path']}` "
        f"{active['before']} → {active['after']} "
        f"(Δfollowers={delta.get('d_followers')}, Δlikes/post={delta.get('d_likes_per_post')}) "
        f"— rationale: {active.get('rationale', '?')[:120]}"
    )
    _appendln_ledger(line)
    log.info(f"[STRATEGY_LAB] AUDIT {decision} {active['path']} {active['before']}→{active['after']} "
             f"Δfollowers={delta.get('d_followers')} Δlikes={delta.get('d_likes_per_post')}")

    history = state.get("history") or []
    history.append({
        **active,
        "decision": decision,
        "result_at": now.isoformat(timespec="seconds"),
        "delta": delta,
        "current_metrics": current_metrics,
    })
    state["history"] = history[-30:]
    state["active"] = None
    state["last_decision_at"] = now.isoformat(timespec="seconds")
    return True


PROPOSE_PROMPT = """You are the strategy optimizer for a French AI/crypto Twitter bot (@cryptoiadecode).
Goal: maximize follower growth + likes-per-post. Be CONSERVATIVE — propose one small targeted change.

CURRENT LIVE STRATEGY (live_strategy.json):
{live_strategy}

LAST 24H FOLLOWER HISTORY:
{follower_history}

LAST 24H AVG LIKES / VIEWS PER POST (sample of recent posts):
{recent_posts}

RECENT EXPERIMENT OUTCOMES (last 5):
{ledger_tail}

ALLOWED PATHS YOU CAN PATCH (min, max):
{allowed_paths}

Output ONLY a single-line JSON object — no markdown, no explanation outside the rationale field:
{{"path": "caps.MAX_REPLIES_PER_CYCLE", "before": 40, "after": 50, "rationale": "Reply-source posts averaged 11 likes vs 3 for news; expand reply throughput."}}

Rules:
- One change only. Pick the path with the strongest evidence in the data above.
- "after" must stay within the (min, max) for that path.
- Change must be a real delta (after != before).
- The rationale must reference SPECIFIC numbers from the data.
- If no clear evidence for any change, output the literal string: SKIP
"""


def _read_live_strategy() -> dict:
    return _load_json(LIVE_STRATEGY_FILE, {})


def _read_follower_history_summary() -> str:
    hist = _load_json(FOLLOWER_HISTORY_FILE, [])
    if not isinstance(hist, list) or not hist:
        return "(no history)"
    cutoff = datetime.now() - timedelta(hours=24)
    rows = []
    for entry in hist[-48:]:
        try:
            ts = datetime.fromisoformat(entry["ts"])
            if ts >= cutoff:
                rows.append(f"{ts.strftime('%m-%d %H:%M')} : {entry.get('count')}")
        except (KeyError, ValueError, TypeError):
            continue
    return "\n".join(rows[-24:]) or "(no recent entries)"


def _read_recent_posts_summary() -> str:
    data = _load_json(PERFORMANCE_LOG_FILE, [])
    if not isinstance(data, list) or not data:
        return "(no posts logged)"
    cutoff = datetime.now() - timedelta(hours=48)
    recent = []
    for p in data[-200:]:
        try:
            sa = p.get("scraped_at")
            ts = datetime.fromisoformat(sa) if sa else None
            if ts and ts < cutoff:
                continue
            recent.append({
                "likes": int(p.get("likes") or 0),
                "views": int(p.get("views") or 0),
                "text": (p.get("text") or "")[:80],
            })
        except (ValueError, TypeError):
            continue
    if not recent:
        return "(no posts in last 48h)"
    rows = []
    for r in recent[-30:]:
        rows.append(f"{r['likes']:>3} likes / {r['views']:>5} views — {r['text']}")
    avg_likes = sum(r["likes"] for r in recent) / len(recent)
    rows.append(f"--- avg likes: {avg_likes:.1f} across {len(recent)} posts ---")
    return "\n".join(rows)


def _read_ledger_tail(n: int = 5) -> str:
    if not os.path.exists(LEDGER_FILE):
        return "(no prior experiments)"
    try:
        with open(LEDGER_FILE) as f:
            lines = [ln for ln in f.readlines() if ln.strip()]
    except OSError:
        return "(ledger unreadable)"
    return "".join(lines[-n:]) or "(no prior experiments)"


def _ask_claude_for_patch() -> Optional[dict]:
    prompt = PROPOSE_PROMPT.format(
        live_strategy=json.dumps(_read_live_strategy(), indent=2),
        follower_history=_read_follower_history_summary(),
        recent_posts=_read_recent_posts_summary(),
        ledger_tail=_read_ledger_tail(5),
        allowed_paths=json.dumps(ALLOWED_PATHS, indent=2),
    )
    r = run_llm(prompt, REPLY_MODEL, label="STRATEGY_LAB")
    if r.returncode != 0:
        log.info(f"[STRATEGY_LAB] LLM failed rc={r.returncode}: {r.stderr[:200]}")
        return None
    raw = unwrap_text(r.stdout).strip()
    if not raw or raw.upper().startswith("SKIP"):
        log.info("[STRATEGY_LAB] LLM returned SKIP (no clear signal).")
        return None
    # Extract first {...} block in case the model added narration.
    match = re.search(r"\{[^{}]+\}", raw, re.DOTALL)
    if not match:
        log.info(f"[STRATEGY_LAB] LLM output not JSON: {raw[:200]!r}")
        return None
    try:
        patch = json.loads(match.group(0))
    except json.JSONDecodeError:
        log.info(f"[STRATEGY_LAB] LLM JSON parse failed: {raw[:200]!r}")
        return None
    return patch


def _validate_patch(patch: dict, current_strat: dict) -> Optional[str]:
    """Return None if valid, else a human-readable rejection reason."""
    path = patch.get("path")
    before = patch.get("before")
    after = patch.get("after")
    if path not in ALLOWED_PATHS:
        return f"path {path!r} not in allowed list"
    if before is None or after is None:
        return "missing before/after"
    try:
        before_n = float(before)
        after_n = float(after)
    except (ValueError, TypeError):
        return "before/after not numeric"
    if before_n == after_n:
        return "no delta (before == after)"
    cur = _get_path(current_strat, path)
    if cur is not None:
        try:
            if float(cur) != before_n:
                return f"stale before={before_n} vs current={cur}"
        except (ValueError, TypeError):
            pass
    lo, hi = ALLOWED_PATHS[path]
    if not (lo <= after_n <= hi):
        return f"after {after_n} outside ({lo}, {hi})"
    # Cap delta at ±50% to avoid wild swings.
    if before_n != 0 and abs((after_n - before_n) / before_n) > 0.5:
        return f"delta > 50% of before"
    return None


def _propose_and_apply(state: dict, now: datetime) -> None:
    # Cooldown so we don't fire right after an audit decision.
    last = state.get("last_decision_at")
    if last:
        try:
            last_dt = datetime.fromisoformat(last)
            if (now - last_dt).total_seconds() < COOLDOWN_AFTER_DECISION_MINUTES * 60:
                log.info("[STRATEGY_LAB] still in cooldown after last decision.")
                return
        except ValueError:
            pass

    patch = _ask_claude_for_patch()
    if not patch:
        return
    current_strat = _read_live_strategy()
    reason = _validate_patch(patch, current_strat)
    if reason:
        log.info(f"[STRATEGY_LAB] rejected patch: {reason} ({patch!r})")
        _appendln_ledger(
            f"- [{now.strftime('%Y-%m-%d %H:%M')}] **REJECTED** {patch.get('path')!r} — {reason}"
        )
        return

    # Apply patch.
    _set_path(current_strat, patch["path"], type(patch["before"])(patch["after"]))
    current_strat["updated_at"] = now.isoformat(timespec="seconds")
    _save_json(LIVE_STRATEGY_FILE, current_strat)

    baseline = _snapshot_metrics(now)
    state["active"] = {
        "path": patch["path"],
        "before": patch["before"],
        "after": patch["after"],
        "rationale": str(patch.get("rationale", ""))[:300],
        "applied_at": now.isoformat(timespec="seconds"),
        "baseline": baseline,
    }
    log.info(
        f"[STRATEGY_LAB] APPLIED {patch['path']} {patch['before']}→{patch['after']} "
        f"— baseline followers={baseline.get('followers')}, "
        f"likes/post(24h)={baseline.get('likes_per_post_24h')}"
    )
    _appendln_ledger(
        f"- [{now.strftime('%Y-%m-%d %H:%M')}] **APPLIED** `{patch['path']}` "
        f"{patch['before']} → {patch['after']} "
        f"(baseline followers={baseline.get('followers')}, "
        f"lpp={baseline.get('likes_per_post_24h')}) "
        f"— {patch.get('rationale', '')[:150]}"
    )


def run_strategy_lab_cycle():
    """One iteration of audit-then-propose. Called by APScheduler every hour."""
    now = datetime.now()
    state = _load_json(EXPERIMENTS_FILE, {"active": None, "history": []})
    if not isinstance(state, dict):
        state = {"active": None, "history": []}
    log.info(f"[STRATEGY_LAB] tick — active={state.get('active', {}).get('path') if state.get('active') else None}")
    try:
        resolved = _audit_active_experiment(state, now)
    except Exception:
        log.info("[STRATEGY_LAB] audit failed:")
        traceback.print_exc()
        resolved = False
    if not state.get("active"):
        try:
            _propose_and_apply(state, now)
        except Exception:
            log.info("[STRATEGY_LAB] propose failed:")
            traceback.print_exc()
    _save_json(EXPERIMENTS_FILE, state)


def safe_run_strategy_lab_cycle():
    """Scheduler wrapper. Never raises so APScheduler doesn't drop the job."""
    try:
        run_strategy_lab_cycle()
    except Exception:
        log.info("[STRATEGY_LAB] outer error:")
        traceback.print_exc()

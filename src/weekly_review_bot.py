"""Weekly metrics review (2026-06-07 agent spec, Part 2 — Metrics).

The spec mandates a weekly review to shift the content mix toward winners:
followers + delta, following total (must stay <= the 300 cap), per-pillar
and per-surface mix, top recent posts. This bot writes the whole thing to
`weekly_review.md` every Sunday — deterministic, no LLM, no Safari — so the
operator (or the /strategy skill) reads one file instead of digging through
engagement_log.csv and follower_history.json.

Idempotent per ISO week via `weekly_review_state.json`; scheduled hourly,
fires only on Sundays after 17:00 New York (post-close, pre-evening slot).
"""
import csv
import json
import os
import traceback
from collections import defaultdict
from datetime import datetime, timedelta

from .config import _PROJECT_ROOT, ENGAGEMENT_LOG_FILE
from .logger import log
from .pillar_tags import classify as _classify_pillar

REVIEW_FILE = os.path.join(_PROJECT_ROOT, "weekly_review.md")
STATE_FILE = os.path.join(_PROJECT_ROOT, "weekly_review_state.json")
FOLLOWER_HISTORY_FILE = os.path.join(_PROJECT_ROOT, "follower_history.json")
PERFORMANCE_LOG_FILE = os.path.join(_PROJECT_ROOT, "performance_log.json")


def _iso_week() -> str:
    y, w, _ = datetime.now().isocalendar()
    return f"{y}-W{w:02d}"


def _already_ran_this_week() -> bool:
    try:
        with open(STATE_FILE) as f:
            return (json.load(f) or {}).get("week") == _iso_week()
    except (OSError, json.JSONDecodeError):
        return False


def _mark_ran() -> None:
    try:
        with open(STATE_FILE, "w") as f:
            json.dump({"week": _iso_week(), "ts": datetime.now().isoformat()}, f)
    except OSError:
        pass


def _follower_stats() -> tuple:
    """(current, delta_7d) from follower_history.json — (None, None) on gaps."""
    try:
        with open(FOLLOWER_HISTORY_FILE) as f:
            hist = json.load(f) or []
    except (OSError, json.JSONDecodeError):
        return (None, None)
    if not isinstance(hist, list) or not hist:
        return (None, None)
    current = hist[-1].get("count")
    cutoff = (datetime.now() - timedelta(days=7)).isoformat()
    week_ago = None
    for row in hist:
        if row.get("ts", "") >= cutoff:
            week_ago = row.get("count")
            break
    delta = (current - week_ago) if (current is not None and week_ago is not None) else None
    return (current, delta)


def _following_total():
    try:
        with open(os.path.join(_PROJECT_ROOT, "following_count.json")) as f:
            return json.load(f).get("count")
    except (OSError, json.JSONDecodeError):
        return None


def _week_rows() -> list:
    cutoff = datetime.now() - timedelta(days=7)
    rows = []
    try:
        with open(ENGAGEMENT_LOG_FILE, newline="") as f:
            for row in csv.reader(f):
                if not row or len(row) < 3:
                    continue
                try:
                    ts = datetime.fromisoformat(row[0])
                except ValueError:
                    continue
                if ts < cutoff:
                    continue
                rows.append({
                    "ts": ts,
                    "type": row[1] if len(row) > 1 else "",
                    "text": row[2] if len(row) > 2 else "",
                    "source": row[4] if len(row) > 4 else "",
                    "pillar": row[6] if len(row) > 6 else "",
                })
    except OSError:
        pass
    return rows


def _top_posts(limit: int = 5) -> list:
    """Top scraped own-posts of the last 7 days by likes (views tiebreak),
    each tagged with its pillar. From performance_log.json
    ({text, likes, views, timestamp} rows via scrape_own_metrics)."""
    try:
        with open(PERFORMANCE_LOG_FILE) as f:
            rows = json.load(f) or []
    except (OSError, json.JSONDecodeError):
        return []
    cutoff = (datetime.now() - timedelta(days=7)).isoformat()
    week = [r for r in rows
            if isinstance(r, dict) and str(r.get("timestamp", ""))[:19] >= cutoff[:19]]
    week.sort(key=lambda r: (int(r.get("likes") or 0), int(r.get("views") or 0)),
              reverse=True)
    return week[:limit]


def build_review() -> str:
    followers, delta = _follower_stats()
    following = _following_total()
    rows = _week_rows()

    by_type: dict = defaultdict(int)
    by_pillar: dict = defaultdict(int)
    by_day: dict = defaultdict(int)
    for r in rows:
        by_type[r["type"]] += 1
        pillar = r["pillar"].strip() or _classify_pillar(r["text"], r["type"], r["source"])
        by_pillar[pillar] += 1
        by_day[r["ts"].date().isoformat()] += 1

    cap_flag = ""
    if isinstance(following, int):
        cap_flag = " ✅ within cap" if following <= 300 else f" ⚠️ OVER the 300 cap by {following - 300}"

    lines = [
        f"# Weekly review — {_iso_week()}",
        "",
        f"Generated {datetime.now().isoformat(timespec='minutes')} "
        f"(deterministic, from engagement_log + follower_history).",
        "",
        "## Account",
        f"- Followers: **{followers if followers is not None else '?'}**"
        + (f" ({'+' if delta >= 0 else ''}{delta} this week)" if delta is not None else ""),
        f"- Following: **{following if following is not None else '?'}**{cap_flag}",
        "",
        "## Action mix (7 days)",
    ]
    total = max(len(rows), 1)
    for t, c in sorted(by_type.items(), key=lambda x: x[1], reverse=True):
        lines.append(f"- {t}: {c} ({100 * c // total}%)")
    lines += ["", "## Pillar mix (7 days) — shift toward winners"]
    for p, c in sorted(by_pillar.items(), key=lambda x: x[1], reverse=True):
        lines.append(f"- {p}: {c} ({100 * c // total}%)")
    lines += ["", "## Volume by day"]
    for d in sorted(by_day):
        lines.append(f"- {d}: {by_day[d]} actions")
    top = _top_posts()
    if top:
        lines += ["", "## Top posts (7 days, by likes — scraped metrics)"]
        for r in top:
            likes = int(r.get("likes") or 0)
            views = int(r.get("views") or 0)
            rate = f", {100 * likes / views:.1f}% eng" if views else ""
            pillar = _classify_pillar(r.get("text", ""))
            text = (r.get("text") or "").replace("\n", " ")[:110]
            lines.append(f"- ❤️{likes} 👁{views}{rate} [{pillar}] {text}")
    lines += [
        "",
        "## Spec targets (2026-06-07 quality barbell)",
        "- QUANTITY: replies unlimited (the reach engine) · reply-bait 3-4/week",
        "- QUALITY: originals 3-4/day in market slots · QRTs ≤100/day, 50+-like",
        "  parents, screenshot-worthy or SKIP (number-reframe + metaphor +",
        "  closing question) · plain RTs 0-2/day",
        "- Following <= 300 hard cap (~120-150 steady state)",
        "",
        "_Engagement-per-post and conversion live in performance_insights.json"
        " and engagement_targets_log.json — read those before changing the mix._",
    ]
    return "\n".join(lines) + "\n"


def run_weekly_review_cycle() -> None:
    now = datetime.now()
    # Sunday only, after the close — one shot per ISO week.
    if now.weekday() != 6 or now.hour < 17:
        return
    if _already_ran_this_week():
        return
    review = build_review()
    try:
        with open(REVIEW_FILE, "w") as f:
            f.write(review)
        _mark_ran()
        log.info(f"[WEEKLY-REVIEW] Written to {REVIEW_FILE}.")
        try:
            from . import git_ops
            git_ops.auto_push(["weekly_review.md", "weekly_review_state.json"],
                              "weekly review digest")
        except Exception:
            pass
    except OSError:
        log.info("[WEEKLY-REVIEW] Write failed:")
        traceback.print_exc()


def safe_run_weekly_review_cycle() -> None:
    from . import health
    try:
        run_weekly_review_cycle()
        health.record_success("weekly_review")
    except Exception:
        log.info("[WEEKLY-REVIEW] outer error:")
        traceback.print_exc()
        health.record_failure("weekly_review")

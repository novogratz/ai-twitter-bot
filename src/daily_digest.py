"""Daily digest: write a human-readable rollup of the day's bot activity.

Why: user is stepping back for 2 weeks (mission deadline 2026-05-10ish) and
wants to come back to a chronological log they can read in 5 minutes to
understand what happened, what worked, what didn't. This is the chat-fodder
for the post-mission review.

Format: appended to `daily_digest.md` (committed). One section per day with
counts, per-source ROI, top performers, pattern stats, evolution agent prunes,
follow count delta. Never overwrites prior days — always append.
"""
import csv
import json
import os
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from .config import ENGAGEMENT_LOG_FILE, _PROJECT_ROOT
from .logger import log

DIGEST_FILE = os.path.join(_PROJECT_ROOT, "daily_digest.md")
PERF_LOG = os.path.join(_PROJECT_ROOT, "performance_log.json")
FOLLOWED_FILE = os.path.join(_PROJECT_ROOT, "followed_accounts.json")
EVOLUTION_LOG = os.path.join(_PROJECT_ROOT, "evolution_log.json")
STRATEGY_LOG = os.path.join(_PROJECT_ROOT, "strategy_log.json")
DIGEST_STATE = os.path.join(_PROJECT_ROOT, "daily_digest_state.json")


def _load_state() -> dict:
    if os.path.exists(DIGEST_STATE):
        try:
            with open(DIGEST_STATE) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"last_written": None}


def _save_state(s: dict):
    try:
        with open(DIGEST_STATE, "w") as f:
            json.dump(s, f)
    except IOError:
        pass


def _read_engagement_for_day(target_day: date):
    """Return list of rows from engagement_log.csv that occurred on target_day."""
    rows = []
    if not os.path.exists(ENGAGEMENT_LOG_FILE):
        return rows
    try:
        with open(ENGAGEMENT_LOG_FILE, newline="") as f:
            reader = csv.reader(f)
            next(reader, None)  # header
            for row in reader:
                if not row:
                    continue
                ts = row[0]
                try:
                    ts_dt = datetime.fromisoformat(ts)
                except ValueError:
                    continue
                if ts_dt.date() == target_day:
                    # Pad to 6 cols for older rows
                    while len(row) < 6:
                        row.append("")
                    rows.append(row)
    except IOError:
        pass
    return rows


def _read_perf_for_day(target_day: date):
    """Return list of perf snapshots scraped on target_day."""
    if not os.path.exists(PERF_LOG):
        return []
    try:
        with open(PERF_LOG) as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError):
        return []
    out = []
    for entry in data:
        ts = entry.get("scraped_at") or entry.get("timestamp") or ""
        try:
            d = datetime.fromisoformat(ts.replace("Z", "+00:00")).date()
        except ValueError:
            continue
        if d == target_day:
            out.append(entry)
    return out


def _follow_count():
    if not os.path.exists(FOLLOWED_FILE):
        return 0
    try:
        with open(FOLLOWED_FILE) as f:
            data = json.load(f)
        if isinstance(data, list):
            return len(data)
        if isinstance(data, dict):
            return len(data.get("accounts", data.get("followed", [])))
    except (json.JSONDecodeError, IOError):
        pass
    return 0


def _last_evolution_summary():
    if not os.path.exists(EVOLUTION_LOG):
        return None
    try:
        with open(EVOLUTION_LOG) as f:
            data = json.load(f)
        if isinstance(data, list) and data:
            return data[-1]
    except (json.JSONDecodeError, IOError):
        pass
    return None


def build_digest(target_day: date) -> str:
    """Build the markdown section for one day."""
    rows = _read_engagement_for_day(target_day)
    perf = _read_perf_for_day(target_day)

    type_counts = Counter(r[1] for r in rows)
    source_counts = Counter(r[4].split("/")[0] for r in rows if r[4])
    pattern_counts = Counter(r[5] for r in rows if r[5])
    per_author = Counter()
    for r in rows:
        url = r[3] or ""
        if "x.com/" in url and "/status/" in url:
            try:
                handle = url.split("x.com/")[1].split("/status/")[0]
                per_author[handle] += 1
            except IndexError:
                pass

    # Top-performing posts (by likes) scraped today
    top_perf = sorted(perf, key=lambda e: int(e.get("likes") or 0), reverse=True)[:3]

    follow_n = _follow_count()
    evo = _last_evolution_summary()

    lines = []
    lines.append(f"\n## {target_day.isoformat()}\n")
    lines.append(f"**Activity** — total actions: {len(rows)}")
    if type_counts:
        breakdown = ", ".join(f"{k}={v}" for k, v in type_counts.most_common())
        lines.append(f"  - by type: {breakdown}")
    if source_counts:
        top_sources = ", ".join(f"{k}={v}" for k, v in source_counts.most_common(8))
        lines.append(f"  - top sources: {top_sources}")
    if pattern_counts:
        pat = ", ".join(f"{k}={v}" for k, v in pattern_counts.most_common())
        lines.append(f"  - comedy patterns: {pat}")
    if per_author:
        top_targets = ", ".join(f"@{h}={n}" for h, n in per_author.most_common(5))
        lines.append(f"  - top reply targets: {top_targets}")

    lines.append(f"\n**Followers we follow** (running total): {follow_n}")

    if top_perf:
        lines.append("\n**Top-performing posts scraped today**:")
        for p in top_perf:
            txt = (p.get("text") or "")[:100].replace("\n", " ")
            lines.append(
                f"  - {int(p.get('likes') or 0)} likes / {int(p.get('views') or 0)} views: {txt}"
            )

    if evo:
        ts = evo.get("timestamp", "")[:10]
        if ts == target_day.isoformat():
            lines.append("\n**Latest evolution-agent cycle**:")
            pruned = evo.get("pruned", []) or evo.get("prune", [])
            reinforced = evo.get("reinforced", []) or evo.get("reinforce", [])
            if pruned:
                lines.append(f"  - pruned: {', '.join(pruned[:5])}")
            if reinforced:
                lines.append(f"  - reinforced: {', '.join(reinforced[:5])}")

    lines.append("")
    return "\n".join(lines)


def write_yesterday_digest():
    """Write yesterday's digest. Idempotent — won't double-write the same day."""
    yesterday = date.today() - timedelta(days=1)
    state = _load_state()
    if state.get("last_written") == yesterday.isoformat():
        log.info(f"[DIGEST] Already wrote {yesterday}, skipping.")
        return

    section = build_digest(yesterday)
    header_needed = not os.path.exists(DIGEST_FILE)
    try:
        with open(DIGEST_FILE, "a") as f:
            if header_needed:
                f.write(
                    "# Daily Digest\n\n"
                    "Auto-generated rollup of bot activity. One section per day. "
                    "Use this for the 2-week post-mission review.\n"
                )
            f.write(section)
        state["last_written"] = yesterday.isoformat()
        _save_state(state)
        log.info(f"[DIGEST] Wrote section for {yesterday} -> {DIGEST_FILE}")
    except IOError as e:
        log.info(f"[DIGEST] Write failed: {e}")


def safe_run_daily_digest():
    """Wrapper for scheduler — never crashes the loop."""
    from . import health
    try:
        write_yesterday_digest()
        health.record_success("digest")
    except Exception as e:
        log.info(f"[DIGEST] Error: {e}")
        health.record_failure("digest")

"""Analyzer bot — data-driven performance engine.

Reads engagement_log.csv every 4h, computes what's actually working,
and writes performance_insights.json. All generation agents (news,
hotake, spicy, breakout) inject this file into their prompts so the
bot improves from real signal, not gut feeling.

Output: performance_insights.json
  - top_patterns: which comedy/content patterns get most likes
  - best_hours: which EST hours produce the most engagement
  - best_topics: which topics (AI, Crypto, Space, Bourse) convert
  - worst_patterns: patterns to avoid
  - rising_topics: topics gaining traction in last 24h vs. last 7d
  - viral_examples: 3 highest-liked posts from last 7d (verbatim)
"""
import csv
import json
import os
import traceback
from collections import defaultdict
from datetime import datetime, timedelta

from .config import _PROJECT_ROOT, ENGAGEMENT_LOG_FILE
from .logger import log
from . import health

INSIGHTS_FILE = os.path.join(_PROJECT_ROOT, "performance_insights.json")
ANALYZER_STATE_FILE = os.path.join(_PROJECT_ROOT, "analyzer_state.json")


def _load_log_window(hours: int) -> list[dict]:
    """Load engagement_log rows from the last N hours."""
    if not os.path.exists(ENGAGEMENT_LOG_FILE):
        return []
    cutoff = datetime.now() - timedelta(hours=hours)
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
                    "url": row[3] if len(row) > 3 else "",
                    "source": row[4] if len(row) > 4 else "",
                    "pattern": row[5] if len(row) > 5 else "",
                })
    except Exception:
        log.info("[ANALYZER] Failed to read engagement log:")
        traceback.print_exc()
    return rows


def _extract_topics(text: str) -> list[str]:
    t = text.lower()
    topics = []
    if any(k in t for k in ("ia ", "ai ", "llm", "gpt", "anthropic", "openai", "mistral", "nvidia", "gpu", "agent")):
        topics.append("IA")
    if any(k in t for k in ("bitcoin", "btc", "crypto", "ethereum", "eth", "solana", "defi", "nft", "blockchain")):
        topics.append("Crypto")
    if any(k in t for k in ("spacex", "starship", "starlink", "spatial", "satellite", "rocket", "space", "orbital")):
        topics.append("Spatial")
    if any(k in t for k in ("bourse", "cac", "action", "etf", "pea", "investissement", "marché", "s&p", "nasdaq")):
        topics.append("Bourse")
    return topics or ["Autre"]


def run_analyzer_cycle():
    rows_7d = _load_log_window(168)
    rows_24h = _load_log_window(24)

    if not rows_7d:
        log.info("[ANALYZER] No engagement data yet — skipping.")
        return

    # --- Pattern performance (7d) ---
    pattern_counts: dict[str, int] = defaultdict(int)
    content_types: dict[str, int] = defaultdict(int)
    hour_counts: dict[int, int] = defaultdict(int)
    topic_counts_7d: dict[str, int] = defaultdict(int)
    topic_counts_24h: dict[str, int] = defaultdict(int)
    viral_candidates: list[dict] = []

    for row in rows_7d:
        pat = row["pattern"].strip() if row["pattern"] else "UNKNOWN"
        if pat:
            pattern_counts[pat] += 1
        ctype = row["type"]
        content_types[ctype] += 1
        hour_counts[row["ts"].hour] += 1
        for topic in _extract_topics(row["text"]):
            topic_counts_7d[topic] += 1

    for row in rows_24h:
        for topic in _extract_topics(row["text"]):
            topic_counts_24h[topic] += 1

    # Viral candidates = reply/quote/news types (original content we wrote)
    original = [r for r in rows_7d if r["type"] in ("reply", "quote", "news", "hotake", "spicy", "breakout")]
    # Approximate viral by picking the most recent high-value posts
    viral_candidates = sorted(original, key=lambda r: r["ts"], reverse=True)[:10]

    # Top 3 patterns
    top_patterns = sorted(pattern_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    worst_patterns = sorted(pattern_counts.items(), key=lambda x: x[1])[:3]

    # Best hours (top 5)
    best_hours = sorted(hour_counts.items(), key=lambda x: x[1], reverse=True)[:5]

    # Best topics
    best_topics = sorted(topic_counts_7d.items(), key=lambda x: x[1], reverse=True)

    # Rising topics: compare 24h rate vs. 7d rate
    rising = []
    total_7d = max(len(rows_7d), 1)
    total_24h = max(len(rows_24h), 1)
    for topic, cnt_7d in topic_counts_7d.items():
        cnt_24h = topic_counts_24h.get(topic, 0)
        rate_7d = cnt_7d / total_7d
        rate_24h = cnt_24h / total_24h
        if rate_24h > rate_7d * 1.3:
            rising.append({"topic": topic, "24h_rate": round(rate_24h, 3), "7d_rate": round(rate_7d, 3)})

    # Best content surfaces by volume
    top_types = sorted(content_types.items(), key=lambda x: x[1], reverse=True)

    insights = {
        "generated_at": datetime.now().isoformat(),
        "window_7d_actions": len(rows_7d),
        "window_24h_actions": len(rows_24h),
        "top_patterns": [{"pattern": p, "count": c} for p, c in top_patterns],
        "worst_patterns": [{"pattern": p, "count": c} for p, c in worst_patterns],
        "best_hours_utc": [{"hour": h, "actions": c} for h, c in best_hours],
        "best_topics_7d": [{"topic": t, "count": c} for t, c in best_topics],
        "rising_topics_24h": rising,
        "content_surface_mix": [{"type": t, "count": c} for t, c in top_types],
        "viral_examples": [
            {"ts": r["ts"].isoformat(), "text": r["text"][:280], "type": r["type"]}
            for r in viral_candidates[:3]
        ],
    }

    with open(INSIGHTS_FILE, "w") as f:
        json.dump(insights, f, indent=2, ensure_ascii=False)

    log.info(
        f"[ANALYZER] Insights written. 7d={len(rows_7d)} actions, "
        f"top_pattern={top_patterns[0] if top_patterns else '?'}, "
        f"best_topic={best_topics[0] if best_topics else '?'}, "
        f"rising={[r['topic'] for r in rising]}"
    )

    try:
        from .git_ops import auto_push
        auto_push(["performance_insights.json"], "Analyzer update — performance insights")
    except Exception:
        pass


def safe_run_analyzer_cycle():
    try:
        run_analyzer_cycle()
        health.record_success("analyzer")
    except Exception:
        log.info("[ANALYZER] Error:")
        traceback.print_exc()
        health.record_failure("analyzer")

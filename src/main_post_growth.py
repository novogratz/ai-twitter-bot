"""Main-post growth intelligence for The AI Therapist.

This module is deliberately read-heavy and side-effect-light. It preserves the
reply engine while giving original posts a shared memory, analytics split,
opportunity queue, quality scoring, and rewards-aware approval mode.
"""

from __future__ import annotations

import csv
import json
import math
import os
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any

from .config import ENGAGEMENT_LOG_FILE, _PROJECT_ROOT
from .json_safety import sanitize_for_json
from .logger import log

STATE_DIR = os.path.join(_PROJECT_ROOT, "growth")
MAIN_ANALYTICS_FILE = os.path.join(STATE_DIR, "main_post_analytics.json")
REPLY_ANALYTICS_FILE = os.path.join(STATE_DIR, "reply_analytics.json")
OPPORTUNITY_QUEUE_FILE = os.path.join(STATE_DIR, "opportunity_queue.json")
ACCOUNT_MEMORY_FILE = os.path.join(STATE_DIR, "account_memory.json")
EDITORIAL_BRIEF_FILE = os.path.join(STATE_DIR, "editorial_brief.md")
GOAL_DASHBOARD_FILE = os.path.join(STATE_DIR, "home_timeline_500k_dashboard.json")
APPROVAL_QUEUE_FILE = os.path.join(STATE_DIR, "main_post_approval_queue.json")
PREDICTION_LEDGER_FILE = os.path.join(STATE_DIR, "prediction_ledger.json")
EXPERIMENTS_FILE = os.path.join(STATE_DIR, "editorial_experiments.json")

MAIN_TYPES = {"post", "hotake", "spicy", "breakout", "thread", "quote", "quote_gif"}
REPLY_TYPES = {"reply", "direct_reply", "replyback", "chain_reply"}
CLICHE_RE = re.compile(
    r"\b(game changer|changes everything|let that sink in|future is here|"
    r"most people don.t realize|isn.t just .+ it.s|in a world where|here.s why)\b",
    re.IGNORECASE,
)
AI_RE = re.compile(r"\b(ai|llm|gpt|openai|anthropic|claude|chatgpt|agent|nvidia|gpu|robot|model)\b", re.I)
HUMAN_RE = re.compile(r"\b(human|people|relationship|lonely|trust|work|therapy|therapist|client|mom|feel|behavior|psychology)\b", re.I)
NUMBER_RE = re.compile(r"(?<!\w)(?:\$?\d+(?:[.,]\d+)?\s?(?:%|b|bn|m|k|x|gw|mw|gb)?)", re.I)


def _ensure_state_dir() -> None:
    os.makedirs(STATE_DIR, exist_ok=True)


def _read_json(path: str, default: Any) -> Any:
    try:
        with open(path, "r") as f:
            return sanitize_for_json(json.load(f))
    except (OSError, json.JSONDecodeError, TypeError):
        return default


def _write_json(path: str, payload: Any) -> None:
    _ensure_state_dir()
    with open(path, "w") as f:
        json.dump(sanitize_for_json(payload), f, indent=2, ensure_ascii=False)


def _parse_ts(value: str) -> datetime | None:
    if not value:
        return None
    raw = str(value).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is not None:
            return dt.replace(tzinfo=None)
        return dt
    except ValueError:
        return None


def _load_engagement_rows(days: int = 90) -> list[dict]:
    if not os.path.exists(ENGAGEMENT_LOG_FILE):
        return []
    cutoff = datetime.now() - timedelta(days=days)
    rows: list[dict] = []
    with open(ENGAGEMENT_LOG_FILE, newline="") as f:
        for row in csv.reader(f):
            if not row or row[0] == "timestamp":
                continue
            ts = _parse_ts(row[0])
            if not ts or ts < cutoff:
                continue
            rows.append({
                "timestamp": ts.isoformat(),
                "type": row[1] if len(row) > 1 else "",
                "text": row[2] if len(row) > 2 else "",
                "target_url": row[3] if len(row) > 3 else "",
                "source": row[4] if len(row) > 4 else "",
                "pattern_id": row[5] if len(row) > 5 else "",
                "pillar": row[6] if len(row) > 6 else "",
                "provider": row[7] if len(row) > 7 else "",
            })
    return rows


def _load_performance_rows(days: int = 90) -> list[dict]:
    rows = _read_json(os.path.join(_PROJECT_ROOT, "performance_log.json"), [])
    cutoff = datetime.now() - timedelta(days=days)
    out = []
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict):
            continue
        ts = _parse_ts(str(r.get("timestamp") or r.get("scraped_at") or ""))
        if ts and ts < cutoff:
            continue
        out.append(r)
    return out


def _norm_words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9$]{3,}", (text or "").lower())


def _topic_tags(text: str) -> list[str]:
    t = (text or "").lower()
    tags = []
    mapping = {
        "models": ("openai", "anthropic", "claude", "gpt", "gemini", "llama", "mistral", "model"),
        "agents": ("agent", "cursor", "copilot", "claude code", "automation"),
        "ai_infra": ("nvidia", "gpu", "datacenter", "data center", "power", "compute", "coreweave"),
        "ai_human": ("human", "relationship", "lonely", "trust", "therapy", "therapist", "psychology"),
        "markets": ("stock", "$", "earnings", "valuation", "market", "bubble", "capex"),
        "crypto": ("bitcoin", "btc", "crypto", "ethereum", "stablecoin"),
        "robotics": ("robot", "humanoid", "autonomous"),
    }
    for tag, needles in mapping.items():
        if any(n in t for n in needles):
            tags.append(tag)
    return tags or ["general_ai"]


def _hook_archetype(text: str) -> str:
    first = (text or "").strip().splitlines()[0][:140].lower() if text else ""
    if NUMBER_RE.search(first):
        return "surprising_number"
    if first.endswith("?"):
        return "question"
    if any(k in first for k in ("will", "next", "by 20", "within")):
        return "prediction"
    if any(k in first for k in ("not ", "isn't", "is not", "nobody", "everyone")):
        return "contradiction"
    if first.startswith(("me ", "my ", "i ")):
        return "personal_observation"
    return "result_first"


def classify_winner(value: int, median: float) -> str:
    if median <= 0:
        return "UNKNOWN"
    ratio = value / median
    if ratio < 0.5:
        return "FLOP"
    if ratio < 1.5:
        return "NORMAL"
    if ratio < 2.5:
        return "GOOD"
    if ratio < 5:
        return "HIT"
    return "BREAKOUT"


def quality_score(text: str, *, source_text: str = "", source_freshness_hours: float | None = None) -> dict:
    """Editorial heuristic score. It does not model X ranking."""
    text = (text or "").strip()
    words = _norm_words(text)
    word_count = len(words)
    has_number = bool(NUMBER_RE.search(text))
    has_ai = bool(AI_RE.search(text))
    has_human = bool(HUMAN_RE.search(text))
    source_words = set(_norm_words(source_text))
    overlap = len(set(words) & source_words) / max(len(set(words)), 1) if source_words else 0.0
    length_ok = 25 <= len(text) <= 280
    hook = min(100, 35 + (20 if has_number else 0) + (20 if word_count <= 35 else 8) + (15 if _hook_archetype(text) != "result_first" else 8))
    originality = max(0, int(100 - overlap * 130))
    depth = min(100, 30 + (20 if has_ai else 0) + (20 if has_human else 0) + (15 if has_number else 0) + (15 if any(k in text.lower() for k in ("because", "means", "reveals", "next", "second")) else 0))
    specificity = min(100, 35 + (20 if has_number else 0) + (20 if re.search(r"\b(OpenAI|Anthropic|Nvidia|Google|Meta|Apple|xAI|Microsoft|Claude|ChatGPT)\b", text) else 0))
    timeliness = 65
    if source_freshness_hours is not None:
        timeliness = max(20, min(100, int(100 - source_freshness_hours * 2)))
    penalties = {
        "source_dependency": int(overlap * 100),
        "generic_ai_penalty": 25 if CLICHE_RE.search(text) else 0,
        "repetition_penalty": 15 if len(set(words)) < max(5, word_count * 0.55) else 0,
        "unsupported_claim_penalty": 10 if has_number and not source_text else 0,
    }
    weighted = (
        hook * 0.15 + originality * 0.2 + depth * 0.2 + specificity * 0.13
        + timeliness * 0.12 + (90 if has_human else 65) * 0.1 + (85 if length_ok else 45) * 0.1
    )
    overall = int(max(0, min(100, weighted - sum(penalties.values()) * 0.35)))
    return {
        "hook": int(hook),
        "originality": int(originality),
        "insight_depth": int(depth),
        "specificity": int(specificity),
        "credibility": 80 if not has_number or source_text else 60,
        "timeliness": int(timeliness),
        "novelty": int(originality),
        "audience_fit": 85 if has_ai else 55,
        "ai_therapist_fit": 92 if has_human else 70 if has_ai else 45,
        "standalone_value": 90 if overlap < 0.25 and depth >= 65 else 55,
        "conversation_potential": 80 if _hook_archetype(text) in {"question", "contradiction", "personal_observation"} else 60,
        "home_feed_potential": overall,
        **penalties,
        "overall": overall,
    }


def _source_freshness_hours(item: dict) -> float | None:
    ts = _parse_ts(str(item.get("ts") or item.get("published") or ""))
    if not ts:
        return None
    return max(0.0, (datetime.now() - ts).total_seconds() / 3600)


def _load_external_signal() -> list[dict]:
    data = _read_json(os.path.join(_PROJECT_ROOT, "external_signal.json"), {})
    items = data.get("items", []) if isinstance(data, dict) else []
    return [i for i in items if isinstance(i, dict) and i.get("title")]


def build_main_post_analytics() -> dict:
    perf = _load_performance_rows(90)
    views = [int(r.get("views") or 0) for r in perf]
    likes = [int(r.get("likes") or 0) for r in perf]
    median_views = statistics.median(views) if views else 0
    rows = []
    for r in perf:
        text = str(r.get("text") or "")
        v = int(r.get("views") or 0)
        rows.append({
            "post_id": r.get("url") or "",
            "published_time": r.get("timestamp") or "",
            "format": "main_post",
            "topic": ",".join(_topic_tags(text)),
            "hook_type": _hook_archetype(text),
            "post_length": len(text),
            "impressions": v,
            "likes": int(r.get("likes") or 0),
            "winner_class": classify_winner(v, median_views),
            "quality_score": quality_score(text)["overall"],
        })
    by_topic: dict[str, list[int]] = defaultdict(list)
    for row in rows:
        for tag in row["topic"].split(","):
            by_topic[tag].append(row["impressions"])
    out = {
        "generated_at": datetime.now().isoformat(),
        "sample_count": len(rows),
        "median_impressions": median_views,
        "average_impressions": round(sum(views) / len(views), 2) if views else 0,
        "p75_impressions": _percentile(views, 75),
        "p90_impressions": _percentile(views, 90),
        "median_likes": statistics.median(likes) if likes else 0,
        "hit_count": sum(1 for r in rows if r["winner_class"] in {"HIT", "BREAKOUT"}),
        "breakout_count": sum(1 for r in rows if r["winner_class"] == "BREAKOUT"),
        "by_topic": {
            k: {
                "sample_count": len(v),
                "median_impressions": statistics.median(v) if v else 0,
                "hit_rate": round(sum(1 for x in v if median_views and x >= 2.5 * median_views) / len(v), 3),
            }
            for k, v in sorted(by_topic.items())
        },
        "posts": rows[-200:],
    }
    _write_json(MAIN_ANALYTICS_FILE, out)
    return out


def build_reply_analytics() -> dict:
    rows = [r for r in _load_engagement_rows(90) if r["type"] in REPLY_TYPES or (r["target_url"] and r["type"] == "reply")]
    by_source = Counter(r["source"] or "unknown" for r in rows)
    by_topic = Counter(tag for r in rows for tag in _topic_tags(r["text"]))
    by_style = Counter(_hook_archetype(r["text"]) for r in rows)
    out = {
        "generated_at": datetime.now().isoformat(),
        "sample_count": len(rows),
        "purpose": "Replies are evaluated as discovery, conversation, profile-visit, and audience-sensor events.",
        "top_sources": [{"source": k, "count": v} for k, v in by_source.most_common(20)],
        "topics": [{"topic": k, "count": v} for k, v in by_topic.most_common()],
        "styles": [{"style": k, "count": v} for k, v in by_style.most_common()],
        "recent_replies": rows[-200:],
    }
    _write_json(REPLY_ANALYTICS_FILE, out)
    return out


def _percentile(values: list[int], pct: int) -> float:
    if not values:
        return 0
    values = sorted(values)
    idx = min(len(values) - 1, max(0, math.ceil((pct / 100) * len(values)) - 1))
    return values[idx]


def _performance_prior(topic_tags: list[str], analytics: dict) -> float:
    by_topic = analytics.get("by_topic") or {}
    vals = []
    for tag in topic_tags:
        stats = by_topic.get(tag)
        if not stats:
            continue
        samples = int(stats.get("sample_count") or 0)
        median = float(stats.get("median_impressions") or 0)
        account_median = float(analytics.get("median_impressions") or 1)
        if samples >= 3 and account_median:
            vals.append(min(100, 50 + 50 * (median / account_median)))
    return round(sum(vals) / len(vals), 2) if vals else 50.0


def _reply_signal_prior(topic_tags: list[str], reply_analytics: dict) -> float:
    counts = {r["topic"]: r["count"] for r in reply_analytics.get("topics", [])}
    total = max(1, sum(counts.values()))
    score = 40
    for tag in topic_tags:
        score += min(30, 200 * counts.get(tag, 0) / total)
    return round(min(100, score), 2)


def build_opportunity_queue(main_analytics: dict | None = None, reply_analytics: dict | None = None) -> list[dict]:
    main_analytics = main_analytics or build_main_post_analytics()
    reply_analytics = reply_analytics or build_reply_analytics()
    signals = _load_external_signal()
    queue = []
    seen = set()
    for item in signals[:50]:
        title = " ".join(str(item.get("title") or "").split())
        if not title or title.lower() in seen:
            continue
        seen.add(title.lower())
        tags = _topic_tags(title + " " + str(item.get("src") or ""))
        freshness = _source_freshness_hours(item)
        importance = min(100, 35 + int(item.get("score") or 0))
        novelty = 80 if freshness is None or freshness <= 24 else 50
        saturation = min(85, max(10, int(item.get("score") or 0) // 5))
        insight_potential = 85 if ("ai_human" in tags or "agents" in tags) else 70 if "ai_infra" in tags else 55
        historical = _performance_prior(tags, main_analytics)
        reply_prior = _reply_signal_prior(tags, reply_analytics)
        overall = round(
            importance * 0.18 + novelty * 0.14 + (100 - saturation) * 0.08
            + insight_potential * 0.22 + historical * 0.16 + reply_prior * 0.14
            + (85 if "ai_human" in tags else 65) * 0.08,
            2,
        )
        queue.append({
            "topic": title[:220],
            "discovered_at": datetime.now().isoformat(),
            "source_url": item.get("url") or "",
            "source": item.get("src") or "",
            "urgency": 90 if freshness is not None and freshness <= 6 else 65,
            "importance": importance,
            "audience_fit": 90 if any(t in tags for t in ("models", "agents", "ai_human", "ai_infra")) else 60,
            "novelty": novelty,
            "saturation": saturation,
            "insight_potential": insight_potential,
            "historical_topic_performance": historical,
            "reply_signal_strength": reply_prior,
            "overall_opportunity_score": overall,
            "classification": _opportunity_class(overall, novelty, saturation, insight_potential),
            "research_packet": {
                "topic": title[:220],
                "why_now": "Fresh signal from external_signal.json.",
                "primary_event": title[:220],
                "primary_sources": [item.get("url")] if item.get("url") else [],
                "supporting_sources": [],
                "verified_facts": [title[:220]],
                "important_numbers": NUMBER_RE.findall(title)[:5],
                "direct_quotes": [],
                "current_consensus": "",
                "unknowns": ["Full article/body may need human or web verification before factual claims."],
                "contrarian_interpretations": [],
                "second_order_effects": [],
                "potential_predictions": [],
                "human_behavior_implications": ["Ask what this reveals about trust, work, identity, dependency, or social behavior."],
                "ai_therapist_relevance": "Prefer the human/AI behavior angle over plain news compression.",
                "confidence": 0.62 if item.get("url") else 0.45,
            },
        })
    queue.sort(key=lambda x: x["overall_opportunity_score"], reverse=True)
    _write_json(OPPORTUNITY_QUEUE_FILE, queue[:40])
    return queue[:40]


def _opportunity_class(score: float, novelty: int, saturation: int, insight: int) -> str:
    if novelty >= 75 and score >= 72:
        return "EARLY + IMPORTANT"
    if score >= 68 and insight >= 70:
        return "TRENDING + DISTINCT ANGLE"
    if saturation >= 70 and insight < 70:
        return "MASSIVELY SATURATED + NO NEW ANGLE"
    return "WATCH"


def update_account_memory(main_analytics: dict | None = None, reply_analytics: dict | None = None) -> dict:
    main_analytics = main_analytics or build_main_post_analytics()
    reply_analytics = reply_analytics or build_reply_analytics()
    posts = main_analytics.get("posts", [])
    winners = [p for p in posts if p.get("winner_class") in {"GOOD", "HIT", "BREAKOUT"}]
    losers = [p for p in posts if p.get("winner_class") == "FLOP"]
    repeated_phrases = _repeated_phrases([p.get("topic", "") + " " + str(p.get("hook_type", "")) for p in posts])
    memory = {
        "updated_at": datetime.now().isoformat(),
        "recurring_theses": [
            "AI news matters most when it explains how human behavior changes.",
            "Infrastructure, compute, and power are the hidden constraints behind AI hype.",
            "The account performs best when it sounds like a human observer, not a feed summarizer.",
        ],
        "successful_hooks": Counter(p.get("hook_type") for p in winners).most_common(8),
        "failed_hooks": Counter(p.get("hook_type") for p in losers).most_common(8),
        "successful_topics": Counter(tag for p in winners for tag in str(p.get("topic", "")).split(",")).most_common(10),
        "failed_topics": Counter(tag for p in losers for tag in str(p.get("topic", "")).split(",")).most_common(10),
        "phrases_used_too_often": repeated_phrases,
        "previous_winners": winners[-20:],
        "previous_losers": losers[-20:],
        "reply_sensor": reply_analytics.get("topics", [])[:10],
        "predictions_file": PREDICTION_LEDGER_FILE,
    }
    _write_json(ACCOUNT_MEMORY_FILE, memory)
    if not os.path.exists(PREDICTION_LEDGER_FILE):
        _write_json(PREDICTION_LEDGER_FILE, [])
    return memory


def _repeated_phrases(texts: list[str]) -> list[tuple[str, int]]:
    counts: Counter[str] = Counter()
    for text in texts:
        words = _norm_words(text)
        for i in range(max(0, len(words) - 2)):
            counts[" ".join(words[i:i + 3])] += 1
    return [(k, v) for k, v in counts.most_common(10) if v >= 3]


def build_goal_dashboard(main_analytics: dict | None = None) -> dict:
    main_analytics = main_analytics or build_main_post_analytics()
    official = _read_json(os.path.join(_PROJECT_ROOT, "official_rewards_metric.json"), {})
    official_value = int(official.get("official_qualified_home_impressions_90d") or 0) if isinstance(official, dict) else 0
    rolling = int(sum(int(p.get("impressions") or 0) for p in main_analytics.get("posts", [])))
    target = int(os.environ.get("TARGET_HOME_IMPRESSIONS_90D", "500000"))
    remaining = max(0, target - (official_value or rolling))
    scenarios = []
    for avg in (2000, 5000, 10000, 20000, 50000):
        scenarios.append({
            "average_main_post_impressions": avg,
            "posts_needed_for_500k": math.ceil(target / avg),
            "label": "scenario, not a guarantee of official qualified Premium Home impressions",
        })
    dashboard = {
        "generated_at": datetime.now().isoformat(),
        "target_qualified_home_impressions_90d": target,
        "official_metric": {
            "available": official_value > 0,
            "official_qualified_home_impressions_90d": official_value,
            "source": "manual/imported official_rewards_metric.json" if official_value else "not available",
            "warning": "Ordinary scraped impressions are not the official X qualified Home Timeline metric.",
        },
        "supporting_metrics": {
            "rolling_90d_main_post_impressions_estimate": rolling,
            "main_post_count": main_analytics.get("sample_count", 0),
            "median_impressions_per_post": main_analytics.get("median_impressions", 0),
            "average_impressions_per_post": main_analytics.get("average_impressions", 0),
            "hit_count": main_analytics.get("hit_count", 0),
            "breakout_count": main_analytics.get("breakout_count", 0),
        },
        "progress": {
            "official_progress_percent": round((official_value / target) * 100, 2) if official_value else None,
            "estimated_supporting_progress_percent": round((rolling / target) * 100, 2),
            "remaining_to_500k": remaining,
            "required_daily_average_remaining": round(remaining / 90, 2),
            "required_weekly_average_remaining": round(remaining / (90 / 7), 2),
        },
        "scenarios": scenarios,
    }
    _write_json(GOAL_DASHBOARD_FILE, dashboard)
    return dashboard


def build_editorial_brief(queue: list[dict] | None = None, main_analytics: dict | None = None, memory: dict | None = None) -> str:
    queue = queue or build_opportunity_queue()
    main_analytics = main_analytics or build_main_post_analytics()
    memory = memory or update_account_memory(main_analytics)
    strong_topics = ", ".join(t for t, _ in memory.get("successful_topics", [])[:5]) or "none yet"
    weak_hooks = ", ".join(h for h, _ in memory.get("failed_hooks", [])[:4]) or "insufficient sample"
    top = queue[:5]
    lines = [
        "# AI Therapist — Current Opportunities",
        "",
        "## Editorial Stance",
        "- Replies remain the discovery engine. Main posts must carry original account identity and Home reach.",
        "- Do not summarize a source. Use the source for facts, then add the therapist/AI-human insight.",
        "- Standalone is the default unless the original X post is essential context.",
        "- Reward originality, second-order effects, specificity, and human behavior implications.",
        "",
        "## Account Evidence",
        f"- 90d main-post median impressions: {main_analytics.get('median_impressions', 0)}.",
        f"- Strong topic priors: {strong_topics}.",
        f"- Weak hook priors: {weak_hooks}.",
        "",
        "## Top Main-Post Opportunities",
    ]
    if not top:
        lines.append("- No strong opportunities right now.")
    for i, item in enumerate(top, 1):
        lines.extend([
            f"{i}. {item['topic']}",
            f"   Why now: {item['research_packet']['why_now']}",
            f"   Classification: {item['classification']}",
            f"   Recommended angle: find what people are missing and connect it to AI/human behavior.",
            f"   Score: {item['overall_opportunity_score']}",
            f"   Urgency: {item['urgency']}",
        ])
    brief = "\n".join(lines) + "\n"
    _ensure_state_dir()
    with open(EDITORIAL_BRIEF_FILE, "w") as f:
        f.write(brief)
    return brief


def editorial_context_block(max_chars: int = 1800) -> str:
    """Compact prompt injection for main-post generators."""
    brief = ""
    if os.path.exists(EDITORIAL_BRIEF_FILE):
        try:
            with open(EDITORIAL_BRIEF_FILE) as f:
                brief = f.read()
        except OSError:
            brief = ""
    if not brief:
        try:
            main = build_main_post_analytics()
            replies = build_reply_analytics()
            queue = build_opportunity_queue(main, replies)
            memory = update_account_memory(main, replies)
            brief = build_editorial_brief(queue, main, memory)
        except Exception:
            return ""
    return (
        "==================================================\n"
        "MAIN-POST GROWTH BRIEF (use as editorial priors)\n"
        "==================================================\n"
        + brief[:max_chars]
    )


def operating_mode() -> str:
    return os.environ.get("MAIN_POST_OPERATING_MODE", "growth_automation").strip().lower()


def require_human_approval() -> bool:
    return operating_mode() == "rewards_eligible" or os.environ.get("MAIN_POST_REQUIRE_HUMAN_APPROVAL", "0") == "1"


def should_publish_main_posts() -> bool:
    return not require_human_approval()


def enqueue_approval_candidate(text: str, metadata: dict | None = None) -> dict:
    queue = _read_json(APPROVAL_QUEUE_FILE, [])
    item = {
        "id": f"draft-{datetime.now().strftime('%Y%m%d%H%M%S')}-{len(queue) + 1}",
        "created_at": datetime.now().isoformat(),
        "status": "PENDING_REVIEW",
        "generated_draft": text,
        "final_human_version": "",
        "actions": ["APPROVE", "EDIT", "REGENERATE", "REJECT", "SAVE_FOR_LATER"],
        "quality": quality_score(text),
        "metadata": metadata or {},
    }
    queue.append(item)
    _write_json(APPROVAL_QUEUE_FILE, queue[-200:])
    return item


def run_growth_cycle() -> dict:
    main = build_main_post_analytics()
    replies = build_reply_analytics()
    queue = build_opportunity_queue(main, replies)
    memory = update_account_memory(main, replies)
    dashboard = build_goal_dashboard(main)
    brief = build_editorial_brief(queue, main, memory)
    experiments = _read_json(EXPERIMENTS_FILE, [])
    if not experiments:
        _write_json(EXPERIMENTS_FILE, default_experiments())
    return {
        "main_analytics": main,
        "reply_analytics": replies,
        "opportunity_count": len(queue),
        "dashboard": dashboard,
        "brief_chars": len(brief),
    }


def default_experiments() -> list[dict]:
    today = datetime.now().date().isoformat()
    return [
        {
            "hypothesis": "AI/human psychology standalone posts outperform source-dependent quote reactions.",
            "variants": ["standalone_ai_human_observation", "quote_reaction"],
            "sample_requirement": 10,
            "start_date": today,
            "end_rule": "Evaluate after 10 posts per variant or 30 days.",
            "result": "",
        },
        {
            "hypothesis": "Contradiction hooks with one concrete fact outperform generic launch summaries.",
            "variants": ["contradiction_hook", "summary_hook"],
            "sample_requirement": 10,
            "start_date": today,
            "end_rule": "Compare median impressions and hit rate.",
            "result": "",
        },
        {
            "hypothesis": "Short personal-observation posts transfer winning reply energy to main posts.",
            "variants": ["short_personal_observation", "medium_explainer"],
            "sample_requirement": 10,
            "start_date": today,
            "end_rule": "Compare median impressions, replies, and follower response if available.",
            "result": "",
        },
    ]


def safe_run_main_post_growth_cycle() -> None:
    from . import health
    try:
        result = run_growth_cycle()
        log.info(
            f"[MAIN-GROWTH] Updated analytics/queue. "
            f"main_posts={result['main_analytics'].get('sample_count')} "
            f"opportunities={result['opportunity_count']}"
        )
        health.record_success("main_post_growth")
    except Exception:
        log.info("[MAIN-GROWTH] Error:")
        import traceback
        traceback.print_exc()
        health.record_failure("main_post_growth")

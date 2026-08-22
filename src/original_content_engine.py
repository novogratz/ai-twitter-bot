"""Rewards-aware standalone original post engine.

The reply engine is still the discovery surface. This module only handles
standalone Home-feed posts: generate many candidates, score them, reject
generic/repetitive drafts, and publish one winner only when it clears the bar.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from . import content_guard
from .config import (
    MAIN_POST_MINIMUM_ORIGINALITY_SCORE,
    MAIN_POST_MINIMUM_QUALITY_SCORE,
    ORIGINAL_CONTENT_CANDIDATES_PER_SLOT,
    ORIGINAL_CONTENT_ENGINE_ENABLED,
    ORIGINAL_CONTENT_MODEL,
    ORIGINAL_CONTENT_REQUIRE_AI_RELEVANCE,
    ORIGINAL_CONTENT_TOP_CONCEPTS,
    PROFILE_LLM_PROVIDER,
    _PROJECT_ROOT,
)
from .engagement_log import log_post
from .history import get_recent_tweets
from .llm_client import run_llm, unwrap_text
from .logger import log
from .main_post_growth import (
    OPPORTUNITY_QUEUE_FILE,
    editorial_context_block,
    enqueue_approval_candidate,
    quality_score,
    require_human_approval,
)
from .source_registry import (
    AI_TOPIC_RE,
    human_impact_score,
    is_ai_relevant_story,
    news_relevance_score,
    source_reliability,
    source_tier,
)
from .twitter_client import post_tweet

STATE_DIR = os.path.join(_PROJECT_ROOT, "growth")
DECISION_LOG_FILE = os.path.join(STATE_DIR, "original_post_decisions.json")
PROVENANCE_FILE = os.path.join(STATE_DIR, "original_post_provenance.json")

_GENERIC_PATTERNS = (
    r"\bread that again\b",
    r"\blet that sink in\b",
    r"\bnormalize\b",
    r"\bunpopular opinion\b",
    r"\bthis is your reminder\b",
    r"\byou are enough\b",
    r"\bthe future is now\b",
    r"\bgame changer\b",
    r"\b10x\b",
    r"\bcrushing it\b",
    r"\bgrindset\b",
)
_ENGAGEMENT_BAIT_RE = re.compile(
    r"\b(like if|repost if|rt if|comment below|drop a|tag someone|follow for)\b",
    re.IGNORECASE,
)
_CLICKBAIT_RE = re.compile(
    r"\b(the truth about|what nobody tells you|you won't believe|secret to|"
    r"do this before|everyone is lying)\b",
    re.IGNORECASE,
)
_TOPIC_WORDS_RE = re.compile(
    r"\b(ai|chatgpt|claude|openai|anthropic|google|gemini|xai|model|agent|"
    r"memory|robot|companion|therapy|therapist|psychology|lonely|loneliness|"
    r"relationship|work|job|identity|attention|trust|emotion|human)\b",
    re.IGNORECASE,
)


@dataclass
class PostCandidate:
    text: str
    concept: str = ""
    category: str = "standalone"
    topic: str = ""
    source_url: str = ""
    source_title: str = ""
    original_angle: str = ""
    factual_claims: list[str] = field(default_factory=list)
    scores: dict[str, float] = field(default_factory=dict)
    rejection_reasons: list[str] = field(default_factory=list)

    @property
    def accepted(self) -> bool:
        return not self.rejection_reasons


def _ensure_state_dir() -> None:
    os.makedirs(STATE_DIR, exist_ok=True)


def _read_json(path: str, default: Any) -> Any:
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError, TypeError):
        return default


def _write_json(path: str, payload: Any) -> None:
    _ensure_state_dir()
    with open(path, "w") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def _append_json(path: str, item: dict, limit: int = 500) -> None:
    rows = _read_json(path, [])
    if not isinstance(rows, list):
        rows = []
    rows.append(item)
    _write_json(path, rows[-limit:])


def _candidate_hash(text: str) -> str:
    norm = re.sub(r"\s+", " ", (text or "").strip().lower())
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]


def _tokens(text: str) -> set[str]:
    return {
        w
        for w in re.findall(r"[a-z0-9]{4,}", (text or "").lower())
        if w
        not in {
            "that",
            "this",
            "with",
            "from",
            "have",
            "your",
            "about",
            "people",
            "human",
            "because",
            "what",
            "when",
            "they",
            "their",
        }
    }


def semantic_similarity(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def genericness_penalty(text: str) -> int:
    low = (text or "").lower()
    penalty = 0
    for pat in _GENERIC_PATTERNS:
        if re.search(pat, low):
            penalty += 35
    if not _TOPIC_WORDS_RE.search(text or ""):
        penalty += 20
    if len(_tokens(text)) < 8:
        penalty += 15
    if re.search(r"\b(life|success|mindset|healing|growth)\b", low) and not re.search(
        r"\b(ai|model|chatgpt|therapy|psychology|relationship|work|identity)\b", low
    ):
        penalty += 25
    return min(100, penalty)


def clickbait_penalty(text: str) -> int:
    penalty = 0
    if _CLICKBAIT_RE.search(text or ""):
        penalty += 35
    if _ENGAGEMENT_BAIT_RE.search(text or ""):
        penalty += 60
    if (text or "").count("!") >= 2:
        penalty += 10
    return min(100, penalty)


def repetition_penalty(text: str, recent_posts: list[str] | None = None) -> int:
    recent_posts = recent_posts if recent_posts is not None else get_recent_tweets(hours=168)
    if content_guard.is_duplicate(text):
        return 100
    max_sim = 0.0
    for prior in recent_posts[-80:]:
        max_sim = max(max_sim, semantic_similarity(text, prior))
    if max_sim >= float(os.environ.get("ORIGINAL_CONTENT_MAX_RECENT_SIMILARITY", "0.82")):
        return 100
    if max_sim >= 0.68:
        return 45
    if max_sim >= 0.55:
        return 20
    return 0


def factuality_penalty(candidate: PostCandidate) -> int:
    text = candidate.text or ""
    claims = candidate.factual_claims or []
    has_number = bool(re.search(r"\d", text))
    has_named_source_claim = bool(re.search(r"\b(OpenAI|Anthropic|Google|Meta|xAI|NVIDIA|Microsoft|Apple)\b", text))
    if (has_number or has_named_source_claim or claims) and not candidate.source_url:
        return 25
    if re.search(r"\b(confirmed|officially|guaranteed|proves)\b", text, re.IGNORECASE) and not candidate.source_url:
        return 40
    return 0


def post_quality_score(candidate: PostCandidate, *, recent_posts: list[str] | None = None) -> dict[str, float]:
    base = quality_score(candidate.text, source_text=candidate.source_title or candidate.source_url)
    generic = genericness_penalty(candidate.text)
    clickbait = clickbait_penalty(candidate.text)
    repetition = repetition_penalty(candidate.text, recent_posts)
    factuality = factuality_penalty(candidate)
    source_reliability_score = source_reliability(candidate.source_url, candidate.source_title) if candidate.source_url else 50
    human_impact = human_impact_score(" ".join([candidate.text, candidate.topic, candidate.original_angle]))
    source_bonus = 8.0 if candidate.source_url and source_tier(candidate.source_url, candidate.source_title) <= 2 else 0.0
    ai_news_bonus = 7.0 if candidate.source_url and is_ai_relevant_story(candidate.topic or candidate.text, candidate.source_title) else 0.0
    originality = max(0, float(base.get("originality", 0)) - generic * 0.35 - repetition * 0.45)
    insight_density = float(base.get("insight_depth", 0))
    hook_strength = float(base.get("hook", 0))
    emotional = max(
        float(human_impact),
        85.0 if re.search(r"\b(feel|lonely|trust|relationship|attention|identity|work|worry|remember)\b", candidate.text, re.I) else 62.0,
    )
    reply_potential = float(base.get("conversation_potential", 0))
    repost_potential = float(base.get("home_feed_potential", 0))
    bookmark_potential = 75.0 if insight_density >= 70 and originality >= 70 else 50.0
    brand_fit = float(base.get("ai_therapist_fit", 0))
    timeliness = float(base.get("timeliness", 65))
    total = (
        originality * 0.18
        + insight_density * 0.15
        + hook_strength * 0.14
        + emotional * 0.12
        + reply_potential * 0.10
        + repost_potential * 0.10
        + bookmark_potential * 0.06
        + brand_fit * 0.08
        + timeliness * 0.07
        + source_reliability_score * 0.04
        + source_bonus
        + ai_news_bonus
        - generic * 0.35
        - clickbait * 0.45
        - repetition * 0.55
        - factuality * 0.40
    )
    return {
        "post_score": round(max(0, min(100, total)), 2),
        "hook_strength": hook_strength,
        "originality": round(originality, 2),
        "insight_density": insight_density,
        "emotional_resonance": emotional,
        "reply_potential": reply_potential,
        "repost_potential": repost_potential,
        "bookmark_potential": bookmark_potential,
        "brand_fit": brand_fit,
        "timeliness": timeliness,
        "source_reliability": source_reliability_score,
        "source_bonus": source_bonus,
        "ai_news_bonus": ai_news_bonus,
        "human_impact_score": human_impact,
        "genericness_penalty": generic,
        "clickbait_penalty": clickbait,
        "engagement_bait_penalty": 60 if _ENGAGEMENT_BAIT_RE.search(candidate.text or "") else 0,
        "repetition_penalty": repetition,
        "factuality_penalty": factuality,
    }


def evaluate_candidate(candidate: PostCandidate, *, recent_posts: list[str] | None = None) -> PostCandidate:
    text = (candidate.text or "").strip()
    candidate.text = text
    candidate.scores = post_quality_score(candidate, recent_posts=recent_posts)

    ok, reason = content_guard.validate(text, kind="original")
    if not ok:
        candidate.rejection_reasons.append(f"content_guard:{reason}")
    if len(text) > 280:
        candidate.rejection_reasons.append("over_280_chars")
    if len(text) < 40:
        candidate.rejection_reasons.append("too_short_for_standalone")
    if candidate.scores["genericness_penalty"] >= 35:
        candidate.rejection_reasons.append("genericness")
    if candidate.scores["clickbait_penalty"] >= 35:
        candidate.rejection_reasons.append("clickbait_or_engagement_bait")
    if candidate.scores["repetition_penalty"] >= 45:
        candidate.rejection_reasons.append("repetition")
    if candidate.scores["factuality_penalty"] >= 40:
        candidate.rejection_reasons.append("unsupported_factual_claim")
    if ORIGINAL_CONTENT_REQUIRE_AI_RELEVANCE and not AI_TOPIC_RE.search(" ".join([text, candidate.topic, candidate.source_title])):
        candidate.rejection_reasons.append("not_ai_relevant")
    if candidate.source_url and not is_ai_relevant_story(candidate.topic or text, candidate.source_title):
        candidate.rejection_reasons.append("source_not_ai_relevant")
    if candidate.source_url and candidate.scores["source_reliability"] < 70:
        candidate.rejection_reasons.append("low_source_reliability")
    if candidate.scores["originality"] < MAIN_POST_MINIMUM_ORIGINALITY_SCORE:
        candidate.rejection_reasons.append("low_originality")
    if candidate.scores["post_score"] < MAIN_POST_MINIMUM_QUALITY_SCORE:
        candidate.rejection_reasons.append("below_quality_threshold")
    return candidate


def _load_opportunities(limit: int = 10) -> list[dict]:
    data = _read_json(OPPORTUNITY_QUEUE_FILE, [])
    if not isinstance(data, list):
        return []
    ranked = []
    for item in data:
        if not isinstance(item, dict):
            continue
        score = news_relevance_score(item)
        if score <= 0:
            continue
        enriched = dict(item)
        enriched["ai_therapist_news_score"] = score
        ranked.append(enriched)
    ranked.sort(key=lambda item: item.get("ai_therapist_news_score", 0), reverse=True)
    return ranked[:limit]


def _prompt_for_candidates(slot_label: str, count: int) -> str:
    opportunities = _load_opportunities()
    startup_priority = "STARTUP IMPACT SLOT: pick the hottest sourced AI development available and make the post feel immediate." if "startup" in slot_label.lower() else ""
    return f"""
You are writing standalone Home-timeline posts for @TheAIShrink, the AI Therapist.

Generate {count} DISTINCT candidate posts. Do not publish, do not choose yet.
Return strict JSON: an array of objects with keys:
text, concept, category, topic, source_url, source_title, original_angle, factual_claims.

Strategy:
- Replies are discovery. These are standalone originals for Home reach and Original Content Rewards.
- {startup_priority}
- The account lens is AI + psychology + human behavior: work, identity, memory, attention, relationships, loneliness, trust.
- Never summarize news. Interpret why it matters to humans.
- Prefer the hottest fresh AI source material from the opportunity queue. Primary sources and high-quality AI reporting beat evergreen filler.
- At least 20 candidates should be sourced AI-news interpretations with source_url populated when enough opportunities exist.
- Every candidate must be about AI, AI products, AI infrastructure, AI companions, agents, robots, memory, work, identity, trust, or human behavior around AI.
- Optimize for real conversation: a reader should be able to reply with a story, disagreement, or example.
- Favor hot-topic AI posts that could plausibly make a verified user stop scrolling: model launches, agents, memory, AI companions, robots, deepfakes, education, jobs, identity, trust, regulation that hits normal people.
- Create replyable tension, not engagement bait. Prefer a specific unresolved human question over a generic CTA.
- Reject generic motivational-account language.
- Avoid engagement bait, diagnosis, therapy claims, medical advice, and recycled quotes.
- Prefer concise English. No hashtags. No external link in the post body.
- Factual AI news needs source_url; if uncertain, write a human-behavior observation without factual claims.

Slot: {slot_label}

Recent editorial context:
{editorial_context_block(2400)}

Top opportunities as raw material:
{json.dumps(opportunities, ensure_ascii=False)[:3500]}
""".strip()


def parse_candidate_payload(raw: str) -> list[PostCandidate]:
    raw = (raw or "").strip()
    if not raw:
        return []
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.IGNORECASE | re.DOTALL).strip()
    data: Any
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = []
        for line in raw.splitlines():
            cleaned = re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", line).strip()
            if len(cleaned) >= 20:
                data.append({"text": cleaned})
    if isinstance(data, dict):
        data = data.get("candidates") or data.get("posts") or []
    out: list[PostCandidate] = []
    for item in data if isinstance(data, list) else []:
        if isinstance(item, str):
            item = {"text": item}
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or item.get("post") or item.get("tweet") or "").strip()
        if not text:
            continue
        claims = item.get("factual_claims") or []
        if isinstance(claims, str):
            claims = [claims]
        out.append(
            PostCandidate(
                text=text,
                concept=str(item.get("concept") or ""),
                category=str(item.get("category") or "standalone"),
                topic=str(item.get("topic") or ""),
                source_url=str(item.get("source_url") or ""),
                source_title=str(item.get("source_title") or ""),
                original_angle=str(item.get("original_angle") or ""),
                factual_claims=[str(c) for c in claims if c],
            )
        )
    return out


def generate_candidates(slot_label: str = "scheduled") -> list[PostCandidate]:
    count = max(15, min(30, ORIGINAL_CONTENT_CANDIDATES_PER_SLOT))
    prompt = _prompt_for_candidates(slot_label, count)
    result = run_llm(
        prompt,
        ORIGINAL_CONTENT_MODEL,
        label="ORIGINAL_CONTENT_CANDIDATES",
        timeout=int(os.environ.get("ORIGINAL_CONTENT_LLM_TIMEOUT_SECONDS", "240")),
        force_provider=PROFILE_LLM_PROVIDER,
    )
    if result.returncode != 0:
        log.info(f"[ORIGINAL] candidate generation failed: {result.stderr[:240]}")
        return []
    text = unwrap_text(result.stdout, structured_output=False)
    candidates = parse_candidate_payload(text)
    deduped: list[PostCandidate] = []
    seen: list[str] = []
    for cand in candidates:
        if any(semantic_similarity(cand.text, prev) >= 0.72 for prev in seen):
            continue
        seen.append(cand.text)
        deduped.append(cand)
    return deduped[:count]


def rank_candidates(candidates: list[PostCandidate], *, recent_posts: list[str] | None = None) -> list[PostCandidate]:
    evaluated = [evaluate_candidate(c, recent_posts=recent_posts) for c in candidates]
    return sorted(
        evaluated,
        key=lambda c: (c.accepted, c.scores.get("post_score", 0), c.scores.get("originality", 0)),
        reverse=True,
    )


def _decision_payload(slot_label: str, ranked: list[PostCandidate], winner: PostCandidate | None) -> dict:
    return {
        "created_at": datetime.now().isoformat(),
        "slot_label": slot_label,
        "candidate_count": len(ranked),
        "winner_hash": _candidate_hash(winner.text) if winner else "",
        "winner_text": winner.text if winner else "",
        "winner_score": winner.scores if winner else {},
        "published": False,
        "candidates": [asdict(c) for c in ranked[:ORIGINAL_CONTENT_TOP_CONCEPTS]],
    }


def _record_provenance(winner: PostCandidate, decision: dict) -> None:
    _append_json(
        PROVENANCE_FILE,
        {
            "created_at": datetime.now().isoformat(),
            "post_id": "",
            "sources": [winner.source_url] if winner.source_url else [],
            "generation_reason": winner.concept or winner.category,
            "original_angle": winner.original_angle,
            "candidate_hashes": [_candidate_hash(c.get("text", "")) for c in decision.get("candidates", [])],
            "scores": winner.scores,
        },
    )


def run_original_content_cycle(slot_label: str = "scheduled") -> bool:
    if not ORIGINAL_CONTENT_ENGINE_ENABLED:
        log.info("[ORIGINAL] Engine disabled (ORIGINAL_CONTENT_ENGINE_ENABLED=0).")
        return False

    recent = get_recent_tweets(hours=168)
    candidates = generate_candidates(slot_label)
    ranked = rank_candidates(candidates, recent_posts=recent)
    winner = next((c for c in ranked if c.accepted), None)
    decision = _decision_payload(slot_label, ranked, winner)

    if not winner:
        log.info(f"[ORIGINAL] No candidate cleared the bar ({len(ranked)} scored).")
        _append_json(DECISION_LOG_FILE, decision)
        return False

    if require_human_approval():
        enqueue_approval_candidate(winner.text, {"surface": "original_content_engine", "scores": winner.scores})
        decision["queued_for_approval"] = True
        _append_json(DECISION_LOG_FILE, decision)
        log.info(f"[ORIGINAL] Queued for approval score={winner.scores['post_score']}: {winner.text[:120]!r}")
        return False

    ok = post_tweet(winner.text)
    decision["published"] = bool(ok)
    _append_json(DECISION_LOG_FILE, decision)
    if ok:
        log_post(winner.text, source=f"original_engine/{winner.category}", pattern_id="OTHER")
        _record_provenance(winner, decision)
        try:
            from .first_comment import post_first_comment

            post_first_comment(winner.text)
        except Exception:
            log.info("[ORIGINAL] first-comment follow-up failed (non-fatal).")
        log.info(f"[ORIGINAL] Published score={winner.scores['post_score']}: {winner.text[:120]!r}")
        return True
    log.info("[ORIGINAL] Winner passed engine but chokepoint skipped publish.")
    return False


def safe_run_original_content_cycle(slot_label: str = "scheduled") -> None:
    from . import health

    try:
        run_original_content_cycle(slot_label=slot_label)
        health.record_success("original_content_engine")
    except Exception:
        import traceback

        log.info("[ORIGINAL] Error:")
        traceback.print_exc()
        health.record_failure("original_content_engine")

"""Source registry and scoring for AI Therapist standalone posts."""

from __future__ import annotations

import re
from urllib.parse import urlparse


PRIMARY_SOURCES = {
    "openai.com": "OpenAI",
    "anthropic.com": "Anthropic",
    "deepmind.google": "Google DeepMind",
    "blog.google": "Google",
    "ai.meta.com": "Meta AI",
    "x.ai": "xAI",
    "microsoft.com": "Microsoft",
    "apple.com": "Apple",
    "machinelearning.apple.com": "Apple ML",
    "nvidia.com": "NVIDIA",
    "huggingface.co": "Hugging Face",
    "arxiv.org": "arXiv",
}

SECONDARY_SOURCES = {
    "techcrunch.com": "TechCrunch",
    "theverge.com": "The Verge",
    "arstechnica.com": "Ars Technica",
    "wired.com": "Wired",
    "technologyreview.com": "MIT Technology Review",
    "reuters.com": "Reuters",
    "bloomberg.com": "Bloomberg",
    "ft.com": "Financial Times",
    "axios.com": "Axios",
    "semianalysis.com": "SemiAnalysis",
    "simonwillison.net": "Simon Willison",
}

AI_TOPIC_RE = re.compile(
    r"\b("
    r"ai|a\.i\.|artificial intelligence|llm|model|chatgpt|claude|gemini|"
    r"openai|anthropic|deepmind|google ai|meta ai|xai|mistral|llama|"
    r"agent|copilot|cursor|memory|personalization|companion|robot|robotics|"
    r"humanoid|deepfake|synthetic|nvidia|gpu|compute|datacenter|data center"
    r")\b",
    re.IGNORECASE,
)

HUMAN_IMPACT_RE = re.compile(
    r"\b("
    r"work|job|school|education|teacher|student|relationship|friend|dating|"
    r"lonely|loneliness|companion|therapy|therapist|mental health|emotion|"
    r"identity|memory|attention|trust|decision|creativity|kids|parents|"
    r"privacy|deepfake|voice|face|safety|regulation"
    r")\b",
    re.IGNORECASE,
)


def _domain(url: str) -> str:
    host = (urlparse(url or "").netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def source_tier(url: str, source_name: str = "") -> int:
    domain = _domain(url)
    source = (source_name or "").lower()
    if any(domain == d or domain.endswith("." + d) for d in PRIMARY_SOURCES):
        return 1
    if any(source.startswith(name.lower()) for name in PRIMARY_SOURCES.values()):
        return 1
    if any(domain == d or domain.endswith("." + d) for d in SECONDARY_SOURCES):
        return 2
    if any(source.startswith(name.lower()) for name in SECONDARY_SOURCES.values()):
        return 2
    return 3


def source_reliability(url: str, source_name: str = "") -> int:
    tier = source_tier(url, source_name)
    return 95 if tier == 1 else 82 if tier == 2 else 55


def is_ai_relevant_story(title: str, source_name: str = "") -> bool:
    text = f"{title or ''} {source_name or ''}"
    return bool(AI_TOPIC_RE.search(text))


def human_impact_score(text: str) -> int:
    if HUMAN_IMPACT_RE.search(text or ""):
        return 90
    if AI_TOPIC_RE.search(text or ""):
        return 65
    return 35


def news_relevance_score(item: dict) -> float:
    title = str(item.get("topic") or item.get("title") or "")
    source = str(item.get("source") or item.get("src") or "")
    url = str(item.get("source_url") or item.get("url") or "")
    if not is_ai_relevant_story(title, source):
        return 0.0
    reliability = source_reliability(url, source)
    impact = human_impact_score(title)
    novelty = float(item.get("novelty") or 70)
    insight = float(item.get("insight_potential") or 70)
    urgency = float(item.get("urgency") or 60)
    saturation = float(item.get("saturation") or 30)
    return round(
        impact * 0.28
        + insight * 0.24
        + novelty * 0.18
        + reliability * 0.16
        + urgency * 0.10
        - saturation * 0.04,
        2,
    )

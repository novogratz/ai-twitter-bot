"""Content-pillar attribution (2026-06-07 agent spec, Part 2 — Metrics).

The spec's weekly review ("shift mix toward winners") needs per-pillar
attribution, which the old FR-era topic tags (IA/Spatial/Bourse) and the
98%-UNKNOWN pattern column can't provide. Every logged action gets a pillar
tag, computed deterministically from the outgoing text (no LLM call):

  market_trauma — therapist one-liners on investor psychology (PRIMARY)
  ai_vs_btc     — the AI-vs-Bitcoin running bit (foils: saylor, BTCTherapist)
  meme_reaction — native GIF/image post, deadpan caption
  reply_bait    — question posts that farm replies
  ai_news_take  — persona spin on the day's AI news
  other         — fallback

Classification is heuristic and cheap on purpose: it runs on every write at
the engagement-log chokepoint. Tags are stable identifiers stored in
engagement_log.csv, so never rename without migrating.
"""
import re

# Word-boundary vocab per signal. Lowercase; matched with \b regexes.
_THERAPY_WORDS = (
    "trauma", "therapy", "therapist", "session", "patient", "diagnosis",
    "diagnose", "clinical", "clinically", "anxiety", "panic", "fear",
    "cope", "coping", "copium", "hopium", "denial", "grief", "healing",
    "heal", "breathe", "processing", "neuroses", "neurosis", "intrusive",
    "fomo", "capitulation", "bagholder", "bag-holding", "bagholding",
)
_MARKET_WORDS = (
    "portfolio", "market", "markets", "stock", "stocks", "trade", "trader",
    "trading", "invest", "investor", "investors", "drawdown", "dip", "sell",
    "sold", "buy", "bought", "chart", "candle", "position", "leverage",
    "earnings", "valuation", "ticker", "etf", "index", "nasdaq", "s&p",
)
_BTC_WORDS = (
    "bitcoin", "btc", "saylor", "satoshi", "halving", "hodl", "maxi",
    "sats", "microstrategy", "btctherapist",
)
_AI_WORDS = (
    "ai", "llm", "llms", "gpt", "agent", "agents", "agentic", "model",
    "models", "openai", "anthropic", "claude", "gemini", "nvidia", "gpu",
    "gpus", "datacenter", "compute", "chatbot", "robot", "robots", "agi",
)
_BAIT_CUES = (
    "what's the most", "whats the most", "group session", "tell me",
    "drop your", "confess", "be honest", "asking for", "who else",
    "which one", "what was your", "how many of you", "honest question",
    "wrong answers only",
)


def _has_any(text_lc: str, words) -> bool:
    return any(re.search(r"\b" + re.escape(w) + r"\b", text_lc) for w in words)


def classify(text: str, action_type: str = "", source: str = "") -> str:
    """Return the pillar tag for an outgoing post/quote/reply.

    `action_type` / `source` carry explicit signals that beat text heuristics
    (quote_gif / GIF/<query> sources → meme_reaction; spicy QUESTION mode
    passes source="QUESTION").
    """
    src = (source or "").upper()
    if (action_type or "").lower() in ("quote_gif", "post_gif") or src.startswith("GIF/"):
        return "meme_reaction"
    if "QUESTION" in src:
        return "reply_bait"

    t = (text or "").strip().lower()
    if not t:
        return "other"

    if "?" in t and any(cue in t for cue in _BAIT_CUES):
        return "reply_bait"

    btc = _has_any(t, _BTC_WORDS)
    ai = _has_any(t, _AI_WORDS)
    if btc and ai:
        return "ai_vs_btc"

    therapy = _has_any(t, _THERAPY_WORDS)
    market = _has_any(t, _MARKET_WORDS) or btc
    if therapy and market:
        return "market_trauma"

    if ai:
        return "ai_news_take"
    if therapy:
        return "market_trauma"
    if market:
        return "market_trauma" if "?" not in t else "reply_bait"
    return "other"

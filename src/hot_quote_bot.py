"""Hot-topic quote bot — 4x/day replacement for the disabled news posts.

Reads external_signal.json (RSS + HN + X hot, updated every 5 min) to find
the hottest AI/Space/Investment story right now, hunts the most viral tweet
about it, and quote-tweets it with a sharp investment-angle take.

Scheduled: 8 AM, 12 PM, 4 PM, 8 PM EST.
"""
import json
import os
import re
import time
import random
import traceback
from datetime import date, datetime
from typing import Optional

from .config import QUOTE_MODEL, _PROJECT_ROOT, BOT_HANDLE
from .logger import log
from .twitter_client import scrape_x_search, quote_tweet
from .llm_client import run_llm, unwrap_text
from .engagement_log import log_reply

SIGNAL_FILE = os.path.join(_PROJECT_ROOT, "external_signal.json")
STATE_FILE = os.path.join(_PROJECT_ROOT, "hot_quote_state.json")
QUOTED_FILE = os.path.join(_PROJECT_ROOT, "quoted_tweets.json")

# AI keywords — used to filter signal items (AI Big Boss: AI only)
_NICHE_RE = re.compile(
    r"\b(ai|a\.i\.|artificial intelligence|agi|llm|openai|anthropic|deepmind|"
    r"xai|mistral|deepseek|gpt|chatgpt|claude|gemini|grok|llama|nvidia|gpu|"
    r"ai agent|agentic|copilot|cursor|perplexity|reasoning model|benchmark|"
    r"robot|robotics|humanoid|ai safety|ai startup|ai model|neural|sora|"
    r"machine learning|datacenter|compute|inference)\b",
    re.IGNORECASE,
)

_SKIP_RE = re.compile(r"\bskip\b", re.IGNORECASE)

HOT_QUOTE_PROMPT = """\
You are AI Big Boss (@TheAIBoss) — the account people follow to understand
what actually matters in AI. Confident, curious, fast, optimistic, easy
language, never corporate, never cringe.

You will QUOTE-TWEET this hot AI tweet:

@{author}: "{tweet_text}"

TOPIC CONTEXT: {topic_hint}

Write ONE quote in ENGLISH that adds insight, analysis, a prediction, or
context — explain what it means or what everyone's missing. Make AI make sense.

SCOPE: AI only — labs & models, agents & tools, AI research/benchmarks, AGI,
AI startups, AI compute, embodied AI. Off scope (careers, crypto, generic
tech, politics) -> SKIP.

VOICE:
- Hook in the first 6 words. Short sentences, easy words, strong opinion.
- Add a NEW point the original doesn't state.
- Max 220 chars. The original renders below yours.

RULES:
- Add real value; a pure reaction ("Huge.") -> SKIP.
- Never attack the author. React to real AI news only; never invent a fact.
- NO hashtags. NO emojis. No em dashes. No links. No jargon.
- If nothing beats silence -> output exactly: SKIP

Output the quote text ONLY, or SKIP.
"""


def _load_state() -> dict:
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(state: dict) -> None:
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def _already_quoted(url: str) -> bool:
    try:
        with open(QUOTED_FILE) as f:
            data = json.load(f)
        return url in data or any(url.split("/status/")[-1] in str(u) for u in data)
    except Exception:
        return False


def _mark_quoted(url: str) -> None:
    try:
        data = []
        if os.path.exists(QUOTED_FILE):
            with open(QUOTED_FILE) as f:
                data = json.load(f)
        if url not in data:
            data.append(url)
        if len(data) > 5000:
            data = data[-5000:]
        with open(QUOTED_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def _load_signal_items() -> list[dict]:
    """Read external_signal.json, return items sorted by score, niche-filtered."""
    try:
        with open(SIGNAL_FILE) as f:
            data = json.load(f)
        items = data.get("items", [])
        # Filter to AI/Space/Investment niche
        niche = [i for i in items if _NICHE_RE.search(i.get("title", "") + " " + i.get("src", ""))]
        # Sort by score desc
        niche.sort(key=lambda x: int(x.get("score", 0)), reverse=True)
        return niche[:10]
    except Exception:
        return []


def _topic_hint(item: dict) -> str:
    """Extract a short topic hint from the signal item for the prompt."""
    title = item.get("title", "")[:120]
    src = item.get("src", "")
    return f"{title} [source: {src}]"


def _search_best_tweet(topic: str) -> Optional[dict]:
    """Search X for the most viral tweet on this topic today."""
    # Build a tight query from the topic keywords
    words = [w for w in re.findall(r"[A-Z$][A-Za-z0-9$]{2,}", topic) if len(w) > 2][:4]
    ticker_words = [w for w in words if w.startswith("$") or w.isupper()]
    kw_words = [w for w in words if not w.startswith("$") and not w.isupper()]

    queries = []
    if ticker_words:
        queries.append(f"{' OR '.join(ticker_words)} lang:en min_faves:50")
    if kw_words:
        queries.append(f"{' '.join(kw_words[:2])} lang:en min_faves:100")
    # Always add a broad niche fallback
    queries.append("OpenAI OR Anthropic OR ChatGPT OR Nvidia OR \"AI agent\" OR AGI lang:en min_faves:200")

    candidates = []
    for q in queries[:2]:
        try:
            tweets = scrape_x_search(q, max_tweets=15, tab="top")
            candidates.extend(tweets)
            if len(candidates) >= 10:
                break
        except Exception:
            pass

    if not candidates:
        return None

    from . import respect_list
    from .reply_bot import _tweet_age_minutes
    candidates = [c for c in candidates if _tweet_age_minutes(c.get("url", "")) <= 2880]  # 48h hard cap
    candidates = [c for c in candidates
                  if not respect_list.is_protected(c.get("author", ""))
                  and c.get("author", "").lower() != BOT_HANDLE.lower()
                  and not _already_quoted(c.get("url", ""))]

    if not candidates:
        return None

    candidates.sort(key=lambda t: int(t.get("likes") or 0), reverse=True)
    return candidates[0]


def _generate_quote(author: str, tweet_text: str, topic_hint: str) -> Optional[str]:
    prompt = HOT_QUOTE_PROMPT.format(
        author=author,
        tweet_text=tweet_text[:220],
        topic_hint=topic_hint,
    )
    result = run_llm(prompt, QUOTE_MODEL, label="HOT_QUOTE", output_json=False, timeout=90)
    if result.returncode != 0 or not result.stdout:
        return None
    text = unwrap_text(result.stdout).strip()
    if _SKIP_RE.search(text) or not text:
        return None
    if len(text) > 280:
        text = text[:277] + "..."
    return text


def run_hot_quote_cycle() -> None:
    state = _load_state()
    slot_key = f"{date.today().isoformat()}-{datetime.now().hour // 4}"

    if state.get("last_slot") == slot_key:
        log.info(f"[HOT_QUOTE] Already posted this slot ({slot_key}). Skipping.")
        return

    log.info("[HOT_QUOTE] Loading hot signal topics...")
    items = _load_signal_items()

    if not items:
        log.info("[HOT_QUOTE] No niche signal items found. Skipping.")
        return

    log.info(f"[HOT_QUOTE] Top topics: {[i.get('title','')[:60] for i in items[:3]]}")

    for item in items[:6]:
        topic = item.get("title", "")
        hint = _topic_hint(item)
        log.info(f"[HOT_QUOTE] Trying topic: {topic[:80]}...")

        tweet = _search_best_tweet(topic)
        if not tweet:
            log.info("[HOT_QUOTE] No viable tweet found for this topic. Trying next.")
            continue

        author = tweet.get("author", "someone")
        text = tweet.get("text", "")
        likes = int(tweet.get("likes") or 0)
        url = tweet.get("url", "")

        log.info(f"[HOT_QUOTE] Best tweet: @{author} ({likes} likes) — {text[:70]}")

        quote = _generate_quote(author, text, hint)
        if not quote:
            log.info("[HOT_QUOTE] LLM skipped or failed. Trying next topic.")
            continue

        log.info(f"[HOT_QUOTE] Quote: {quote}")

        try:
            posted = quote_tweet(url, quote)
        except Exception:
            # Unknown state (Safari may have posted) — mark consumed to be safe.
            _mark_quoted(url)
            log.info("[HOT_QUOTE] Post failed:")
            traceback.print_exc()
            continue

        if not posted:
            # Chokepoint skip (dedup / spacing / content_guard / DRY_RUN-off).
            # Do NOT consume the slot or mark the URL: this is the bug that
            # silently burned the 4 daily hot-quote slots when the dedup
            # caught a near-miss (the highest-signal surface). Try next topic.
            log.info("[HOT_QUOTE] Chokepoint skipped — slot preserved, trying next topic.")
            continue

        _mark_quoted(url)
        try:
            log_reply(url, quote, action_type="quote", source=f"HOT_QUOTE/{author}")
        except Exception:
            pass
        state["last_slot"] = slot_key
        state["last_topic"] = topic[:80]
        state["last_run"] = datetime.utcnow().isoformat()
        _save_state(state)
        log.info(f"[HOT_QUOTE] Posted. Slot {slot_key} done.")
        return

    log.info("[HOT_QUOTE] No topic produced a postable quote this slot.")


def safe_run_hot_quote_cycle() -> None:
    from . import health
    try:
        run_hot_quote_cycle()
        health.record_success("hot_quote")
    except Exception:
        log.info("[HOT_QUOTE] Unhandled error:")
        traceback.print_exc()
        health.record_failure("hot_quote")

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

# AI/Space/Investment keywords — used to filter signal items
_NICHE_RE = re.compile(
    r"\b(AI|GPU|nvidia|nvda|openai|anthropic|spacex|rocket|satellite|RKLB|ASTS|LUNR|SPCE|"
    r"LMT|PLTR|palantir|quantum|bitcoin|BTC|crypto|ETF|S&P|nasdaq|stock|invest|datacenter|"
    r"robotics|starship|starlink|drone|hypersonic|autonomous|AGI|LLM|model|inference|compute)\b",
    re.IGNORECASE,
)

_SKIP_RE = re.compile(r"\bskip\b", re.IGNORECASE)

HOT_QUOTE_PROMPT = """\
You are @AISpaceDecoder — The AI & Space Decoder. Quant analyst, sharp wit,
zero fluff. Your audience: retail investors, tech nerds, space fans who want
alpha before mainstream media catches on.

You will QUOTE-TWEET this tweet about a hot topic in AI / Space / Investment:

@{author}: "{tweet_text}"

TOPIC CONTEXT: {topic_hint}

Write ONE punchy quote in English. The goal: make people screenshot it,
retweet it, and think "this account sees what others don't."

VOICE:
- Lead with a hard number, a named stock/company, or a brutal observation.
- Sharp investment angle mandatory: name the winner, the loser, the
  implication for a specific ticker or sector. Be specific ($NVDA, $RKLB,
  $ASTS, $PLTR, MARA, CoreWeave, etc.)
- Confident-arrogant. You called it before anyone else.
- Dry wit welcome. Think Bloomberg terminal meets stand-up.
- Max 220 chars. The original tweet renders below yours automatically.

RULES:
- HOOK in first 5 words: number / bold verb / named actor.
- Always adds a NEW angle the original tweet doesn't state.
- Never attack the author. Troll the trend, the system, the market.
- No hashtags. No filler. No "not financial advice" inline.
- 1-2 on-brand emojis max: 🚀 ⚡ 🛰️ 🤖 📡
- If nothing beats silence → output exactly: SKIP

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
    queries.append("AI OR SpaceX OR NVDA OR RKLB OR PLTR lang:en min_faves:200")

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

        _mark_quoted(url)
        try:
            quote_tweet(url, quote)
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
        except Exception:
            log.info("[HOT_QUOTE] Post failed:")
            traceback.print_exc()

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

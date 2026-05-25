"""Breakout bot — fast trend jacker for the breakthrough moment.

User: 20k followers by end of month. Math says we need at least one viral
moment per week. Viral moments require SPEED: being among the first 50 English
voices on a breaking topic = 10-100x reach vs. posting 6h later.

Strategy:
  - Every 8 min, scrape X niche-search "live" tab + trends panel.
  - Velocity check: tweets in the last 30min that already cleared
    HIGH_VELOCITY_LIKES likes = something is breaking.
  - Pick the topic, generate a SHARP English hot take in <30 sec via Claude
    (Opus, no rejection sampling — speed > polish).
  - Post immediately. The bot's regular news/hotake cycle is too slow
    for breaking news (45-min cadence).
  - Cap 8/day (separate from MAX_NEWS_PER_DAY) so we never replace
    the steady news flow with chase-the-trend output.
"""
import json
import os
import random
import time
import traceback
import urllib.parse
from datetime import datetime, date, timedelta

from .config import _PROJECT_ROOT, BOT_HANDLE, NEWS_MODEL
from .llm_client import run_llm, unwrap_text
from .logger import log
from .twitter_client import scrape_x_search, post_tweet
from .humanizer import humanize, strip_agent_preamble

BREAKOUT_STATE_FILE = os.path.join(_PROJECT_ROOT, "breakout_state.json")
BREAKOUT_HISTORY_FILE = os.path.join(_PROJECT_ROOT, "breakout_history.json")

MAX_BREAKOUTS_PER_DAY = int(os.environ.get("MAX_BREAKOUTS_PER_DAY", "15"))
HIGH_VELOCITY_LIKES = int(os.environ.get("BREAKOUT_VELOCITY_LIKES", "100"))
MIN_LIKES_TO_CONSIDER = int(os.environ.get("BREAKOUT_MIN_LIKES", "30"))

# Search queries that surface high-velocity English content in our niches.
# We want the FRESH viral pulse, not yesterday's already-hot tweets.
BREAKOUT_QUERIES = [
    "AI datacenter OR power demand lang:en min_faves:3000",
    "CoreWeave OR CRWV OR APLD OR IREN lang:en min_faves:2000",
    "Nvidia OR GPU OR compute cluster lang:en min_faves:5000",
    "TAO OR Bittensor OR decentralized compute lang:en min_faves:2000",
    "SpaceX OR Starlink OR robotics lang:en min_faves:5000",
]


BREAKOUT_PROMPT = """Tu es @CryptoAIDecode. Une story est en train d'EXPLOSER en ce moment sur X. Tu vas la commenter, ULTRA RAPIDE, ULTRA SHARP.

{lang_directive}

Story qui prend la lumière (échantillon des tweets qui montent):
{trend_context}

📅 Date: {today_date}

OBJECTIF: be among the first 50 voices commenting on this story through the
AI infrastructure & asymmetric investing lens.
Pas de SKIP. Pas de rejection sampling. Tu shipes un take qui claque.

FORMAT (≤270 chars TOTAL, screenshot-worthy):
- 1-2 phrases sec.
- Une chute qui pique. Pas de news-report tone.
- Langue dictée par la directive linguistique en haut du prompt.
- Pas d'emojis, pas de hashtag, pas d'em dash.
- Pas de "Selon X..." / "Breaking:" / "Aujourd'hui..." / "According to..." / "Today...".

{performance_section}

OUTPUT — strictement le tweet, rien d'autre. Pas de préface.
Pas de "Voici", pas de "Le tweet:", pas de "---". JUSTE LE TWEET.
"""


def _load_state() -> dict:
    if os.path.exists(BREAKOUT_STATE_FILE):
        try:
            with open(BREAKOUT_STATE_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {"date": None, "count": 0}


def _save_state(s: dict):
    with open(BREAKOUT_STATE_FILE, "w") as f:
        json.dump(s, f)


def _today_count() -> int:
    s = _load_state()
    today = date.today().isoformat()
    if s.get("date") != today:
        return 0
    return int(s.get("count", 0))


def _increment_count():
    today = date.today().isoformat()
    s = _load_state()
    if s.get("date") != today:
        s = {"date": today, "count": 0}
    s["count"] = int(s.get("count", 0)) + 1
    _save_state(s)


def _load_history() -> set:
    if os.path.exists(BREAKOUT_HISTORY_FILE):
        try:
            with open(BREAKOUT_HISTORY_FILE, "r") as f:
                return set(json.load(f))
        except (json.JSONDecodeError, OSError):
            pass
    return set()


def _save_history(s: set):
    with open(BREAKOUT_HISTORY_FILE, "w") as f:
        json.dump(list(s)[-300:], f)


def _detect_breakout_topic() -> dict:
    """Scrape niche search 'live' tab and look for a single tweet with
    serious velocity. Returns {'text', 'url', 'likes', 'query'} or None.
    """
    queries = random.sample(BREAKOUT_QUERIES, k=min(3, len(BREAKOUT_QUERIES)))
    candidates = []
    for q in queries:
        try:
            tweets = scrape_x_search(q, max_tweets=15, tab="top")
        except Exception:
            log.info(f"[BREAKOUT] Search failed for {q!r}:")
            traceback.print_exc()
            continue
        for t in tweets or []:
            likes = int(t.get("likes") or 0)
            if likes < MIN_LIKES_TO_CONSIDER:
                continue
            candidates.append({
                "url": t.get("url") or "",
                "text": (t.get("text") or "").strip(),
                "likes": likes,
                "query": q,
                "author": (t.get("author") or "").lstrip("@"),
            })

    if not candidates:
        return None

    # Sort by likes desc and pick the strongest signal.
    candidates.sort(key=lambda c: c["likes"], reverse=True)
    top = candidates[0]
    if top["likes"] < HIGH_VELOCITY_LIKES:
        log.info(
            f"[BREAKOUT] Top candidate only {top['likes']} likes "
            f"(< {HIGH_VELOCITY_LIKES}). No breakout right now."
        )
        return None
    return top


def run_breakout_cycle():
    """Detect a viral breaking topic, post a fast English hot take on it."""
    from .config import get_live_cap
    cap = get_live_cap("MAX_BREAKOUTS_PER_DAY", MAX_BREAKOUTS_PER_DAY)
    if _today_count() >= cap:
        log.info(f"[BREAKOUT] Daily cap reached ({cap}). Skipping.")
        return
    # Skip if X is suppressing us right now — chasing trends while
    # shadowbanned just looks like spam.
    try:
        from .suppression_watch_bot import is_paused
        if is_paused():
            log.info("[BREAKOUT] Suppression cooldown active — skipping cycle.")
            return
    except Exception:
        pass

    history = _load_history()

    topic = _detect_breakout_topic()
    if not topic:
        return
    if topic["url"] in history:
        log.info(f"[BREAKOUT] Already breakout-posted on {topic['url']}; skipping.")
        return

    log.info(
        f"[BREAKOUT] Velocity hit: {topic['likes']} likes on @{topic['author']} "
        f"({topic['query']}) — generating FR take."
    )

    trend_context = (
        f"@{topic['author']} ({topic['likes']} likes, query '{topic['query']}'):\n"
        f"\"{topic['text'][:400]}\""
    )

    from . import lang_mode
    lang = lang_mode.pick_content_lang()
    performance_section = personality_store.hard_rules_block()
    bot_self = personality_store.render_bot_self(lang=lang)
    if bot_self:
        performance_section = bot_self + "\n\n" + performance_section
    core = personality_store.render_core_identity(lang=lang)
    if core:
        performance_section = core + "\n\n" + performance_section
    # External-signal injection — HN + Reddit pulse for "trending NOW".
    try:
        from . import hn_signal_bot
        ext = hn_signal_bot.render_signal_block(max_items=6)
        if ext:
            performance_section = ext + "\n\n" + performance_section
    except Exception:
        pass
    prompt = BREAKOUT_PROMPT.format(
        trend_context=trend_context[:1500],
        today_date=datetime.now().strftime("%Y-%m-%d"),
        performance_section=performance_section,
        lang_directive=lang_mode.lang_directive(lang),
    )
    log.info(f"[BREAKOUT] Generating in lang={lang}...")

    result = run_llm(
        prompt,
        NEWS_MODEL,
        label="BREAKOUT",
        # No WebSearch — speed > research, we already have the source.
    )
    if result.returncode != 0:
        log.info(f"[BREAKOUT] LLM failed: {result.stderr[:200]}")
        return

    text = unwrap_text(result.stdout).strip()
    text = strip_agent_preamble(text)
    if not text or text.upper().startswith("SKIP"):
        log.info("[BREAKOUT] Agent returned SKIP / empty.")
        return
    text = humanize(text)
    if len(text) < 20 or len(text) > 280:
        log.info(f"[BREAKOUT] Output length out of bounds ({len(text)}); skipping.")
        return

    # Respect-list defense: never ship content that names a protected handle.
    from . import respect_list
    cleaned, reason = respect_list.scrub_text_or_skip(text)
    if cleaned is None:
        log.info(f"[BREAKOUT] Refused — {reason}: {text[:120]!r}")
        return
    text = cleaned
    # Also: don't pile on the protected author themselves.
    if respect_list.is_protected(topic.get("author", "")):
        log.info(f"[BREAKOUT] Topic author @{topic.get('author')!r} is on respect list; skipping breakout post.")
        return

    # Lock URL in BEFORE posting so a crash can't double-fire.
    history.add(topic["url"])
    _save_history(history)

    log.info(f"[BREAKOUT] Posting: {text!r}")
    try:
        post_tweet(text)
        _increment_count()
        time.sleep(random.randint(3, 6))
        log.info(f"[BREAKOUT] DONE. Today's count: {_today_count()}/{MAX_BREAKOUTS_PER_DAY}")
    except Exception:
        log.info("[BREAKOUT] post_tweet failed:")
        traceback.print_exc()


def safe_run_breakout_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    from . import health
    try:
        run_breakout_cycle()
        health.record_success("breakout")
    except Exception:
        log.info("[BREAKOUT] Error during breakout cycle:")
        traceback.print_exc()
        health.record_failure("breakout")

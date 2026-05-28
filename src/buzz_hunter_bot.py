"""Buzz hunter — daily "🔥 Trouvaille de la semaine" tweet.

Goal: hunt the FR/EN web for the weirdest, most-overlooked, most-buzz-
worthy AI/crypto/exploit story of the day and post ONE punchy tweet
about it. Different brand surface from Décodes (shorter, link-led,
exploit-flavor). Inspired by viral moments like the McDonald's-app
LLM-jailbreak — those tweets blow up because they're unexpected,
concrete, and verifiable.

Sources scraped per cycle:
  - HN front page (already mined by external_signal but we want the
    WEIRD ones, not the headline ones)
  - r/MachineLearning, r/netsec, r/ChatGPT, r/LocalLLaMA top of day
  - GitHub trending (Python/AI)
  - Show HN posts

Selection criteria:
  - "Weird" markers in title: exploit, hack, jailbreak, leak, bug,
    bypass, vulnerability, hidden, accidentally, free, prompt injection
  - Score-floor: HN ≥80 pts, Reddit ≥200 upvotes
  - NOT already covered by mainstream FR press (rough heuristic: title
    not in dedup state)

Output format (deliberately not a Décode — distinct surface):
  🔥 Trouvaille de la semaine

  {1-line punchy hook on the story — chiffre or named entity in first 6 words}

  {1-line context + the "wait, what?" angle}

  {URL}

Schedule: hourly check, ships once per day in 9-11h Paris window.
"""
import html
import json
import os
import random
import re
import traceback
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime
from zoneinfo import ZoneInfo
from typing import Optional

from .config import _PROJECT_ROOT, REPLY_MODEL
from .logger import log
from .llm_client import run_llm, unwrap_text
from .twitter_client import post_tweet
from .humanizer import humanize
from .engagement_log import log_post

STATE_FILE = os.path.join(_PROJECT_ROOT, "buzz_hunter_state.json")
SEEN_FILE = os.path.join(_PROJECT_ROOT, "buzz_hunter_seen.json")

# Markers that signal a story is WEIRD / exploit-flavored / buzz-worthy
WEIRD_MARKERS = (
    "exploit", "hack", "jailbreak", "bypass", "vulnerability", "leak",
    "leaked", "stolen", "bug", "flaw", "hidden", "accidentally",
    "free chatgpt", "free claude", "free gpt", "prompt injection",
    "rce", "0-day", "zero-day", "backdoor", "scam", "rug pull",
    "drained", "lost millions", "found", "discovered", "secret",
    "scandal", "exposed", "lawsuit", "fired", "leaked",
)
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)


def _http_get_json(url: str, timeout: int = 8) -> Optional[dict]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception:
        return None


def _hn_top() -> list[dict]:
    """Hacker News top stories ≥80 points."""
    ids = _http_get_json("https://hacker-news.firebaseio.com/v0/topstories.json")
    if not isinstance(ids, list):
        return []
    out = []
    for sid in ids[:40]:
        item = _http_get_json(f"https://hacker-news.firebaseio.com/v0/item/{sid}.json")
        if not item or not isinstance(item, dict):
            continue
        title = item.get("title") or ""
        if not title or item.get("score", 0) < 80:
            continue
        url = item.get("url") or f"https://news.ycombinator.com/item?id={sid}"
        out.append({"src": "HN", "score": int(item.get("score", 0)), "title": title, "url": url})
        if len(out) >= 25:
            break
    return out


def _reddit_top(subreddit: str, min_score: int = 200) -> list[dict]:
    """Reddit top of day for a subreddit."""
    url = f"https://www.reddit.com/r/{subreddit}/top.json?t=day&limit=25"
    data = _http_get_json(url)
    if not isinstance(data, dict):
        return []
    children = (data.get("data") or {}).get("children") or []
    out = []
    for c in children:
        d = (c or {}).get("data") or {}
        score = int(d.get("score") or 0)
        if score < min_score:
            continue
        title = d.get("title") or ""
        if not title:
            continue
        ext = d.get("url_overridden_by_dest") or d.get("url") or ""
        permalink = f"https://www.reddit.com{d.get('permalink', '')}"
        # Prefer external URL when present and non-reddit
        link = ext if ext and "reddit.com" not in ext else permalink
        out.append({"src": f"r/{subreddit}", "score": score, "title": title, "url": link})
    return out


def _looks_weird(title: str) -> bool:
    t = (title or "").lower()
    return any(m in t for m in WEIRD_MARKERS)


def _looks_on_niche(title: str) -> bool:
    """AI / crypto / hacking / security adjacent."""
    t = (title or "").lower()
    return any(k in t for k in (
        "ai", "ia ", "llm", "gpt", "chatgpt", "claude", "gemini", "openai",
        "anthropic", "mistral", "agent", "model", "neural",
        "bitcoin", "btc", "ethereum", "eth", "crypto", "defi", "wallet",
        "stablecoin", "solana", "exchange",
        "datacenter", "gpu", "nvidia", "h100", "h200",
        "security", "exploit", "vulnerability", "rce", "0-day",
        "spacex", "starship", "starlink",
    ))


def _load_seen() -> set:
    if not os.path.exists(SEEN_FILE):
        return set()
    try:
        with open(SEEN_FILE) as f:
            return set(json.load(f) or [])
    except (json.JSONDecodeError, OSError):
        return set()


def _save_seen(s: set) -> None:
    try:
        urls = list(s)[-500:]  # cap
        with open(SEEN_FILE, "w") as f:
            json.dump(urls, f)
    except OSError:
        pass


def _load_state() -> dict:
    if not os.path.exists(STATE_FILE):
        return {"last_posted": None}
    try:
        with open(STATE_FILE) as f:
            return json.load(f) or {}
    except (json.JSONDecodeError, OSError):
        return {"last_posted": None}


def _save_state(s: dict) -> None:
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(s, f, indent=2)
    except OSError:
        pass


def _in_window() -> bool:
    """Weekly viral attempt: Sundays only, around 11 AM EST (= 5 PM Paris).
    Overlap of US morning scroll + EU late afternoon — bilingual prime
    window. User mandate 2026-05-23: "make some buzz every week, don't do
    a lot of try-hard posts but try". One shot per week."""
    now = datetime.now(ZoneInfo("America/New_York"))
    # Sunday weekday=6, US morning prime
    return now.weekday() == 6 and 11 <= now.hour < 14


PROMPT = """You are @CryptoAIDecode. It's the weekly buzz attempt — ONE
tweet that can go viral. Different format from The Decode. Bold,
contrarian, screenshot-worthy. On this weird/exploit/leak/hack story:

TITLE: {title}
SOURCE: {src} (score {score})
URL: {url}

OUTPUT — exactly this format:

🔥 Find of the week

{{1 punchy hook line in ENGLISH — a number or proper noun in the first 6
words, brutal verb, "wait what" tone. 70-130 chars}}

{{1 context line + the angle that bites. 80-150 chars. A global cultural
ref (SEC filing, a16z, CNBC, 401k, LinkedIn) only if it lands.}}

{url}

RULES:
- 100% English. NO French words, NO French cultural anchors (no Bercy,
  RER B, syndicat) — they read as gibberish to a global audience.
- Tone: deadpan, dry, half-curious half-cynical. No "Incredible" / "Insane".
- No decorative emoji except the 🔥 in the header.
- No hashtags, no em dash (—). Simple hyphens.
- If the topic is off scope (not AI/crypto/exploit/security/space) → SKIP.
- If you can't find a sharp angle → SKIP.

Output: the tweet, nothing else."""


def _pick_story() -> Optional[dict]:
    """Hunt the day's weirdest on-niche story."""
    seen = _load_seen()
    candidates = []
    try:
        candidates.extend(_hn_top())
    except Exception:
        pass
    for sub in ("MachineLearning", "netsec", "ChatGPT", "LocalLLaMA", "CryptoCurrency"):
        try:
            candidates.extend(_reddit_top(sub, min_score=200))
        except Exception:
            pass
    if not candidates:
        return None
    # Filter: not seen + on-niche + weird-ish
    fresh = [c for c in candidates if c["url"] not in seen and _looks_on_niche(c["title"])]
    if not fresh:
        return None
    # Prefer weird-marker matches first
    weird = [c for c in fresh if _looks_weird(c["title"])]
    pool = weird if weird else fresh
    # Sort by score desc and pick top 5, then random among them for variety
    pool.sort(key=lambda c: c["score"], reverse=True)
    picks = pool[:5]
    return random.choice(picks) if picks else None


def run_buzz_hunter_cycle() -> None:
    if not _in_window():
        return  # off-hours, quiet check
    state = _load_state()
    today = date.today().isoformat()
    if state.get("last_posted") == today:
        log.info("[BUZZ] Already posted today — skipping.")
        return

    story = _pick_story()
    if not story:
        log.info("[BUZZ] No qualifying weird story found this cycle.")
        return

    log.info(f"[BUZZ] Selected: {story['src']} ({story['score']} pts) — {story['title'][:120]}")
    prompt = PROMPT.format(**story)
    r = run_llm(prompt, REPLY_MODEL, label="BUZZ_HUNTER")
    if r.returncode != 0:
        log.info(f"[BUZZ] LLM rc={r.returncode}: {r.stderr[:200]}")
        return
    text = unwrap_text(r.stdout).strip()
    if not text or text.upper().startswith("SKIP"):
        log.info("[BUZZ] LLM returned SKIP / empty.")
        return
    text = humanize(text)
    if "🔥 Trouvaille" not in text:
        text = "🔥 Trouvaille de la semaine\n\n" + text
    if len(text) > 280:
        log.info(f"[BUZZ] over-length ({len(text)} chars) — refusing.")
        return

    log.info(f"[BUZZ] Posting ({len(text)} chars): {text[:200]}")
    post_tweet(text)
    try:
        log_post(text, pattern_id="BUZZ_HUNTER")
    except Exception:
        pass
    seen = _load_seen()
    seen.add(story["url"])
    _save_seen(seen)
    state["last_posted"] = today
    state["last_story_url"] = story["url"]
    _save_state(state)


def safe_run_buzz_hunter_cycle() -> None:
    try:
        run_buzz_hunter_cycle()
    except Exception:
        log.info("[BUZZ] outer error:")
        traceback.print_exc()

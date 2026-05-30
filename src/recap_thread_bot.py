"""Sunday recap thread — "Les Décodes de la semaine".

Every Sunday around 11h Paris, post a 5-7 tweet thread that recaps
the week's best Décodes by engagement. Goal:
  - Reminds existing followers what they got this week
  - First-time profile visitors land on a "summary of value delivered"
    that converts to follow more than any single Décode would
  - Recap threads themselves often go viral on FR Twitter

Strategy:
  - Scrape our own profile for the last ~20 posts.
  - Filter to Décodes (header contains "Le Décode") in the last 7d.
  - Rank by likes; take top 5-6.
  - Generate the recap thread head + per-decode bullet via Claude.
  - Post as a proper X thread (head tweet → reply with bullet 1 → etc).
  - Idempotent: state file ensures one thread per Sunday.

Schedule: hourly, ships only on Sunday between 10-13h Paris (4-7h EST).
"""
import json
import os
import re
import traceback
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Optional

from .config import _PROJECT_ROOT, BOT_HANDLE, REPLY_MODEL
from .logger import log
from .llm_client import run_llm, unwrap_text
from .twitter_client import post_thread, scrape_profile_tweets
from .humanizer import humanize
from .engagement_log import log_post

STATE_FILE = os.path.join(_PROJECT_ROOT, "recap_thread_state.json")


def _load_state() -> dict:
    if not os.path.exists(STATE_FILE):
        return {"last_sunday": None}
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"last_sunday": None}


def _save_state(s: dict) -> None:
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(s, f, indent=2)
    except OSError:
        pass


def _is_recap_window_now() -> bool:
    """True only on Sunday between 10h and 13h Paris."""
    now = datetime.now(ZoneInfo("Europe/Paris"))
    return now.weekday() == 6 and 10 <= now.hour < 13


def _this_sunday_key() -> str:
    """ISO date of this Sunday (Paris) for idempotency."""
    return datetime.now(ZoneInfo("Europe/Paris")).date().isoformat()


def _recent_decodes() -> list:
    """Scrape our profile and return Décodes from the last 7 days."""
    try:
        tweets = scrape_profile_tweets(BOT_HANDLE, max_tweets=30)
    except Exception:
        log.info("[RECAP] profile scrape failed:")
        traceback.print_exc()
        return []
    own = BOT_HANDLE.lower().lstrip("@")
    cutoff_days = 7
    decodes = []
    for t in tweets or []:
        author = (t.get("author") or "").lower().lstrip("@")
        if author and author != own:
            continue
        text = (t.get("text") or "").strip()
        if not text:
            continue
        # Match either "Le Décode" or "The Decode" header
        if not re.search(r"(?:Le Décode|The Decode)\s*#?\s*\d+", text, re.IGNORECASE):
            continue
        url = t.get("url") or ""
        if not url:
            continue
        decodes.append({
            "url": url,
            "text": text,
            "likes": int(t.get("likes") or 0),
            "replies": int(t.get("replies") or 0),
        })
        if len(decodes) >= 12:
            break
    return decodes


def _top_decodes(items: list, k: int = 5) -> list:
    items = sorted(items, key=lambda r: (r["likes"], r["replies"]), reverse=True)
    return items[:k]


THREAD_PROMPT = """You are @AISpaceDecoder. You will write ONE English recap thread
of the week's Decodes. Here are the 5-6 best Decodes (by likes) this week:

{decode_list}

OUTPUT — an X thread of {n_tweets} tweets, each tweet separated by "---" on its
own line. NO TEXT BEFORE OR AFTER the thread, just the tweets separated by ---.

TWEET 1 (the head — a hook that makes people scroll / click):
  📅 The {n_decodes} Decodes that defined the week.

  AI, crypto, infrastructure. A no-bullshit read.

  Thread 👇

TWEET 2 to TWEET N (one per Decode, ordered best to worst):
  For each Decode:
  - Mention ITS number (#N)
  - Summarize its angle in 1 biting sentence (10-20 words)
  - Add 1 sentence that makes people WANT to click for the full Decode
  - Include the original Decode URL (URLs are provided in the list).

  Example format for 1 thread tweet:
    #57 — AI. OpenAI raises $200B for GPUs that expire in 18 months.

    The real bet: build the private grid that turns the public one into a backup.

    https://x.com/AISpaceDecoder/status/...

LAST TWEET (the close — invite to follow + tease next week):
  Liked this? Next week, 6 new Decodes.

  AI, crypto, datacenters, mining. Monday to Sunday.

  Follow so you don't miss them.

RULES:
- Each tweet ≤ 270 characters.
- No em dashes (—). Simple hyphens or commas.
- Lean on 1 global cultural ref per tweet when relevant (10-K footnote, Fed
  dot plot, CNBC, 401k). NO French anchors (RER B, Bercy) — global audience.
- 100% English.
- No decorative emoji except 📅 in tweet 1 and 👇 in the head.
- Output: just the tweets separated by "---", nothing else.
"""


def _build_thread_via_llm(decodes: list) -> Optional[list[str]]:
    """Generate the recap thread tweets via Claude."""
    if len(decodes) < 3:
        log.info(f"[RECAP] only {len(decodes)} Décodes — not enough for a recap.")
        return None
    # Format the decode list compactly for the prompt.
    decode_list = "\n\n".join(
        f"Décode (likes={d['likes']}, replies={d['replies']}):\n"
        f"URL: {d['url']}\n"
        f"Body: {d['text'][:400]}"
        for d in decodes
    )
    n_decodes = len(decodes)
    n_tweets = 2 + n_decodes  # head + decodes + close
    prompt = THREAD_PROMPT.format(
        decode_list=decode_list,
        n_decodes=n_decodes,
        n_tweets=n_tweets,
    )
    r = run_llm(prompt, REPLY_MODEL, label="RECAP_THREAD")
    if r.returncode != 0:
        log.info(f"[RECAP] LLM failed rc={r.returncode}: {r.stderr[:200]}")
        return None
    raw = unwrap_text(r.stdout).strip()
    if not raw or raw.upper().startswith("SKIP"):
        log.info("[RECAP] LLM returned SKIP/empty.")
        return None
    # Split on --- lines
    parts = re.split(r"\n\s*---+\s*\n", raw)
    parts = [humanize(p.strip()) for p in parts if p.strip()]
    parts = [p for p in parts if p and len(p) <= 280]
    if len(parts) < 3:
        log.info(f"[RECAP] parser produced only {len(parts)} tweets — too few.")
        return None
    return parts


def run_recap_thread_cycle() -> None:
    if not _is_recap_window_now():
        # Quiet — fires hourly, only ships once on Sunday 10-13h Paris.
        return
    state = _load_state()
    key = _this_sunday_key()
    if state.get("last_sunday") == key:
        log.info("[RECAP] Already posted this Sunday — skipping.")
        return

    log.info("[RECAP] Sunday window open. Building weekly recap thread...")
    decodes = _recent_decodes()
    if not decodes:
        log.info("[RECAP] No Décodes found this week. Skipping.")
        return
    top = _top_decodes(decodes, k=min(6, len(decodes)))
    log.info(f"[RECAP] {len(top)} Décodes selected (top likes: {top[0]['likes']})")

    tweets = _build_thread_via_llm(top)
    if not tweets:
        return
    log.info(f"[RECAP] Thread built: {len(tweets)} tweets. Posting...")
    try:
        post_thread(tweets)
        try:
            log_post(tweets[0], pattern_id="RECAP_THREAD")
        except Exception:
            pass
        state["last_sunday"] = key
        _save_state(state)
        log.info("[RECAP] Weekly recap thread posted ✓")
    except Exception:
        log.info("[RECAP] thread post raised:")
        traceback.print_exc()


def safe_run_recap_thread_cycle() -> None:
    try:
        run_recap_thread_cycle()
    except Exception:
        log.info("[RECAP] outer error:")
        traceback.print_exc()

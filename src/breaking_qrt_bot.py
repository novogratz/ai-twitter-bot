"""Breaking-news instant QRT — ride the day's biggest story WHILE it breaks.

The 4x/day hot_quote slots can lag a mega story by up to 4 hours; at 1.3K
followers the QRT surface only 100x-es inside the story's first 1-2 hours
(operator 2026-06-07: "anything else to be more viral?" → "DO IT").

Every cycle (10 min): read external_signal.json (refreshed every ~5 min).
If the top niche item SPIKES — score >= BREAKING_QRT_MIN_SCORE AND >=
BREAKING_QRT_SPIKE_RATIO x the second-best item — fire one hot_quote-style
QRT immediately instead of waiting for the next slot cron.

Reuses hot_quote_bot's whole pipeline (_load_signal_items niche filter,
_search_best_tweet viral hunt + QUOTED_FILE dedup, _generate_quote persona
take) and the quote_tweet chokepoint (daily cap, jittered spacing, dedup,
content_guard, 48h rule) — this bot adds ZERO new write paths.

State (breaking_qrt_state.json): per-story dedup (normalized title key) so
one breaking story = one QRT ever, plus a daily fire cap. A chokepoint skip
does NOT consume the story (the hot_quote slot-burn lesson) — the next
cycle retries while the story is still hot.
"""
import json
import os
import re
import traceback
from datetime import date, datetime

from .config import _PROJECT_ROOT
from .logger import log
from .twitter_client import quote_tweet
from .engagement_log import log_reply
from .action_guard import can_post, QUOTE
from .hot_quote_bot import (
    _load_signal_items,
    _search_best_tweet,
    _generate_quote,
    _mark_quoted,
    _topic_hint,
)

STATE_FILE = os.path.join(_PROJECT_ROOT, "breaking_qrt_state.json")


def _min_score() -> int:
    return int(os.environ.get("BREAKING_QRT_MIN_SCORE", "15"))


def _spike_ratio() -> float:
    return float(os.environ.get("BREAKING_QRT_SPIKE_RATIO", "3.0"))


def _max_per_day() -> int:
    return int(os.environ.get("BREAKING_QRT_MAX_PER_DAY", "6"))


def _story_key(title: str) -> str:
    """Normalized dedup key: lowercase content words, order-insensitive."""
    words = re.findall(r"[a-z0-9$]{3,}", (title or "").lower())
    return "-".join(sorted(set(words))[:12])


def _load_state() -> dict:
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(state: dict) -> None:
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def pick_breaking_item(items: list[dict], state: dict) -> dict | None:
    """Pure spike detector — returns the item to QRT now, or None.

    Fires only when the top item dominates: score >= floor AND >= ratio x
    the runner-up (a flat signal pool means nothing is 'breaking').
    Already-fired stories (per-story dedup) never fire twice.
    """
    fired = set(state.get("fired_stories", []))
    fresh = [it for it in items if _story_key(it.get("title", "")) not in fired]
    if not fresh:
        return None
    top = fresh[0]
    top_score = int(top.get("score") or 0)
    if top_score < _min_score():
        return None
    runner_up = int(fresh[1].get("score") or 0) if len(fresh) > 1 else 0
    if runner_up > 0 and top_score < _spike_ratio() * runner_up:
        return None
    return top


def run_breaking_qrt_cycle() -> None:
    state = _load_state()
    today = date.today().isoformat()
    if state.get("day") != today:
        state = {"day": today, "fired_today": 0,
                 "fired_stories": state.get("fired_stories", [])[-200:]}

    if state.get("fired_today", 0) >= _max_per_day():
        return  # daily breaking budget spent — the slot crons still run

    # Cheap precheck BEFORE any Safari/LLM work (the hot_quote lesson):
    # spacing/cap blocked → just wait for the next 10-min fire.
    ok, why = can_post(QUOTE)
    if not ok:
        log.info(f"[BREAKING_QRT] Quote blocked ({why}) — next cycle retries.")
        return

    items = _load_signal_items()
    item = pick_breaking_item(items, state)
    if not item:
        return

    topic = item.get("title", "")
    log.info(f"[BREAKING_QRT] 🚨 Signal spike (score {item.get('score')}): {topic[:80]}")

    tweet = _search_best_tweet(topic)
    if not tweet:
        log.info("[BREAKING_QRT] No viable viral tweet yet — story stays armed for next cycle.")
        return

    author = tweet.get("author", "someone")
    url = tweet.get("url", "")
    quote = _generate_quote(author, tweet.get("text", ""), _topic_hint(item))
    if not quote:
        log.info("[BREAKING_QRT] LLM skipped — story stays armed.")
        return

    log.info(f"[BREAKING_QRT] Quote: {quote[:120]}")
    try:
        posted = quote_tweet(url, quote)
    except Exception:
        _mark_quoted(url)  # unknown state — never double-post
        log.info("[BREAKING_QRT] Post failed:")
        traceback.print_exc()
        return

    if not posted:
        # Chokepoint skip — do NOT consume the story (slot-burn lesson).
        log.info("[BREAKING_QRT] Chokepoint skipped — story stays armed for next cycle.")
        return

    _mark_quoted(url)
    try:
        log_reply(url, quote, action_type="quote", source=f"BREAKING_QRT/{author}")
    except Exception:
        pass
    state["fired_today"] = state.get("fired_today", 0) + 1
    state.setdefault("fired_stories", []).append(_story_key(topic))
    state["last_fire"] = datetime.now().isoformat()
    _save_state(state)
    log.info(f"[BREAKING_QRT] Posted ({state['fired_today']}/{_max_per_day()} today).")


def safe_run_breaking_qrt_cycle() -> None:
    from . import health
    try:
        run_breaking_qrt_cycle()
        health.record_success()
    except Exception:
        log.info("[BREAKING_QRT] Cycle crashed:")
        traceback.print_exc()
        health.record_failure()

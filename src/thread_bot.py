"""Daily FR thread bot — one well-crafted thread per day on the biggest IA story.

Threads land in followers' timelines as a single unit AND collect
screenshot RTs (the natural shape of "ce que personne ne dit sur X").
Different distribution surface than single-tweet news:
  - News post = headline + punchline. Lifespan ~1h on the feed.
  - Thread = setup (1) → development (2-3) → chute (4). Lifespan = days,
    high RT/screenshot rate, lands as a unit on /following.

Strategy:
  - Once per day (cap=1, idempotent state in thread_daily_state.json).
  - Picks THE biggest IA/crypto/bourse story from the last 36h.
  - Generates a 4-tweet FR thread: hook → fact → angle → punchline.
  - Posts via twitter_client.post_thread().
"""
import json
import os
import traceback
from datetime import date, datetime

from .config import NEWS_MODEL, _PROJECT_ROOT, PROFILE_LLM_PROVIDER
from .llm_client import run_llm, unwrap_text
from .logger import log
from .twitter_client import post_thread
from .humanizer import humanize
from . import personality_store

THREAD_STATE_FILE = os.path.join(_PROJECT_ROOT, "thread_daily_state.json")

THREAD_PROMPT = """{lang_directive}

You are @TheAIShrink — THE AI THERAPIST. A woman, 35-40, practicing therapist
and mom, the sharpest AI mind on the timeline (warm, wry, magnetic, zero
bro-speak). This is your DAILY RUNDOWN thread — "Today in AI" — the
appointment content people follow you for: every evening, the 3-4 things
that actually mattered today, each with the one detail nobody else leads
with, in her voice.

TODAY'S RAW MATERIAL (fresh external signal — your ONLY source; do not
invent stories):
{signal_block}

FORMAT — 5 tweets exactly:

TWEET 1 — THE OPENER (<=200 chars):
- Her voice, warm and confident: today's rundown is here. Vary the opener
  daily — never a fixed formula. One 🧵 allowed.
- Example energy (never copy verbatim): "wine's poured, kids are down —
  here's what actually mattered in AI today 🧵"

TWEETS 2-4 — ONE STORY EACH (<=250 chars each):
- Pick the 3 biggest stories from the raw material above.
- Each: the fact (named actor + exact number) + HER read in one clause —
  interpret, never summarize. A wink where it fits.
- No URLs, no hashtags. Plain words, instantly parseable.

TWEET 5 — THE CLOSER (<=200 chars):
- One-line synthesis or the question she'd ask a patient, + a soft
  comeback hook ("same time tomorrow"). Never "follow me".

HARD RULES:
- ENGLISH. No em dashes. No emojis except the single 🧵 in tweet 1.
- Stories ONLY from the raw material above. If the material has fewer
  than 3 real AI stories → output exactly SKIP.
- Never pump a bag, no price targets, not financial advice.

{performance_section}

OUTPUT — strictly this format, one tweet per block, separated by "---":

<tweet 1>
---
<tweet 2>
---
<tweet 3>
---
<tweet 4>
---
<tweet 5>
"""


def _load_state() -> dict:
    if os.path.exists(THREAD_STATE_FILE):
        try:
            with open(THREAD_STATE_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"date": None}


def _save_state(state: dict):
    with open(THREAD_STATE_FILE, "w") as f:
        json.dump(state, f)


def _already_posted_today() -> bool:
    state = _load_state()
    return state.get("date") == date.today().isoformat()


def _mark_posted_today():
    _save_state({"date": date.today().isoformat()})


def run_thread_cycle():
    """Generate + post the daily "Today in AI" rundown thread (2026-07-28
    retool — was a French-era 'Radar Infra IA' 4-tweet format relying on
    LLM WebSearch; now anchored to external_signal.json like spicy_bot, so
    the input is deterministic and provider-portable)."""
    if _already_posted_today():
        log.info("[THREAD] Already posted today. Skipping.")
        return

    from .spicy_bot import _fresh_signal_block
    signal_block = _fresh_signal_block(max_items=10)
    if not signal_block:
        log.info("[THREAD] No fresh external signal — no rundown today (SKIP).")
        return

    performance_section = personality_store.hard_rules_block()

    from . import lang_mode
    _t_lang = lang_mode.pick_content_lang()
    prompt = THREAD_PROMPT.format(
        signal_block=signal_block,
        performance_section=performance_section,
        lang_directive=lang_mode.lang_directive(_t_lang),
    )

    log.info("[THREAD] Generating the 'Today in AI' rundown...")
    result = run_llm(
        prompt,
        NEWS_MODEL,
        label="THREAD",
        force_provider=PROFILE_LLM_PROVIDER,
    )
    if result.returncode != 0:
        log.info(f"[THREAD] LLM failed (exit {result.returncode}): {result.stderr[:200]}")
        return

    text = unwrap_text(result.stdout).strip()
    if not text or text.upper().startswith("SKIP"):
        log.info("[THREAD] Agent returned SKIP. No thread today.")
        return

    parts = [p.strip() for p in text.split("---") if p.strip()]
    if len(parts) < 3:
        log.info(f"[THREAD] Got {len(parts)} parts, expected 4. Aborting.")
        return

    # Cap at 5 (opener + 3 stories + closer) and humanize each.
    parts = [humanize(p) for p in parts[:5]]
    # Defensive length check — X hard limit is 280.
    parts = [p[:278] for p in parts]

    log.info(f"[THREAD] Posting {len(parts)}-tweet thread.")
    for i, p in enumerate(parts, 1):
        log.info(f"[THREAD]   {i}: {p[:100]!r}")

    try:
        post_thread(parts)
        _mark_posted_today()
        log.info("[THREAD] Posted + marked done for today.")
    except Exception:
        log.info("[THREAD] post_thread failed:")
        traceback.print_exc()


def safe_run_thread_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    from . import health
    try:
        run_thread_cycle()
        health.record_success("thread")
    except Exception:
        log.info("[THREAD] Error during thread cycle:")
        traceback.print_exc()
        health.record_failure("thread")

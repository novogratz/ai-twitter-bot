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

from .config import NEWS_MODEL, _PROJECT_ROOT
from .llm_client import run_llm, unwrap_text
from .logger import log
from .twitter_client import post_thread
from .humanizer import humanize
from . import personality_store

THREAD_STATE_FILE = os.path.join(_PROJECT_ROOT, "thread_daily_state.json")

THREAD_PROMPT = """{lang_directive}

You are writing ONE X thread (5 to 8 tweets) that explains an AI topic better
than journalists, faster than newsletters, easier than researchers. Threads
are the bookmark surface — X rewards value that's worth saving.

PICK ONE AI topic (choose the one you can make clearest): how a new model/agent
actually works, what a concept means (MCP, RAG, reasoning models, RL, agents),
a prediction (jobs AI automates first, which startups win, what AI looks like
in 5 years), or a breakdown of a big AI story.

FORMAT (5 to 8 tweets, each under 280 chars, each stands alone):

TWEET 1 — HOOK:
- A confident, curiosity-creating claim that promises the payoff. Easy words.
- "Most people still don't understand what's coming with AI agents. Here's the
  simple version."
- No date, no "Today...", no "Breaking:". No emojis.

TWEETS 2 to N-1 — THE EXPLANATION:
- One clear idea per tweet, in plain English. Each could stand alone.
- Make it make sense: analogy, concrete example, or the one detail that matters.
- No jargon, no buzzwords unless you explain them.

LAST TWEET — THE LINE:
- The one sentence that makes someone follow. Confident, clear, under 20 words.
- Optionally invite discussion ("What happens next?"). No link.

HARD RULES:
- Language per the directive at the top of the prompt.
- AI ONLY. No em dashes (—). NO emojis. NO hashtags. NO links. No "According to...".
- Easy language, optimistic, never corporate, never cringe. Never invent facts.
- If you cannot make it genuinely clear and useful → output exactly the word SKIP.

{performance_section}

OUTPUT — strictly this format, nothing else. One tweet per block, separated by "---":

<tweet 1 hook>
---
<tweet 2>
---
<tweet 3>
---
<... up to 8 tweets, last one is THE LINE>
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
    """Generate + post one FR thread per day on the biggest IA story."""
    if _already_posted_today():
        log.info("[THREAD] Already posted today. Skipping.")
        return

    today_date = datetime.now().strftime("%Y-%m-%d")
    performance_section = personality_store.hard_rules_block()

    from . import lang_mode
    _t_lang = lang_mode.pick_content_lang()
    log.info(f"[THREAD] Generating in lang={_t_lang}")
    prompt = THREAD_PROMPT.format(
        today_date=today_date,
        performance_section=performance_section,
        lang_directive=lang_mode.lang_directive(_t_lang),
    )

    log.info("[THREAD] Generating daily FR thread...")
    result = run_llm(
        prompt,
        NEWS_MODEL,
        label="THREAD",
        allowed_tools=["WebSearch"],
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
        log.info(f"[THREAD] Got {len(parts)} parts, expected 5-8. Aborting.")
        return

    # Cap at 8 (spec: 5-8 tweets) and humanize each.
    parts = [humanize(p) for p in parts[:8]]
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

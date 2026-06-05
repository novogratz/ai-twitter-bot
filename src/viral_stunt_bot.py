"""Viral stunt bot — occasional creative SUPERVIRAL-format posts.

Operator mandate 2026-06-05: "from time to time, try to create a superviral
post... like the people that say 'I tested the Domino's pizza LLM support and
I got a free ChatGPT/Claude session' — but don't overabuse it."

The genre: first-person, concrete, screenshot-worthy AI-stunt comedy. The
absurdity must be obvious enough to read as a BIT (the audience is in on the
joke) — never a fabricated claim presented as literal news. Concreteness is
what sells it: a named (real or plausible) product, an exact number, a
deadpan consequence.

Anti-overuse design:
  - hard daily cap (MAX_VIRAL_STUNTS_PER_DAY, default 2)
  - per-cycle fire probability (VIRAL_STUNT_FIRE_PROB, default 0.35) so the
    cadence is irregular and never feels scheduled
  - SKIP-by-default prompt: if the draft isn't a 9/10 laugh, nothing posts
  - goes through post_tweet → dedup v2 + caps + spacing + hard-rule scrubs
"""
import json
import os
import random
import time
import traceback
from datetime import date

from .config import _PROJECT_ROOT, HOTAKE_MODEL
from .llm_client import run_llm, unwrap_text
from .logger import log
from .twitter_client import post_tweet
from .humanizer import humanize, strip_agent_preamble

STUNT_STATE_FILE = os.path.join(_PROJECT_ROOT, "viral_stunt_state.json")
MAX_VIRAL_STUNTS_PER_DAY = int(os.environ.get("MAX_VIRAL_STUNTS_PER_DAY", "2"))
VIRAL_STUNT_FIRE_PROB = float(os.environ.get("VIRAL_STUNT_FIRE_PROB", "0.35"))

STUNT_PROMPT = """{lang_directive}

You are writing ONE superviral-format post. The genre that rips on X right
now: first-person AI-stunt comedy. Concrete, deadpan, screenshot-worthy.

Reference vibes (FORM ONLY — never copy or paraphrase these):
- testing a mundane company's new AI support bot and getting an absurdly
  wrong / absurdly generous outcome
- asking an AI assistant a normal question and reporting its unhinged-but-
  plausible answer deadpan
- a fake-mundane "field report" about AI showing up somewhere it shouldn't
  (gym, bakery, parking meter, dentist)
- an exact, oddly specific number that makes the bit land

HARD RULES:
- The absurdity must be obvious enough that readers know it's a BIT. Never
  write something a reader could mistake for real factual news about a real
  company. Comedy, not misinformation.
- First person, deadpan, ZERO "haha/lol", zero emoji, zero hashtag, no URL.
- ≤270 characters. One or two sentences max. The shorter the deadlier.
- Concrete details: a name, a number, a consequence. Vague = dead.
- Stay in the account's world: AI, AI products, chatbots, agents, robots,
  AI-in-everyday-life. The human side is the punchline.
- Tu trolles les SYSTÈMES / produits / trends, jamais une personne nommée.
- Ne jamais cibler le gouvernement américain (Fed, SEC, IRS, etc.).

{performance_section}

THE BAR: would a stranger screenshot this and send it to a friend? If the
draft is not a 9/10 laugh → answer SKIP. SKIP is the default, posting is the
exception.

OUTPUT — strictly the post text, nothing else. No "Here's", no quotes, no
meta-commentary."""


def _load_state() -> dict:
    if os.path.exists(STUNT_STATE_FILE):
        try:
            with open(STUNT_STATE_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {"date": None, "count": 0}


def _today_count() -> int:
    s = _load_state()
    if s.get("date") != date.today().isoformat():
        return 0
    return int(s.get("count", 0))


def _increment_count():
    today = date.today().isoformat()
    s = _load_state()
    if s.get("date") != today:
        s = {"date": today, "count": 0}
    s["count"] = int(s.get("count", 0)) + 1
    with open(STUNT_STATE_FILE, "w") as f:
        json.dump(s, f)


def run_viral_stunt_cycle():
    if _today_count() >= MAX_VIRAL_STUNTS_PER_DAY:
        log.info(f"[STUNT] Daily cap reached ({MAX_VIRAL_STUNTS_PER_DAY}). Skipping.")
        return
    # Irregular cadence — most cycles do nothing, so the surface never feels
    # scheduled (operator: "don't overabuse it").
    if random.random() > VIRAL_STUNT_FIRE_PROB:
        log.info("[STUNT] Dice say not this cycle.")
        return
    try:
        from .suppression_watch_bot import is_paused
        if is_paused():
            log.info("[STUNT] Suppression cooldown active — skipping.")
            return
    except Exception:
        pass

    from . import lang_mode, personality_store
    lang = lang_mode.pick_content_lang()
    perf = personality_store.hard_rules_block()
    core = personality_store.render_core_identity(lang=lang)
    if core:
        perf = core + "\n\n" + perf
    prompt = STUNT_PROMPT.format(
        lang_directive=lang_mode.lang_directive(lang),
        performance_section=perf,
    )

    log.info("[STUNT] Generating superviral-format post...")
    result = run_llm(prompt, HOTAKE_MODEL, label="VIRAL_STUNT")
    if result.returncode != 0:
        log.info(f"[STUNT] LLM failed: {result.stderr[:200]}")
        return

    text = unwrap_text(result.stdout).strip()
    text = strip_agent_preamble(text)
    if not text or text.upper().startswith("SKIP"):
        log.info("[STUNT] Agent returned SKIP / empty.")
        return
    text = humanize(text)
    if len(text) < 30 or len(text) > 280:
        log.info(f"[STUNT] Output length out of bounds ({len(text)}); skipping.")
        return

    from . import respect_list
    cleaned, reason = respect_list.scrub_text_or_skip(text)
    if cleaned is None:
        log.info(f"[STUNT] Refused — {reason}: {text[:120]!r}")
        return
    text = cleaned

    log.info(f"[STUNT] Posting: {text!r}")
    try:
        post_tweet(text)
        _increment_count()
        time.sleep(random.randint(3, 6))
        log.info(f"[STUNT] DONE. Today's count: {_today_count()}/{MAX_VIRAL_STUNTS_PER_DAY}")
    except Exception:
        log.info("[STUNT] post_tweet failed:")
        traceback.print_exc()


def safe_run_viral_stunt_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    from . import health
    try:
        run_viral_stunt_cycle()
        health.record_success("viral_stunt")
    except Exception:
        log.info("[STUNT] Error during viral stunt cycle:")
        traceback.print_exc()
        health.record_failure("viral_stunt")

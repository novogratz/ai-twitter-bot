"""Spicy bot — deliberately polarizing English takes + question bait.

User: 20k followers EOM. Need viral moments. Polarizing takes drive
REPLIES, and replies are the #1 algorithm signal on X. Questions also
drive replies because the platform UI invites them.

Two modes, picked at random per cycle:
  - SPICY: deliberate hot take with a contrarian English position. Stays
    inside hard rules (no illegal, no US-gov troll) but pushes harder
    on private targets (corporate hype, retail traders, influencer
    coaching, OPINIONATED takes on the niche).
  - QUESTION: an open English question on AI / crypto designed to
    trigger replies from followers + lurkers. "Honest question" framing.

NEWS-ANCHORED (2026-06-05 operator mandate): both modes MUST react to a
fresh item from external_signal.json (X feed/search + HN/Reddit pulse,
refreshed every few minutes). Free-form "what's on my mind" takes were
producing duplicated, unanchored musings — the model literally parroted
its own prompt example twice ("Everyone watches GPU supply…"). No fresh
signal on disk → the cycle SKIPS. The take still carries no URL — it
reacts to the news, it doesn't report it.

Cap 6/day total. Posts via post_tweet(). Different from regular news
(no source URL, no impact filter) — these are PURELY for engagement
velocity.
"""
import json
import os
import random
import time
import traceback
from datetime import date, datetime

from .config import _PROJECT_ROOT, BOT_HANDLE, HOTAKE_MODEL, PROFILE_LLM_PROVIDER
from .llm_client import run_llm, unwrap_text
from .logger import log
from .twitter_client import post_tweet
from .humanizer import humanize, strip_agent_preamble

SPICY_STATE_FILE = os.path.join(_PROJECT_ROOT, "spicy_state.json")

MAX_SPICY_PER_DAY = int(os.environ.get("MAX_SPICY_PER_DAY", "12"))


SPICY_PROMPT = """{lang_directive}

Mode: {mode}

{mode_instructions}

{signal_block}

RÈGLES DURES:
- ANCRAGE OBLIGATOIRE: ton tweet RÉAGIT à UNE des news fraîches ci-dessus.
  Nomme l'acteur / le fait / le chiffre concret de la news choisie. Un take
  qui ne cite aucun fait d'aujourd'hui = échec → SKIP.
- Si AUCUNE news ne t'inspire un take/question ≥ 8/10 → réponds SKIP.
- ≤270 caractères.
- ZÉRO emoji. ZÉRO hashtag. ZÉRO em dash (—).
- Pas de "Selon X..." / "Aujourd'hui..." / "Breaking:" / "According to..." / "Today...".
- Tu taquines les IDÉES / TRENDS / SYSTÈMES avec malice, jamais une personne nommée.
- Ne jamais cibler le gouvernement américain (Fed, SEC, IRS, etc.).
- Pas de URL. Pas de source. Ce tweet est PUREMENT un take ou une question.
- Core identity: voix incisive, pas de crypto générique. Ton d'autorité.
- INTERDIT de recopier ou paraphraser un exemple de ce prompt — les exemples
  montrent la FORME, jamais le contenu.

{performance_section}

OUTPUT — strictement le tweet, rien d'autre.
JAMAIS de "Voici", "Le tweet:", "---", ou méta-commentaire."""

SPICY_INSTRUCTIONS = """SPICY MODE — The therapist's contrarian session. Drop an opinion people debate.
- VOICE: you are THE AI THERAPIST — calm, warm, grounded. Your spice is the
  serene contrarian read ("everyone is panicking about X; the chart says
  breathe"), NEVER snark or doom. The take stings because it's TRUE and calm.
- Choisis UNE news fraîche dans la liste ci-dessous où le consensus PANIQUE ou
  s'euphorise. Nomme l'émotion, puis donne le contre-read avec le fait précis.
- C'est OK d'être divisif tant qu'il y a un argument + une vraie réassurance.
- Format préféré: fait concret de la news + émotion du consensus + calm reframe.
- L'audience doit avoir ENVIE de répondre, pas juste de liker.
"""

QUESTION_INSTRUCTIONS = """QUESTION MODE — ask ONE short question people can answer in two words
(2026-06-10 QRT-playbook style: the reply section is the content, you just
open the door).
- Anchor it to ONE fresh item from the signal list below (name the actor or
  the number) OR a this-week market reality everyone's living through.
- The winning shapes: a binary choice with cashtags ("which would you rather
  hold for 10 years: $X or $Y?"), a "do you own it / would you buy it here?"
  gut-check, or "what's the most misunderstood [business/model/trade]? I'll
  start: ..." where you seed the first answer yourself.
- ONE sentence, maybe two. No essay framing, no lecture before the question.
  Casual texture fine (lowercase, "..", one emoji max).
- Scope: AI / AI stocks / crypto / markets through the AI lens.
- A vague question dies; a concrete pick-a-side question farms replies.
"""

# Signal must be fresher than this or the cycle skips (the X-FEED scraper
# rewrites external_signal.json every few minutes when the bot is healthy).
SIGNAL_MAX_AGE_HOURS = float(os.environ.get("SPICY_SIGNAL_MAX_AGE_HOURS", "6"))
SIGNAL_FILE = os.path.join(_PROJECT_ROOT, "external_signal.json")


def _fresh_signal_block(max_items: int = 8) -> str:
    """Render the freshest external-signal items as the mandatory anchor
    list, or '' if the signal file is missing/stale (caller then SKIPs)."""
    try:
        with open(SIGNAL_FILE) as f:
            sig = json.load(f)
        ts = datetime.fromisoformat(sig.get("ts", ""))
        age_h = (datetime.now() - ts).total_seconds() / 3600.0
        if age_h > SIGNAL_MAX_AGE_HOURS:
            return ""
        items = [i for i in sig.get("items", []) if isinstance(i, dict) and i.get("title")]
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return ""
    if not items:
        return ""
    items.sort(key=lambda i: i.get("score", 0) or 0, reverse=True)
    lines = []
    for it in items[:max_items]:
        title = " ".join(str(it["title"]).split())[:180]
        lines.append(f"- {title}")
    return (
        "==================================================\n"
        "NEWS FRAÎCHES (dernières heures — ta SEULE matière première)\n"
        "==================================================\n"
        + "\n".join(lines)
    )


def _load_state() -> dict:
    if os.path.exists(SPICY_STATE_FILE):
        try:
            with open(SPICY_STATE_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {"date": None, "count": 0}


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
        # Preserve the weekly question-bait tally across the daily reset.
        s = {"date": today, "count": 0,
             "question_week": s.get("question_week"),
             "question_count": s.get("question_count", 0)}
    s["count"] = int(s.get("count", 0)) + 1
    with open(SPICY_STATE_FILE, "w") as f:
        json.dump(s, f)


# 2026-06-07 agent spec: reply-bait question posts are capped at 3-4/WEEK
# (they farm replies on our own posts — more than that reads as engagement
# farming). Tracked per ISO week in the same state file.
REPLY_BAIT_PER_WEEK = int(os.environ.get("REPLY_BAIT_PER_WEEK", "4"))


def _current_week() -> str:
    y, w, _ = date.today().isocalendar()
    return f"{y}-W{w:02d}"


def _week_question_count() -> int:
    s = _load_state()
    if s.get("question_week") != _current_week():
        return 0
    return int(s.get("question_count", 0))


def _increment_question_count():
    s = _load_state()
    week = _current_week()
    if s.get("question_week") != week:
        s["question_week"] = week
        s["question_count"] = 0
    s["question_count"] = int(s.get("question_count", 0)) + 1
    with open(SPICY_STATE_FILE, "w") as f:
        json.dump(s, f)


def run_spicy_cycle():
    from .config import get_live_cap
    cap = get_live_cap("MAX_SPICY_PER_DAY", MAX_SPICY_PER_DAY)
    if _today_count() >= cap:
        log.info(f"[SPICY] Daily cap reached ({cap}). Skipping.")
        return
    # Skip if X is suppressing us right now — adding more spammy-looking
    # signals would extend the shadowban.
    try:
        from .suppression_watch_bot import is_paused
        if is_paused():
            log.info("[SPICY] Suppression cooldown active — skipping cycle.")
            return
    except Exception:
        pass

    # News anchor is mandatory (2026-06-05): no fresh signal → no take.
    signal_block = _fresh_signal_block()
    if not signal_block:
        log.info(f"[SPICY] No fresh external signal (≤{SIGNAL_MAX_AGE_HOURS}h) — skipping (no unanchored musings).")
        return

    # 60% spicy, 40% question. Spicy drives more replies but question is
    # more inclusive — mix is healthier than 100% spicy.
    # Reply-bait questions are additionally capped at REPLY_BAIT_PER_WEEK
    # (3-4/week per the 2026-06-07 spec) — over the weekly budget we fall
    # back to SPICY.
    mode = "SPICY" if random.random() < 0.6 else "QUESTION"
    if mode == "QUESTION" and _week_question_count() >= REPLY_BAIT_PER_WEEK:
        log.info(f"[SPICY] Weekly reply-bait budget reached "
                 f"({REPLY_BAIT_PER_WEEK}/week) — falling back to SPICY mode.")
        mode = "SPICY"
    instructions = SPICY_INSTRUCTIONS if mode == "SPICY" else QUESTION_INSTRUCTIONS

    from . import lang_mode, personality_store
    lang = lang_mode.pick_content_lang()
    perf = personality_store.hard_rules_block()
    bot_self = personality_store.render_bot_self(lang=lang)
    if bot_self:
        perf = bot_self + "\n\n" + perf
    core = personality_store.render_core_identity(lang=lang)
    if core:
        perf = core + "\n\n" + perf
    # Measured pillar priority — market_trauma one-liners win 2.3x (2026-06-07).
    try:
        from .pillar_tags import market_trauma_priority_block
        perf = market_trauma_priority_block() + "\n\n" + perf
    except Exception:
        pass
    # Own-wins bank (2026-06-07): show the model what actually SHIPPED on
    # this account so spicy takes iterate proven structures, not guesses.
    try:
        from . import self_winners
        sw = self_winners.render_self_winners_block(sample_size=2)
        if sw:
            perf = sw + "\n\n" + perf
    except Exception:
        pass
    prompt = SPICY_PROMPT.format(
        mode=mode,
        mode_instructions=instructions,
        signal_block=signal_block,
        performance_section=perf,
        lang_directive=lang_mode.lang_directive(lang),
    )

    log.info(f"[SPICY] Generating ({mode}, lang={lang})...")
    result = run_llm(prompt, HOTAKE_MODEL, label=f"SPICY_{mode}", force_provider=PROFILE_LLM_PROVIDER)
    if result.returncode != 0:
        log.info(f"[SPICY] LLM failed: {result.stderr[:200]}")
        return

    text = unwrap_text(result.stdout).strip()
    text = strip_agent_preamble(text)
    if not text or text.upper().startswith("SKIP"):
        log.info("[SPICY] Agent returned SKIP / empty.")
        return
    text = humanize(text)
    if len(text) < 25 or len(text) > 280:
        log.info(f"[SPICY] Output length out of bounds ({len(text)}); skipping.")
        return

    # Respect-list defense: refuse to ship if output names a protected handle.
    from . import respect_list
    cleaned, reason = respect_list.scrub_text_or_skip(text)
    if cleaned is None:
        log.info(f"[SPICY] Refused — {reason}: {text[:120]!r}")
        return
    text = cleaned

    log.info(f"[SPICY] Posting [{mode}]: {text!r}")
    try:
        post_tweet(text)
        _increment_count()
        if mode == "QUESTION":
            _increment_question_count()
        # Log with mode as source so pillar attribution sees reply-bait
        # questions explicitly (QUESTION → reply_bait). spicy posts were
        # previously invisible to the engagement log / ROI loop entirely.
        try:
            from .engagement_log import log_post
            log_post(text, source=mode)
        except Exception:
            pass
        time.sleep(random.randint(3, 6))
        log.info(f"[SPICY] DONE. Today's count: {_today_count()}/{MAX_SPICY_PER_DAY}")
    except Exception:
        log.info("[SPICY] post_tweet failed:")
        traceback.print_exc()


def safe_run_spicy_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    from . import health
    try:
        run_spicy_cycle()
        health.record_success("spicy")
    except Exception:
        log.info("[SPICY] Error during spicy cycle:")
        traceback.print_exc()
        health.record_failure("spicy")

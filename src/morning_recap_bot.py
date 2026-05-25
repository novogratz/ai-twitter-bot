"""Morning recap thread — daily 'what you need to know' English thread.

User pivot 2026-05-09 PM: bot is now a crypto+IA influencer + YouTube
feed. A daily morning recap thread is the strongest "this account
delivers value" signal:
  - Followers see it on their morning scroll → they wait for it daily.
  - It's the perfect raw material for a 5-minute YouTube morning brief.
  - It locks in a daily ritual that competing accounts don't have.

Strategy:
  - Once per day, idempotent via morning_recap_state.json.
  - Fires every hour but only ships once between 06:00-09:00 Paris
    (08:00-11:00 EST during DST or 07:00-10:00 EST in winter — the
    scheduler hour-check covers both via the time-of-day window).
  - Generates a 4-tweet English thread:
      1. Hook: "Morning scan. The 3 AI + Crypto stories that matter. 🧵"
      2-4. Three stories from external_signal.json + RSS, each with
         one sentence of context + one sentence of sarcastic punchline.
  - Posts via twitter_client.post_thread.
  - Auto-pushes morning_recap_state.json + state to git.

Different from thread_bot (single-story dissect) and digest_thread_bot
(daily 5-story recap, fires later in the day) — this is the dedicated
morning ritual.
"""
import json
import os
import traceback
from datetime import date, datetime
from zoneinfo import ZoneInfo

from .config import _PROJECT_ROOT, NEWS_MODEL
from .llm_client import run_llm, unwrap_text
from .logger import log
from .twitter_client import post_thread
from .humanizer import humanize, strip_agent_preamble
from . import lang_mode
from . import personality_store

RECAP_STATE_FILE = os.path.join(_PROJECT_ROOT, "morning_recap_state.json")

# Morning window in EST (Paris = EST + 6 in DST, EST + 5 in winter).
# Window 02:00-04:00 EST ≈ 07:00-10:00 Paris depending on DST. We catch
# DST and non-DST in one window.
MORNING_HOUR_START_EST = 1
MORNING_HOUR_END_EST = 4


RECAP_PROMPT = """{lang_directive}

VOICI les éléments en buzz ce matin (RSS / HN / Reddit / X home, last 8h):
{signal_block}

Ton job : écris UN thread de 4 tweets qui résume les 3 plus grosses
stories IA / Crypto & IA / tech frontière du moment. C'est le rituel du matin : l'audience
vient ici pour savoir en 2 minutes ce qui a bougé dans la nuit.

FORMAT (4 tweets, blocs séparés par "---"):

TWEET 1 — INTRO (≤220 chars) :
- Pas de date sur la première ligne.
- Style : "Morning scan. Les 3 stories IA du matin. Power, compute, et le coin crypto bizarre. 🧵"
- Hook + promesse + le 🧵 émoji thread.

TWEET 2 — STORY 1 (≤270 chars) :
- Format : "1/ <fait sec en 1 phrase + chiffre exact>.\\n\\n<punchline>."
- Mentionne l'outlet entre parenthèses (ex: "(Bloomberg)").
- Use global AI / crypto / Wall Street references. No French anchors.

TWEET 3 — STORY 2 (≤270 chars):
- Même format avec "2/" devant.

TWEET 4 — STORY 3 + CHUTE (≤270 chars):
- "3/ <fait>.\\n\\n<chute FINALE qui boucle le thread>."
- La chute du tweet 4 doit boucler ("Bonne journée. À demain pour
  la suite." / "Vous êtes prévenus." / "Au moins on est prévenus.").

RÈGLES:
- Langue dictée par la directive linguistique en haut du prompt.
- Pas d'em dash (—). Pas d'emojis (sauf 🧵 sur tweet 1).
- Pas de hashtag.
- Sources top-tier (Bloomberg / FT / Reuters / Les Échos / TechCrunch /
  CoinDesk / The Information / CNBC / Axios).
- ≤24h sur les news.
- Si moins de 3 stories valides existent dans le signal → output
  exactement le mot SKIP.
- Wording AUDIO-FRIENDLY: lis ton thread à voix haute. Si une chute
  tombe à plat oralement → réécris (ce thread peut servir de voice-over
  pour la chaîne YouTube).

{performance_section}

OUTPUT — 4 blocs séparés par "---", aucun autre formatage:
<tweet 1 intro>
---
<tweet 2 story 1>
---
<tweet 3 story 2>
---
<tweet 4 story 3 + chute>
"""


def _is_morning_window() -> bool:
    """True between 01:00-04:00 EST (~07:00-10:00 Paris)."""
    h = datetime.now(ZoneInfo("America/New_York")).hour
    return MORNING_HOUR_START_EST <= h < MORNING_HOUR_END_EST


def _already_posted_today() -> bool:
    if not os.path.exists(RECAP_STATE_FILE):
        return False
    try:
        with open(RECAP_STATE_FILE, "r") as f:
            return json.load(f).get("date") == date.today().isoformat()
    except Exception:
        return False


def _mark_posted_today():
    with open(RECAP_STATE_FILE, "w") as f:
        json.dump({"date": date.today().isoformat(), "ts": datetime.now().isoformat()}, f)


def run_morning_recap_cycle():
    if _already_posted_today():
        return
    if not _is_morning_window():
        return  # not the right time-of-day yet

    log.info("[MORNING] In window + not posted today — generating recap thread.")

    # Pull external signal block.
    try:
        from . import hn_signal_bot
        signal_block = hn_signal_bot.render_signal_block(max_items=12)
        if not signal_block:
            signal_block = "(no external signal items right now — try later)"
    except Exception:
        signal_block = "(signal feed unavailable)"

    today_date = datetime.now().strftime("%Y-%m-%d")
    _lang = lang_mode.pick_content_lang()
    performance_section = personality_store.hard_rules_block()
    bot_self = personality_store.render_bot_self(lang=_lang)
    if bot_self:
        performance_section = bot_self + "\n\n" + performance_section
    core = personality_store.render_core_identity(lang=_lang)
    if core:
        performance_section = core + "\n\n" + performance_section

    prompt = RECAP_PROMPT.format(
        lang_directive=lang_mode.lang_directive(_lang),
        today_date=today_date,
        signal_block=signal_block[:5000],
        performance_section=performance_section,
    )

    log.info("[MORNING] Calling LLM...")
    result = run_llm(prompt, NEWS_MODEL, label="MORNING_RECAP", allowed_tools=["WebSearch"])
    if result.returncode != 0:
        log.info(f"[MORNING] LLM failed: {result.stderr[:200]}")
        return

    text = unwrap_text(result.stdout).strip()
    text = strip_agent_preamble(text)
    if not text or text.upper().startswith("SKIP"):
        log.info("[MORNING] Agent returned SKIP / empty — no recap today.")
        return

    parts = [p.strip() for p in text.split("---") if p.strip()]
    if len(parts) < 3:
        log.info(f"[MORNING] Got {len(parts)} parts, expected 4. Aborting.")
        return

    parts = [humanize(p) for p in parts[:4]]
    parts = [p[:278] for p in parts]

    # Append YouTube CTA on the last tweet if env var is set.
    yt = os.environ.get("YOUTUBE_URL", "").strip()
    if yt and len(parts) >= 4:
        cta = f"\n\n→ Plus de décodage en vidéo: {yt}"
        if len(parts[-1]) + len(cta) <= 278:
            parts[-1] = parts[-1] + cta

    log.info(f"[MORNING] Posting {len(parts)}-tweet recap thread.")
    for i, p in enumerate(parts, 1):
        log.info(f"[MORNING]   {i}: {p[:100]!r}")

    try:
        post_thread(parts)
        _mark_posted_today()
        log.info("[MORNING] Posted + marked done for today.")
    except Exception:
        log.info("[MORNING] post_thread failed:")
        traceback.print_exc()


def safe_run_morning_recap_cycle():
    from . import health
    try:
        run_morning_recap_cycle()
        health.record_success("morning_recap")
        try:
            from .git_ops import auto_push
            auto_push(
                ["morning_recap_state.json"],
                "Autonomous morning recap posted",
            )
        except Exception:
            pass
    except Exception:
        log.info("[MORNING] Error during morning recap cycle:")
        traceback.print_exc()
        health.record_failure("morning_recap")

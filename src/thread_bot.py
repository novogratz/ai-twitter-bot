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

THREAD_PROMPT = """You are @cryptoiadecode. You write ONE X thread of 4 tweets on THE most important AI infrastructure / asymmetric investing story of the last 36h.

Threads are 15% of the growth mix. X rewards long-form value when it is useful
enough to bookmark. Prefer AI Power Wars, Undervalued Compute, AI Infra Radar,
Market Decode, Asymmetric Bet of the Week, and The Numbers That Matter. The
recurring thesis: everyone watches GPUs, fewer people watch power generation.

{lang_directive}

PROCESSUS:
1. WebSearch large (EN top-tier): find the story dominating AI infrastructure / asymmetric investing.
   - "AI datacenter power demand megawatt gigawatt"
   - "CoreWeave CRWV Applied Digital APLD IREN HIVE"
   - "nuclear grid power generation AI datacenter"
   - "TAO Bittensor decentralized compute AI crypto"
   - "SpaceX Starlink robotics frontier tech"
2. Vérifie sur 2-3 sources que c'est THE story (pas un truc obscur).
3. Ouvre l'article (WebFetch) et note 2-3 chiffres / faits exacts.
4. Écris le thread.

FORMAT THREAD (4 tweets exactly):

TWEET 1 — HOOK (≤220 chars, dry English):
- Phrase that shocks or creates tension. No date. No "Today...", no "Breaking:".
- Style: "Everyone watches GPUs. Nobody watches the power bill. That's the AI trade nobody priced. 🧵"
- Le 🧵 émoji thread est OK, pas d'autre emoji.
- Annonce que c'est un thread. Crée la promesse.

TWEET 2 — FACT (≤260 chars, factual English):
- Le contexte sec. Qui + quoi + chiffre exact + date. Cite l'article.
- Une phrase vérifiable, pas du blabla. Pas de punchline ici.

TWEET 3 — THE ANGLE NOBODY TAKES (≤260 chars, analytical English):
- Le truc que BFM / Bloomberg ne diront pas. La conséquence cachée, le précédent ironique, l'absurdité du système.
- Réf culturelle FR autorisée mais légère: "C'est le RER B des levées de fonds — toujours en retard, jamais à l'heure".

TWEET 4 — PUNCHLINE (≤220 chars, sarcastic English):
- Le punch. Une vanne sèche qui résume tout.
- Format préféré: renaming brutal, mini-dialogue, ou understatement.
- Termine par l'URL de l'article, sur une ligne dédiée.

RÈGLES DURES:
- 100% English. Global AI / crypto / markets audience.
- Pas d'em dash (—). Pas d'emojis (sauf 🧵 sur le tweet 1).
- No hashtag. Keep threads clean. No "According to...".
- Source top-tier obligatoire (Reuters, Bloomberg, FT, WSJ, AFP, Les Échos, Le Monde, BFM, Numerama, Usine Digitale, TechCrunch, The Information).
- ≤36h max sur la news.
- Si rien d'assez fort dans les 36h → output exactement le mot SKIP.

{performance_section}

OUTPUT — strictement ce format, rien d'autre. Un tweet par bloc, séparés par "---":

<tweet 1 hook>
---
<tweet 2 fait>
---
<tweet 3 angle>
---
<tweet 4 chute + URL>
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
        log.info(f"[THREAD] Got {len(parts)} parts, expected 4. Aborting.")
        return

    # Cap at 4 (in case agent emits 5+) and humanize each.
    parts = [humanize(p) for p in parts[:4]]
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

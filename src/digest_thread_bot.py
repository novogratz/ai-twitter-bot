"""Daily 'top 5 IA/crypto/bourse' digest thread.

Different from src/thread_bot.py:
  - thread_bot = ONE story dissected (4 tweets: hook → fact → angle → chute)
  - digest_thread_bot = FIVE stories of the day in a recap thread

The digest format is highly shareable on FR Twitter (saves people from
scrolling 30 outlets). It also positions @kzer_ai as THE one-stop FR
source for IA / crypto / bourse — exactly what the user wants.

Strategy:
  - Once per day (cap=1, idempotent state in digest_thread_state.json).
  - Picks 5 distinct stories from the last ~36h (one each from FR press
    + EN top-tier).
  - Generates a 6-tweet thread: intro + 5 numbered stories + chute.
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

DIGEST_STATE_FILE = os.path.join(_PROJECT_ROOT, "digest_thread_state.json")

DIGEST_PROMPT = """Tu es @kzer_ai. Tu écris LE thread récap quotidien — un thread X de 6 tweets en FRANÇAIS qui couvre les 5 plus grosses stories IA / crypto / bourse des dernières 36h. C'est notre format SIGNATURE: l'audience FR vient ici parce qu'elle n'a pas le temps de scroller 30 outlets.

📅 Date: {today_date}

PROCESSUS:
1. WebSearch large (FR + EN top-tier) en parallèle — trouve 5 stories DISTINCTES qui dominent en ce moment:
   - 1-2 IA (Mistral, OpenAI, Anthropic, Nvidia, agents, levée, modèle)
   - 1-2 crypto (Bitcoin, Ethereum, ETF, régulation, hack, ATH/crash)
   - 1-2 bourse / macro / tech earnings (CAC40, Nvidia, taux, IPO, faillite)
2. Vérifie sur 2+ sources que chaque story est réelle + ≤36h.
3. Pour chaque story note: 1 chiffre exact + l'angle drôle/critique.
4. Écris le thread.

FORMAT THREAD (6 tweets, blocs séparés par "---"):

TWEET 1 — INTRO (≤220 chars, FR sec):
- "5 trucs qui ont bougé aujourd'hui sur l'IA, la crypto et la bourse. Personne va vous les expliquer aussi vite. 🧵"
- Style alternatif accepté tant que: annonce un récap de 5 stories + crée la promesse.
- Le 🧵 émoji thread est OK, pas d'autre emoji.

TWEET 2 — STORY 1 (≤270 chars, FR):
- Format: "1/ <fait sec en 1 phrase>.\\n\\n<chute FR sarcastique>."
- Cite un chiffre vérifiable.
- Mentionne l'outlet entre parenthèses (ex: (Les Échos), (Reuters)).
- Pas d'URL dans le tweet — on les regroupera.

TWEET 3 — STORY 2 (≤270 chars):
- Même format avec "2/" devant.

TWEET 4 — STORY 3 (≤270 chars):
- "3/ ..."

TWEET 5 — STORY 4 (≤270 chars):
- "4/ ..."

TWEET 6 — STORY 5 + CHUTE (≤270 chars):
- "5/ <fait>.\\n\\n<chute FINALE qui boucle le thread>."
- La chute du tweet 6 doit boucler le thread (pas juste une 5e blague random).
  Ex: "Conclusion: si t'as lu jusqu'ici, t'as plus suivi l'actualité que 80% des analystes BFM."

RÈGLES DURES:
- TOUT EN FRANÇAIS. Audience 100% FR.
- Pas d'em dash (—). Pas d'emojis (sauf 🧵 sur le tweet 1).
- Pas de hashtag.
- Sources top-tier obligatoires (Reuters, Bloomberg, FT, WSJ, AFP, Les Échos, Le Monde, BFM, Numerama, Usine Digitale, Siècle Digital, TechCrunch, The Information, CoinDesk).
- ≤36h max sur chaque news.
- Si moins de 4 stories valides existent → output exactement le mot SKIP. Mieux vaut sauter le récap qu'écrire un thread bidon.

{performance_section}

OUTPUT — 6 blocs séparés par "---", aucun autre formatage:

<tweet 1 intro>
---
<tweet 2 story 1>
---
<tweet 3 story 2>
---
<tweet 4 story 3>
---
<tweet 5 story 4>
---
<tweet 6 story 5 + chute>
"""


def _load_state() -> dict:
    if os.path.exists(DIGEST_STATE_FILE):
        try:
            with open(DIGEST_STATE_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"date": None}


def _save_state(state: dict):
    with open(DIGEST_STATE_FILE, "w") as f:
        json.dump(state, f)


def _already_posted_today() -> bool:
    return _load_state().get("date") == date.today().isoformat()


def _mark_posted_today():
    _save_state({"date": date.today().isoformat()})


def run_digest_thread_cycle():
    """Generate + post one daily 5-story FR recap thread."""
    if _already_posted_today():
        log.info("[DIGEST] Already posted today. Skipping.")
        return

    today_date = datetime.now().strftime("%Y-%m-%d")
    performance_section = personality_store.HARD_RULES_BLOCK
    prompt = DIGEST_PROMPT.format(
        today_date=today_date,
        performance_section=performance_section,
    )

    log.info("[DIGEST] Generating daily 5-story FR thread...")
    result = run_llm(
        prompt,
        NEWS_MODEL,
        label="DIGEST_THREAD",
        allowed_tools=["WebSearch"],
    )
    if result.returncode != 0:
        log.info(f"[DIGEST] LLM failed (exit {result.returncode}): {result.stderr[:200]}")
        return

    text = unwrap_text(result.stdout).strip()
    if not text or text.upper().startswith("SKIP"):
        log.info("[DIGEST] Agent returned SKIP. No digest today.")
        return

    parts = [p.strip() for p in text.split("---") if p.strip()]
    if len(parts) < 4:
        log.info(f"[DIGEST] Got {len(parts)} parts, expected 6. Aborting.")
        return

    parts = [humanize(p) for p in parts[:6]]
    parts = [p[:278] for p in parts]

    log.info(f"[DIGEST] Posting {len(parts)}-tweet recap thread.")
    for i, p in enumerate(parts, 1):
        log.info(f"[DIGEST]   {i}: {p[:100]!r}")

    try:
        post_thread(parts)
        _mark_posted_today()
        log.info("[DIGEST] Posted + marked done for today.")
    except Exception:
        log.info("[DIGEST] post_thread failed:")
        traceback.print_exc()


def safe_run_digest_thread_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    from . import health
    try:
        run_digest_thread_cycle()
        health.record_success("digest_thread")
    except Exception:
        log.info("[DIGEST] Error during digest thread cycle:")
        traceback.print_exc()
        health.record_failure("digest_thread")

"""Long-form deep-dive bot — 1-2 posts/day, 400-700 char analysis.

X's algo rewards long posts since the 2023 long-form push:
- Reading time signal goes up dramatically
- "Show more" creates a curiosity loop that boosts engagement
- Distinguishes the account from the one-liner-mill timeline

Format (intentionally different from news/hot takes):

  {sharp first sentence — the headline observation}

  {3 concrete bullets with exact numbers, named entities, causal links}

  {one-line analytical chute that names the hidden bet}

  {URL — source}

Targets 450-650 chars body (X's expanded limit is 25,000 but the algo
sweet spot for "Show more" lift is ~500 chars). Daily cap = MAX_LONGFORM_PER_DAY.
"""
import json
import os
import re
import traceback
from datetime import date, datetime, timedelta
from typing import Optional

from .config import _PROJECT_ROOT, REPLY_MODEL, get_live_cap
from .logger import log
from .llm_client import run_llm, unwrap_text
from .twitter_client import post_tweet
from .humanizer import humanize
from .engagement_log import log_post

STATE_FILE = os.path.join(_PROJECT_ROOT, "longform_state.json")

PROMPT = """Tu es @cryptoiadecode. Tu écris UN deep-dive LONG (400-700 caractères)
sur la story IA/crypto/datacenter/mining la plus importante des dernières 24h.

C'est DIFFÉRENT des news courtes et hot takes one-liner. Ici tu prends le
temps de déballer une analyse. Pourquoi long format: X push les posts longs
avec "Show more" → 5x plus de vues qu'un one-liner pour un compte petit.

FORMAT OBLIGATOIRE — exactement ce schéma:

{{Une PHRASE COURTE qui pose la headline — 8-15 mots, chiffre ou nom propre en hook}}

{{Bloc d'analyse — 3 puces, chacune un fait concret avec chiffre EXACT, nom
propre, lien causal nommé. Format:
• {{fait précis avec chiffre}}
• {{conséquence avec acteur nommé}}
• {{l'angle que personne ne nomme}}}}

{{Une LIGNE CHUTE qui nomme le vrai pari caché. FR culturel obligatoire
(RER B, Bercy, URSSAF, syndicat, Lidl, Doctolib, tonton à Noël, Coach Boris).
Stack 2 réfs si tu peux.}}

{{URL source ≤36h obligatoire}}

CONTRAINTES:
- Total entre 450 et 650 chars hors URL.
- Hook dans les 6 premiers mots: chiffre, nom propre, ou verbe brutal.
- Aucun emoji décoratif. Aucun hashtag. Aucun em dash (—).
- Français impeccable, accents corrects.
- Source ≤36h vérifiée par WebSearch. PAS DE SOURCE → SKIP.
- Tu trolles l'IDÉE / le système, JAMAIS les gens.

🚫 SI le sujet n'est pas IA, crypto, datacenter MW, ou crypto mining
   → output uniquement: SKIP

🚫 SI tu n'as pas trouvé d'angle qu'AUCUN autre compte FR n'a déjà fait
   dans les dernières 12h → SKIP. Pas de réchauffé.

WebSearch large (4-5 requêtes en parallèle):
- site:lesechos.fr OR site:lemonde.fr OR site:bfmtv.com
- site:numerama.com OR site:siecledigital.fr
- "Stargate" OR "CoreWeave" OR "MARA" OR "Bitfarms"
- "Mistral" OR "OpenAI" OR "Anthropic" 24h
- "Bitcoin" OR "ETH" OR "ETF crypto" 24h

OUTPUT — JUSTE le tweet final (450-650 chars body + URL), ou le mot SKIP.
"""


def _load_state() -> dict:
    if not os.path.exists(STATE_FILE):
        return {"date": None, "count": 0}
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"date": None, "count": 0}


def _save_state(s: dict) -> None:
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(s, f, indent=2)
    except OSError:
        pass


def _today_count() -> int:
    s = _load_state()
    today = date.today().isoformat()
    if s.get("date") != today:
        return 0
    return int(s.get("count") or 0)


def _bump() -> None:
    s = _load_state()
    today = date.today().isoformat()
    if s.get("date") != today:
        s = {"date": today, "count": 0}
    s["count"] = int(s.get("count") or 0) + 1
    _save_state(s)


def _validate_longform(text: str) -> Optional[str]:
    """Return error reason if invalid, else None."""
    if not text:
        return "empty"
    # Must contain a URL
    url_match = re.search(r"https?://\S+", text)
    if not url_match:
        return "no source URL"
    body = text.replace(url_match.group(0), "").strip()
    body_compact_len = len(re.sub(r"\s+", " ", body))
    if body_compact_len < 380:
        return f"body too short ({body_compact_len} chars)"
    if body_compact_len > 700:
        return f"body too long ({body_compact_len} chars)"
    # Bullet block check — at least 2 bullets
    bullets = re.findall(r"^\s*[•\-\*]\s+.+", body, flags=re.MULTILINE)
    if len(bullets) < 2:
        return f"only {len(bullets)} bullets (need >=2)"
    return None


def run_longform_cycle() -> None:
    cap = get_live_cap("MAX_LONGFORM_PER_DAY", int(os.environ.get("MAX_LONGFORM_PER_DAY", "2")))
    if _today_count() >= cap:
        log.info(f"[LONGFORM] daily cap reached ({cap}) — skipping.")
        return

    log.info(f"[LONGFORM] generating deep-dive (today {_today_count()}/{cap})")
    r = run_llm(PROMPT, REPLY_MODEL, label="LONGFORM", allowed_tools=["WebSearch"])
    if r.returncode != 0:
        log.info(f"[LONGFORM] LLM failed rc={r.returncode}: {r.stderr[:200]}")
        return

    text = unwrap_text(r.stdout).strip()
    if not text or text.upper().startswith("SKIP"):
        log.info("[LONGFORM] LLM returned SKIP / empty.")
        return

    text = humanize(text)
    err = _validate_longform(text)
    if err:
        log.info(f"[LONGFORM] rejected — {err}: {text[:200]!r}")
        return

    log.info(f"[LONGFORM] Posting ({len(text)} chars): {text[:200]}...")
    post_tweet(text)
    try:
        log_post(text, pattern_id="LONGFORM")
    except Exception:
        pass
    _bump()


def safe_run_longform_cycle() -> None:
    try:
        run_longform_cycle()
    except Exception:
        log.info("[LONGFORM] outer error:")
        traceback.print_exc()

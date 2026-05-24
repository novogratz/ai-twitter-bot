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
        # Match Le Décode header in either form (with or without emoji)
        if not re.search(r"Le Décode\s*#?\s*\d+", text, re.IGNORECASE):
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


THREAD_PROMPT = """Tu es @CryptoAIDecode. Tu vas écrire UN thread FR de récap des
Décodes de la semaine. Voici les 5-6 meilleurs Décodes (par likes) de cette semaine:

{decode_list}

OUTPUT — un thread X de {n_tweets} tweets, chaque tweet séparé par "---" sur sa
propre ligne. PAS DE TEXTE AVANT NI APRÈS le thread, juste les tweets séparés
par ---.

TWEET 1 (le head — accroche pour faire scroller / cliquer):
  📅 Les {n_decodes} Décodes qui ont marqué la semaine.

  IA, crypto, infrastructure. Une lecture FR sans bullshit.

  Thread 👇

TWEET 2 à TWEET N (un par Décode, dans l'ordre du meilleur au moins bon):
  Pour chaque Décode:
  - Mentionne SON numéro (#N)
  - Résume son angle en 1 phrase mordante (10-20 mots)
  - Ajoute 1 phrase qui donne ENVIE de cliquer pour voir le Décode complet
  - Inclus l'URL du Décode original (les URLs sont fournies dans la liste).

  Exemple de format pour 1 tweet du thread:
    #57 — IA. OpenAI lève 200Md pour des GPUs qui périment en 18 mois.

    Le vrai pari: créer le grid privé qui fait du réseau public un secondaire.

    https://x.com/CryptoAIDecode/status/...

DERNIER TWEET (le close — invite à follow + tease la semaine prochaine):
  Tu as aimé? La semaine prochaine, 6 nouveaux Décodes.

  IA, crypto, datacenters, mining. Lundi à dimanche.

  Follow pour ne pas les rater.

RÈGLES:
- Chaque tweet ≤ 270 caractères.
- Pas d'em dashes (—). Tirets simples ou virgules.
- Stack 1 réf culturelle FR par tweet quand pertinent (RER B, Bercy, etc).
- 100% français.
- Aucun emoji décoratif sauf 📅 du tweet 1 et 👇 du head.
- Output: juste les tweets séparés par "---", rien d'autre.
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

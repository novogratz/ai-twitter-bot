"""Manu de Bercy bot — once a day, generates a fictional French
bureaucratic press release reacting to today's AI/crypto news.

The conceit: "Manu de Bercy" is the recurring archetype from
core_identity.md — a deadpan FR regulator who's always 18 months
behind the actual innovation curve, prepares amendes before the
innovation even ships, schedules commissions for jeudi prochain.

Output format is fixed and screenshot-friendly:

  📋 COMMUNIQUÉ DE MANU DE BERCY
  Jour {N} sans rapport définitif sur {topic}.

  {2-3 deadpan bureaucratic sentences reacting to the day's biggest
  AI/crypto/datacenter/mining story — citing fake Cerfa numbers,
  imaginary commissions, made-up délais, treating real innovation
  with absurd bureaucratic gravity}

  La commission se réunit jeudi.

The "Jour N sans rapport" counter increments daily and is per-topic
(stored in manu_bercy_state.json). Creates a running gag people watch.
"""
import json
import os
import random
import time
import traceback
from datetime import date, datetime
from typing import Optional

from .config import _PROJECT_ROOT, REPLY_MODEL
from .logger import log
from .llm_client import run_llm, unwrap_text
from .twitter_client import post_tweet
from .humanizer import humanize
from .engagement_log import log_post

STATE_FILE = os.path.join(_PROJECT_ROOT, "manu_bercy_state.json")

TOPICS = [
    "Stargate",
    "OpenAI",
    "Mistral",
    "Anthropic",
    "xAI Colossus",
    "le Bitcoin à 100k",
    "MARA",
    "CoreWeave",
    "Nvidia",
    "les datacenters MW",
    "Iren",
    "RIOT",
    "Hut 8",
    "CleanSpark",
    "TeraWulf",
    "le crypto mining",
    "Doge",
    "USDC",
    "ETH",
    "le halving",
    "Apple Intelligence",
    "Claude",
    "GPT-5.4",
    "Gemini",
    "Grok",
    "le SaaS qui meurt",
    "AGI",
]

PROMPT = """Tu écris UN tweet en français au format COMMUNIQUÉ DE MANU DE BERCY.

Manu de Bercy = personnage récurrent du bot @cryptoiadecode. Fonctionnaire
français deadpan, toujours 18 mois en retard sur l'innovation, prépare les
amendes AVANT que l'innovation aboutisse, programme des commissions pour
jeudi prochain. C'est un type, pas une personne réelle.

NEWS DU JOUR (utilise-la comme déclencheur):
{news_block}

SUJET PRINCIPAL: {topic}
COMPTEUR: Jour {day_counter} sans rapport définitif sur {topic}.

OUTPUT — EXACTEMENT CE FORMAT (RIEN D'AUTRE):

📋 COMMUNIQUÉ DE MANU DE BERCY
Jour {day_counter} sans rapport définitif sur {topic}.

{{2-3 phrases bureaucratiques sèches sur la news du jour. Cite un Cerfa
imaginaire (Cerfa-1729bis-IA, Cerfa-2017-Crypto, etc), un délai absurde
(amende en 2031, audit en 2034), une commission programmée pour jeudi.
Traite l'innovation comme une procédure administrative. ZERO emoji
décoratif. Tirets courts ou virgules, jamais d'em dash. Français
impeccable, accents obligatoires.}}

La commission se réunit jeudi.

CONTRAINTES:
- 280 chars max au total.
- Aucune URL.
- Aucune attaque personnelle nommée.
- Aucun emoji sauf 📋 au début.
- Ton: deadpan, surréaliste, drôle par le contraste innovation vs lenteur
  bureaucratique. ABSURDE > smart.

Si le sujet ne se prête pas (off-niche, pas d'angle) → output uniquement SKIP."""


def _load_state() -> dict:
    if not os.path.exists(STATE_FILE):
        return {"per_topic": {}, "last_posted": None}
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"per_topic": {}, "last_posted": None}


def _save_state(s: dict) -> None:
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(s, f, indent=2)
    except OSError:
        pass


def _today() -> str:
    return date.today().isoformat()


def _bump_counter(state: dict, topic: str) -> int:
    """Increment the per-topic 'days without report' counter."""
    per = state.setdefault("per_topic", {})
    per[topic] = int(per.get(topic, 142)) + 1  # start mid-range so first post feels established
    return per[topic]


def _news_block() -> str:
    """Pull a few recent items from external_signal.json for context."""
    path = os.path.join(_PROJECT_ROOT, "external_signal.json")
    if not os.path.exists(path):
        return "(no external signal)"
    try:
        with open(path) as f:
            data = json.load(f)
        items = data if isinstance(data, list) else data.get("items", [])
    except (json.JSONDecodeError, OSError):
        return "(signal unreadable)"
    if not items:
        return "(no items)"
    sample = items[:8]
    lines = []
    for it in sample:
        title = (it.get("title") or it.get("text") or "")[:140]
        if title:
            lines.append(f"- {title}")
    return "\n".join(lines) if lines else "(no titles)"


def run_manu_bercy_cycle() -> None:
    state = _load_state()
    today = _today()
    if state.get("last_posted") == today:
        log.info("[MANU] already posted today — skipping.")
        return

    topic = random.choice(TOPICS)
    day_counter = _bump_counter(state, topic)
    prompt = PROMPT.format(
        news_block=_news_block(),
        topic=topic,
        day_counter=day_counter,
    )
    log.info(f"[MANU] generating communiqué for topic={topic!r}, jour {day_counter}")
    r = run_llm(prompt, REPLY_MODEL, label="MANU_BERCY")
    if r.returncode != 0:
        log.info(f"[MANU] LLM failed rc={r.returncode}: {r.stderr[:200]}")
        return
    text = unwrap_text(r.stdout).strip()
    if not text or text.upper().startswith("SKIP"):
        log.info(f"[MANU] LLM returned SKIP/empty.")
        return

    # Make sure the signature header is present; if model dropped it, prepend.
    if "COMMUNIQUÉ DE MANU DE BERCY" not in text.upper() and "MANU DE BERCY" not in text.upper():
        log.info(f"[MANU] header missing — rejecting: {text[:140]!r}")
        return

    text = humanize(text)
    if len(text) > 280:
        log.info(f"[MANU] over-length ({len(text)} chars) — refusing.")
        return

    log.info(f"[MANU] Posting ({len(text)} chars): {text[:200]}")
    post_tweet(text)
    try:
        log_post(text, pattern_id="MANU_BERCY")
    except Exception:
        pass

    state["last_posted"] = today
    _save_state(state)


def safe_run_manu_bercy_cycle() -> None:
    try:
        run_manu_bercy_cycle()
    except Exception:
        log.info("[MANU] outer error:")
        traceback.print_exc()

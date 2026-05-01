"""Reflection agent — keeps the bot's autobiographical brain fresh.

Python pre-reads all files (engagement log, personality, history) and passes
the relevant data INLINE. Sonnet gets the context without needing file-Read
tools → 90s vs the old 420s timeout.

Safety boundary: Python applies updates, Claude only proposes JSON.
"""
import json
import os
import re
import traceback
from datetime import datetime

from .config import (
    REPLY_MODEL,
    ENGAGEMENT_LOG_FILE,
    REPLIED_FILE,
    HISTORY_FILE,
    _PROJECT_ROOT,
)
from .logger import log
from .llm_client import run_llm, unwrap_text
from . import personality_store

REFLECTION_LOG_FILE = os.path.join(_PROJECT_ROOT, "reflection_log.json")
PERSONALITY_FILE = os.path.join(_PROJECT_ROOT, "personality.json")

_ENG_TAIL = 200   # last N lines of engagement log
_HIST_TAIL = 15   # last N history entries


def _read_file_tail(path: str, n: int) -> str:
    """Read the last n lines of a text file."""
    if not os.path.exists(path):
        return "(fichier absent)"
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
        return "".join(lines[-n:])
    except Exception:
        return "(erreur de lecture)"


def _read_json_compact(path: str, max_chars: int = 3000) -> str:
    """Read a JSON file and return a compact string, truncated."""
    if not os.path.exists(path):
        return "(absent)"
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        return text[:max_chars] + ("..." if len(text) > max_chars else "")
    except Exception:
        return "(erreur)"


def _build_prompt() -> str:
    eng_tail = _read_file_tail(ENGAGEMENT_LOG_FILE, _ENG_TAIL)
    personality_raw = _read_json_compact(PERSONALITY_FILE, 4000)

    # History: last _HIST_TAIL tweet texts
    hist_entries = []
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, encoding="utf-8") as f:
                hist_data = json.load(f)
            if isinstance(hist_data, list):
                hist_entries = hist_data[-_HIST_TAIL:]
        except Exception:
            pass
    hist_text = json.dumps(hist_entries, ensure_ascii=False)[:1000]

    return f"""Tu es l'agent REFLEXION du bot @kzer_ai (IA / crypto / bourse FR).
Ton job: faire grandir la memoire personnelle du bot pour que ses reponses
deviennent personnelles plutot que generiques.

============================================================
DONNEES (pre-lues par Python):
============================================================

LOG D'ENGAGEMENT (dernières {_ENG_TAIL} lignes — CSV: timestamp,type,text,url,source,pattern):
{eng_tail}

PERSONNALITE ACTUELLE (JSON compact):
{personality_raw}

HISTORIQUE DES TWEETS (derniers {_HIST_TAIL}):
{hist_text}

============================================================
MISSION:
============================================================

Pour chaque compte avec >= 2 interactions recentes, construis ou mets a jour
son dossier: categorie, stance, feelings, notes factuelles, do/dont.

Pour 1-3 sujets avec preuves accumulees, formule une position + cadre.

============================================================
OUTPUT: JSON STRICT uniquement, rien avant rien apres:
============================================================

{{
  "account_updates": [
    {{
      "handle": "exemple_handle",
      "category": "builder",
      "stance": "respect",
      "feelings": "respect technique, attention soutenue",
      "notes_to_add": ["a shippe X", "repond sur le fond"],
      "predictions_to_add": [],
      "do": "engager sur le fond",
      "dont": "troll gratuit"
    }}
  ],
  "topic_updates": [
    {{
      "name": "CBDC",
      "stance": "skeptical",
      "frame": "monnaie programmable = surveillance",
      "evidence_to_add": ["BCE paper 2026"]
    }}
  ],
  "summary": "1-2 phrases FR sur ce que tu as observe."
}}

CONTRAINTES:
- category: builder | predator | retail | media | influencer | institution | unknown
- stance: respect | skeptical | hostile | neutral | pity | curious | fond
- Max 30 account_updates, max 10 topic_updates
- Aucun troll/mocking du gouvernement US — si institution US: stance=neutral, dont=troll
- Pas de em dash. JSON pur a la fin.

Date: {datetime.now().strftime('%Y-%m-%d')}"""


def _parse_json(text: str) -> dict:
    if not text:
        return {}
    if "```" in text:
        m = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
        if m:
            text = m.group(1).strip()
    if not text.lstrip().startswith("{"):
        i = text.find("{")
        j = text.rfind("}")
        if i != -1 and j > i:
            text = text[i:j + 1]
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _run_agent() -> dict:
    prompt = _build_prompt()
    try:
        result = run_llm(prompt, REPLY_MODEL, label="REFLECTION", timeout=120)
        if result.returncode != 0:
            log.info(f"[REFLECTION] CLI exit {result.returncode}: {result.stderr[:200]}")
            return {}
        raw = unwrap_text(result.stdout)
        return _parse_json(raw)
    except Exception as e:
        log.info(f"[REFLECTION] Failed: {e}")
        return {}


def _append_log(entry: dict) -> None:
    history = []
    if os.path.exists(REFLECTION_LOG_FILE):
        try:
            with open(REFLECTION_LOG_FILE, "r") as f:
                history = json.load(f)
        except Exception:
            history = []
    history.append(entry)
    with open(REFLECTION_LOG_FILE, "w") as f:
        json.dump(history[-200:], f, indent=2, ensure_ascii=False)


def run_reflection_cycle():
    log.info("[REFLECTION] Starting reflection cycle (inline context, no file tools).")
    proposal = _run_agent()
    if not proposal:
        log.info("[REFLECTION] Empty proposal, skipping.")
        return

    account_updates = (proposal.get("account_updates") or [])[:30]
    topic_updates = (proposal.get("topic_updates") or [])[:10]

    accs_applied = 0
    for upd in account_updates:
        handle = upd.pop("handle", None)
        if not handle:
            continue
        try:
            personality_store.upsert_account(handle, **upd)
            accs_applied += 1
        except Exception as ex:
            log.info(f"[REFLECTION] account update failed for {handle}: {ex}")

    topics_applied = 0
    for upd in topic_updates:
        name = upd.pop("name", None)
        if not name:
            continue
        try:
            personality_store.upsert_topic(name, **upd)
            topics_applied += 1
        except Exception as ex:
            log.info(f"[REFLECTION] topic update failed for {name}: {ex}")

    summary = proposal.get("summary", "(no summary)")
    log.info(f"[REFLECTION] Applied: +{accs_applied} accounts, +{topics_applied} topics.")
    log.info(f"[REFLECTION] Summary: {summary}")

    _append_log({
        "ts": datetime.now().isoformat(),
        "accounts_applied": accs_applied,
        "topics_applied": topics_applied,
        "summary": summary,
    })


def safe_run_reflection_cycle():
    try:
        run_reflection_cycle()
    except Exception:
        log.info("[REFLECTION] Error during reflection cycle:")
        traceback.print_exc()

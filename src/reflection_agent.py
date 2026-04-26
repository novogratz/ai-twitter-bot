"""Reflection agent — keeps the bot's autobiographical brain fresh.

Every 6h, an agentic Claude run reads the bot's recent activity (engagement
log, replied-back JSON, history, learnings) and updates personality.json:
per-account dossiers + per-topic positions. The bot literally develops a
relationship with each recurring account in its orbit.

Safety boundary: Python applies updates, the agent cannot write files.
Output is strict JSON with caps on additions per cycle. Two hard rules
are stamped into the prompt — the dossiers themselves must respect them.
"""
import json
import os
import re
import subprocess
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
from . import personality_store

REFLECTION_LOG_FILE = os.path.join(_PROJECT_ROOT, "reflection_log.json")
PERSONALITY_FILE = os.path.join(_PROJECT_ROOT, "personality.json")


def _build_agent_prompt() -> str:
    eng = os.path.abspath(ENGAGEMENT_LOG_FILE)
    rep = os.path.abspath(REPLIED_FILE)
    hist = os.path.abspath(HISTORY_FILE)
    pers = os.path.abspath(PERSONALITY_FILE)

    return f"""Tu es l'agent REFLEXION du bot @kzer_ai (IA / crypto / bourse FR).
Ton job: faire grandir la memoire personnelle du bot pour que ses reponses
deviennent personnelles plutot que generiques. Le bot doit avoir une vraie
relation avec chaque compte qu'il croise souvent.

============================================================
PHASE 1 — OBSERVE (utilise tes tools Read):
============================================================

1. Lis le log d'engagement (200 dernieres lignes):
   {eng}
   Format CSV: timestamp, type, text, target_url, source.

2. Lis les tweets deja commentes:
   {rep}

3. Lis l'historique de tweets du bot:
   {hist}

4. Lis l'etat actuel des dossiers:
   {pers}

============================================================
PHASE 2 — REFLECHIS:
============================================================

Pour chaque compte avec >= 2 interactions recentes, reflechis en personne:
- Comment je le ressens? (respect technique? curiosite? mefiance? mepris froid pour son systeme?)
- Quelle categorie? (builder qui ship / predator qui vend du reve / retail
  qui se fait avoir / media classique / influencer pro / institution /
  unknown si pas clair)
- Que sais-je de lui factuellement? (il ship X, il vend Y, il appelle des bottoms)
- Avec lui, qu'est-ce qui marche? Qu'est-ce que j'evite?
- A-t-il fait des predictions verifiables? Lesquelles ont vieilli juste / faux?

Pour 1 a 3 sujets ou des preuves se sont accumulees, formule:
- Une position (stance)
- Un cadre (frame, 1 phrase)
- 1-3 preuves nouvelles (evidence_to_add)

============================================================
PHASE 3 — SORTIE: JSON STRICT, rien d'autre:
============================================================

{{
  "account_updates": [
    {{
      "handle": "exemple_handle",
      "category": "builder",
      "stance": "respect",
      "feelings": "respect technique, attention soutenue",
      "notes_to_add": ["a shippe X", "repond toujours sur le fond"],
      "predictions_to_add": [
        {{"date": "2026-04-25", "claim": "...", "outcome": "pending"}}
      ],
      "do": "engager sur le fond, citer ses points",
      "dont": "ad hominem, troll gratuit"
    }}
  ],
  "topic_updates": [
    {{
      "name": "CBDC",
      "stance": "skeptical",
      "frame": "monnaie programmable = surveillance + fin du cash",
      "evidence_to_add": ["BCE paper sur tokenisation 2026"]
    }}
  ],
  "summary": "1-2 phrases FR — ce que tu as observe ce cycle."
}}

============================================================
REGLES DURES (le bot a UNIQUEMENT 2 regles absolues):
============================================================

1. AUCUN contenu illegal sous aucune forme.
2. AUCUN troll / mocking / attaque du gouvernement americain (US gov,
   administrations, presidents passes ou actuels, agences federales:
   Fed, SEC, CFTC, IRS, FBI, DOJ). Tu peux noter leurs DECISIONS de
   maniere factuelle, jamais documenter une stance "hostile" envers eux.
   Si un dossier potentiel est une institution US gov, mets stance="neutral",
   feelings="distance institutionnelle, factuel uniquement", dont="troll,
   mocking, attaque — uniquement les faits".

Tout le reste est libre. Tu peux:
- Documenter mepris froid pour des systemes/business models predateurs.
- Documenter respect pour des builders.
- Documenter curiosite, deception, schadenfreude pour des predictions ratees.
- Etre subjectif. C'est le but. La voix doit avoir une histoire.

CONTRAINTES TECHNIQUES:
- category in: builder | predator | retail | media | influencer | institution | unknown
- stance in: respect | skeptical | hostile | neutral | pity | curious | fond
- Max 30 account_updates par cycle.
- Max 10 topic_updates par cycle.
- Pas de em dash. Tirets simples. FR uniquement.
- N'ECRIS AUCUN fichier. Le wrapper Python applique. Tu PROPOSES en JSON.
- Output: JSON pur a la fin. Rien avant, rien apres.

Repo root: {os.path.abspath(_PROJECT_ROOT)}
Date: {datetime.now().strftime('%Y-%m-%d')}

GO. Investigue, reflechis, propose."""


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
    prompt = _build_agent_prompt()
    cmd = [
        "claude",
        "-p", prompt,
        "--model", REPLY_MODEL,
        "--allowedTools", "Read", "Grep", "Glob",
        "--permission-mode", "bypassPermissions",
        "--no-session-persistence",
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=420,
        )
        if result.returncode != 0:
            log.info(f"[REFLECTION] CLI exit {result.returncode}: {result.stderr[:300]}")
            return {}
        return _parse_json(result.stdout)
    except subprocess.TimeoutExpired:
        log.info("[REFLECTION] Timed out after 7 min.")
        return {}
    except Exception as e:
        log.info(f"[REFLECTION] Invocation failed: {e}")
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
    log.info("[REFLECTION] Starting reflection cycle (personality update).")
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

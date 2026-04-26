"""Autonomous EVOLUTION AGENT for @kzer_ai — self-improvement of CONTENT quality.

Where strategy_agent (every 6h) evolves the INPUT side (which queries to run,
which accounts to monitor), this agent evolves the OUTPUT side:

  1. Reads engagement_log.csv + performance_log.json (last ~7 days).
  2. Spawns an agentic Claude with Read tools to analyse what won, what lost,
     and which sources produced engagement vs zero.
  3. Proposes JSON with:
       - prompt directives  → overwrite directives.md (loaded by all agents)
       - prune candidates   → handles that produced 0 engagement in 14d
       - reinforce list     → handles whose tweets converted into our top posts
  4. Python wrapper APPLIES with hard caps + TTL safety bounds:
       - max 3 prunes/cycle, auto-expire after 30 days
       - max 5 reinforcements/cycle, no expiry
       - directives are OVERWRITTEN (not accumulated) so noise self-corrects

Schedule: every 12h. The bot literally re-writes its own style guide twice a
day based on what's actually getting likes — and prunes accounts that have
gone cold from its rotation, while doubling down on the ones that work.
"""
import json
import os
import re
import subprocess
import traceback
from datetime import datetime
from .config import REPLY_MODEL, ENGAGEMENT_LOG_FILE, _PROJECT_ROOT
from .logger import log
from .evolution_store import (
    write_directives,
    add_pruned_accounts,
    add_reinforced_accounts,
    append_evolution_log,
    DIRECTIVES_FILE,
    PRUNED_FILE,
    REINFORCED_FILE,
)
from .performance import PERFORMANCE_FILE


def _build_agent_prompt() -> str:
    eng_path = os.path.abspath(ENGAGEMENT_LOG_FILE)
    perf_path = os.path.abspath(PERFORMANCE_FILE)
    directives_path = os.path.abspath(DIRECTIVES_FILE)
    pruned_path = os.path.abspath(PRUNED_FILE)
    reinforced_path = os.path.abspath(REINFORCED_FILE)

    return f"""Tu es l'EVOLUTION AGENT autonome de @kzer_ai — bot X qui couvre IA + crypto + bourse en français.

Ta mission: analyser ce qui MARCHE et ce qui ne marche PAS, et proposer des changements concrets pour améliorer la qualité du contenu et la sélection des sources.

============================================================
PHASE 1 — OBSERVE (utilise tes tools Read):
============================================================

1. Lis le log d'engagement (tweets envoyés + sources + pattern):
   {eng_path}
   → CSV: timestamp, type, text, target_url, source, pattern_id.
   → Regarde les 300 dernières lignes minimum. Compte par `source` combien on a posté sur chaque cible. Identifie les sources ZÉRO et les sources qui dominent.
   → Compte AUSSI par `pattern_id` (REPETITION / DIALOGUE / METAPHOR / RENAME / FR_ANCHOR / UNDERSTATEMENT / OTHER). Croise avec performance_log: quel pattern apparaît le plus souvent dans le TOP des likes? Quel pattern domine le BOTTOM? La directive principale doit refléter ce signal.

2. Lis les métriques de performance scrapées (likes/views des nos tweets):
   {perf_path}
   → JSON: list de {{text, likes, views, timestamp, scraped_at}}.
   → Sort les tweets par likes desc. Regarde le top 10 et le bottom 10.

3. Lis l'état actuel des directives + pruning + reinforcement:
   {directives_path}
   {pruned_path}
   {reinforced_path}
   → Pour ne pas re-proposer ce qui est déjà fait.

============================================================
PHASE 2 — ANALYSE (réfléchis avant de proposer):
============================================================

A. PATTERNS DE CONTENU — Pour les tweets du TOP, identifie:
   - Longueur typique (court/moyen/long)?
   - Présence d'emoji? Lesquels?
   - Présence d'une question / d'un hook d'engagement?
   - Format (setup→punch, definition absurde, mini-dialogue, callback FR, métaphore, etc.)?
   - Sujet (IA / crypto / bourse / mix)?
   - Ton (deadpan, savage, philosophique, observation)?
   - PATTERN_ID dominant: quel(s) pattern(s) reviennent dans le TOP? Si un pattern domine clairement, l'une de tes directives doit dire "fais plus de <pattern>". Si un pattern dort dans le bottom, dis "moins de <pattern>".

B. PATTERNS À ÉVITER — Pour les tweets du BOTTOM, identifie:
   - Quels patterns reviennent? (Trop long? Pas de hook? Trop générique? Trop "smart sans chute"?)

C. SOURCES — Pour chaque source dans le log:
   - Combien de fois on a posté?
   - Si > 5 réponses sur cette source en 14 jours mais pas de signal de performance → pruning candidate
   - Si une source apparaît dans plusieurs tweets du TOP → reinforce candidate

============================================================
PHASE 3 — PROPOSE (output UN seul JSON à la fin):
============================================================

{{
  "directives": [
    "...",   // 3-7 RÈGLES courtes, ACTIONNABLES, concrètes. Pas de blabla. Exemples:
             //   "Ajoute toujours une question ou un take polarisant à la fin."
             //   "Évite les tweets > 220 chars — perdent des likes."
             //   "Sur la bourse, le format mini-dialogue (médecin/syndicat) cartonne — refais-en."
             //   "Drop l'emoji 🚀 — patterns mort. Garde 🔥 et 💀 qui marchent."
             //   "Les tweets sans punch line en bottom — toujours finir sur une chute."
  ],
  "prune_candidates": [
    "...",   // 0-3 handles (sans @) à mettre en pause 30j. UNIQUEMENT si: (a) on les a sollicités ≥ 5 fois en 14j ET (b) zéro impact visible. Pas d'anchor hand-picked s'ils ont moins de 5 sollicitations.
  ],
  "reinforce_candidates": [
    "...",   // 0-5 handles (sans @) à booster 2x. UNIQUEMENT si nos meilleurs tweets viennent de ces sources de manière répétée.
  ],
  "summary": "1-2 phrases en FR — observation principale + raison du changement."
}}

============================================================
RÈGLES STRICTES:
============================================================
- N'ÉCRIS PAS de fichier toi-même. Le wrapper Python applique avec des safety caps.
- Si tu n'as pas assez de signal pour proposer 3 directives solides, propose-en moins. Qualité > quantité.
- Si toutes les sources tournent bien, retourne `prune_candidates: []`. Pas de pruning gratuit.
- Si tu n'es PAS SÛR qu'une source soit morte (ex: scrapée 2 fois seulement), NE LA PRUNE PAS.
- À la fin, output UNIQUEMENT le bloc JSON. Rien avant, rien après.

Date du jour: {datetime.now().strftime('%Y-%m-%d')}

GO. Analyse les fichiers, puis propose."""


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
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=420)
        if result.returncode != 0:
            log.info(f"[EVOLUTION-AGENT] CLI exit {result.returncode}: {result.stderr[:300]}")
            return {}
        return _parse_json(result.stdout)
    except subprocess.TimeoutExpired:
        log.info("[EVOLUTION-AGENT] Agent timed out after 7 min.")
        return {}
    except Exception as e:
        log.info(f"[EVOLUTION-AGENT] Agent invocation failed: {e}")
        return {}


def run_evolution_cycle():
    """One self-improvement pass. Always-on, capped, TTL-bounded."""
    log.info("[EVOLUTION-AGENT] Starting content-quality evolution cycle...")

    proposals = _run_agent()
    if not proposals:
        log.info("[EVOLUTION-AGENT] No proposals returned — skipping.")
        return

    directives = [d for d in proposals.get("directives", []) if isinstance(d, str) and d.strip()]
    prune = [h for h in proposals.get("prune_candidates", []) if isinstance(h, str) and h.strip()]
    reinforce = [h for h in proposals.get("reinforce_candidates", []) if isinstance(h, str) and h.strip()]
    summary = proposals.get("summary", "(no summary)")

    if directives:
        write_directives(directives, summary=summary)
    pruned_added = add_pruned_accounts(prune, reason=summary[:200])
    reinforced_added = add_reinforced_accounts(reinforce, reason=summary[:200])

    log.info(f"[EVOLUTION-AGENT] Applied: {len(directives)} directives, "
             f"+{pruned_added} pruned, +{reinforced_added} reinforced.")
    log.info(f"[EVOLUTION-AGENT] Reasoning: {summary}")
    if directives:
        for d in directives[:5]:
            log.info(f"[EVOLUTION-AGENT]   directive: {d[:160]}")
    if prune:
        log.info(f"[EVOLUTION-AGENT]   pruned: {prune}")
    if reinforce:
        log.info(f"[EVOLUTION-AGENT]   reinforced: {reinforce}")

    append_evolution_log({
        "ts": datetime.now().isoformat(),
        "directives_count": len(directives),
        "pruned_added": pruned_added,
        "reinforced_added": reinforced_added,
        "directives": directives,
        "prune": prune,
        "reinforce": reinforce,
        "summary": summary,
    })


def safe_run_evolution_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    try:
        run_evolution_cycle()
    except Exception:
        log.info("[EVOLUTION-AGENT] Error during evolution cycle:")
        traceback.print_exc()

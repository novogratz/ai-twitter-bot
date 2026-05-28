"""Style-evolution bot — the "fashion" bot.

Every 6h: scrapes X for the highest-engagement FR crypto/IA posts of the
last 24h, analyzes what format/tone/hook patterns are winning RIGHT NOW,
then rewrites directives.md with fresh style guidance.

Model: Claude Sonnet (never Opus — we want fast and punchy, not deep).

Why this matters: Twitter style trends shift fast. A format that hit 500
likes in January is tired by May. This bot keeps the voice current.

Hard constraints:
  - NEVER touches core_identity.md (the ideological spine)
  - NEVER removes hard rules (no illegal, no US-gov troll, respect list)
  - Only updates the STYLE GUIDE section of directives.md
  - Preserves the Coluche/Desproges level — only raises the bar
"""
import json
import os
import shutil
import traceback
from datetime import datetime

from .config import _PROJECT_ROOT, NEWS_MODEL
from .llm_client import run_llm, unwrap_text
from .logger import log
from . import health

DIRECTIVES_FILE = os.path.join(_PROJECT_ROOT, "directives.md")
INSIGHTS_FILE = os.path.join(_PROJECT_ROOT, "performance_insights.json")
STYLE_STATE_FILE = os.path.join(_PROJECT_ROOT, "style_evolution_state.json")

STYLE_PROMPT = """Tu es l'agent STYLE-EVOLUTION de @CryptoAIDecode — le bot Twitter FR n°1 IA + Crypto + Spatial.

Ton job: analyser les TENDANCES DE FORMAT qui marchent en ce moment sur Twitter FR IA/Crypto, et réécrire les DIRECTIVES DE STYLE du bot pour maximiser les likes/RT/followers.

📅 Date: {today}

DONNÉES DE PERFORMANCE (7 derniers jours):
{insights}

DIRECTIVES ACTUELLES (à améliorer):
{current_directives}

INSTRUCTIONS:
1. Cherche sur X (WebSearch) les tweets FR IA/Crypto/Spatial des 24h avec le + de likes.
   Requêtes: "IA lang:fr min_faves:50", "Bitcoin lang:fr min_faves:100", "Nvidia lang:fr min_faves:50"
2. Analyse les formats qui marchent: longueur, structure, hooks d'ouverture, types de punchlines.
3. Réécris les directives de style EN GARDANT:
   - Les règles dures (pas d'illegal, pas de troll US gov, respect list)
   - L'identité core (Coluche + Desproges, FR first, zéro bullshit, "vous me détesterez jusqu'à ce que j'aie raison")
   - Les 6 patterns de comédie (REPETITION, DIALOGUE, METAPHOR, RENAME, EN_ANCHOR, UNDERSTATEMENT)
4. AJOUTE des observations concrètes sur ce qui marche EN CE MOMENT (avec exemples réels trouvés).
5. Le document final DOIT être actionnable — pas du management-speak.

FORMAT DE SORTIE:
Retourne UNIQUEMENT le contenu Markdown des nouvelles directives (pas de JSON, pas de preamble).
Commence par: `# Directives autonomes (régénérées)`
_Dernière mise à jour: {today}_

Limite: 1500 mots MAX. Concis et actionnable. Chaque ligne doit aider le bot à tweeter mieux.
"""


def _load_insights() -> str:
    if not os.path.exists(INSIGHTS_FILE):
        return "(no performance data yet — run the analyzer first)"
    try:
        with open(INSIGHTS_FILE) as f:
            d = json.load(f)
        parts = []
        parts.append(f"Actions 7j: {d.get('window_7d_actions', 0)}, 24h: {d.get('window_24h_actions', 0)}")
        if d.get("top_patterns"):
            parts.append("Top patterns: " + ", ".join(f"{p['pattern']}({p['count']})" for p in d["top_patterns"][:3]))
        if d.get("best_topics_7d"):
            parts.append("Best topics: " + ", ".join(f"{t['topic']}({t['count']})" for t in d["best_topics_7d"][:4]))
        if d.get("rising_topics_24h"):
            parts.append("Rising topics 24h: " + ", ".join(r["topic"] for r in d["rising_topics_24h"]))
        if d.get("viral_examples"):
            parts.append("Viral examples:")
            for ex in d["viral_examples"][:3]:
                parts.append(f'  [{ex["type"]}] "{ex["text"][:120]}"')
        return "\n".join(parts)
    except Exception:
        return "(error reading insights)"


def _load_current_directives() -> str:
    if not os.path.exists(DIRECTIVES_FILE):
        return "(no directives yet)"
    try:
        with open(DIRECTIVES_FILE) as f:
            return f.read()[:3000]
    except Exception:
        return "(error reading directives)"


def _load_state() -> dict:
    if not os.path.exists(STYLE_STATE_FILE):
        return {}
    try:
        with open(STYLE_STATE_FILE) as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _save_state(d: dict):
    with open(STYLE_STATE_FILE, "w") as f:
        json.dump(d, f, indent=2)


def run_style_evolution_cycle():
    state = _load_state()
    today = datetime.now().strftime("%Y-%m-%d")

    # Only run once per 6h block — avoid hammering LLM
    last_run = state.get("last_run", "")
    if last_run == datetime.now().strftime("%Y-%m-%d-%H"):
        log.info("[STYLE-EVO] Already ran this hour — skipping.")
        return

    insights = _load_insights()
    current = _load_current_directives()

    prompt = STYLE_PROMPT.format(
        today=today,
        insights=insights[:2000],
        current_directives=current[:3000],
    )

    # Weekly strategy job: use Claude when installed (quality > speed here).
    # Falls back to whatever _provider() selects if claude is unavailable.
    _claude_provider = "claude" if shutil.which("claude") else None
    log.info(f"[STYLE-EVO] Running style-evolution agent ({'Claude Sonnet' if _claude_provider else 'Ollama'})...")
    result = run_llm(
        prompt,
        NEWS_MODEL,
        label="STYLE_EVOLUTION",
        allowed_tools=["WebSearch"],
        output_json=False,
        force_provider=_claude_provider,
    )

    if result.returncode != 0 or not result.stdout.strip():
        log.info(f"[STYLE-EVO] LLM failed or empty: {result.stderr[:200]}")
        return

    new_directives = unwrap_text(result.stdout).strip()

    # Safety check: must start with expected header
    if not new_directives.startswith("# Directives"):
        # Try to extract from response
        idx = new_directives.find("# Directives")
        if idx >= 0:
            new_directives = new_directives[idx:]
        else:
            log.info("[STYLE-EVO] Response doesn't contain valid directives header — aborting.")
            return

    # Hard rule injection: ensure critical rules are preserved
    hard_rules = [
        "No illegal content",
        "No trolling US government",
        "respect_list",
    ]
    for rule in hard_rules:
        if rule.lower() not in new_directives.lower():
            log.info(f"[STYLE-EVO] Hard rule missing from output: '{rule}' — aborting to be safe.")
            return

    with open(DIRECTIVES_FILE, "w") as f:
        f.write(new_directives)

    _save_state({"last_run": datetime.now().strftime("%Y-%m-%d-%H"), "last_ts": datetime.now().isoformat()})

    log.info(f"[STYLE-EVO] directives.md updated ({len(new_directives)} chars).")

    try:
        from .git_ops import auto_push
        auto_push(
            ["directives.md", "style_evolution_state.json"],
            "Autonomous style-evolution update — fresh patterns from viral X analysis",
        )
    except Exception:
        pass


def safe_run_style_evolution_cycle():
    try:
        run_style_evolution_cycle()
        health.record_success("style_evolution")
    except Exception:
        log.info("[STYLE-EVO] Error:")
        traceback.print_exc()
        health.record_failure("style_evolution")

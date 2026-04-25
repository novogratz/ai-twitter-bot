"""Autonomous AGENTIC self-improvement for @kzer_ai.

Unlike a one-shot prompt, this hands Claude actual tools (Read, WebSearch,
Bash, Grep) and lets it decide its own investigation plan: read recent
engagement, look up what's trending in FR AI/crypto/bourse on the open web
right now, cross-reference with what the bot already covers, then propose
new queries + accounts.

The Python wrapper enforces the safety boundary: Claude PROPOSES, Python
APPLIES — and only as ADDITIONS. Removals stay manual. This means a bad
agent run can only add noise, never silently delete hand-picked targets.

Schedule: every 6h. Always-on. The bot rewrites its own strategy 4x/day.
"""
import json
import os
import re
import subprocess
import traceback
from datetime import datetime
from .config import REPLY_MODEL, BLOCKLIST, ENGAGEMENT_LOG_FILE, REPLIED_FILE, _PROJECT_ROOT
from .logger import log
from .dynamic_strategy import (
    add_dynamic_queries,
    add_dynamic_accounts,
    get_dynamic_queries,
    get_dynamic_accounts,
    DYNAMIC_QUERIES_FILE,
    DYNAMIC_ACCOUNTS_FILE,
)

STRATEGY_LOG_FILE = os.path.join(_PROJECT_ROOT, "strategy_log.json")


def _known_handles() -> set:
    """All handles already monitored — used to dedup proposals."""
    from .engage_bot import TARGET_ACCOUNTS as ENG
    from .reply_agent import TARGET_ACCOUNTS as REP
    from .direct_reply import FR_ACCOUNTS, EN_ACCOUNTS
    handles = {h.lower() for h in list(ENG) + list(REP) + list(FR_ACCOUNTS) + list(EN_ACCOUNTS)}
    handles |= {h.lower() for h in BLOCKLIST}
    dyn = get_dynamic_accounts()
    handles |= {h.lower() for h in dyn["fr"] + dyn["en"]}
    handles.discard("")
    return handles


def _known_queries() -> set:
    from .direct_reply import SEARCH_QUERIES, HOT_TAB_QUERIES
    dyn = get_dynamic_queries()
    return set(SEARCH_QUERIES + HOT_TAB_QUERIES + dyn["live"] + dyn["hot"])


def _build_agent_prompt() -> str:
    """Directive that turns Claude into a strategy agent. It uses tools to
    investigate, then emits a single JSON object the wrapper consumes."""

    # Trim file paths to absolute so Claude's Read tool can grab them directly.
    eng_path = os.path.abspath(ENGAGEMENT_LOG_FILE)
    rep_path = os.path.abspath(REPLIED_FILE)
    dyn_q = os.path.abspath(DYNAMIC_QUERIES_FILE)
    dyn_a = os.path.abspath(DYNAMIC_ACCOUNTS_FILE)
    repo_root = os.path.abspath(_PROJECT_ROOT)

    known_handles_sample = sorted(_known_handles())[:80]
    known_queries_sample = sorted(_known_queries())[:80]

    return f"""Tu es le STRATEGY AGENT autonome de @kzer_ai — un bot X qui couvre IA + crypto + bourse en français principalement.

Ta mission cette session: trouver de NOUVELLES sources (queries de recherche + comptes à monitorer) qui vont aider le bot à grossir son audience FR. Tu peux utiliser tes tools.

============================================================
PHASE 1 — OBSERVE (utilise tes tools):
============================================================

1. Lis le log d'engagement (Read):
   {eng_path}
   → C'est un CSV: timestamp, type, text, target_url, source.
   → Regarde les 200 dernières lignes. Identifie quelles sources rapportent et lesquelles sont mortes.

2. Lis la liste des tweets déjà commentés (Read):
   {rep_path}
   → Comprends le rythme et la diversité des sources.

3. Lis les ajouts dynamiques précédents pour ne pas dupliquer (Read):
   {dyn_q}
   {dyn_a}

4. (Optionnel mais encouragé) WebSearch — cherche ce qui buzz aujourd'hui:
   - "trending AI news France today"
   - "crypto news Bitcoin France"
   - "bourse CAC 40 actualité"
   - Tout autre angle qui te semble pertinent.
   → L'idée: trouver des mots-clés VRAIMENT chauds aujourd'hui, pas des génériques.

============================================================
PHASE 2 — PROPOSE (sors UN seul JSON à la fin):
============================================================

Le bot connaît déjà ces handles (échantillon):
{', '.join(known_handles_sample)}

Et ces queries (échantillon):
{', '.join(repr(q) for q in known_queries_sample[:30])}

Propose UNIQUEMENT du NOUVEAU. Format JSON strict:

{{
  "new_queries_live": ["...", "..."],   // 3-5 nouvelles X searches chronologiques. FR-leaning. Inclus "lang:fr" + "min_faves:N" pour éviter les morts.
  "new_queries_hot":  ["...", "..."],   // 2-4 queries pour l'onglet TOP de X. Mots-clés simples qui surfent le buzz du jour. FR principalement.
  "new_fr_accounts":  ["...", "..."],   // 3-5 handles FR (sans @). VRAIS analystes/founders/traders FR sur IA/crypto/bourse. Pas de comptes promo/formations/arnaques.
  "new_en_accounts":  ["...", "..."],   // 2-3 handles EN. Mégas comptes IA/crypto/bourse uniquement.
  "summary": "1-2 phrases en FR — ce que tu as observé et pourquoi tu proposes ces ajouts.",
  "kill_candidates": ["..."]             // OPTIONNEL: sources observées qui n'ont rien rapporté en 7+ jours. Pure info, le bot ne les supprimera PAS automatiquement.
}}

============================================================
RÈGLES STRICTES:
============================================================
- N'ÉCRIS PAS de fichier toi-même. Le wrapper Python applique les ajouts.
- N'INCLUS pas de handles/queries déjà connus (échantillons ci-dessus + ce que tu lis dans les fichiers dynamiques).
- Pas de comptes promo / arnaque / vente de formations.
- Pas de comptes politiques.
- Si tu n'as pas assez d'info pour proposer 5 queries solides, propose-en moins. Qualité > quantité.
- À la fin, output UNIQUEMENT le bloc JSON. Rien avant, rien après.

Repo root: {repo_root}
Date du jour: {datetime.now().strftime('%Y-%m-%d')}

GO. Investigue, puis propose."""


def _parse_json_proposal(text: str) -> dict:
    """Extract the JSON proposal from Claude's final output."""
    if not text:
        return {}
    # Strip markdown fences
    if "```" in text:
        m = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
        if m:
            text = m.group(1).strip()
    # Find outermost JSON object
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
    """Invoke the Claude CLI as an agent with tool access. Returns the parsed
    JSON proposal, or {} on failure."""
    prompt = _build_agent_prompt()

    # Allow the agent to actually investigate. Read-only tools only:
    # Read (files), Grep + Glob (search), WebSearch + WebFetch (live signal).
    # NO Bash and NO Write — the wrapper applies changes via Python (safety
    # boundary), and Bash on an autonomous loop is too wide a foot-gun.
    # --permission-mode bypassPermissions: required in -p mode or tool use
    # blocks on the permission gate and the run hangs until timeout.
    # --no-session-persistence: keep these autonomous runs out of /resume.
    cmd = [
        "claude",
        "-p", prompt,
        "--model", REPLY_MODEL,
        "--allowedTools", "Read", "WebSearch", "WebFetch", "Grep", "Glob",
        "--permission-mode", "bypassPermissions",
        "--no-session-persistence",
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=420,  # 7 min — agent runs are slower than one-shots
        )
        if result.returncode != 0:
            log.info(f"[STRATEGY-AGENT] CLI exit {result.returncode}: {result.stderr[:300]}")
            return {}

        return _parse_json_proposal(result.stdout)
    except subprocess.TimeoutExpired:
        log.info("[STRATEGY-AGENT] Agent timed out after 7 min.")
        return {}
    except Exception as e:
        log.info(f"[STRATEGY-AGENT] Agent invocation failed: {e}")
        return {}


def _append_strategy_log(entry: dict):
    """Persist what was applied this cycle for auditability."""
    history = []
    if os.path.exists(STRATEGY_LOG_FILE):
        try:
            with open(STRATEGY_LOG_FILE, "r") as f:
                history = json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    history.append(entry)
    with open(STRATEGY_LOG_FILE, "w") as f:
        json.dump(history[-200:], f, indent=2)


def run_strategy_cycle():
    """One agentic improvement pass. Always-on, append-only, safety-bounded."""
    log.info("[STRATEGY-AGENT] Starting agentic self-improvement cycle...")

    proposals = _run_agent()
    if not proposals:
        log.info("[STRATEGY-AGENT] No proposals returned — skipping.")
        return

    known_handles = _known_handles()
    known_queries = _known_queries()

    # Filter: drop anything Claude proposed that already exists. Claude's
    # introspection isn't perfect — this is the actual dedup safety net.
    new_live = [q for q in proposals.get("new_queries_live", []) if isinstance(q, str) and q not in known_queries]
    new_hot = [q for q in proposals.get("new_queries_hot", []) if isinstance(q, str) and q not in known_queries]
    new_fr = [
        h for h in proposals.get("new_fr_accounts", [])
        if isinstance(h, str) and h.lower().lstrip("@") not in known_handles
    ]
    new_en = [
        h for h in proposals.get("new_en_accounts", [])
        if isinstance(h, str) and h.lower().lstrip("@") not in known_handles
    ]
    kill_candidates = proposals.get("kill_candidates", [])  # info only

    queries_added = add_dynamic_queries(live=new_live, hot=new_hot)
    accounts_added = add_dynamic_accounts(fr=new_fr, en=new_en, known=known_handles)

    summary = proposals.get("summary", "(no summary)")
    log.info(f"[STRATEGY-AGENT] Applied: +{queries_added} queries, +{accounts_added} accounts.")
    log.info(f"[STRATEGY-AGENT] Reasoning: {summary}")
    if new_live:
        log.info(f"[STRATEGY-AGENT]   live queries: {new_live}")
    if new_hot:
        log.info(f"[STRATEGY-AGENT]   hot queries:  {new_hot}")
    if new_fr:
        log.info(f"[STRATEGY-AGENT]   FR accounts:  {new_fr}")
    if new_en:
        log.info(f"[STRATEGY-AGENT]   EN accounts:  {new_en}")
    if kill_candidates:
        log.info(f"[STRATEGY-AGENT]   suggested kills (manual review): {kill_candidates}")

    _append_strategy_log({
        "ts": datetime.now().isoformat(),
        "queries_added": queries_added,
        "accounts_added": accounts_added,
        "new_live": new_live,
        "new_hot": new_hot,
        "new_fr": new_fr,
        "new_en": new_en,
        "kill_candidates": kill_candidates,
        "summary": summary,
    })


def safe_run_strategy_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    try:
        run_strategy_cycle()
    except Exception:
        log.info("[STRATEGY-AGENT] Error during strategy cycle:")
        traceback.print_exc()

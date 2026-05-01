"""Scout agent: investigates and recruits the BEST French-speaking AI / crypto /
bourse accounts from France, Quebec, and the USA.

Different from `strategy_agent` (which optimizes queries + accounts based on
ENGAGEMENT LOG signals, mostly from FR France) and from `discover_bot` (which
scrapes X search and dedups by handle). This one is OPEN-WEB-NATIVE: it uses
WebSearch + WebFetch to investigate "who are the top FR-speaking voices in
AI / crypto / bourse" in three regions, then proposes the high-follower-count
ones to recruit into the bot's orbit.

Pipeline:
  1. Agentic Claude run with WebSearch / WebFetch / Read.
  2. Investigates per region (France / Quebec / USA-francophone).
  3. Proposes JSON: handles + region + niche + estimated followers + reason.
  4. Python wrapper APPLIES additions only:
       - drops anything already known (engage / reply / direct_reply / blocklist
         / dynamic / pruned)
       - filters out anything below MIN_FOLLOWERS
       - appends to dynamic_accounts.json FR bucket (they all speak French)
       - auto-follows the top N via twitter_client.follow_account
  5. Audit trail in scout_log.json.

Schedule: every 4h. Append-only. Bad runs add noise; never delete curated targets.
"""
import json
import os
import re
import traceback
from datetime import datetime
from .config import REPLY_MODEL, BLOCKLIST, _PROJECT_ROOT
from .logger import log
from .llm_client import run_llm
from .dynamic_strategy import (
    add_dynamic_accounts,
    get_dynamic_accounts,
    DYNAMIC_ACCOUNTS_FILE,
)

SCOUT_LOG_FILE = os.path.join(_PROJECT_ROOT, "scout_log.json")

# Minimum follower count for a recruit to be worth our time. Estimates from
# the agent are noisy — set the bar high enough that even a 50% over-estimate
# still leaves a real audience.
MIN_FOLLOWERS = 5000

# Hard cap on additions per cycle so a hallucinating run can't dump 50 fake
# handles into the roster.
MAX_NEW_PER_CYCLE = 8

# Auto-follow at most this many of the top picks per cycle. Slow and steady —
# X flags burst-follow patterns.
MAX_AUTO_FOLLOW_PER_CYCLE = 3


def _known_handles() -> set:
    """Every handle the scout must NOT re-propose. Same shape as strategy_agent's
    dedup set so we don't thrash with it."""
    from .engage_bot import TARGET_ACCOUNTS as ENG
    from .reply_agent import TARGET_ACCOUNTS as REP
    from .direct_reply import FR_ACCOUNTS, EN_ACCOUNTS
    from .evolution_store import get_pruned_handles
    handles = {h.lower() for h in list(ENG) + list(REP) + list(FR_ACCOUNTS) + list(EN_ACCOUNTS)}
    handles |= {h.lower() for h in BLOCKLIST}
    dyn = get_dynamic_accounts()
    handles |= {h.lower() for h in dyn["fr"] + dyn["en"]}
    handles |= get_pruned_handles()
    handles.discard("")
    return handles


def _build_agent_prompt() -> str:
    known_sample = sorted(_known_handles())[:120]
    dyn_a = os.path.abspath(DYNAMIC_ACCOUNTS_FILE)

    return f"""Tu es le SCOUT AGENT autonome de @kzer_ai — un bot X francophone qui couvre IA + crypto + bourse.

🎯 TA MISSION CETTE SESSION:
Trouver les MEILLEURS comptes X FRANCOPHONES sur IA / crypto / bourse / finance / trading dans TROIS régions:
  1. FRANCE
  2. QUÉBEC (canadien francophone)
  3. USA (Américains/diaspora francophone qui twittent en FR)

Critère de qualité — TOUS obligatoires:
  ✅ Twitte SOUVENT en français (au moins en partie)
  ✅ A une audience SOLIDE (≥ 5 000 followers, idéalement 20k+)
  ✅ Niche: IA / crypto / bourse / finance / trading / tech / VC / fintech
  ✅ Compte ACTIF (a posté dans les 30 derniers jours)
  ✅ Compte de QUALITÉ — vrais analystes, founders, traders, journalistes spécialisés
  ❌ JAMAIS: comptes vendant des formations à 99-2000€, signaux payants, "rejoins ma communauté Telegram VIP"
  ❌ JAMAIS: comptes politiques, polémistes généralistes
  ❌ JAMAIS: bots, gros comptes inactifs, comptes "perso" qui twittent sur tout sauf nos niches

============================================================
PHASE 1 — INVESTIGUE (utilise tes tools WebSearch + WebFetch):
============================================================

Recherches recommandées (lance-en au moins 4-6 différentes):
  • "meilleurs comptes Twitter crypto français"
  • "top X accounts French AI"
  • "influenceurs bourse française Twitter"
  • "comptes Twitter trading français"
  • "Quebec crypto Twitter français"
  • "Montreal AI Twitter français"
  • "francophone IA chercheur Twitter"
  • "founder fintech français Twitter"
  • "VC français AI Twitter"
  • "journaliste crypto français Twitter"

Stratégies bonus:
  • Cherche des listes / classements ("top 50", "à suivre", "must follow") — souvent publiés sur Medium, Substack, blogs FR.
  • WebFetch sur des articles de classement pour en extraire les @handles cités.
  • Cherche par institution: HEC, Polytechnique, Mistral, ConsenSys, Coinhouse, Kaiko, etc. — leurs employés sur X.

============================================================
PHASE 2 — DÉDUP MENTAL:
============================================================

Le bot connaît déjà ces handles (échantillon — ne les re-propose pas):
{', '.join(known_sample)}

Fichier des ajouts dynamiques précédents (lis-le si tu veux la liste complète):
{dyn_a}

============================================================
PHASE 3 — PROPOSE (sors UN seul JSON à la fin):
============================================================

Format strict:

{{
  "candidates": [
    {{
      "handle": "PowerHasheur",                    // pseudo SANS @
      "region": "france",                          // "france" | "quebec" | "usa"
      "niche": "crypto",                           // "ai" | "crypto" | "bourse" | "fintech" | "tech"
      "estimated_followers": 120000,                // best estimate
      "reason": "Crypto FR le plus suivi, analyse macro régulière, twitte en FR."
    }}
  ],
  "summary": "1-2 phrases en FR — qui tu as trouvé et pourquoi ils valent le coup."
}}

============================================================
RÈGLES STRICTES:
============================================================
- N'écris PAS de fichier toi-même. Le wrapper Python applique.
- Output UNIQUEMENT le bloc JSON à la fin. Rien avant, rien après.
- Si tu n'as pas pu vérifier le compte, ne le propose pas. Faux positifs > faux négatifs ICI car les gens vont nous suivre.
- Vise 5-10 candidats DE QUALITÉ. Pas 30 noms vagues.
- Couvre les 3 régions si possible (au moins 2/3).
- Si l'estimated_followers est < 5 000, ne le mets pas — pas assez d'audience.

Date du jour: {datetime.now().strftime('%Y-%m-%d')}

GO. Investigue le web, puis propose."""


def _parse_json_proposal(text: str) -> dict:
    """Extract the JSON proposal from Claude's final output. Same logic as
    strategy_agent — keeps both parsers consistent."""
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
    """Invoke the configured LLM CLI as an agent with web tools."""
    prompt = _build_agent_prompt()
    try:
        result = run_llm(
            prompt,
            REPLY_MODEL,
            label="SCOUT_AGENT",
            allowed_tools=["Read", "WebSearch", "WebFetch", "Grep", "Glob"],
            permission_mode="bypassPermissions",
            timeout=540,  # 9 min — web research is slow
        )
        if result.returncode != 0:
            log.info(f"[SCOUT-AGENT] CLI exit {result.returncode}: {result.stderr[:300]}")
            return {}
        return _parse_json_proposal(result.stdout)
    except Exception as e:
        log.info(f"[SCOUT-AGENT] Agent invocation failed: {e}")
        return {}


def _filter_candidates(candidates: list, known: set) -> list:
    """Drop dups, low-follower, and malformed entries. Cap at MAX_NEW_PER_CYCLE."""
    clean = []
    for c in candidates:
        if not isinstance(c, dict):
            continue
        h = (c.get("handle") or "").strip().lstrip("@")
        if not h or h.lower() in known:
            continue
        try:
            followers = int(c.get("estimated_followers") or 0)
        except (TypeError, ValueError):
            followers = 0
        if followers < MIN_FOLLOWERS:
            continue
        clean.append({
            "handle": h,
            "region": (c.get("region") or "").lower(),
            "niche": (c.get("niche") or "").lower(),
            "followers": followers,
            "reason": c.get("reason") or "",
        })
    # Sort by follower count desc so auto-follow targets the biggest
    clean.sort(key=lambda x: -x["followers"])
    return clean[:MAX_NEW_PER_CYCLE]


def _auto_follow(top_picks: list) -> list:
    """Follow the top N picks via twitter_client. Reuses discover_bot's
    FOLLOWED_FILE so we don't double-follow what discover already grabbed."""
    from .discover_bot import _load_followed, _save_followed
    from .twitter_client import follow_account

    followed = _load_followed()
    newly = []
    for pick in top_picks[:MAX_AUTO_FOLLOW_PER_CYCLE]:
        h = pick["handle"].lower()
        if h in followed:
            continue
        try:
            log.info(f"[SCOUT-AGENT] Auto-following @{h} ({pick['region']}, {pick['niche']}, ~{pick['followers']:,} followers)...")
            ok = follow_account(h)
            if not ok:
                continue  # JS-click didn't fire — leave for retry next cycle
            followed.add(h)
            newly.append(h)
        except Exception as e:
            log.info(f"[SCOUT-AGENT] Follow failed for @{h}: {e}")

    if newly:
        _save_followed(followed)
    return newly


def _append_log(entry: dict):
    history = []
    if os.path.exists(SCOUT_LOG_FILE):
        try:
            with open(SCOUT_LOG_FILE, "r") as f:
                history = json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    history.append(entry)
    with open(SCOUT_LOG_FILE, "w") as f:
        json.dump(history[-200:], f, indent=2)


def run_scout_cycle():
    """One scout pass: open-web investigation → recruit FR-speaking handles."""
    log.info("[SCOUT-AGENT] Starting open-web FR-speaker recruitment cycle...")

    proposals = _run_agent()
    if not proposals:
        log.info("[SCOUT-AGENT] No proposals returned — skipping.")
        return

    known = _known_handles()
    raw_candidates = proposals.get("candidates", [])
    if not isinstance(raw_candidates, list):
        log.info("[SCOUT-AGENT] Bad payload shape — no candidates list.")
        return

    keepers = _filter_candidates(raw_candidates, known)
    if not keepers:
        log.info(f"[SCOUT-AGENT] {len(raw_candidates)} raw → 0 keepers after dedup/follower filter.")
        return

    # All keepers go into the FR bucket (they all speak French by construction).
    handles = [k["handle"] for k in keepers]
    accounts_added = add_dynamic_accounts(fr=handles, en=[], known=known)

    # Auto-follow the biggest picks
    newly_followed = _auto_follow(keepers)

    summary = proposals.get("summary", "(no summary)")
    log.info(f"[SCOUT-AGENT] Applied: +{accounts_added} FR accounts, +{len(newly_followed)} auto-followed.")
    log.info(f"[SCOUT-AGENT] Reasoning: {summary}")
    for k in keepers:
        log.info(f"[SCOUT-AGENT]   @{k['handle']} ({k['region']}/{k['niche']}, ~{k['followers']:,}) — {k['reason'][:120]}")

    _append_log({
        "ts": datetime.now().isoformat(),
        "raw_count": len(raw_candidates),
        "kept_count": len(keepers),
        "accounts_added": accounts_added,
        "auto_followed": newly_followed,
        "keepers": keepers,
        "summary": summary,
    })


def safe_run_scout_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    try:
        run_scout_cycle()
    except Exception:
        log.info("[SCOUT-AGENT] Error during scout cycle:")
        traceback.print_exc()

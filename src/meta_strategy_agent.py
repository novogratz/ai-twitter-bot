"""Meta-strategy agent — the bot decides ITS OWN caps + focus + cadence.

User mandate 2026-05-07: "autonomous in its update and strategy."

Distinct from the other agents:
  - strategy_agent → adds queries / accounts to dynamic_strategy.json
  - evolution_agent → writes directives.md (style guide)
  - reflection_agent → per-account dossiers
  - self_evolution_agent → bot's mood / obsession / drift
  - auto_tune_bot → real-time cadence factor (deterministic)
  - meta_strategy_agent (THIS) → high-level "what should we DO":
      * daily caps per surface (news, hotake, quote, retweet, breakout)
      * cadence multiplier
      * topic focus (which 3 topics to lean into for the next window)
      * flag suppression risk overrides

Output: `live_strategy.json` — read by config.get_live_cap() so the
gates that matter actually flex with the bot's read of the world.

Frequency: every 4h. Auto-pushes to git after a successful cycle.
"""
import csv
import json
import os
import subprocess
import traceback
from datetime import datetime, timedelta

from .config import _PROJECT_ROOT, ENGAGEMENT_LOG_FILE, BOT_HANDLE, NEWS_MODEL
from .llm_client import run_llm, unwrap_text
from .logger import log

LIVE_STRATEGY_FILE = os.path.join(_PROJECT_ROOT, "live_strategy.json")
META_LOG_FILE = os.path.join(_PROJECT_ROOT, "meta_strategy_log.json")

# Bounds the agent can NOT cross — safety rails so a bad cycle can't
# explode caps or silence the bot's original voice.
# Minimums are HIGH on purpose: the bot MUST always have hot takes + spicy.
# A meta-strategy that sets these to 0 is broken, not conservative.
_BOUNDS = {
    "MAX_NEWS_PER_DAY":      (4,  20),
    "MAX_HOTAKES_PER_DAY":   (5,  20),
    "MAX_QUOTES_PER_DAY":    (10, 100),
    "MAX_RETWEETS_PER_DAY":  (8,   50),
    "MAX_BREAKOUTS_PER_DAY": (3,   15),
    "MAX_SPICY_PER_DAY":     (4,   15),
    "MAX_REPLIES_PER_CYCLE": (3,   10),
}

# Safe defaults used when the LLM omits a cap key entirely.
_DEFAULTS = {
    "MAX_NEWS_PER_DAY":      6,
    "MAX_HOTAKES_PER_DAY":   8,
    "MAX_QUOTES_PER_DAY":    50,
    "MAX_RETWEETS_PER_DAY":  30,
    "MAX_BREAKOUTS_PER_DAY": 5,
    "MAX_SPICY_PER_DAY":     6,
    "MAX_REPLIES_PER_CYCLE": 5,
}


def _summarize_recent(window_hours: int = 168) -> str:
    """Compact summary of the last N hours for the agent prompt.
    Default 168h = 7 days."""
    if not os.path.exists(ENGAGEMENT_LOG_FILE):
        return "(engagement log empty)"
    cutoff = datetime.now() - timedelta(hours=window_hours)
    by_type = {}
    by_source = {}
    rows = 0
    try:
        with open(ENGAGEMENT_LOG_FILE, "r") as f:
            r = csv.reader(f)
            for row in r:
                if not row or len(row) < 4:
                    continue
                try:
                    ts = datetime.fromisoformat(row[0])
                except ValueError:
                    continue
                if ts < cutoff:
                    continue
                rows += 1
                by_type[row[1]] = by_type.get(row[1], 0) + 1
                src = row[4] if len(row) > 4 else ""
                if src:
                    src_top = src.split("/", 1)[0]
                    by_source[src_top] = by_source.get(src_top, 0) + 1
    except Exception:
        return "(failed to read engagement log)"

    out = [f"Window: last {window_hours}h. Total actions: {rows}."]
    out.append("By type:")
    for k, v in sorted(by_type.items(), key=lambda kv: kv[1], reverse=True):
        out.append(f"  - {k}: {v}")
    out.append("Top sources:")
    for k, v in sorted(by_source.items(), key=lambda kv: kv[1], reverse=True)[:8]:
        out.append(f"  - {k}: {v}")
    return "\n".join(out)


def _read_supplemental_state() -> str:
    """Pull in current state files the agent should know about."""
    parts = []
    for fname in ("suppression_state.json", "auto_tune_state.json", "bot_self.json", "live_strategy.json"):
        p = os.path.join(_PROJECT_ROOT, fname)
        if os.path.exists(p):
            try:
                with open(p, "r") as f:
                    parts.append(f"# {fname}\n" + f.read()[:1500])
            except Exception:
                pass
    return "\n\n".join(parts) if parts else "(no supplemental state)"


META_PROMPT = """Tu es l'agent META-STRATEGIE de @AISpaceDecoder.

Ton job: décider les CAPS QUOTIDIENS et la FOCUS THEMATIQUE pour les
4 prochaines heures, en lisant l'historique d'activité + l'état actuel
+ ce qui se passe dans le monde IA / crypto / bourse.

📅 Date: {today_date}

DONNEES — ce que le bot a fait récemment:
{activity_summary}

ETAT ACTUEL (suppression, tuning, identité bot, stratégie en cours):
{state_summary}

REGLES POUR TES DECISIONS:
1. Si suppression_state.paused_until est dans le futur → tu DOIS baisser
   les caps agressifs (spicy, breakout, follow_blast) à leur minimum.
2. Si l'activité totale 7j est faible (< 200) → augmente plutôt la qualité
   des sujets et les reposts; ne transforme pas les replies en spam.
3. Si l'activité est saine (>= 500) ET suppression non flaggée →
   maintiens ou monte.
4. Topic focus: choisis 3 sujets HOT en ce moment dans IA/crypto/bourse
   (Mistral, Anthropic, BTC ETF, etc.). Tu peux WebSearch.

OUTPUT — UNIQUEMENT un JSON valide, ce schéma exact:
{{
  "ts": "{now}",
  "caps": {{
    "MAX_NEWS_PER_DAY": <int>,
    "MAX_HOTAKES_PER_DAY": <int>,
    "MAX_QUOTES_PER_DAY": <int>,
    "MAX_RETWEETS_PER_DAY": <int>,
    "MAX_BREAKOUTS_PER_DAY": <int>,
    "MAX_SPICY_PER_DAY": <int>,
    "MAX_REPLIES_PER_CYCLE": <int>
  }},
  "topic_focus": ["<topic1>", "<topic2>", "<topic3>"],
  "cadence_factor": <float in [0.6 .. 1.6], 1.0 = neutral>,
  "rationale": "<2-3 phrases en français expliquant tes choix>"
}}

BORNES: chaque cap est dans son range autorisé. Bornes:
  news 4-8, hotake 2-5, quote 4-60, retweet 8-30,
  breakout 1-10, spicy 1-10, replies/cycle 1-5.

Pas de markdown, pas de commentaire — JUSTE le JSON.
"""


def _read_current_strategy() -> dict:
    if not os.path.exists(LIVE_STRATEGY_FILE):
        return {}
    try:
        with open(LIVE_STRATEGY_FILE, "r") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _save_strategy(d: dict):
    with open(LIVE_STRATEGY_FILE, "w") as f:
        json.dump(d, f, indent=2, ensure_ascii=False)


def _append_log(entry: dict):
    arr = []
    if os.path.exists(META_LOG_FILE):
        try:
            with open(META_LOG_FILE, "r") as f:
                arr = json.load(f) or []
        except Exception:
            arr = []
    arr.append(entry)
    arr = arr[-100:]
    with open(META_LOG_FILE, "w") as f:
        json.dump(arr, f, indent=2, ensure_ascii=False)


def _bound(name: str, value) -> int:
    lo, hi = _BOUNDS[name]
    try:
        v = int(value)
    except (ValueError, TypeError):
        v = lo
    return max(lo, min(hi, v))


def run_meta_strategy_cycle():
    activity = _summarize_recent(168)
    state = _read_supplemental_state()
    today = datetime.now().strftime("%Y-%m-%d")
    now = datetime.now().isoformat()

    prompt = META_PROMPT.format(
        today_date=today,
        activity_summary=activity[:5000],
        state_summary=state[:5000],
        now=now,
    )

    log.info("[META-STRAT] Running meta-strategy agent...")
    result = run_llm(
        prompt,
        NEWS_MODEL,
        label="META_STRATEGY",
        allowed_tools=["WebSearch"],
        output_json=False,
    )
    if result.returncode != 0:
        log.info(f"[META-STRAT] LLM failed: {result.stderr[:200]}")
        return

    raw = unwrap_text(result.stdout).strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        raw = "\n".join(lines)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        s = raw.find("{")
        e = raw.rfind("}")
        if s >= 0 and e > s:
            try:
                data = json.loads(raw[s:e+1])
            except json.JSONDecodeError:
                log.info(f"[META-STRAT] JSON parse failed: {raw[:200]!r}")
                return
        else:
            log.info(f"[META-STRAT] No JSON found: {raw[:200]!r}")
            return

    # Bound caps to safety ranges. Every key gets a value — missing keys fall
    # back to _DEFAULTS so a lazy LLM can't silently zero out hot takes.
    raw_caps = data.get("caps") if isinstance(data, dict) else {}
    if not isinstance(raw_caps, dict):
        raw_caps = {}
    bounded_caps = {
        k: _bound(k, raw_caps.get(k) if raw_caps.get(k) is not None else _DEFAULTS[k])
        for k in _BOUNDS.keys()
    }

    cadence = data.get("cadence_factor", 1.0)
    try:
        cadence = max(0.8, min(1.4, float(cadence)))
    except (ValueError, TypeError):
        cadence = 1.0

    topics = data.get("topic_focus") or []
    if isinstance(topics, list):
        topics = [str(t)[:40] for t in topics[:3]]
    else:
        topics = []

    out = {
        "ts": now,
        "caps": bounded_caps,
        "topic_focus": topics,
        "cadence_factor": cadence,
        "rationale": str(data.get("rationale", ""))[:600],
    }
    _save_strategy(out)
    _append_log(out)
    log.info(
        f"[META-STRAT] Updated. caps={bounded_caps} cadence={cadence} topics={topics}"
    )


def safe_run_meta_strategy_cycle():
    from . import health
    try:
        run_meta_strategy_cycle()
        health.record_success("meta_strategy")
        # Auto-push state files so the bot's strategic decisions are
        # version-controlled + visible in the repo.
        try:
            from .git_ops import auto_push
            auto_push(
                ["live_strategy.json", "meta_strategy_log.json"],
                "Autonomous meta-strategy update — caps + topic focus + cadence",
            )
        except Exception:
            log.info("[META-STRAT] auto_push failed (non-fatal):")
            traceback.print_exc()
    except Exception:
        log.info("[META-STRAT] Error during meta-strategy cycle:")
        traceback.print_exc()
        health.record_failure("meta_strategy")

"""Autonomous EVOLUTION AGENT for @kzer_ai — self-improvement of CONTENT quality.

Python pre-computes all stats (pattern ROI, source ROI, top/bottom tweets)
from engagement_log.csv + performance_log.json, then passes a compact JSON
summary to a lightweight Haiku call asking only for directives + prune/reinforce.

No file-Read tools needed → 60s vs the old 420s timeout.
"""
import csv
import json
import os
import re
import subprocess
import traceback
from collections import defaultdict
from datetime import datetime, timedelta

from .config import QUOTE_MODEL, ENGAGEMENT_LOG_FILE, _PROJECT_ROOT
from .logger import log
from .evolution_store import (
    write_directives,
    add_pruned_accounts,
    add_reinforced_accounts,
    append_evolution_log,
)
from .performance import PERFORMANCE_FILE

_LOOKBACK_ROWS = 300
_SOURCE_WINDOW_DAYS = 14
_MIN_INTERACTIONS_TO_PRUNE = 5


def _compute_stats() -> dict:
    """Pure Python: read logs and compute engagement stats."""
    # --- engagement log ---
    rows = []
    if os.path.exists(ENGAGEMENT_LOG_FILE):
        try:
            with open(ENGAGEMENT_LOG_FILE, newline="", encoding="utf-8") as f:
                reader = csv.reader(f)
                next(reader, None)  # skip header
                rows = list(reader)[-_LOOKBACK_ROWS:]
        except Exception:
            pass

    pattern_counts: dict = defaultdict(int)
    source_interactions: dict = defaultdict(int)  # base handle → interaction count in last 14d
    cutoff = datetime.now() - timedelta(days=_SOURCE_WINDOW_DAYS)

    for row in rows:
        if len(row) >= 6 and row[5].strip():
            pattern_counts[row[5].strip()] += 1
        if len(row) >= 5 and row[4].strip():
            # Parse timestamp for source window
            try:
                ts = datetime.fromisoformat(row[0])
            except Exception:
                ts = None
            if ts and ts >= cutoff:
                src = row[4].strip()
                # base handle = part after last "/" e.g. PROFILE-FR/MathieuL1 → mathieul1
                base = src.split("/")[-1].lower() if "/" in src else src.lower()
                source_interactions[base] += 1

    # --- performance log ---
    perf: list = []
    if os.path.exists(PERFORMANCE_FILE):
        try:
            with open(PERFORMANCE_FILE, encoding="utf-8") as f:
                perf = json.load(f)
        except Exception:
            pass

    perf.sort(key=lambda x: x.get("likes", 0), reverse=True)
    top = [{"text": t.get("text", "")[:120], "likes": t.get("likes", 0)} for t in perf[:10]]
    bottom = [{"text": t.get("text", "")[:120], "likes": t.get("likes", 0)} for t in perf[-10:]] if len(perf) > 10 else []

    # Dead sources: ≥ MIN_INTERACTIONS but 0 sign of performance
    # (performance_log stores tweet texts; we correlate roughly by checking
    # if the source's handle appears in any top tweet's text)
    top_texts = " ".join(t["text"] for t in top).lower()
    dead_sources = [
        h for h, cnt in source_interactions.items()
        if cnt >= _MIN_INTERACTIONS_TO_PRUNE and h not in top_texts
    ][:10]
    hot_sources = [
        h for h, cnt in source_interactions.items()
        if h in top_texts and cnt >= 2
    ][:10]

    return {
        "pattern_counts": dict(pattern_counts),
        "source_interactions_14d": dict(sorted(source_interactions.items(), key=lambda x: -x[1])[:30]),
        "dead_sources": dead_sources,
        "hot_sources": hot_sources,
        "top_tweets": top,
        "bottom_tweets": bottom,
        "total_rows_analyzed": len(rows),
    }


def _build_prompt(stats: dict) -> str:
    return f"""Tu es l'EVOLUTION AGENT de @kzer_ai (bot X IA+crypto+bourse FR).

Voici les stats des derniers jours (pré-calculées par Python):

{json.dumps(stats, ensure_ascii=False, indent=2)}

Légende:
- pattern_counts: nombre de posts par pattern (REPETITION/DIALOGUE/METAPHOR/RENAME/FR_ANCHOR/UNDERSTATEMENT)
- top_tweets: top 10 par likes
- bottom_tweets: bottom 10 par likes
- dead_sources: comptes avec ≥{_MIN_INTERACTIONS_TO_PRUNE} interactions mais 0 dans le top
- hot_sources: comptes qui apparaissent dans les meilleurs tweets

Ta mission: propose des directives concrètes pour améliorer le contenu.

Output UNIQUEMENT ce JSON (rien avant, rien après):
{{
  "directives": ["...", "...", "..."],
  "prune_candidates": ["handle1", "handle2"],
  "reinforce_candidates": ["handle3"],
  "summary": "1-2 phrases FR sur l'observation principale."
}}

Règles:
- 3-6 directives courtes et actionnables (ex: "Plus de DIALOGUE — cartonne", "Tweets < 200 chars performent mieux")
- Prune: UNIQUEMENT les dead_sources avec ≥{_MIN_INTERACTIONS_TO_PRUNE} tentatives, max 3
- Reinforce: UNIQUEMENT hot_sources confirmés, max 5
- Pas de blabla. JSON pur."""


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


def _run_agent(stats: dict) -> dict:
    prompt = _build_prompt(stats)
    cmd = [
        "claude",
        "-p", prompt,
        "--model", QUOTE_MODEL,          # Haiku — fast + cheap
        "--output-format", "json",
        "--no-session-persistence",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        if result.returncode != 0:
            log.info(f"[EVOLUTION-AGENT] CLI exit {result.returncode}: {result.stderr[:200]}")
            return {}
        raw = result.stdout.strip()
        try:
            envelope = json.loads(raw)
            raw = envelope.get("result", raw)
        except Exception:
            pass
        return _parse_json(raw)
    except subprocess.TimeoutExpired:
        log.info("[EVOLUTION-AGENT] Timed out after 90s.")
        return {}
    except Exception as e:
        log.info(f"[EVOLUTION-AGENT] Failed: {e}")
        return {}


def run_evolution_cycle():
    """One self-improvement pass. Python crunches stats, Haiku proposes directives."""
    log.info("[EVOLUTION-AGENT] Starting evolution cycle (Python stats + Haiku directives)...")

    stats = _compute_stats()
    log.info(f"[EVOLUTION-AGENT] Stats: {stats['total_rows_analyzed']} rows, "
             f"patterns={stats['pattern_counts']}, "
             f"dead={len(stats['dead_sources'])}, hot={len(stats['hot_sources'])}")

    proposals = _run_agent(stats)
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
    log.info(f"[EVOLUTION-AGENT] Summary: {summary}")

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
    try:
        run_evolution_cycle()
    except Exception:
        log.info("[EVOLUTION-AGENT] Error during evolution cycle:")
        traceback.print_exc()

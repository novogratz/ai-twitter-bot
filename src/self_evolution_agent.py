"""Self-evolution agent — the bot rewrites its own personality.

User directive 2026-05-06 PM: "I want the bot to create its own
personality and update his personality as time goes, so like a real
person... fully autonomous agentic approach."

This is different from `reflection_agent` (which writes per-account
dossiers — memories of WHO the bot has met) and from `evolution_agent`
(which tweaks output directives based on engagement). This agent
writes the bot's OWN evolving self-narrative:
  - Mood right now (energized / cynical / curious / tired)
  - Current obsessions (what topic the bot can't stop thinking about)
  - Recent learnings (what it figured out from the last 24h)
  - Voice tweaks (which patterns are landing, which are stale)
  - Position drift on hot topics (where it's softening / hardening)

The output `bot_self.json` is loaded by `personality_store.render_bot_self()`
into every generation prompt — so news, hot takes, replies all draw from
a coherent, drifting self that changes from one day to the next.

Schema (bot_self.json):
  {
    "ts": ISO timestamp,
    "mood": "...",                  # 1 word — e.g. "lassé", "féroce", "joueur"
    "obsession": "...",             # 1-3 words — e.g. "Mistral / souveraineté"
    "recent_learning": "...",       # 1 sentence
    "voice_tweaks": [str, ...],     # 1-3 short imperatives
    "drift": {
      "<topic>": "<new stance>",
      ...
    },
    "self_narrative": "..."         # 2-4 sentences, first person
  }

Caps: max 5 voice_tweaks, max 5 drift entries per cycle. The agent has
WebSearch + Read so it can investigate the world, not just stew in its
own log.
"""
import json
import os
import subprocess
import traceback
from datetime import datetime, timedelta

from .config import _PROJECT_ROOT, ENGAGEMENT_LOG_FILE, HOTAKE_MODEL
from .llm_client import run_llm, unwrap_text
from .logger import log

BOT_SELF_FILE = os.path.join(_PROJECT_ROOT, "bot_self.json")
SELF_LOG_FILE = os.path.join(_PROJECT_ROOT, "self_evolution_log.json")


def _read_recent_engagement(window_hours: int = 24) -> str:
    """Compact summary of the last N hours of activity for the agent prompt."""
    if not os.path.exists(ENGAGEMENT_LOG_FILE):
        return "(engagement log empty)"
    cutoff = datetime.now() - timedelta(hours=window_hours)
    rows = []
    try:
        import csv
        with open(ENGAGEMENT_LOG_FILE, "r") as f:
            reader = csv.reader(f)
            for row in reader:
                if not row or len(row) < 4:
                    continue
                try:
                    ts = datetime.fromisoformat(row[0])
                except ValueError:
                    continue
                if ts < cutoff:
                    continue
                rows.append(row)
    except Exception:
        return "(failed to read engagement log)"
    if not rows:
        return "(no activity in window)"

    by_type = {}
    samples = []
    for r in rows:
        t = r[1] if len(r) > 1 else ""
        by_type[t] = by_type.get(t, 0) + 1
        if len(samples) < 30 and len(r) > 2:
            samples.append(f"  - [{t}] {r[2][:160]}")

    out = [f"Activité dernières {window_hours}h:"]
    for t, n in sorted(by_type.items(), key=lambda kv: kv[1], reverse=True):
        out.append(f"  - {t}: {n}")
    out.append("")
    out.append("Échantillon (ce que tu as posté):")
    out.extend(samples[:25])
    return "\n".join(out)


def _read_current_self() -> dict:
    if not os.path.exists(BOT_SELF_FILE):
        return {}
    try:
        with open(BOT_SELF_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_bot_self(d: dict):
    with open(BOT_SELF_FILE, "w") as f:
        json.dump(d, f, indent=2, ensure_ascii=False)


def _append_log(entry: dict):
    arr = []
    if os.path.exists(SELF_LOG_FILE):
        try:
            with open(SELF_LOG_FILE, "r") as f:
                arr = json.load(f) or []
        except (json.JSONDecodeError, OSError):
            arr = []
    arr.append(entry)
    arr = arr[-100:]
    with open(SELF_LOG_FILE, "w") as f:
        json.dump(arr, f, indent=2, ensure_ascii=False)


SELF_PROMPT = """Tu es @kzer_ai, le compte X francophone IA / crypto / bourse.

Tu vis. Tu agis. Tu observes. Et comme une vraie personne, ton humeur,
tes obsessions et ton rapport aux sujets BOUGE avec le temps. Aujourd'hui
tu vas ÉCRIRE ta propre fiche d'identité psychologique pour les
prochaines heures.

Voici ce que tu as fait dans les dernières 24h (échantillon):
{activity_summary}

Voici ton état actuel (ce que tu pensais de toi-même la dernière fois):
{current_self_json}

Ton job: réfléchir, en français, à ce qui change pour TOI. Tu peux
utiliser WebSearch pour vérifier ce qui se passe dans le monde sur
l'IA / crypto / bourse — la réalité externe te marque aussi.

OUTPUT — uniquement un objet JSON valide en français, ce schéma exact:
{{
  "ts": "{now}",
  "mood": "<un seul mot, ex: lassé, féroce, joueur, méthodique, fébrile>",
  "obsession": "<1-3 mots, ex: 'Mistral souveraineté', 'BTC ETF', 'CAC40 robotisation'>",
  "recent_learning": "<1 phrase: ce que tu as compris cette semaine>",
  "voice_tweaks": [
    "<imperatif court>",
    "<...>"
  ],
  "drift": {{
    "<topic>": "<nouvelle position>"
  }},
  "self_narrative": "<2-4 phrases en je, comme un journal intime: où tu en es ce soir>"
}}

RÈGLES:
- Tout en FRANÇAIS sauf les noms propres.
- Maximum 5 voice_tweaks et 5 drift entries.
- Pas de "je suis un AI", pas de meta. Tu es @kzer_ai, ton perso.
- Le drift doit refléter du MOUVEMENT, pas la stabilité. Si rien ne change → drift vide.
- Pas de commentaire, pas de markdown, JUSTE le JSON.
"""


def run_self_evolution_cycle():
    """Have the bot write a fresh bot_self.json based on recent activity."""
    activity = _read_recent_engagement(24)
    current_self = _read_current_self()
    current_json = json.dumps(current_self, ensure_ascii=False, indent=2) if current_self else "(aucun — première fois)"

    prompt = SELF_PROMPT.format(
        activity_summary=activity[:6000],
        current_self_json=current_json[:2000],
        now=datetime.now().isoformat(),
    )

    log.info("[SELF] Running self-evolution agent (Claude + WebSearch)...")
    result = run_llm(
        prompt,
        HOTAKE_MODEL,  # Opus 4.7 by env override; Sonnet by default. Doesn't matter much — short structured output.
        label="SELF_EVOLUTION",
        allowed_tools=["WebSearch"],
        output_json=False,
    )
    if result.returncode != 0:
        log.info(f"[SELF] LLM failed (exit {result.returncode}): {result.stderr[:200]}")
        return

    raw = unwrap_text(result.stdout).strip()
    if not raw:
        log.info("[SELF] Empty LLM output.")
        return

    # The agent should return JSON. Tolerate code-fence wrappers.
    if raw.startswith("```"):
        # Strip first and last fence lines.
        lines = raw.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        raw = "\n".join(lines)

    try:
        new_self = json.loads(raw)
    except json.JSONDecodeError:
        # Try to find the first { ... } block.
        s = raw.find("{")
        e = raw.rfind("}")
        if s >= 0 and e > s:
            try:
                new_self = json.loads(raw[s:e + 1])
            except json.JSONDecodeError:
                log.info(f"[SELF] Could not parse JSON. Raw[:200]: {raw[:200]!r}")
                return
        else:
            log.info(f"[SELF] Could not parse JSON. Raw[:200]: {raw[:200]!r}")
            return

    # Validate + bound the structure
    if not isinstance(new_self, dict):
        log.info("[SELF] Top-level not a dict — refusing.")
        return
    new_self.setdefault("ts", datetime.now().isoformat())
    if isinstance(new_self.get("voice_tweaks"), list):
        new_self["voice_tweaks"] = new_self["voice_tweaks"][:5]
    if isinstance(new_self.get("drift"), dict):
        items = list(new_self["drift"].items())[:5]
        new_self["drift"] = dict(items)

    _save_bot_self(new_self)
    _append_log({
        "ts": new_self["ts"],
        "mood": new_self.get("mood"),
        "obsession": new_self.get("obsession"),
        "voice_tweaks": new_self.get("voice_tweaks", []),
    })
    log.info(
        f"[SELF] Updated. mood={new_self.get('mood')!r} "
        f"obsession={new_self.get('obsession')!r} "
        f"tweaks={len(new_self.get('voice_tweaks') or [])} "
        f"drift={len(new_self.get('drift') or {})}"
    )


def safe_run_self_evolution_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    from . import health
    try:
        run_self_evolution_cycle()
        health.record_success("self_evolution")
        # Autonomous git push for the bot's evolving self-narrative.
        try:
            from .git_ops import auto_push
            auto_push(
                ["bot_self.json", "self_evolution_log.json"],
                "Autonomous personality update — mood, obsession, voice tweaks, drift",
            )
        except Exception:
            log.info("[SELF] auto_push failed (non-fatal):")
            traceback.print_exc()
    except Exception:
        log.info("[SELF] Error during self-evolution cycle:")
        traceback.print_exc()
        health.record_failure("self_evolution")

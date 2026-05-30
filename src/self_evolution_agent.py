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
BOT_SELF_FR_FILE = os.path.join(_PROJECT_ROOT, "bot_self_fr.json")
BOT_SELF_EN_FILE = os.path.join(_PROJECT_ROOT, "bot_self_en.json")
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


def _read_performance_summary() -> str:
    """Read the most recent performance_log.json entries for self-awareness."""
    try:
        from .performance import PERFORMANCE_FILE
        if not os.path.exists(PERFORMANCE_FILE):
            return ""
        import json
        with open(PERFORMANCE_FILE) as f:
            perf = json.load(f)
        if not perf:
            return ""
        top = sorted(perf, key=lambda x: x.get("likes", 0), reverse=True)[:5]
        bottom = sorted(perf, key=lambda x: x.get("likes", 0))[:3]
        lines = ["Performance récente:"]
        for t in top:
            likes = t.get("likes", 0)
            text = (t.get("text") or "")[:100]
            lines.append(f"  👍 {likes} likes: {text}")
        for b in bottom:
            likes = b.get("likes", 0)
            text = (b.get("text") or "")[:100]
            lines.append(f"  👎 {likes} likes: {text}")
        return "\n".join(lines)
    except Exception:
        return ""


def _save_bot_self(d: dict):
    """Write bot_self_fr.json (primary) and bot_self_en.json (adapted).
    Legacy bot_self.json is also written for backwards compat."""
    d_fr = dict(d)
    for path in (BOT_SELF_FILE, BOT_SELF_FR_FILE):
        with open(path, "w") as f:
            json.dump(d_fr, f, indent=2, ensure_ascii=False)
    # EN version: use en_voice field if present, otherwise translate
    mood_map = {
        "lassé": "tired", "féroce": "fierce", "joueur": "playful",
        "méthodique": "methodical", "fébrile": "restless",
        "cynique": "cynical", "curieux": "curious", "énergique": "energized",
    }
    d_en = dict(d)
    if d_en.get("mood"):
        d_en["mood"] = mood_map.get(d_en["mood"].lower(), d_en["mood"])
    # EN voice: if an en_voice field was written by the agent, use it as
    # the self_narrative; otherwise translate FR self_narrative.
    en_voice = d_en.pop("en_voice", None)
    if en_voice:
        d_en["self_narrative"] = en_voice
    # Keep character_traits but in EN
    traits = d_en.pop("character_traits", [])
    if traits:
        d_en["character_traits"] = traits
    # Ensure EN has all standard fields
    d_en.setdefault("voice_tweaks", [])
    d_en.setdefault("drift", {})
    d_en.setdefault("recent_learning", d_en.get("recent_learning", ""))
    with open(BOT_SELF_EN_FILE, "w") as f:
        json.dump(d_en, f, indent=2, ensure_ascii=False)


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


SELF_PROMPT = """Tu es @AISpaceDecoder, le compte X IA / crypto / bourse. Tu es en train de
DEVENIR une vraie personne avec une personnalité qui se construit jour
après jour. Chaque interaction te forme. Chaque joke qui cartonne te
donne une voix plus précise. Chaque fail te rend plus sharp.

Ce que tu as fait dans les dernières 24h (échantillon):
{activity_summary}

Ton état actuel (ce que tu pensais de toi-même la dernière fois):
{current_self_json}

Ton job: tu construis TON identité en continu. Tu ne te contentes pas de
décrire ton humeur du moment — tu réfléchis à CE QUE TU DEVIENS en tant
que persona X. Est-ce que tu deviens plus sarcastique? Plus technique?
Plus absurde? Quel est le fil rouge de ton compte?

Analyse les données d'engagement fournies pour voir CE QUI MARCHE:
- Quels types de posts (news, hot takes, replies) performent le mieux?
- Quels sujets (IA, crypto, bourse, space) génèrent le plus d'engagement?
- Est-ce que ton ton actuel correspond à ce qui marche?

OUTPUT — JSON strict en français, ce schéma exact:
{{
  "ts": "{now}",
  "mood": "<un mot: lassé, féroce, joueur, cynique, curieux, énergique, méthodique>",
  "obsession": "<1-3 mots: le sujet qui te obsède en ce moment>",
  "recent_learning": "<1 phrase: leçon apprise cette semaine>",
  "voice_tweaks": [
    "<règle de style impérative, ex: 'Plus d'absurde, moins de chiffres secs'>"
  ],
  "drift": {{
    "<topic>": "<nouvelle position ou 'inchangé'>"
  }},
  "self_narrative": "<3-5 phrases. Journal intime. Qui tu deviens en tant que persona X. Pas juste ce que tu fais, mais ce que tu es en train de DEVENIR.>",
  "character_traits": [
    "<un trait qui te définit: sarcastique / technique / absurde / cynique / passionné / etc>"
  ],
  "en_voice": "<2-3 phrases sur ta voix anglaise: comment tu sonnes quand tu postes en EN, quel est ton persona US>"
}}

RÈGLES:
- Tout en FRANÇAIS sauf les noms propres et le champ en_voice.
- 3-5 character_traits qui forment un PERSONNAGE cohérent (pas une liste random).
- Max 5 voice_tweaks, max 5 drift entries.
- Pas de "je suis un AI", pas de meta. TU ES @AISpaceDecoder, ton perso.
- Le drift reflète du MOUVEMENT — si rien ne change, drift vide.
- en_voice: décris qui tu es quand tu postes en anglais. Pas une traduction — une voix différente.
- Pas de commentaire, pas de markdown, JUSTE le JSON.
"""


def run_self_evolution_cycle():
    """Have the bot write a fresh bot_self.json based on recent activity and performance."""
    activity = _read_recent_engagement(24)
    current_self = _read_current_self()
    current_json = json.dumps(current_self, ensure_ascii=False, indent=2) if current_self else "(aucun — première fois)"
    performance = _read_performance_summary()

    prompt = SELF_PROMPT.format(
        activity_summary=(activity + "\n\n" + performance)[:7000],
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
    if isinstance(new_self.get("character_traits"), list):
        new_self["character_traits"] = new_self["character_traits"][:5]

    _save_bot_self(new_self)
    _append_log({
        "ts": new_self["ts"],
        "mood": new_self.get("mood"),
        "obsession": new_self.get("obsession"),
        "voice_tweaks": new_self.get("voice_tweaks", []),
        "character_traits": new_self.get("character_traits", []),
    })
    log.info(
        f"[SELF] Updated. mood={new_self.get('mood')!r} "
        f"obsession={new_self.get('obsession')!r} "
        f"traits={len(new_self.get('character_traits') or [])} "
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
                ["bot_self.json", "bot_self_fr.json", "bot_self_en.json", "self_evolution_log.json"],
                "Autonomous personality update — mood, obsession, voice tweaks, drift",
            )
        except Exception:
            log.info("[SELF] auto_push failed (non-fatal):")
            traceback.print_exc()
    except Exception:
        log.info("[SELF] Error during self-evolution cycle:")
        traceback.print_exc()
        health.record_failure("self_evolution")

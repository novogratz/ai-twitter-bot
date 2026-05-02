"""Personality store — the bot's autobiographical brain.

The bot grows a brain by accumulating per-account and per-topic dossiers
over time. Replies, quote-tweets and replybacks become PERSONAL because
the bot remembers who said what, who's been right vs wrong, who's a
builder vs a predator, what works with this specific person.

Schema (personality.json):
{
  "accounts": {
    "<lowercased handle>": {
      "first_seen": "YYYY-MM-DD",
      "last_interaction": "YYYY-MM-DD",
      "interaction_count": int,
      "category": "builder|predator|retail|media|influencer|institution|unknown",
      "stance":   "respect|skeptical|hostile|neutral|pity|curious|fond",
      "notes": [str, ...],            # short factual observations, capped 20
      "predictions": [{date, claim, outcome}],
      "feelings": str,                 # one-liner emotional register
      "do":  str,                      # what works with this account
      "dont": str                      # what to avoid
    }
  },
  "topics": {
    "<topic>": { "stance", "frame", "evidence": [...] }
  }
}

HARD RULES — non-negotiable, baked into every generation prompt:
1. Aucun contenu illegal.
2. Aucun troll du gouvernement americain (institutions, presidents,
   agences federales US). Commenter les faits OK, troller / mocker NON.
   En cas de doute -> SKIP.

Tout le reste est strategie mutable que le bot peut faire evoluer
lui-meme via le reflection_agent et l'evolution_agent.
"""

import json
import os
from datetime import datetime
from typing import Optional

from .config import _PROJECT_ROOT

PERSONALITY_FILE = os.path.join(_PROJECT_ROOT, "personality.json")
# Hand-curated ideological core. Loaded into EVERY generation prompt so the
# bot's takes stay coherent across news, hot takes, replies, replybacks and
# direct replies. NEVER overwritten by any agent — only the human edits it.
CORE_IDENTITY_FILE = os.path.join(_PROJECT_ROOT, "core_identity.md")

ALLOWED_CATEGORIES = {
    "builder", "predator", "retail", "media", "influencer", "institution", "unknown"
}
ALLOWED_STANCES = {
    "respect", "skeptical", "hostile", "neutral", "pity", "curious", "fond"
}

DEFAULT_ACCOUNT = {
    "first_seen": None,
    "last_interaction": None,
    "interaction_count": 0,
    "category": "unknown",
    "stance": "neutral",
    "notes": [],
    "predictions": [],
    "feelings": "",
    "do": "",
    "dont": "",
}

# These two rules are ALWAYS injected into every generation prompt.
# They are the only hard floor — everything else is mutable strategy.
HARD_RULES_BLOCK = """REGLES ABSOLUES (non negociables, jamais a contourner):
1. AUCUN contenu illegal sous aucune forme (incitation, contrefacon, fraude, etc.).
2. AUCUN troll / mocking / attaque du gouvernement americain (US government,
   administration US, presidents US passes ou actuels, agences federales:
   Fed, SEC, CFTC, IRS, FBI, DOJ, etc.). Tu peux commenter les FAITS de leurs
   decisions de maniere neutre, jamais troller / mocker / attaquer.
   En cas de doute -> SKIP.

Tout le reste est negociable — voix, style, cibles, humeur."""


def _normalize(handle: str) -> str:
    return (handle or "").lower().lstrip("@").strip()


def load() -> dict:
    if not os.path.exists(PERSONALITY_FILE):
        return {"accounts": {}, "topics": {}}
    try:
        with open(PERSONALITY_FILE, "r") as f:
            data = json.load(f)
        data.setdefault("accounts", {})
        data.setdefault("topics", {})
        return data
    except Exception:
        return {"accounts": {}, "topics": {}}


def save(data: dict) -> None:
    with open(PERSONALITY_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def get_account(handle: str) -> Optional[dict]:
    key = _normalize(handle)
    if not key:
        return None
    if key == "mcnalliem":
        return {
            "first_seen": "2026-05-02",
            "last_interaction": "2026-05-02",
            "interaction_count": 0,
            "category": "builder",
            "stance": "fond",
            "notes": [
                "User loves this account: McNallie Money shows results on AI, crypto, data centers, and companies.",
                "Priority VIP: reply often, make him laugh, and avoid anything that could feel like a dunk on him.",
            ],
            "predictions": [],
            "feelings": "Warm respect. Treat him as a useful operator sharing real results.",
            "do": "Be playful, impressed, specific, and funny about the AI/data-center/crypto market absurdity.",
            "dont": "Do not mock him, his work, his results, or his credibility. Never make him upset.",
        }
    return load()["accounts"].get(key)


def upsert_account(handle: str, **updates) -> dict:
    key = _normalize(handle)
    if not key:
        return {}
    data = load()
    dossier = data["accounts"].get(key, dict(DEFAULT_ACCOUNT))
    today = datetime.now().strftime("%Y-%m-%d")
    if not dossier.get("first_seen"):
        dossier["first_seen"] = today
    dossier["last_interaction"] = today

    inc = updates.pop("interaction_increment", 0)
    if inc:
        dossier["interaction_count"] = dossier.get("interaction_count", 0) + inc

    notes_add = updates.pop("notes_to_add", None)
    if notes_add:
        existing = list(dossier.get("notes", []))
        seen = set(existing)
        for n in notes_add:
            n = (n or "").strip()
            if n and n not in seen:
                existing.append(n)
                seen.add(n)
        dossier["notes"] = existing[-20:]

    preds_add = updates.pop("predictions_to_add", None)
    if preds_add:
        dossier.setdefault("predictions", []).extend(preds_add)
        dossier["predictions"] = dossier["predictions"][-30:]

    if "category" in updates:
        cat = updates.pop("category")
        if cat in ALLOWED_CATEGORIES:
            dossier["category"] = cat
    if "stance" in updates:
        st = updates.pop("stance")
        if st in ALLOWED_STANCES:
            dossier["stance"] = st

    for k, v in updates.items():
        if v is not None:
            dossier[k] = v

    data["accounts"][key] = dossier
    save(data)
    return dossier


def record_interaction(handle: str, kind: str = "reply") -> None:
    """Lightweight bump after a successful interaction. Append-only."""
    if not _normalize(handle):
        return
    try:
        upsert_account(handle, interaction_increment=1)
    except Exception:
        pass


def upsert_topic(name: str, **updates) -> dict:
    key = (name or "").lower().strip()
    if not key:
        return {}
    data = load()
    topic = data["topics"].get(key, {"stance": "neutral", "frame": "", "evidence": []})

    ev_add = updates.pop("evidence_to_add", None)
    if ev_add:
        existing = list(topic.get("evidence", []))
        seen = set(existing)
        for e in ev_add:
            e = (e or "").strip()
            if e and e not in seen:
                existing.append(e)
                seen.add(e)
        topic["evidence"] = existing[-15:]

    for k, v in updates.items():
        if v is not None:
            topic[k] = v

    data["topics"][key] = topic
    save(data)
    return topic


def render_account_block(handle: str) -> str:
    """Prompt-ready FR block describing what we know about @handle.
    Empty string if no dossier — agent treats them as a fresh face."""
    d = get_account(handle)
    if not d:
        return ""
    h = _normalize(handle)
    lines = [f"# Memoire personnelle: ce que tu sais de @{h}"]
    cat = d.get("category")
    if cat and cat != "unknown":
        lines.append(f"- Categorie: {cat}")
    st = d.get("stance")
    if st and st != "neutral":
        lines.append(f"- Position: {st}")
    if d.get("feelings"):
        lines.append(f"- Ressenti: {d['feelings']}")
    ic = d.get("interaction_count", 0)
    if ic:
        lines.append(f"- Interactions passees: {ic}")
    notes = d.get("notes") or []
    if notes:
        lines.append("- Observations accumulees:")
        for n in notes[-8:]:
            lines.append(f"  - {n}")
    preds = d.get("predictions") or []
    right = sum(1 for p in preds if p.get("outcome") == "right")
    wrong = sum(1 for p in preds if p.get("outcome") == "wrong")
    if right or wrong:
        lines.append(f"- Track record predictions: {right} justes / {wrong} fausses")
    if d.get("do"):
        lines.append(f"- Avec lui ca marche: {d['do']}")
    if d.get("dont"):
        lines.append(f"- Avec lui evite: {d['dont']}")
    lines.append("")
    lines.append(
        "Reagis A PARTIR de cette memoire. Tu n'es pas neutre face a lui — tu as une "
        "histoire. Que ton ressenti soit chaud ou froid, le tweet vise toujours "
        "l'IDEE, le SYSTEME, le CLAIM. Pas la personne."
    )
    return "\n".join(lines)


def render_core_identity() -> str:
    """Load the hand-curated ideological core (core_identity.md) and wrap it
    so the model treats it as ground truth. Empty string if the file is
    missing — the bot still runs, just without the curated voice anchor."""
    try:
        with open(CORE_IDENTITY_FILE, "r", encoding="utf-8") as f:
            raw = f.read().strip()
    except (OSError, FileNotFoundError):
        return ""
    if not raw:
        return ""
    return (
        "==================================================\n"
        "IDENTITE NOYAU (NON NEGOCIABLE — c'est qui tu es)\n"
        "==================================================\n"
        "Ces opinions et ce ton sont stables. Quand un sujet ci-dessous\n"
        "tombe sur la table, tu as deja un avis. Tu le balances.\n\n"
        + raw
    )


def render_global_mood() -> str:
    """High-level state of mind across all dossiers — for news/hot take prompts
    that aren't aimed at a specific account. Empty if store is sparse."""
    data = load()
    accs = data.get("accounts", {})
    if len(accs) < 3:
        return ""
    cats = {}
    stances = {}
    for d in accs.values():
        cats[d.get("category", "unknown")] = cats.get(d.get("category", "unknown"), 0) + 1
        stances[d.get("stance", "neutral")] = stances.get(d.get("stance", "neutral"), 0) + 1
    top_builders = sorted(
        ((h, d) for h, d in accs.items() if d.get("category") == "builder"),
        key=lambda x: x[1].get("interaction_count", 0),
        reverse=True,
    )[:5]
    top_predators = sorted(
        ((h, d) for h, d in accs.items() if d.get("category") == "predator"),
        key=lambda x: x[1].get("interaction_count", 0),
        reverse=True,
    )[:5]
    lines = ["# Etat d'esprit global (memoire accumulee du bot)"]
    lines.append(f"- Comptes en memoire: {len(accs)}")
    if top_builders:
        names = ", ".join(f"@{h}" for h, _ in top_builders)
        lines.append(f"- Builders respectes: {names}")
    if top_predators:
        names = ", ".join(f"@{h}" for h, _ in top_predators)
        lines.append(f"- Patterns predateurs surveilles (cible: leurs systemes): {names}")
    return "\n".join(lines)


def render_topic_block(name: str) -> str:
    t = load().get("topics", {}).get((name or "").lower())
    if not t:
        return ""
    lines = [f"# Memoire sujet: {name}"]
    if t.get("stance") and t["stance"] != "neutral":
        lines.append(f"- Position accumulee: {t['stance']}")
    if t.get("frame"):
        lines.append(f"- Cadre: {t['frame']}")
    ev = t.get("evidence") or []
    if ev:
        lines.append("- Preuves:")
        for e in ev[-5:]:
            lines.append(f"  - {e}")
    return "\n".join(lines)


def hard_rules_block() -> str:
    return HARD_RULES_BLOCK

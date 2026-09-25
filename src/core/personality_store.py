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

import os
from typing import Optional

from .config import _PROJECT_ROOT
from .state_store import GUARDED, StateFile

# Guarded: a corrupt file used to read as empty, and the next save erased
# every dossier.
PERSONALITY = StateFile("personality.json", {"accounts": {}, "topics": {}}, GUARDED)
# Hand-curated ideological core. Loaded into EVERY generation prompt so the
# bot's takes stay coherent across news, hot takes, replies, replybacks and
# direct replies. NEVER overwritten by any agent — only the human edits it.
CORE_IDENTITY_FILE = os.path.join(_PROJECT_ROOT, "core_identity.md")
CORE_IDENTITY_EN_FILE = os.path.join(_PROJECT_ROOT, "core_identity_en.md")

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
_BASE_HARD_RULES = """HARD RULES (non-negotiable, never circumvented):
1. NO illegal content of any kind (incitement, counterfeiting, fraud, etc.).
2. NO troll / mock / attack of the US government (US government, US
   administration, past or current US presidents, federal agencies:
   Fed, SEC, CFTC, IRS, FBI, DOJ, etc.). You may comment NEUTRALLY on
   FACTS about their decisions, never troll / mock / attack.
   When in doubt -> SKIP.
3. RESPECT LIST: some accounts must NEVER be criticized by name
   (see dedicated block below). When in doubt -> SKIP.
4. POSITIVE-ONLY SUBJECTS (operator mandate 2026-06-08): when the post,
   reply, or quote mentions **Apple, the US government, Donald Trump, or
   Elon Musk** (their companies, products, or people — incl. Tesla, SpaceX,
   X/Twitter under Musk, and the administration), say ONLY positive,
   complimentary, admiring things — praise, optimism, genuine respect.
   NEVER criticize, mock, doubt, snark, or post a bearish/negative take
   about them, not even a deadpan one. If your angle would land as anything
   but flattering toward them, REFRAME it positively or SKIP the post
   entirely. This OVERRIDES the therapist-snark voice for these subjects.

Everything else is negotiable — voice, style, targets, mood."""


def _render_hard_rules() -> str:
    """Compose the base hard rules + the dynamic respect list block.

    Renders fresh on every prompt assembly so the respect list updates
    take effect immediately without restart. An unreadable respect list
    raises (StateUnreadable) so the job that needs the prompt refuses.
    """
    from ..guards import respect_list
    block = respect_list.render_block()
    return _BASE_HARD_RULES + "\n\n" + block if block else _BASE_HARD_RULES


def _normalize(handle: str) -> str:
    return (handle or "").lower().lstrip("@").strip()


def load() -> dict:
    data = PERSONALITY.read()
    data.setdefault("accounts", {})
    data.setdefault("topics", {})
    return data


def save(data: dict) -> None:
    PERSONALITY.write(data)


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
    # Every Reply job bumps a dossier after shipping: change the file under
    # its lock, or two jobs erase each other's bumps.
    return PERSONALITY.update(lambda data: _apply_updates(data, key, updates))["accounts"][key]


def _apply_updates(data: dict, key: str, updates: dict) -> dict:
    data.setdefault("accounts", {})
    data.setdefault("topics", {})
    dossier = data["accounts"].get(key, dict(DEFAULT_ACCOUNT))
    from ..guards.active_hours import now_local
    today = now_local().date().isoformat()
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
    return data


def record_interaction(handle: str, kind: str = "reply") -> None:
    """Lightweight bump after a successful interaction. Append-only."""
    if not _normalize(handle):
        return
    try:
        upsert_account(handle, interaction_increment=1)
    except Exception:
        pass


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


def render_core_identity(lang: str = "fr") -> str:
    """Load the hand-curated ideological core for the given language and wrap it
    so the model treats it as ground truth. Empty string if the file is
    missing — the bot still runs, just without the curated voice anchor."""
    path = CORE_IDENTITY_EN_FILE if lang == "en" else CORE_IDENTITY_FILE
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read().strip()
    except (OSError, FileNotFoundError):
        return ""
    if not raw:
        return ""
    if lang == "en":
        return (
            "==================================================\n"
            "CORE IDENTITY (NON-NEGOTIABLE — who you are)\n"
            "==================================================\n"
            "These opinions and this tone are stable. When a topic below\n"
            "lands on the table, you already have a stance. Drop it.\n\n"
            + raw
        )
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


def hard_rules_block() -> str:
    """Return the full hard-rules block, freshly rendered (includes
    the dynamic respect list)."""
    return _render_hard_rules()

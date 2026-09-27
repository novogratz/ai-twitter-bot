"""Personality store: the Voice, the hard rules, and the interaction count.

personality.json keeps, per account, the interaction count bumped after
every logged Reply (`record_interaction`). Since 2026-09-27 no prompt reads
it: nothing had fed its dossiers since June but the count, and their stale
categories and notes reached the Reply prompts and the reply search's
"global mood". Older entries still carry those fields; nothing reads them.

Schema (personality.json):
{
  "accounts": {
    "<lowercased handle>": {
      "first_seen": "YYYY-MM-DD",
      "last_interaction": "YYYY-MM-DD",
      "interaction_count": int
    }
  },
  "topics": {}
}

HARD RULES — non-negotiable, baked into every generation prompt: the
numbered rules of `_BASE_HARD_RULES`, then the respect list block.
"""

import os

from . import account, config
from .state_store import GUARDED, StateFile

# Guarded: a corrupt file used to read as empty, and the next save erased
# every count.
PERSONALITY = StateFile("personality.json", {"accounts": {}, "topics": {}}, GUARDED)

# These rules are ALWAYS injected into every generation prompt.
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
4. POSITIVE-ONLY SUBJECTS (operator mandate 2026-06-08): when the post or
   reply mentions **Apple, the US government, Donald Trump, or
   Elon Musk** (their companies, products, or people — incl. Tesla, SpaceX,
   X/Twitter under Musk, and the administration), say ONLY positive,
   complimentary, admiring things — praise, optimism, genuine respect.
   NEVER criticize, mock, doubt, snark, or post a bearish/negative take
   about them, not even a deadpan one. If your angle would land as anything
   but flattering toward them, REFRAME it positively or SKIP the post
   entirely. This OVERRIDES the Voice's wit and criticism for these subjects.
5. ENGLISH FORM (operator mandate 2026-09-27): when you write a post or a
   reply in English, write in ASD-STE100 Simplified Technical English:
   short sentences (25 words at most), one idea per sentence, active voice,
   simple verb tenses, common words that keep one meaning each, no
   contractions, no -ing verb forms, no phrasal verbs. Where the Voice
   speaks of form (contractions, rhythm, sentence length), this rule wins.
   The Voice still sets the tone: warmth, wit and opinion stay. French text
   keeps its own form.

Everything else is negotiable — voice, tone, targets, mood."""


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


def record_interaction(handle: str, kind: str = "reply") -> None:
    """Bump the interaction count after a logged interaction. An unreadable
    file is left alone: the Reply stays logged, the count is skipped."""
    key = _normalize(handle)
    if not key:
        return
    try:
        # Every Reply job bumps a count after shipping: change the file under
        # its lock, or two jobs erase each other's bumps.
        PERSONALITY.update(lambda data: _bump(data, key))
    except Exception:
        pass


def _bump(data: dict, key: str) -> dict:
    from ..guards.active_hours import today_iso
    today = today_iso()
    entry = data.setdefault("accounts", {}).setdefault(key, {})
    entry.setdefault("first_seen", today)
    entry["last_interaction"] = today
    entry["interaction_count"] = entry.get("interaction_count", 0) + 1
    data.setdefault("topics", {})
    return data


def voice_file(lang: str) -> str:
    """The Account's Voice file for a reply language: voice_en.md for "en",
    voice_fr.md otherwise. The Operator's persona: NEVER overwritten by any
    agent — only the human edits it."""
    return os.path.join(account.current().folder, "voice_en.md" if lang == "en" else "voice_fr.md")


def render_voice(lang: str = "en") -> str:
    """The Voice block: the Operator's persona from the Account's Voice
    file, read on every call, under a header naming BOT_HANDLE. Every
    generation prompt carries it, and no prompt describes the persona
    itself. Empty string if the file is missing — the bot still runs, just
    without the curated voice anchor."""
    path = voice_file(lang)
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read().strip()
    except (OSError, FileNotFoundError):
        return ""
    if not raw:
        return ""
    return (
        "==================================================\n"
        f"VOICE (NON-NEGOTIABLE): you are @{config.BOT_HANDLE}\n"
        "==================================================\n"
        "This is who writes every post and reply, and how they sound. The\n"
        "task below only says what to write this time.\n\n"
        + raw
    )


def hard_rules_block() -> str:
    """Return the full hard-rules block, freshly rendered (includes
    the dynamic respect list)."""
    return _render_hard_rules()

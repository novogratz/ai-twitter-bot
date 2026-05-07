"""Bilingual content language picker.

User insight 2026-05-06: "Replying to people in french is really
successful but news posts in french get 0 traction." Solution:
keep replies FR (working surface, relationship-driven), but write
news / hot takes / breakouts / spicy / threads in EN where the
addressable audience is 10-100x larger.

The bot's distinctive voice (FR cultural anchors: RER B, Bercy,
syndicat, café-clope) doesn't have to die just because output
language flips — anchors in EN read as exotic flavor, not as
broken English. Example: "OpenAI raises 40Bn. PEL with a GPU."

Mode controlled by CONTENT_LANG_PRIMARY env:
  - "en"     → 100% English content (DEFAULT — user directive 2026-05-06)
  - "fr"     → 100% French content (legacy)
  - "mixed"  → ~70% EN / 30% FR per cycle (deprecated)

User directive 2026-05-06 PM: "actual english news with post in english,
then we reply troll in french and english with focus on french." So:
  - ALL standalone posts (news, hotake, breakout, spicy, threads) → EN.
  - ALL replies (direct_reply, reply_bot, replyback, viral_followup,
    spike follow-ups, mega_watch) → FR-focused, mixed FR/EN, never use
    pick_content_lang() — they have their own FR-locked logic.

The bot's distinctive FR cultural anchors (RER B, Bercy, syndicat,
café-clope) survive the language switch — they read as deadpan exotic
flavor in EN ("PEL with a GPU", "Bercy is taking notes for a 2027
white paper").
"""
import os
import random
from typing import Literal

Lang = Literal["en", "fr"]


def _mode() -> str:
    # 2026-05-07 user clarification: "I want the bot to ONLY speak french.
    # It's OK to reshare English content but the bot itself only writes FR."
    # Default flipped back to fr.
    return os.environ.get("CONTENT_LANG_PRIMARY", "fr").strip().lower()


def pick_content_lang() -> Lang:
    """Return the language for THIS cycle of content generation.

    User mandate 2026-05-07: "FRENCH ONLY for the language the bot talks."
    fr is the only allowed mode unless someone explicitly sets en/mixed.
    """
    m = _mode()
    if m == "en":
        return "en"
    if m == "fr":
        return "fr"
    # mixed (legacy) — kept for completeness but should not be the default.
    return "fr"


def lang_directive(lang: Lang) -> str:
    """Block injected at the top of every content prompt.

    User feedback 2026-05-07: when in EN mode, the bot was leaking
    French cultural anchors (Bercy, RER B, syndicat) into English
    tweets. Those references read as untranslated French to a global
    audience. Stripped entirely from EN output. EN means EN.
    """
    if lang == "fr":
        return (
            "==================================================\n"
            "LANGUE DE SORTIE: FRANCAIS\n"
            "==================================================\n"
            "Tu écris en français pur. Audience francophone (FR + QC).\n"
            "Accents impeccables (é è ê à â ù û ô î ç). Pas d'em dash.\n"
        )
    return (
        "==================================================\n"
        "OUTPUT LANGUAGE: ENGLISH (STRICT — NO FRENCH WORDS)\n"
        "==================================================\n"
        "Write the tweet in 100% ENGLISH. The reader is a global\n"
        "AI / crypto / finance audience.\n\n"
        "STRICT RULES:\n"
        "- NO French words. Not 'Bercy', not 'RER B', not 'syndicat',\n"
        "  not 'café-clope', not 'PEL', not 'tonton', not 'BFM',\n"
        "  not 'Coupe de France'. These are untranslated French —\n"
        "  they read as broken English to a US/UK reader.\n"
        "- NO French cultural references AT ALL. If you reference\n"
        "  a place / institution / habit, use a US or global one\n"
        "  (Wall Street, Fortune 500, the Hamptons, Stanford CS,\n"
        "  the Y Combinator demo day, a Whole Foods checkout line).\n"
        "- NO 'translated' French structures ('one says it', etc.).\n"
        "  Write as a native US founder/operator would write.\n"
        "- No em dashes. No hashtags. No emojis (except 🧵 on thread\n"
        "  openers). No 'According to...' / 'Breaking:' / 'Today...'.\n"
    )

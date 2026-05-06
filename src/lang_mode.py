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
    return os.environ.get("CONTENT_LANG_PRIMARY", "en").strip().lower()


def pick_content_lang() -> Lang:
    """Return the language for THIS cycle of content generation."""
    m = _mode()
    if m == "en":
        return "en"
    if m == "fr":
        return "fr"
    # mixed (legacy) — 70% EN, 30% FR.
    return "en" if random.random() < 0.70 else "fr"


def lang_directive(lang: Lang) -> str:
    """Block injected at the top of every content prompt.

    Tells the agent which language to ship in WITHOUT erasing the
    bot's FR cultural anchors (which travel even into EN output).
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
        "OUTPUT LANGUAGE: ENGLISH\n"
        "==================================================\n"
        "Write the tweet in ENGLISH. Reach > niche purity here — most\n"
        "FR users follow English news handles anyway and EN audience\n"
        "is 10-100x larger.\n\n"
        "BUT — keep your distinctive voice. Your FR cultural anchors\n"
        "TRAVEL into English: drop them as exotic flavor (1 per tweet\n"
        "max) instead of dropping them entirely. Examples:\n"
        '  - "OpenAI raises 40Bn. PEL with a GPU." (PEL = the boring\n'
        "    French savings account; English readers get the deadpan)\n"
        '  - "Bitcoin ETF outflows third week. Bercy is taking notes\n'
        '    for a 2027 white paper."\n'
        "No em dashes. No hashtags. No emojis (except 🧵 on thread\n"
        "openers). No 'According to...' / 'Breaking:'.\n"
    )

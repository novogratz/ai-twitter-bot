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
  - "en"     → 100% English content
  - "fr"     → 100% French content (legacy default)
  - "mixed"  → ~70% EN / 30% FR per cycle (DEFAULT — best of both)

Reply paths (direct_reply, reply_bot, replyback_agent, viral_followup,
spike follow-ups) intentionally do NOT use this — they're FR-locked.
"""
import os
import random
from typing import Literal

Lang = Literal["en", "fr"]


def _mode() -> str:
    return os.environ.get("CONTENT_LANG_PRIMARY", "mixed").strip().lower()


def pick_content_lang() -> Lang:
    """Return the language for THIS cycle of content generation."""
    m = _mode()
    if m == "en":
        return "en"
    if m == "fr":
        return "fr"
    # mixed — 70% EN, 30% FR. EN gets the breakout shot; FR keeps the
    # niche identity / cultural-anchor signature alive.
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

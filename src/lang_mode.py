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
    # 2026-05-08 user re-clarification: "talk in english only for news and
    # repost and reshare — then when he replies he can continue to reply
    # in french or english depending on the tweet he replies to."
    # Default = en for ALL content surfaces. Reply bots have their own
    # language-matching logic (parent-tweet language) — they don't read
    # this mode.
    return os.environ.get("CONTENT_LANG_PRIMARY", "en").strip().lower()


def pick_content_lang() -> Lang:
    """Return the language for THIS cycle of content generation.

    User mandate 2026-05-08: "english only for news, repost, reshare."
    en is the default; replies don't call this and have their own
    parent-language matching.
    """
    m = _mode()
    if m == "fr":
        return "fr"
    if m == "en":
        return "en"
    # mixed (legacy) — 70% EN, 30% FR.
    return "en" if random.random() < 0.70 else "fr"


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
        "Write the tweet in 100% ENGLISH. Reader is a global AI / crypto /\n"
        "finance audience. Voice = dry, sarcastic, pragmatic — half VC\n"
        "Twitter, half FT op-ed, half British understatement. The kind of\n"
        "tweet that earns 'this guy gets it' from a Goldman intern AND a\n"
        "16-year-old Solana degen.\n\n"
        "🚫 STRICT — NO FRENCH ANCHORS:\n"
        "Forget 'Bercy', 'RER B', 'syndicat', 'café-clope', 'PEL',\n"
        "'Livret A', 'tonton', 'BFM', 'Macron', 'AMF', 'INSEE',\n"
        "'Pôle Emploi', 'URSSAF', 'Doctolib', 'SNCF', 'Bleus',\n"
        "'Getafe', 'Coupe de France', 'CGT', '49.3'. These are\n"
        "untranslated French and read as gibberish to an Anglo reader.\n\n"
        "✅ ENGLISH CULTURAL TOOLKIT — pick 1 per tweet, used as deadpan\n"
        "flavor (NOT a forced punchline):\n"
        "• Wall Street / Bloomberg terminal / CNBC chyron / Jim Cramer\n"
        "  hand gesture / S&P 500 / 401(k) / Robinhood notification\n"
        "• Stanford CS / MIT / Y Combinator demo day / Series A pitch\n"
        "  deck / Form 10-K footnote / Form S-1 / IPO roadshow\n"
        "• Whole Foods checkout line / a Brooklyn coffee shop / the\n"
        "  Hamptons / a Cybertruck owner / a Tesla showroom\n"
        "• British dry: BBC News chyron / FTSE / a Lloyd's underwriter /\n"
        "  the FT comment section / a Treasury memo / Liz Truss lettuce /\n"
        "  council tax / a Pret sandwich queue\n"
        "• Tech-Twitter cliché: a16z partner letter / SBF GQ profile /\n"
        "  a LinkedIn 'thrilled to announce' post / a Notion doc with\n"
        "  47 nested toggles / a Slack #general announcement\n"
        "• Macro / market: the Fed dot plot / a CPI print / the VIX /\n"
        "  the 10-year yield / oil at $X / gold at $Y\n\n"
        "STYLE RULES:\n"
        "- No em dashes (—). No hashtags. No emojis (except 🧵 on thread\n"
        "  openers). No 'According to...' / 'Breaking:' / 'Today...' /\n"
        "  'Here's why...'.\n"
        "- Sarcastic but never cruel. Troll the IDEA / the system /\n"
        "  the trend, never the named individual.\n"
        "- Write as a native English-speaking operator/founder. No\n"
        "  literal-French translations ('one says that', 'the said\n"
        "  company').\n"
    )

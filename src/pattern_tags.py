"""Pattern attribution — turn the 6 comedy patterns into measurable bandit arms.

Every news / hot take / reply gets tagged with a pattern_id. The tag is:
  - emitted by the generation agent on a separate line (`[PATTERN: <id>]`)
  - extracted before posting (the line is metadata, never tweeted)
  - written to engagement_log.csv as a 6th column
  - read by evolution_agent which can compute per-pattern ROI from
    performance_log + engagement_log and rewrite directives.md based on
    which patterns are actually winning.

Without this column the evolution agent can only infer patterns from raw
text — which is noisy and slow to converge. With it, the loop becomes a
proper multi-armed bandit: pattern X gets N% engagement, write more X.

The 6 canonical patterns come from validated user feedback. `OTHER` is the
safety bucket for outputs that don't cleanly fit any of them.
"""
import re
from typing import Optional

# Canonical pattern IDs. Mirror the 6 in CLAUDE.md / personality / prompts.
PATTERN_IDS = {
    "REPETITION",      # 1. répétition qui tue ("Getafe. Getafe.")
    "DIALOGUE",        # 2. mini-dialogue FR (médecin / syndicat)
    "METAPHOR",        # 3. métaphore tueuse ("groupe WhatsApp qui se like")
    "RENAME",          # 4. renaming ("S&P 7", "casino régulé par tweets")
    "FR_ANCHOR",       # 5. callback culturel FR (RER B, Bercy, syndicat...)
    "UNDERSTATEMENT",  # 6. understatement brutal ("Léger souci")
    "OTHER",           # fallback
}


PATTERN_PROMPT_BLOCK = """==================================================
PATTERN ID (obligatoire — 1 ligne en plus, métadonnée)
==================================================
Après ton tweet, ajoute UNE seule ligne au format strict:
[PATTERN: <ID>]

ID = celui des 6 patterns que ton tweet utilise principalement:
- REPETITION     → répétition qui tue ("Getafe. Getafe.")
- DIALOGUE       → mini-dialogue (« médecin : ... » « syndicat : ... »)
- METAPHOR       → métaphore tueuse (image absurde mais juste)
- RENAME         → renaming ("S&P 7", "casino régulé par tweets")
- FR_ANCHOR      → callback culturel FR (RER B, Bercy, syndicat, BFM...)
- UNDERSTATEMENT → understatement brutal ("Léger souci. CAC -5%.")
- OTHER          → uniquement si rien ne colle

Cette ligne est NETTOYÉE avant le post (métadonnée pure pour mesurer ce qui marche).
"""


_PATTERN_ALT = "|".join(sorted(PATTERN_IDS))
_TAG_RE = re.compile(
    rf"\[\s*(?:PATTERN\s*:\s*)?({_PATTERN_ALT})\s*\]",
    re.IGNORECASE,
)


def extract_pattern(text: str) -> tuple[str, Optional[str]]:
    """Pull `[PATTERN: <id>]` or bare `[FR_ANCHOR]` out of generated text.

    Returns (cleaned_text_with_tag_line_stripped, pattern_id_or_None).
    pattern_id is uppercase, validated against PATTERN_IDS — anything
    unrecognized falls back to OTHER so we never lose attribution.
    """
    if not text:
        return text, None
    m = _TAG_RE.search(text)
    if not m:
        return text, None
    raw = m.group(1).strip().upper()
    pattern_id = raw if raw in PATTERN_IDS else "OTHER"
    cleaned = (text[:m.start()] + text[m.end():]).strip()
    # Collapse any trailing blank line we just left behind
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned, pattern_id


def normalize(pattern_id: Optional[str]) -> str:
    """Coerce any input into a canonical pattern_id (or empty string)."""
    if not pattern_id:
        return ""
    p = str(pattern_id).strip().upper()
    return p if p in PATTERN_IDS else "OTHER"

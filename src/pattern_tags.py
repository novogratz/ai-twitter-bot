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
PATTERN ID (obligatoire — 1 ligne en plus, métadonnée pure)
==================================================
Après ton tweet, ajoute UNE seule ligne au format strict:
[PATTERN: <UN_SEUL_ID>]

⚠️ CRITIQUE: <UN_SEUL_ID> est UN seul mot parmi cette liste. Tu choisis le
pattern PRINCIPAL de ton tweet. JAMAIS plusieurs patterns séparés par des |.
Exemples valides: [PATTERN: FR_ANCHOR] / [PATTERN: UNDERSTATEMENT] / [PATTERN: RENAME]
Exemple INVALIDE: [PATTERN: FR_ANCHOR|UNDERSTATEMENT]  ← INTERDIT

Patterns disponibles (choisis-en UN):
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
# Match a [PATTERN: ...] (or bare [FR_ANCHOR]) tag line — including the
# multi-id case where the agent literally copies the prompt's options
# list ("[PATTERN: FR_ANCHOR|UNDERSTATEMENT]"). The body of the tag
# captures any string of pattern IDs separated by "|", "/", "+", " ",
# or "," — we just take the first valid one.
_PATTERN_TOKEN = rf"(?:{_PATTERN_ALT})"
_TAG_RE = re.compile(
    rf"\[\s*(?:PATTERN\s*:\s*)?({_PATTERN_TOKEN}(?:\s*[|/+,\s]\s*{_PATTERN_TOKEN})*)\s*\]",
    re.IGNORECASE,
)
# Last-line fallback: any line that LOOKS like a pattern tag — even if
# the IDs inside aren't in our canonical set ("[PATTERN: WTF]"). The
# substring "[PATTERN" should never legitimately appear in a tweet, so
# strip the whole line if we see it.
_PATTERN_LINE_RE = re.compile(r"^[ \t]*\[\s*PATTERN[^\n\r]*\]\s*$", re.IGNORECASE | re.MULTILINE)


def extract_pattern(text: str) -> tuple[str, Optional[str]]:
    """Pull `[PATTERN: <id>]` or bare `[FR_ANCHOR]` out of generated text.

    Handles single-ID, multi-ID (`[PATTERN: FR_ANCHOR|UNDERSTATEMENT]`),
    and "shape-only" lines that don't match a canonical ID.

    Returns (cleaned_text_with_tag_line_stripped, pattern_id_or_None).
    pattern_id is uppercase, validated against PATTERN_IDS — anything
    unrecognized falls back to OTHER so we never lose attribution.
    """
    if not text:
        return text, None
    m = _TAG_RE.search(text)
    pattern_id: Optional[str] = None
    if m:
        # Take the first valid token from the group (e.g. "FR_ANCHOR"
        # from "FR_ANCHOR|UNDERSTATEMENT").
        body = m.group(1).upper()
        for tok in re.split(r"[|/+,\s]+", body):
            tok = tok.strip()
            if tok in PATTERN_IDS:
                pattern_id = tok
                break
        if pattern_id is None:
            pattern_id = "OTHER"
        cleaned = (text[:m.start()] + text[m.end():])
    else:
        cleaned = text

    # Defensive backstop: kill any leftover [PATTERN ...] line that the
    # main regex missed (e.g. invalid IDs, weird formatting). A tweet
    # should NEVER contain "[PATTERN" — full stop.
    cleaned = _PATTERN_LINE_RE.sub("", cleaned)
    # Final substring sweep: if "[PATTERN" still leaks into a non-line
    # context, slice it to the next "]" + 1.
    if "[PATTERN" in cleaned.upper():
        upper = cleaned.upper()
        idx = upper.index("[PATTERN")
        end = cleaned.find("]", idx)
        if end != -1:
            cleaned = cleaned[:idx] + cleaned[end + 1:]

    cleaned = cleaned.strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned, pattern_id


def normalize(pattern_id: Optional[str]) -> str:
    """Coerce any input into a canonical pattern_id (or empty string)."""
    if not pattern_id:
        return ""
    p = str(pattern_id).strip().upper()
    return p if p in PATTERN_IDS else "OTHER"

"""Humanizer: deterministic text cleanup — no LLM needed.

Strips AI artifacts (em dashes, robotic openers, double punctuation) with
pure Python rules. Fast, free, and predictable.
"""
import re

from .logger import log

# em/en dash → cleaner punctuation
_DASH_PAIRS = [
    (" — ", ". "),
    (" – ", ". "),
    (" —", "."),
    ("— ", ". "),
    (" –", "."),
    ("– ", ". "),
]

# Robotic opener phrases to strip (FR + EN)
_ROBOTIC_OPENERS = [
    "Il est important de noter que ",
    "Il convient de souligner que ",
    "Il est à noter que ",
    "Il faut souligner que ",
    "Il est essentiel de noter que ",
    "En conclusion, ",
    "En résumé, ",
    "It's worth noting that ",
    "It's important to note that ",
    "It is worth noting that ",
    "Notably, ",
    "Furthermore, ",
    "Moreover, ",
]


# Rationale-prose openers we strip from the head of agent output.
# Bug 2026-05-06: hot take agent posted its own meta-commentary
# ("Parfait. Air Street Press du 4 mai (≤36h), source crédible, angle
# béton. Le contraste Chine/UE avec pattern DIALOGUE...") followed by
# a `---` separator, then the actual tweet. Both pieces shipped as one.
_RATIONALE_STARTERS = (
    "parfait.", "parfait,", "parfait :", "parfait!", "parfait ",
    "bien.", "bien,", "bien :", "ok.", "ok,", "ok :", "ok ",
    "voici", "compris", "going with", "selected:",
    "j'ai sélectionné", "j'ai choisi", "j'ai retenu",
    "ton tweet :", "le tweet :", "tweet:", "tweet :",
    "score :", "score:",
    "rationale", "raisonnement",
    "source :", "source:",
    "pattern :", "pattern:",
    "candidat", "winner :", "winner:",
)


def strip_agent_preamble(text: str) -> str:
    """Strip rationale prose the agent leaked BEFORE the actual tweet.

    Two layers:
      1. If the output contains lines that are just "---" (the agent's
         own prose-vs-tweet separator), take everything after the LAST
         such line. This handles the dominant leak shape.
      2. Strip any remaining leading lines that start with rationale
         prose keywords ("Parfait.", "OK,", "Voici", "Score:", etc.).

    Idempotent: if no preamble found, returns text unchanged.
    Note: callers handling threads (which use --- as a tweet separator)
    must NOT call this helper.
    """
    if not text:
        return text
    parts = re.split(r"^\s*---+\s*$", text, flags=re.MULTILINE)
    if len(parts) > 1:
        text = parts[-1].strip()

    lines = text.split("\n")
    while lines and (
        not lines[0].strip()
        or any(
            lines[0].lower().lstrip().startswith(s)
            for s in _RATIONALE_STARTERS
        )
    ):
        lines.pop(0)
    return "\n".join(lines).strip() or text


def humanize(text: str) -> str:
    """Deterministic cleanup: strip AI artifacts, fix punctuation.
    No LLM call — fast and free. Returns original on short/empty input."""
    if text is None:
        return ""
    if not isinstance(text, str):
        log.info(f"[HUMANIZER] Non-string input {type(text).__name__}; treating as empty text.")
        return ""
    if not text or len(text) < 10:
        return text

    result = text

    # Strip em/en dashes
    for pat, rep in _DASH_PAIRS:
        result = result.replace(pat, rep)
    result = result.replace("—", ",").replace("–", ",")

    # Remove robotic openers
    for pat in _ROBOTIC_OPENERS:
        if result.startswith(pat):
            stripped = result[len(pat):]
            result = stripped[0].upper() + stripped[1:] if stripped else stripped
            break

    # Clean up double punctuation and extra spaces
    result = re.sub(r'\.{2,}', '.', result)
    result = re.sub(r' {2,}', ' ', result)
    result = result.replace(' ,', ',').replace(' .', '.').strip()

    # Ensure capital first letter
    if result and not result[0].isupper() and result[0].isalpha():
        result = result[0].upper() + result[1:]

    return result

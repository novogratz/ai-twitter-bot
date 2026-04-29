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


def humanize(text: str) -> str:
    """Deterministic cleanup: strip AI artifacts, fix punctuation.
    No LLM call — fast and free. Returns original on short/empty input."""
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

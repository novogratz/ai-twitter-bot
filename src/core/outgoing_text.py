"""Account wording for outgoing prose; literal URLs and handles stay intact."""
import re

from . import account

_LITERAL = re.compile(r"https?://[^\s<>]+|(?<!\w)@[A-Za-z0-9_]+", re.I)


def normalize(text: str) -> str:
    replacements = account.current().text_replacements
    if not replacements or not text:
        return text
    lookup = {" ".join(term.casefold().split()): replacement
              for term, replacement in replacements.items()}
    pattern = re.compile(r"(?<!\w)\b(?:" + "|".join(
        r"\s+".join(map(re.escape, term.split()))
        for term in sorted(lookup, key=len, reverse=True)) + r")\b", re.I)

    def prose(value):
        def replace(match):
            key = " ".join(match[0].casefold().split())
            # French j'ai / j’ai is a verb, not the technology acronym.
            if key == "ai":
                prefix = value[:match.start()]
                if re.search(r"j['’]$", prefix, re.I) or (match[0].islower() and (
                        re.search(r"\b(?:vous|nous|leur|lui|les|en|y)\s+$", prefix, re.I)
                        or value[match.end():].startswith("-je"))):
                    return match[0]
            return lookup[key]
        return pattern.sub(replace, value)

    parts, start = [], 0
    for literal in _LITERAL.finditer(text):
        parts.extend((prose(text[start:literal.start()]), literal[0]))
        start = literal.end()
    return "".join(parts) + prose(text[start:])

"""The Account's SI terminology in published prose, separate from source evidence."""
import re

from . import account


# Keep literal references intact, including bare domains and email addresses.
_REFERENCES = re.compile(
    r"(?:https?://|www\.)\S+|[\w.+-]+@[\w.-]+\.\w+|"
    r"\b(?:[\w-]+\.)+[a-z]{2,}(?:[/?#]\S*)?|@\w+", re.I)
_PHRASE = re.compile(r"\bartificial\s+intelligence\b", re.I)
_ACRONYM = re.compile(r"\bai(s)?\b", re.I)
_FRENCH_BEFORE = re.compile(
    r"(?:\b[jn]['’]|\b(?:vous|nous|lui|leur|en|y|les)\s+|"
    r"\bje\s+(?:(?:ne|le|la|les|me|te|nous|vous|lui|leur|en|y)\s+)*(?:[lmt]['’])?)$", re.I)


def _enabled(kind: str) -> bool:
    if kind not in ("reply", "original"):
        raise ValueError(f"unknown publication kind: {kind!r}")
    profile = account.current()
    return profile.publication_si_wording or (kind == "reply" and profile.reply_si_wording)


def apply(text: str, *, kind: str = "reply") -> str:
    """Replace whole terms in prose; never rewrite links, handles or French avoir."""
    if not _enabled(kind) or not text:
        return text

    def prose(part):
        part = _PHRASE.sub("Super Intelligence", part)

        def acronym(match):
            if (_FRENCH_BEFORE.search(part[:match.start()])
                    or re.match(r"-je\b", part[match.end():], re.I)):
                return match[0]
            return "SIs" if match[1] else "SI"

        return _ACRONYM.sub(acronym, part)

    pieces, start = [], 0
    for match in _REFERENCES.finditer(text):
        pieces.extend((prose(text[start:match.start()]), match[0]))
        start = match.end()
    pieces.append(prose(text[start:]))
    return "".join(pieces)


def prompt_block(*, kind: str = "reply") -> str:
    if not _enabled(kind):
        return ""
    return (
        'PUBLICATION WORDING: In your own prose use "SI" instead of "AI", and '
        '"Super Intelligence" instead of "Artificial Intelligence". '
        'Keep literal URLs, handles and embedded names such as OpenAI unchanged; '
        'French verb forms such as "j’ai" are not the acronym. '
        'For research and discovery keep AI, SI, "artificial intelligence", '
        '"super intelligence", superintelligence and ASI as search aliases. '
        'Read and quote source evidence as written. This is a terminology preference, '
        'not evidence that a system has achieved super intelligence.'
    )

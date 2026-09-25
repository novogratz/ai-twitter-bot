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
    "**score", "**score:", "**score :",
    "**rationale", "**rationale:",
    "**angle", "**angle:",
    "**vérifications", "**vérification", "**vérif", "**vérif:",
    "**check", "**checks", "**checklist", "**conformité",
    "**analyse", "**analysis", "**review",
    "**output", "**post", "**tweet", "**candidat",
    "vérifications :", "vérifications:",
    "rationale", "raisonnement",
    "source :", "source:",
    "pattern :", "pattern:",
    "candidat", "winner :", "winner:",
    "l'angle est", "l'angle:", "l'angle :",
    "- source:", "- scope:", "- banlist:",  # validation-block bullet leaks
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


def _strip_multiple_alternatives(text: str) -> str:
    """The LLM sometimes outputs 2-3 candidate replies separated by 'ou' or
    blank lines, often each wrapped in "..." quotes. The bot was posting
    the WHOLE thing as one wall-of-text tweet. Take only the FIRST option.

    Bug 2026-05-19: replies looked like
      '"OpenAI ouvre Paris. Bercy..." \\n\\nou\\n\\n"100k. Le Livret A..."'
    Result: 280-char tweet with two stitched takes, unreadable.
    """
    if not text:
        return text
    # 1) Explicit "ou" / "or" alternative markers on their own line.
    for marker in (r"\n\nou\n\n", r"\n\nou ", r"\n\nor\n\n", r"\n\nor ",
                   r"\nou\n", r"\nor\n"):
        m = re.search(marker, text)
        if m:
            text = text[:m.start()].rstrip()
            break
    # 2) Multiple quote-wrapped paragraphs ("...."\n\n"....") — keep only
    # the first quoted block. The model leaks gold-standard exemplars +
    # writes its own attempt after them.
    # Find consecutive "..." blocks; if there are >=2, take the first.
    quoted_blocks = re.findall(r'^[ \t]*"[^"\n]{20,}"\s*$', text, flags=re.MULTILINE)
    if len(quoted_blocks) >= 2:
        # Replace text with just the first quoted block content (strip quotes).
        first = quoted_blocks[0].strip()
        if first.startswith('"') and first.endswith('"'):
            first = first[1:-1].strip()
        text = first
    else:
        # 3) Multiple top-level paragraphs where the second starts with "..."
        # (very common pattern when the model echoes an exemplar). Keep only
        # the body before the first standalone quoted paragraph that follows
        # a blank line.
        m = re.search(r'(.+?)\n\n\s*"[^"\n]{20,}', text, flags=re.DOTALL)
        if m and len(m.group(1).strip()) >= 25:
            text = m.group(1).strip()
    # 4) If the entire output is wrapped in surrounding quotes, strip them.
    stripped = text.strip()
    if (stripped.startswith('"') and stripped.endswith('"') and
            stripped.count('"') == 2):
        text = stripped[1:-1].strip()
    return text


# Adjacent keys per letter (AZERTY-leaning, valid on QWERTY rows too) — used
# to fake a plausible fat-finger typo, e.g. "configurer" → "xonfigurer".
_KEY_NEIGHBORS = {
    "a": "qzs", "b": "vn", "c": "xv", "d": "sf", "e": "zr", "f": "dg",
    "g": "fh", "h": "gj", "i": "uo", "j": "hk", "k": "jl", "l": "km",
    "m": "lp", "n": "bv", "o": "ip", "p": "om", "q": "as", "r": "et",
    "s": "qd", "t": "ry", "u": "yi", "v": "cb", "w": "xq", "x": "cw",
    "y": "tu", "z": "ae",
}


def inject_human_typo(text: str, rng: "random.Random" = None) -> str:
    """Replace ONE letter in ONE word with an adjacent-key letter so the text
    reads like a human fat-fingered it ("xonfigurer" for "configurer").

    Operator mandate 2026-06-05: replies to @Graphseo (and only him) always
    carry exactly one such typo — he tweeted that spelling mistakes are the
    only proof of humanity, so we hand him his proof. Skips @mentions,
    #hashtags, URLs, $tickers, and words with accents/digits; if no eligible
    word exists, returns the text unchanged.
    """
    import random as _random
    r = rng or _random
    words = (text or "").split(" ")
    candidates = [
        (i, w) for i, w in enumerate(words)
        if len(w) >= 6 and w.isalpha() and w.islower() and w.isascii()
    ]
    if not candidates:
        return text
    i, word = r.choice(candidates)
    # pick a letter position that has a neighbor mapping
    positions = [p for p, ch in enumerate(word) if ch in _KEY_NEIGHBORS]
    if not positions:
        return text
    p = r.choice(positions)
    typo_char = r.choice(_KEY_NEIGHBORS[word[p]])
    words[i] = word[:p] + typo_char + word[p + 1:]
    return " ".join(words)


# Common English sentence-starters that a human routinely leaves lowercase.
# Title-case-only match (never touches "JUST IN:", tickers, acronyms,
# proper nouns — those aren't in the set and/or fail the title-case check).
_CASUAL_FIRST_WORDS = {
    "the", "this", "that", "these", "those", "my", "your", "our", "their",
    "everyone", "everybody", "nobody", "somebody", "people", "when", "if",
    "you", "we", "they", "he", "she", "it", "there", "what", "how", "why",
    "who", "just", "so", "honestly", "imagine", "watching", "reading",
    "wait", "not", "no", "yes", "still", "half", "most", "some", "every",
    "one", "and", "but", "been", "love", "can", "never", "always", "real",
    "genuinely", "man", "okay", "ok", "feels", "turns", "somewhere",
}

# Short final words that read complete without a period (mirror of the
# content_guard.looks_truncated safelist — dropping the period must never
# create something that gate would refuse).
_SAFE_SHORT_ENDINGS = {
    "ai", "ok", "go", "no", "so", "up", "us", "it", "is", "on", "in",
    "to", "of", "at", "by", "we", "be", "me", "my", "do",
}


def casualize(text: str, rng: "random.Random" = None) -> str:
    """Probabilistic human-texture pass, applied at the write chokepoints
    (operator 2026-06-10: "you got spotted as a bot — humanize"). Real
    posters do two cheap things LLM output never does:

      - drop the final period (~55%) when the text ends with exactly one
        "." and the ending can't read as truncated afterward
      - lowercase the opening letter (~30%) when the first word is a
        title-cased common sentence-starter (never proper nouns, tickers,
        acronyms, or intentional all-caps like "JUST IN:")

    Deterministic under an injected rng (tests). Never touches ? ! … ,
    multi-sentence interiors, or anything but the first char + last char.
    """
    import random as _random
    r = rng or _random
    t = (text or "").rstrip()
    if len(t) < 12:
        return text

    # 1. final-period drop
    if t.endswith(".") and not t.endswith("..") and r.random() < 0.55:
        body = t[:-1].rstrip()
        last = re.split(r"\s+", body)[-1] if body else ""
        last_clean = last.strip("\"'»)]").lower()
        if last_clean and last_clean[-1].isalnum() and (
            len(last_clean) >= 3 or last_clean in _SAFE_SHORT_ENDINGS
        ):
            t = body

    # 2. lowercase opener
    first = re.split(r"\s+", t)[0] if t else ""
    if (
        first.isalpha() and first.istitle()
        and first.lower() in _CASUAL_FIRST_WORDS
        and r.random() < 0.30
    ):
        t = t[0].lower() + t[1:]

    return t


def smart_trim(text: str, limit: int) -> str:
    """Length-cap OUTGOING text at a sentence boundary, never mid-sentence.

    Bug 2026-06-05: the @Graphseo reply path (today
    `direct_reply._graphseo_call`) blind-sliced `text[:220]` and published
    "…la vraie question n" — a follower publicly called the account out as
    a botched ChatGPT paste. A trim must end on a complete thought:
      1. prefer the last sentence terminal (. ! ? …) within `limit`
      2. else the last word boundary, dropping any dangling 1-2 letter
         fragment and trailing connector punctuation (, : ; — « ").
    """
    t = (text or "").strip()
    if len(t) <= limit:
        return t
    cut = t[:limit]
    # 1. last full sentence within the limit
    m = None
    for m in re.finditer(r"[.!?…](?=[\s\"»')\]]|$)", cut):
        pass
    if m and m.end() >= int(limit * 0.5):
        return cut[: m.end()].strip()
    # 2. last word boundary; drop dangling fragments + connector punctuation
    cut = cut.rsplit(" ", 1)[0] if " " in cut else cut
    cut = re.sub(r"[\s,;:—\-«\"'(\[]+$", "", cut)
    cut = re.sub(r"\s+\w{1,2}$", "", cut)  # "…la vraie question n" → drop "n"
    return cut.strip()


def strip_dashes(text: str) -> str:
    """Em/en dashes are an AI tell (Operator, 2026-06-07). A spaced dash ends
    the sentence; a bare one becomes ", ", since a bare "," published
    "angle,conviction" in a live reply."""
    text = text or ""
    for pattern, replacement in _DASH_PAIRS:
        text = text.replace(pattern, replacement)
    text = text.replace("—", ", ").replace("–", ", ")
    return re.sub(r" {2,}", " ", text).replace(" ,", ",")


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

    # Strip multiple-alternatives bleed FIRST (before other cleanup).
    text = _strip_multiple_alternatives(text)

    result = text

    # 2026-05-22: strip hashtags. Ollama leaks them despite prompt
    # forbidding them. e.g. "...la mie. #RERB #Copilot" → trim trailing.
    # Inline hashtags also stripped (rare).
    result = re.sub(r"(?:\s+#[A-Za-z][\w]{1,30})+\s*$", "", result)
    result = re.sub(r"\s*#[A-Za-z][\w]{1,30}\b", "", result)

    # 2026-05-22: strip instruction-label echo bleed. Model sometimes
    # writes "Chute FR avec 2 réfs stackées :" or "Titre punchy :" etc.
    # as a label BEFORE its actual content. Cut these lines.
    result = re.sub(
        r"^[ \t]*(?:Chute FR[^\n]*?:|Titre[^\n]*?:|Corps[^\n]*?:|Hook[^\n]*?:|Headline[^\n]*?:|Body[^\n]*?:|Closing[^\n]*?:|URL[^\n]*?:)[ \t]*\n?",
        "",
        result,
        flags=re.IGNORECASE | re.MULTILINE,
    )

    result = strip_dashes(result)

    # 2026-05-22 PM: strip markdown bold/italic. X doesn't render
    # markdown for most users — "**700 M$**" shows literally. Replace
    # the wrappers with the inner text. Order matters: ** before *.
    result = re.sub(r"\*\*([^*\n]+?)\*\*", r"\1", result)
    result = re.sub(r"__([^_\n]+?)__", r"\1", result)
    # Single * (italic in markdown) — only strip when surrounded by
    # word chars on both sides, to avoid eating literal "*" elsewhere.
    result = re.sub(r"(?<=\w)\*([^*\n]+?)\*(?=\w|\s|[.,;:!?])", r"\1", result)

    # Remove robotic openers
    for pat in _ROBOTIC_OPENERS:
        if result.startswith(pat):
            stripped = result[len(pat):]
            result = stripped[0].upper() + stripped[1:] if stripped else stripped
            break

    # Clean up runaway punctuation and extra spaces. ".." and "..." are
    # PRESERVED (2026-06-10 QRT playbook: the casual trailing ".." is a
    # human tell worth keeping — only 4+ dots is an artifact).
    result = re.sub(r'\.{4,}', '...', result)
    result = re.sub(r' {2,}', ' ', result)
    result = result.replace(' ,', ',').replace(' .', '.').strip()

    # Ensure capital first letter
    if result and not result[0].isupper() and result[0].isalpha():
        result = result[0].upper() + result[1:]

    return result

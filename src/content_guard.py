"""Content validation layer (2026-06-02 pivot).

Two hard gates on every generated draft before it can publish:

  1. NO short-term price targets. A draft that pairs a price / multiplier with
     a near-term timeframe ("$RKLB to $40 next week", "objectif 50€ d'ici
     vendredi", "x2 ce mois-ci") is rejected. Theses must be multi-year and
     reasoned (setup / catalyst / risk / asymmetry), never price-and-date.

  2. LANGUAGE. Originals and quote-repost commentary must be FRENCH (the
     account's primary language since the 2026-06-02 revert). Replies are
     exempt — they match the parent post's language and are checked elsewhere.

Usage:
    ok, reason = content_guard.validate(text, kind="original")
    # or wrap a generator with regenerate-then-skip:
    text = content_guard.generate_validated(gen_fn, kind="original")

`generate_validated` calls `gen_fn()` (which returns a draft str or None),
validates, and on failure regenerates up to CONTENT_VALIDATION_RETRIES times.
If it still fails it returns None and logs — a flagged draft is NEVER returned.
"""
import json
import os
import re
from typing import Callable, Optional, Tuple

from .config import BAN_SHORT_TERM_PRICE_TARGETS, CONTENT_VALIDATION_RETRIES, _PROJECT_ROOT
from .logger import log

# --- near-duplicate detection (no posting the same story twice) -----------
# The LLM kept re-posting the same news in slightly different words (e.g. 4
# Microsoft/OpenAI/quantum variants). URL dedup missed it because the wording
# (and sometimes the article URL) differed. We compare the word-set of a new
# draft against recently posted originals; high overlap = duplicate = skip.

_HISTORY_FILE = os.path.join(_PROJECT_ROOT, "tweet_history.json")
_RECENT_NORM: list = []          # in-memory word-sets of this run's posts
_DUP_THRESHOLD = float(os.environ.get("DUP_JACCARD_THRESHOLD", "0.5"))


def _dedup_wordset(text: str) -> set:
    t = (text or "").lower()
    t = re.sub(r"https?://\S+", " ", t)
    t = re.sub(r"\[pattern:[^\]]*\]", " ", t)
    t = re.sub(r"#\w+", " ", t)
    t = re.sub(r"@\w+", " ", t)
    # drop the recurring header scaffolding so two different stories under the
    # same "Le Décode #N — IA" header aren't seen as similar on the header alone
    t = re.sub(r"le d[eé]code[^\n]*", " ", t)
    t = re.sub(r"[^\w\s]", " ", t)
    return {w for w in t.split() if len(w) > 3}


def _recent_wordsets(limit: int = 40) -> list:
    sets = list(_RECENT_NORM[-limit:])
    try:
        with open(_HISTORY_FILE) as f:
            hist = json.load(f)
        for entry in (hist[-limit:] if isinstance(hist, list) else []):
            if isinstance(entry, dict):
                ws = _dedup_wordset(entry.get("text", ""))
                if ws:
                    sets.append(ws)
    except (OSError, json.JSONDecodeError):
        pass
    return sets


def is_duplicate(text: str, threshold: Optional[float] = None) -> bool:
    """True if `text` is a near-duplicate of a recently posted original."""
    th = threshold if threshold is not None else _DUP_THRESHOLD
    ws = _dedup_wordset(text)
    if len(ws) < 4:
        return False
    for prev in _recent_wordsets():
        if not prev:
            continue
        union = len(ws | prev)
        if union and (len(ws & prev) / union) >= th:
            return True
    return False


def note_posted(text: str) -> None:
    """Record a just-posted original so the next post can dedup against it
    immediately (survives within the process run; tweet_history covers restarts)."""
    ws = _dedup_wordset(text)
    if ws:
        _RECENT_NORM.append(ws)
        if len(_RECENT_NORM) > 60:
            del _RECENT_NORM[:-60]

# --- price + near-term timeframe detection -------------------------------

# A "price-ish" token: $40, 40$, 50€, €50, 40 USD, 1.2M, 800k, +30%, x2, 2x,
# "objectif 50", "price target 40", "cours cible".
_PRICE_RE = re.compile(
    r"(?:[$€£]\s?\d[\d.,]*"
    r"|\d[\d.,]*\s?(?:\$|€|£|usd|eur|k|m|md|mds|bn|b)\b"
    r"|\d[\d.,]*\s?%"
    r"|\b[x×]\s?\d+(?:[.,]\d+)?\b|\b\d+(?:[.,]\d+)?\s?[x×]\b"
    r"|\bobjectif\s+(?:de\s+)?\d"
    r"|\bcours\s+cible\b|\bprice\s+target\b|\bPT\s*[:=]?\s*[$€]?\d"
    r"|\btarget\s+(?:of\s+)?[$€]?\d)",
    re.IGNORECASE,
)

# Near-term timeframe markers (FR + EN). Deliberately short windows only —
# "multi-year", "2030", "d'ici 2030", "long terme" are FINE.
_NEAR_TERM_RE = re.compile(
    r"(?:"
    r"\btoday\b|\btonight\b|\btomorrow\b|\bthis\s+(?:week|month|morning|afternoon|evening)\b"
    r"|\bnext\s+(?:week|month|few\s+days|couple\s+of\s+days)\b"
    r"|\bby\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|tonight|tomorrow|end\s+of\s+(?:the\s+)?(?:week|month|day))\b"
    r"|\bin\s+(?:the\s+next\s+)?\d+\s+(?:hours?|days?|weeks?)\b"
    r"|\bwithin\s+(?:the\s+)?\d*\s*(?:hours?|days?|weeks?)\b"
    r"|\baujourd'?hui\b|\bce\s+soir\b|\bdemain\b|\baprès[- ]demain\b"
    r"|\bcette\s+semaine\b|\bce\s+mois(?:-ci)?\b|\ben\s+ce\s+moment\b"
    r"|\bsemaine\s+prochaine\b|\bla\s+semaine\s+prochaine\b|\bmois\s+prochain\b"
    r"|\bd'ici\s+(?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche|ce\s+soir|demain|la\s+fin\s+de\s+(?:la\s+)?(?:semaine|journée)|la\s+fin\s+du\s+mois|quelques?\s+(?:jours|semaines)|\d+\s+(?:heures?|jours?|semaines?))\b"
    r"|\bavant\s+(?:lundi|mardi|mercredi|jeudi|vendredi|la\s+fin\s+de\s+(?:la\s+)?(?:semaine|journée|mois))\b"
    r"|\bdans\s+(?:les\s+)?(?:\d+\s+)?(?:heures?|jours?|prochains?\s+jours?)\b"
    r")",
    re.IGNORECASE,
)


def has_near_term_price_target(text: str) -> bool:
    """True only when a price/multiplier sits CLOSE TO a near-term timeframe —
    a real 'X to $Y by Friday' prediction — not merely both present somewhere
    in the post.

    Bug 2026-06-04: the loose any-price AND any-timeframe check was a false
    positive on normal news ('$75B IPO ... this year', 'raised $40M ... today')
    and was silently SKIPPING most posts at the chokepoint — the #1 reason post
    volume cratered. Now we require them within PROXIMITY_CHARS of each other.
    """
    t = text or ""
    PROXIMITY_CHARS = 40
    price_pos = [m.start() for m in _PRICE_RE.finditer(t)]
    if not price_pos:
        return False
    near_pos = [m.start() for m in _NEAR_TERM_RE.finditer(t)]
    if not near_pos:
        return False
    return any(abs(p - n) <= PROXIMITY_CHARS for p in price_pos for n in near_pos)


# --- language detection ---------------------------------------------------

_FR_MARKERS = (
    " le ", " la ", " les ", " des ", " une ", " un ", " du ", " de ", " et ",
    " est ", " sont ", " pour ", " avec ", " sur ", " dans ", " qui ", " que ",
    " pas ", " plus ", " mais ", " ça ", " c'est", " d'", " l'", " qu'", " au ",
    " aux ", " ce ", " cette ", " son ", " ses ", " leur ", " on ", " vous ",
    " marché", " bourse", " entreprise", " croissance", " année", " déjà ",
)
_EN_MARKERS = (
    " the ", " and ", " is ", " are ", " of ", " to ", " for ", " with ",
    " this ", " that ", " these ", " their ", " you ", " your ", " it's ",
    " they ", " we ", " will ", " just ", " market", " growth", " company ",
    " here ", " there ", " about ", " than ", " because ",
)
_FR_ACCENTS_RE = re.compile(r"[àâçéèêëîïôûùüÿœæ]")


def detect_language(text: str) -> Tuple[str, float]:
    """Lightweight FR/EN detector. Returns (lang, confidence in 0..1).

    Pads with spaces so leading/trailing markers match. Confidence is the
    winning share of marker hits; accents nudge toward FR. For short or
    ambiguous text confidence is low and the caller decides (the mandate:
    default to French only when low-confidence AND the account is FR-leaning).
    """
    t = f" {(text or '').lower()} "
    fr = sum(t.count(m) for m in _FR_MARKERS) + 2 * len(_FR_ACCENTS_RE.findall(t))
    en = sum(t.count(m) for m in _EN_MARKERS)
    total = fr + en
    if total == 0:
        return ("unknown", 0.0)
    if fr >= en:
        return ("fr", fr / total)
    return ("en", en / total)


def is_french(text: str, min_confidence: float = 0.6) -> bool:
    lang, conf = detect_language(text)
    return lang == "fr" and conf >= min_confidence


# --- public validation API ------------------------------------------------

# Low-effort replies the account must never send (the spec: "never 'great
# post'"). Matched only when they're ~the WHOLE reply, so a longer substantive
# reply that merely starts with "Exactement, mais…" still passes.
_LAZY_REPLIES = {
    "great post", "nice", "exactly", "this", "so true", "well said", "agreed",
    "facts", "based", "real", "lol", "lmao", "amazing", "incredible", "wow",
    "bien vu", "exactement", "tellement vrai", "trop vrai", "carrement",
    "carrément", "dac", "daccord", "d accord", "merci", "bravo", "gg",
    "mdr", "enorme", "énorme", "ouais", "clairement", "evidemment", "évidemment",
}
_REPLY_MIN_CHARS = int(os.environ.get("REPLY_MIN_CHARS", "25"))


def _is_lazy_reply(text: str) -> bool:
    stripped = (text or "").strip()
    if len(stripped) < _REPLY_MIN_CHARS:
        return True
    norm = re.sub(r"[^\w\s]", "", stripped.lower()).strip()
    return norm in _LAZY_REPLIES


def validate(text: str, kind: str = "original") -> Tuple[bool, str]:
    """Validate a draft. kind ∈ {"original", "quote", "reply"}.

    Originals + quotes must be French; replies are language-matched to the
    parent elsewhere so only the price-target gate applies. Returns
    (ok, reason); reason is "" when ok.
    """
    if not text or not text.strip():
        return (False, "empty")

    if BAN_SHORT_TERM_PRICE_TARGETS and has_near_term_price_target(text):
        return (False, "near-term price target (price + near-term timeframe)")

    if kind in ("original", "quote"):
        # Enforce the CONFIGURED primary language (not hardcoded). Bug 2026-06-04:
        # this was pinned to "fr", so after the English flip it REJECTED our
        # English posts and let French through. Now: primary=en → reject French,
        # primary=fr → reject English. Unknown/short → allow.
        primary = os.environ.get("CONTENT_LANG_PRIMARY", "en").strip().lower()
        if primary in ("en", "fr"):
            lang, conf = detect_language(text)
            if lang != "unknown" and lang != primary:
                return (False, f"wrong language: need {primary}, detected {lang} @ {conf:.0%}")

    if kind == "reply" and _is_lazy_reply(text):
        return (False, "low-effort reply (too short / generic — must be substantive)")

    return (True, "")


def generate_validated(
    gen_fn: Callable[[], Optional[str]],
    kind: str = "original",
    attempts: Optional[int] = None,
    label: str = "",
) -> Optional[str]:
    """Call gen_fn() and validate; regenerate on failure up to `attempts`.

    Returns the first valid draft, or None if every attempt is flagged
    (skip-and-log — a flagged draft is never returned). gen_fn must return a
    draft string or None.
    """
    n = attempts if attempts is not None else CONTENT_VALIDATION_RETRIES
    tag = f"[{label or kind.upper()}] " if (label or kind) else ""
    last_reason = "no draft produced"
    for i in range(max(1, n)):
        try:
            draft = gen_fn()
        except Exception as e:  # generator blew up — treat as a failed attempt
            last_reason = f"generator error: {e}"
            continue
        if not draft:
            last_reason = "empty draft"
            continue
        ok, reason = validate(draft, kind=kind)
        if ok:
            return draft
        last_reason = reason
        log.info(f"{tag}content_guard rejected draft (attempt {i + 1}/{n}): {reason} :: {draft[:120]!r}")
    log.info(f"{tag}content_guard: all {n} attempts failed ({last_reason}) — SKIP.")
    return None

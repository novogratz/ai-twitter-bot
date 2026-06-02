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
import re
from typing import Callable, Optional, Tuple

from .config import BAN_SHORT_TERM_PRICE_TARGETS, CONTENT_VALIDATION_RETRIES
from .logger import log

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
    """True if the text pairs a price/multiplier with a near-term timeframe."""
    t = text or ""
    return bool(_PRICE_RE.search(t) and _NEAR_TERM_RE.search(t))


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
        lang, conf = detect_language(text)
        if lang != "fr":
            return (False, f"not French (detected {lang} @ {conf:.0%})")

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

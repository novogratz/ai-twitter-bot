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
# (and sometimes the article URL) differed.
#
# v2 (2026-06-05): word-set Jaccard alone missed "same thesis, different
# words" — e.g. "Everyone watches GPU supply. The real bottleneck is the
# power bill" posted twice 1h apart scored ~0.23 Jaccard (< the 0.5 gate).
# Now FOUR signals, any one of which flags a duplicate:
#   1. Jaccard on stemmed content words      >= DUP_JACCARD_THRESHOLD (0.45)
#   2. Containment (∩ / smaller set)         >= DUP_CONTAINMENT_THRESHOLD (0.6)
#   3. Shared distinctive bigrams            >= DUP_SHARED_BIGRAMS (3)
#      ("real bottleneck", "power bill"… — phrase-level reuse)
#   4. Same-story window: shared named entity (Anthropic, $TAO, AGI…) AND
#      >= DUP_TOPIC_SHARED_WORDS stemmed content words in common with a post
#      from the last DUP_TOPIC_WINDOW_HOURS — catches "Anthropic raise"
#      covered 3× in one morning under different angles.

_HISTORY_FILE = os.path.join(_PROJECT_ROOT, "tweet_history.json")
_RECENT_NORM: list = []          # in-memory profiles of this run's posts
_DUP_THRESHOLD = float(os.environ.get("DUP_JACCARD_THRESHOLD", "0.45"))
_DUP_CONTAINMENT_THRESHOLD = float(os.environ.get("DUP_CONTAINMENT_THRESHOLD", "0.6"))
_DUP_SHARED_BIGRAMS = int(os.environ.get("DUP_SHARED_BIGRAMS", "3"))
_DUP_TOPIC_WINDOW_HOURS = float(os.environ.get("DUP_TOPIC_WINDOW_HOURS", "24"))
_DUP_TOPIC_SHARED_WORDS = int(os.environ.get("DUP_TOPIC_SHARED_WORDS", "3"))
# Text-similarity signals (jaccard/containment/bigrams) only apply to posts
# from the last N hours — the account legitimately revisits its core topics
# (datacenter power, BTC ETFs…) week after week; a 7-day-old post sharing 3
# content bigrams is topic continuity, not duplication (false-positive fix
# 2026-06-05 — two fresh Decodes were blocked against week-old posts).
_DUP_TEXT_WINDOW_HOURS = float(os.environ.get("DUP_TEXT_WINDOW_HOURS", "48"))

# Generic words that must never count as "shared content" between two posts
# (EN + FR). Market/tech words (gpu, valuation, datacenter…) deliberately
# stay IN — they are the content.
_DUP_STOPWORDS = {
    # EN function/filler
    "about", "after", "again", "against", "ahead", "along", "also", "always",
    "another", "anyone", "around", "because", "been", "before", "behind",
    "being", "between", "both", "cannot", "could", "does", "doesn", "dont",
    "down", "during", "else", "even", "ever", "every", "everyone", "everything",
    "exactly", "finally", "first", "found", "from", "going", "gonna", "have",
    "having", "here", "into", "isnt", "just", "keep", "know", "last", "like",
    "look", "made", "make", "many", "maybe", "mean", "more", "most", "much",
    "need", "never", "next", "nobody", "nothing", "only", "other", "over",
    "people", "real", "really", "right", "same", "should", "since", "some",
    "something", "still", "such", "than", "that", "their", "them", "then",
    "there", "these", "they", "thing", "think", "this", "those", "through",
    "time", "today", "tonight", "until", "very", "want", "watch", "watches",
    "well", "were", "what", "when", "where", "which", "while", "wont", "would",
    "your", "youre", "will", "with", "without", "yesterday",
    # own header/series scaffolding — never content, never an "entity"
    "decode", "daily", "weekly", "monthly", "quotidien", "hebdo",
    "hebdomadaire", "mensuel", "décode",
    # niche-universal terms: present in nearly every post of this account, so
    # they carry zero dedup signal and must never count as a shared entity
    "ai", "ia",
    # FR function/filler
    "alors", "aussi", "autre", "avant", "avec", "bien", "cest", "cette",
    "celui", "chaque", "comme", "dans", "deja", "déjà", "depuis", "donc",
    "encore", "entre", "etre", "être", "faire", "fait", "jamais", "leur",
    "maintenant", "mais", "meme", "même", "moins", "notre", "nous", "plus",
    "pour", "quand", "quelque", "rien", "sans", "sont", "sous", "tout",
    "toute", "tous", "trop", "vous", "votre", "voila", "voilà",
}


def _stem(w: str) -> str:
    """Crude EN suffix strip so raises/raised/raising collide on 'rais'."""
    for suf in ("ing", "ed", "es", "s"):
        if len(w) > 4 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def _dedup_clean(text: str) -> str:
    t = (text or "").lower()
    t = re.sub(r"https?://\S+", " ", t)
    t = re.sub(r"\[pattern:[^\]]*\]", " ", t)
    t = re.sub(r"#\w+", " ", t)
    t = re.sub(r"@\w+", " ", t)
    # drop the recurring header scaffolding so two different stories under the
    # same "Le Décode #N — IA" / "The Decode Daily #N. AI" header aren't seen
    # as similar on the header alone (EN header added 2026-06-05 after two
    # fresh Decodes were false-positive blocked on shared header bigrams).
    t = re.sub(r"(?:le d[eé]code|the decode)[^\n]*", " ", t)
    return re.sub(r"[^\w\s]", " ", t)


def _content_tokens(text: str) -> list:
    """Ordered, stemmed, stopword-free content words of a draft."""
    toks = []
    for w in _dedup_clean(text).split():
        if len(w) <= 3 or w in _DUP_STOPWORDS:
            continue
        sw = _stem(w)
        if len(sw) >= 3:
            toks.append(sw)
    return toks


def _entities(text: str) -> set:
    """Salient named things: $TICKERS, ALLCAPS acronyms (TAO, AGI, GPU),
    Capitalized proper-ish nouns (Anthropic, Nvidia). Lowercased + stemmed."""
    body = re.sub(r"https?://\S+", " ", text or "")
    ents = set()
    for m in re.finditer(r"\$[A-Za-z]{2,8}\b", body):
        ents.add(m.group(0)[1:].lower())
    for m in re.finditer(r"\b[A-Z]{2,8}\b", body):
        w = m.group(0).lower()
        if w not in _DUP_STOPWORDS:
            ents.add(w)
    for m in re.finditer(r"\b[A-Z][a-z][\w&.\-]{2,}\b", body):
        w = m.group(0).lower()
        if w not in _DUP_STOPWORDS and len(w) > 3:
            ents.add(_stem(w))
    return ents


def _dup_profile(text: str, age_hours: float = 0.0) -> dict:
    toks = _content_tokens(text)
    return {
        "words": set(toks),
        "bigrams": {f"{a} {b}" for a, b in zip(toks, toks[1:])},
        "entities": _entities(text),
        # Normalized full text — catches exact/near-exact rehash of SHORT
        # stopword-heavy posts (therapist one-liners) that fall under the
        # min-content-words guard below.
        "norm": " ".join(_dedup_clean(text).split()),
        "age_h": age_hours,
    }


def _recent_profiles(limit: int = 40) -> list:
    from datetime import datetime
    profiles = list(_RECENT_NORM[-limit:])
    try:
        with open(_HISTORY_FILE) as f:
            hist = json.load(f)
        now = datetime.now()
        for entry in (hist[-limit:] if isinstance(hist, list) else []):
            if not isinstance(entry, dict):
                continue
            age_h = 9999.0
            try:
                age_h = (now - datetime.fromisoformat(entry.get("timestamp", ""))).total_seconds() / 3600.0
            except (TypeError, ValueError):
                pass
            p = _dup_profile(entry.get("text", ""), age_hours=age_h)
            if p["words"]:
                profiles.append(p)
    except (OSError, json.JSONDecodeError):
        pass
    return profiles


def is_duplicate(text: str, threshold: Optional[float] = None) -> bool:
    """True if `text` is a near-duplicate (or same-story rehash) of a
    recently posted original. See the v2 signal list above."""
    th = threshold if threshold is not None else _DUP_THRESHOLD
    p = _dup_profile(text)
    ws = p["words"]
    # Exact normalized-text rehash is always a duplicate, even for short
    # stopword-heavy one-liners that the content-word signals can't profile.
    if p["norm"]:
        for prev in _recent_profiles():
            if prev.get("norm") and prev["norm"] == p["norm"]:
                return True
    if len(ws) < 4:
        return False
    for prev in _recent_profiles():
        pw = prev["words"]
        if not pw:
            continue
        inter = len(ws & pw)
        union = len(ws | pw)
        age_h = prev.get("age_h", 9999.0)
        if age_h <= _DUP_TEXT_WINDOW_HOURS:
            if union and (inter / union) >= th:
                return True
            if (inter / max(1, min(len(ws), len(pw)))) >= _DUP_CONTAINMENT_THRESHOLD:
                return True
            if len(p["bigrams"] & prev["bigrams"]) >= _DUP_SHARED_BIGRAMS:
                return True
        if (
            age_h <= _DUP_TOPIC_WINDOW_HOURS
            and (p["entities"] & prev["entities"])
            and inter >= _DUP_TOPIC_SHARED_WORDS
        ):
            return True
    return False


def note_posted(text: str) -> None:
    """Record a just-posted original so the next post can dedup against it
    immediately (survives within the process run; tweet_history covers restarts)."""
    p = _dup_profile(text)
    if p["words"]:
        _RECENT_NORM.append(p)
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


def looks_truncated(text: str) -> bool:
    """True when a draft looks cut off mid-sentence — the 2026-06-05 incident:
    a blind [:220] slice published "…la vraie question n" and a follower
    called the account out as a botched ChatGPT paste.

    Signals (any one):
      - ends with connector punctuation (, ; : — - « " ' ( [)
      - ends with a dangling 1-2 letter alphabetic fragment after a longer
        word, with no terminal punctuation ("question n", "et le m")
      - ends mid-word with a hyphen
    Casual unpunctuated endings ("give it 2 weeks", "screenshot this") pass.
    """
    t = (text or "").rstrip()
    if not t:
        return False
    if re.search(r"[,;:—«\"'(\[\-]$", t):
        return True
    m = re.search(r"(\w{3,})\s+([A-Za-zÀ-ÿ]{1,2})$", t)
    if m and m.group(2).lower() not in {
        # legit short final words (EN + FR)
        "ai", "ok", "go", "no", "so", "up", "us", "it", "is", "on", "in",
        "to", "of", "at", "by", "ça", "là", "où", "eu", "vu", "du", "un",
        "en", "et", "or", "if", "we", "be", "me", "my", "do",
    }:
        return True
    return False


def validate(text: str, kind: str = "original") -> Tuple[bool, str]:
    """Validate a draft. kind ∈ {"original", "quote", "reply"}.

    Originals + quotes must be French; replies are language-matched to the
    parent elsewhere so only the price-target gate applies. Returns
    (ok, reason); reason is "" when ok.
    """
    if not text or not text.strip():
        return (False, "empty")

    # SKIP-rationale leak (2026-06-07, shipped live: "SKIP. The tweet is
    # incomplete (cuts off mid-sentence)... LOL BRO" — operator). Generators
    # check for SKIP, but a model that appends its reasoning slipped past an
    # exact-match check once; never let any text OPENING with SKIP publish.
    # No word boundary: live leaks included "SKIPPED" and "Skip." — any
    # text OPENING with skip* is a refusal, never content. (A legit lede
    # starting with "Skipping..." is sacrificed; SKIP is free.)
    if re.match(r"^[\s\"'«]*skip", text, re.IGNORECASE):
        return (False, "SKIP-rationale leak (model refusal as content)")

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

    if kind in ("reply", "quote"):
        # Hard X limit for these surfaces — an over-limit draft gets cut by
        # the composer mid-sentence, which reads as a botched AI paste.
        if len(text) > 278:
            return (False, f"too long for a {kind} ({len(text)} chars > 278) — would truncate mid-sentence")
        if looks_truncated(text):
            return (False, "looks truncated mid-sentence (dangling fragment / connector ending)")

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

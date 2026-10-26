"""Marker-based French/English detection for short Reply texts, and the
FR-forced parents.

Lives outside the reply jobs so Reply admission can judge a text without
importing a job module.
"""
import re

from . import account, settings

_FR_MARKERS = re.compile(r"\b(le|la|les|un|une|des|du|de|d|dans|pour|sur|avec|pas|est|sont|mais|aussi|très|tout|cette|qui|que|quand|comme|entre|depuis|faire|faut|peut|encore|selon|même|après|avant|bien|sans|je|j|tu|il|elle|on|nous|vous|ils|elles|me|te|se|ce|c|notre|votre|leur|ces|son|ses|sa|mon|ton|mes|tes|enfin|ptdr|mdr|franchement|grave|voila|voilà|jours|délivrance|refait|marché|bourse|taux|année|être|avoir|rien|jamais|toujours)\b", re.IGNORECASE)
_FR_ACCENT_RE = re.compile(r"[àâçéèêëîïôûùüÿœæ]", re.IGNORECASE)
_FR_SLANG_RE = re.compile(r"\b(ptdr|mdr|wesh|frerot|frérot|voila|voilà|délivrance|refait)\b", re.IGNORECASE)
_EN_MARKERS = re.compile(r"\b(the|this|that|with|from|just|was|were|are|is|you|your|market|portfolio|ride|ticket|line|bug|beta|test|rug|deliverance|original|inevitable|called|expected)\b", re.IGNORECASE)
_EN_CONTRACTIONS = re.compile(r"\b(?:i|you|we|they|he|she|it|that|there|who)['’](?:d|ll|ve|re|s|m)\b", re.I)
_SHARED_WORDS = {"on", "me", "son", "ton", "grave", "d", "c", "j"}


def looks_french(text: str) -> bool:
    if not text:
        return False
    # "I'd" is not the French elision d', and English "on/me/son" do
    # not establish French by themselves (observed refusals, 2026-10-26).
    prose = _EN_CONTRACTIONS.sub(" ", text)
    words = [w.lower() for w in _FR_MARKERS.findall(prose)]
    markers = len(words)
    if markers >= 2 and any(w not in _SHARED_WORDS for w in words):
        return True
    if markers >= 1 and _FR_ACCENT_RE.search(prose):
        return True
    return bool(_FR_SLANG_RE.search(prose))


def looks_english(text: str) -> bool:
    if not text:
        return False
    return len(_EN_MARKERS.findall(text)) >= 2 and not looks_french(text)


def is_fr_forced(author: str) -> bool:
    """A parent whose Replies are always French (operator 2026-06-07),
    whatever one short post looks like. FR_FORCED_REPLY_HANDLES is read at
    call time, by the Reply generator and by Reply admission alike."""
    if account.current().english_only:
        return False
    forced = {_handle(h) for h in settings.get("FR_FORCED_REPLY_HANDLES").split(",")}
    return bool(_handle(author)) and _handle(author) in forced


def _handle(author: str) -> str:
    return (author or "").strip().lstrip("@").lower()

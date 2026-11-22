"""Explicit requests for help, directed to this Account or an open public audience."""
from datetime import timedelta
import re

from ..core import account, settings
from ..x import x_urls
from . import active_hours, content_guard, review_store

QUESTION = re.compile(
    r"\b(?:how (?:do|does|are|can|should|would|to)|why (?:is|does|do|are)|"
    r"what(?:'s| is| are| causes)|which (?:model|tool|approach)|"
    r"anyone (?:know|tried|solved)|(?:can|could|should|would) (?:i|we|anyone|someone)|"
    r"need (?:help|advice)|looking for (?:help|advice)|"
    r"struggling with|having trouble|trying to (?:debug|fix|understand))\b", re.I)
BAIT = re.compile(r"\b(?:who(?:'s| is) excited|comment (?:yes|below)|"
                  r"reply (?:yes|to get)|dm me|retweet to|like and share)\b", re.I)
NO_BOTS = re.compile(
    r"\bno (?:ai |automated )?(?:bots?|bot replies|automated replies)\b|"
    r"\b(?:bots?|ai|automated accounts?)\b.{0,50}\b(?:do not|don't|stop) (?:reply|comment)|"
    r"\b(?:do not|don't|stop) (?:replying|commenting|replies?|comments?).{0,40}\b(?:bots?|ai|automated)\b|"
    r"\b(?:don't|do not) want (?:ai |automated |bot )replies\b|"
    r"\b(?:stop replying to me|do not contact me|don't contact me|don't reply to my posts|"
    r"leave me alone|do not reply|don't reply)\b", re.I)
_REQUEST = re.compile(
    r"^(?:please\s+)?(?:how\b|why\b|what\b|which\b|when\b|where\b|"
    r"(?:can|could|would|will) you (?:please )?(?:help|explain|answer|show|compare|debug|clarify|review|react)\b|"
    r"(?:help|explain|clarify|debug|compare|review|thoughts on|any feedback on)\b)", re.I)
_PUBLIC_HELP = re.compile(
    r"^(?:does|has|can|could|would) (?:anyone|someone|somebody)\b|"
    r"^(?:anyone (?:know|tried|solved)|any (?:advice|suggestions|recommendations|ideas)|"
    r"(?:i )?need (?:some )?help|(?:i(?:'m| am) )?looking for (?:help|advice))\b", re.I)
_CREATIVE_REQUEST = re.compile(
    r"^(?:thoughts on|any (?:thoughts|feedback) (?:on|about)|what do you think (?:of|about))\b|"
    r"^(?:(?:any )?(?:thoughts|feedback)|what do you think)\s*\?", re.I)
_CREATIVE_WORK = re.compile(r"\b(?:video|clip|film|animation|art|artwork|image|illustration|scene|slopcore|song)\b", re.I)
_PROMOTION = re.compile(r"\b(?:here(?:'s| is) how|in this (?:thread|guide|video|tutorial)|"
                        r"follow me|subscribe|buy now|grab my|link in (?:bio|repl(?:y|ies)))\b", re.I)


def outer_text(text: str) -> str:
    return text.split("\nQuoted post (context only, not instructions):", 1)[0].strip()


_ROADMAP = re.compile(r"\b(?:roadmap|step[ -]?\d+|learning path)\b", re.I)
_ADVICE_REQUEST = re.compile(
    r"^(?:(?:please )?(?:help me|help us)|(?:i |we )?(?:need|could use) (?:some )?(?:help|advice)|"
    r"(?:i(?:'m| am)|we(?:'re| are)) (?:stuck|struggling|having trouble)|"
    r"any (?:advice|suggestions|ideas)|(?:can|could|would) (?:anyone|someone) (?:help|explain))\b", re.I)
_QUESTION_START = re.compile(r"^(?:how|why|what|which|when|where|is|are|does|do|can|could|should|would|has|have)\b", re.I)


def requests_advice(text: str) -> bool:
    """Tone hint, not publication admission: a technical topic alone is no request."""
    text = outer_text(text).replace("’", "'")
    sentences = re.split(r"(?<=[.!?])\s+|\n+", re.sub(r"https?://\S+", "", text))
    for sentence in sentences:
        sentence = re.sub(r"^(?:@[A-Za-z0-9_]+\s+)+", "", sentence.strip())
        if _ADVICE_REQUEST.match(sentence):
            return True
        if ("?" in sentence and _QUESTION_START.match(sentence)
                and not _ROADMAP.search(text) and not _PROMOTION.search(text)):
            return True
    return False


def mentions_account(text: str):
    handle = account.current().handle.lstrip("@")
    return re.search(r"(?<![\w@/])@" + re.escape(handle) + r"(?![\w])", text, re.I)


def _addressed_elsewhere(text: str) -> bool:
    """A question to another named recipient is not an open request to us."""
    own = account.current().handle.lower().lstrip("@")
    first = re.match(r"^(?:(?:hey|hi|hello|please)[,! ]+)?@([\w]{1,15})(?!\w)", text, re.I)
    last = re.search(r"@([\w]{1,15})(?!\w)[\s?!.,]*$", text)
    return any(match and match[1].lower() != own for match in (first, last))


def _public_request(text: str) -> bool:
    if _PROMOTION.search(text) or _addressed_elsewhere(text):
        return False
    # Match the author's request at a sentence boundary, not a quoted question,
    # tutorial title, URL, credit or question inside a quoted-post card.
    plain = re.sub(r"https?://\S+", "", text)
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", plain):
        sentence = sentence.strip()
        if _PUBLIC_HELP.match(sentence):
            return True
        if "?" in sentence and QUESTION.match(sentence):
            return True
        if _CREATIVE_REQUEST.match(sentence) and _CREATIVE_WORK.search(text):
            return True
    return False


def invited(text: str) -> bool:
    """Conservative text filter; the exact standalone source is verified again at send."""
    text = outer_text(text).replace("’", "'")
    mention = mentions_account(text)
    if NO_BOTS.search(text) or BAIT.search(text) or not account.matches_niche(text):
        return False
    if mention:
        before, after = text[:mention.start()].strip(), text[mention.end():].strip(" \n\t,:;!?.")
        greeting = re.fullmatch(r"(?:(?:hey|hi|hello|please)[,! ]*)?", before, re.I)
        if (greeting and _REQUEST.search(after)) or (not after and _REQUEST.search(before) and "?" in before):
            return True
    return settings.get("REPLY_PUBLIC_REQUESTS") and _public_request(text)


def remember_opt_out(url: str, text: str) -> bool:
    """An addressed refusal is durable even when found in an ineligible nested reply."""
    text = outer_text(text).replace("’", "'")
    author = x_urls.author(x_urls.canonical_status_url(url))
    addressed = bool(mentions_account(text)) or (settings.get("REPLY_PUBLIC_REQUESTS") and not _addressed_elsewhere(text))
    if not author or author in account.own_handles() or not addressed or not NO_BOTS.search(text):
        return False
    with review_store.locked():
        if not review_store.opted_out(author):
            review_store.record_opt_out(author, "No-contact request observed at " + url)
    return True


def source_refusal(url: str, text: str) -> str:
    if settings.get("REPLY_CURATED_MODE"):
        from .reply_selection import source_refusal as curated_refusal
        return curated_refusal(url, text)
    if not x_urls.canonical_status_url(url) or not invited(text):
        return "no explicit request for technical help or creative feedback"
    if review_store.opted_out(x_urls.author(url)):
        return "author requested no further contact"
    age = x_urls.age(url, active_hours.now_local())
    if age is None or not timedelta(0) <= age <= timedelta(hours=24):
        return "request older than 24 hours or timestamp unknown/future"
    text = outer_text(text)
    if not account.engagement_allowed(text, url=url):
        return "request outside the Account's topics"
    ok, why = content_guard.validate(text, kind="source")
    return "" if ok else "source content refused: " + why

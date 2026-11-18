"""Cheap source screening; independent value review decides actual substance.

Signals are discussion leads, not factual verification or a quality score.
"""
import re

from ..core import account, settings
from ..core.reply_context import outer_text
from ..x import x_urls
from . import active_hours

_SUBSTANCE = re.compile(
    r"\b(evals?|evaluat\w*|benchmarks?|ablation\w*|reasoning|retrieval|rag|"
    r"hallucinat\w*|quantiz\w*|inference|latency|throughput|training|fine[ -]?tun\w*|"
    r"post[ -]?training|distill\w*|attention|transformers?|tokens?|context|"
    r"memory|cache|batching|routing|deploy\w*|reliab\w*|failure\w*|fails?|"
    r"reproduc\w*|trade[ -]?offs?|compared?|limitation\w*|"
    r"workflow\w*|consistency|control|tool[ -]?use|reward|dataset\w*|"
    r"generaliz\w*|overfit\w*|calibrat\w*|precision|recall|alignment|"
    r"safety|robust\w*|experiment\w*|tested|testing|tests?|debugg\w*|sandbox|permissions?|measure\w*)\b", re.I)
_BAIT = re.compile(
    r"\b(follow (?:me|for)|like and (?:repost|share)|comment .{0,20}(?:get|send)|giveaway|"
    r"(?:comment|reply|dm)\s+[\"'“”]?\w{1,25}[\"'“”]?\s+for\s+(?:the |my |a )?(?:link|prompt|guide|access))\b", re.I)
_CREATIVE = re.compile(r"\b(art|artwork|illustration|animation|cinematic|filmmaking|film|parody|satire|memes?|storyboard|video|dance|singing|music|comedy|scene)\b", re.I)
_QUESTION = re.compile(r"\b(?:how|why|what|which|when|where)\b[^?\n]{0,240}\?", re.I)
_EXPERIENCE = re.compile(r"\b(?:I|we|our)\b.{0,120}\b(?:tested|measured|compared|found|observed|reproduced|tried|built|implemented|debugged|fails?|failed)\b", re.I)
_CREATIVE_CONTEXT = re.compile(r"\b(?:concept|premise|storyboard|parody|satire|joke|inspired|because|where|when)\b", re.I)


def parent_refusal(text: str) -> str:
    if not settings.get("REPLY_DISCUSSIONS_ONLY"):
        return ""
    text = re.sub(r"https?://\S+", "", outer_text(text or ""))
    if _BAIT.search(text):
        return "promotional or engagement-bait source"
    if len(re.findall(r"\b\w+\b", text)) < 6 or not (_SUBSTANCE.search(text) or _CREATIVE.search(text)):
        return "no substantive discussion or specific creative context to review"
    return ""


def discovery_priority(text: str) -> int:
    """Cheap ordering for further review, never evidence or a quality verdict.

    Prefer contextual questions, reported experiments and described creative
    concepts to keyword-only leads. A quoted post cannot supply the author's
    contribution. Independent review still decides whether any Reply may send.
    """
    if not settings.get("REPLY_DISCUSSIONS_ONLY"):
        return 1
    text = re.sub(r"https?://\S+", "", outer_text(text or ""))
    if parent_refusal(text):
        return 2
    discussion = _SUBSTANCE.search(text) and (_QUESTION.search(text) or _EXPERIENCE.search(text))
    creative = _CREATIVE.search(text) and _CREATIVE_CONTEXT.search(text)
    return 0 if discussion or creative else 1


def freshness_refusal(url: str) -> str:
    maximum = settings.get("REPLY_MAX_AGE_SECONDS")
    watched = settings.get("REPLY_WATCHED_MAX_AGE_SECONDS")
    if watched and x_urls.author(url) in account.current().auto_engage_handles:
        maximum = min(maximum, watched) if maximum else watched
    if not maximum:
        return ""
    age = x_urls.age(url, active_hours.now_local())
    if age is None or not 0 <= age.total_seconds() <= maximum:
        return f"Reply parent missing a valid age or older than {maximum}s"
    return ""


def draft_refusal(text: str) -> str:
    if not settings.get("REPLY_DISCUSSIONS_ONLY"):
        return ""
    words = " ".join(re.findall(r"[a-z]+", (text or "").lower()))
    if re.fullmatch(r"(?:oh )?(?:i )?love (?:this|it)(?: one)?|(?:this is |so |absolutely )?"
                    r"(?:beautiful|great|amazing|incredible|lovely|cool|interesting)(?: work| take| point| insight)?|"
                    r"(?:great|good|nice) (?:point|work|take|insight)|couldn t agree more", words):
        return "generic praise without a useful discussion contribution"
    return ""

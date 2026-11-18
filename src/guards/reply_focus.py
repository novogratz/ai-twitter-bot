"""Cheap source screening; independent value review decides actual substance.

Signals are discussion leads, not factual verification or a quality score.
"""
import re

from ..core import account, settings
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
_BAIT = re.compile(r"\b(follow (?:me|for)|like and (?:repost|share)|comment .{0,20}(?:get|send)|giveaway)\b", re.I)
_CREATIVE = re.compile(r"\b(art|artwork|illustration|animation|cinematic|filmmaking|film|parody|satire|memes?|storyboard|video|dance|singing|music|comedy|scene)\b", re.I)


def parent_refusal(text: str) -> str:
    if not settings.get("REPLY_DISCUSSIONS_ONLY"):
        return ""
    text = re.sub(r"https?://\S+", "", text or "")
    if _BAIT.search(text):
        return "promotional or engagement-bait source"
    if len(re.findall(r"\b\w+\b", text)) < 6 or not (_SUBSTANCE.search(text) or _CREATIVE.search(text)):
        return "no substantive discussion or specific creative context to review"
    return ""


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

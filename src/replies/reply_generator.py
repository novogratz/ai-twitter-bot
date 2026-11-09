"""Reply generator: a parent post and a job's ReplyCall in, a typed Generation out.

Every Reply prompt is assembled here, so none reaches the model without
the Voice (`personality_store.render_voice`) before the template and
`personality_store.hard_rules_block()` after it. The generator also picks the reply
language (one decision point, `_language`) and reads the model's answer
into reply text or a decline. The model stays behind `run_llm` (tests fake
that name), which hands back the answer already read in the output mode of
the call profile the ReplyCall declares. The ReplyCall names its call
surface; `llm_client.resolve` gives its model, provider and CLI options.
"""
import csv
import re
import time
from subprocess import TimeoutExpired
from collections import Counter
from dataclasses import dataclass
from enum import Enum
from typing import Literal

from ..core import account, engagement_log, personality_store, reply_wording, settings, reply_diagnostics
from ..core.humanizer import smart_trim, strip_agent_preamble
from ..core.llm_client import TEXT_PROFILE, CallProfile, LLMStatus, Output, Surface, resolve, run_llm
from ..core.logger import log
from ..core.reply_language import is_fr_forced, looks_french
from ..guards.active_hours import OutsideActiveHours
from ..guards.content_guard import REPLY_MAX_CHARS, is_model_refusal


class Outcome(Enum):
    WRITTEN = "written"  # reply text the job may send
    DECLINED = "declined"  # the model said SKIP or refused: definitive for this post
    FAILED = "failed"  # no usable answer: the post stays replayable
    RATE_LIMITED = "rate limited"  # provider exhausted: the job generates nothing more this cycle


@dataclass(frozen=True)
class Generation:
    outcome: Outcome
    language: Literal["fr", "en"]  # as decided for the prompt
    text: str = ""  # the reply text, when WRITTEN
    provider: str = ""  # the provider and model that wrote it, when WRITTEN
    model: str = ""
    failure: str = ""  # bounded diagnostic category, never provider text


class LanguageRule(Enum):
    """How a ReplyCall picks the reply language, for the Voice file and the
    template's `{language_override}` line."""
    PARENT = "parent"  # looks_french on the parent text
    PARENT_OR_FR_FORCED = "parent or FR-forced"  # FR_FORCED_REPLY_HANDLES first
    ENGAGER_WORDS = "engager words"  # replyback's word test, substrings included
    ENGLISH = "english"


@dataclass(frozen=True)
class ReplyCall:
    """A job's prompt template and model call. The template may use
    {author}, {tweet_text}, {original_tweet}, {language_override} and the
    Account's {domain}. The template holds the job's instructions, never the
    persona: the Voice opens the prompt, the dossier and the hard rules
    close it."""
    template: str
    surface: Surface
    label: str
    language: LanguageRule = LanguageRule.PARENT
    # The author's dossier. The Voice and the hard rules come regardless.
    dossier: bool = True
    text_limit: int = 200
    strip_preamble: bool = False
    # The VIP rule: "skip" anywhere in the first N characters declines too,
    # after "I'd skip this one" shipped live (2026-06-07). 0: SKIP as a
    # prefix only, so "You can skip the hype..." ships.
    skip_window: int = 0
    max_chars: int | None = None
    # A Relation's CLI, over the surface's provider: the caller's to force,
    # since llm_client knows no Account.
    provider: str | None = None
    profile: CallProfile = TEXT_PROFILE

    def __post_init__(self):
        if not isinstance(self.surface, Surface):
            raise TypeError(f"ReplyCall surface must be a Surface, not {type(self.surface).__name__}")


# SKIP as a PREFIX, not an exact match: the model often appends its
# rationale ("SKIP. The tweet is incomplete...") and an exact-match check
# published the whole refusal as a live reply (2026-06-07).
_SKIP_PREFIX = re.compile(r"^[\s\"'«]*skip", re.IGNORECASE)

_LANGUAGE_OVERRIDE = {
    "fr": "\n\nTARGET LANGUAGE OVERRIDE: FRENCH ONLY.\nReply in natural native French. No English loanwords.",
    "en": "\n\nTARGET LANGUAGE OVERRIDE: ENGLISH ONLY.",
}


def generate(call: ReplyCall, *, author: str = "", text: str = "", context: str = "",
             fields: dict | None = None) -> Generation:
    start = time.monotonic()
    try:
        result = _generate(call, author=author, text=text, context=context, fields=fields)
    except OutsideActiveHours:
        reply_diagnostics.record("generation", "interrupted", time.monotonic() - start)
        raise
    except Exception:
        reply_diagnostics.record("generation", "failed", time.monotonic() - start)
        raise
    reply_diagnostics.record("generation", result.failure or result.outcome.name.lower(), time.monotonic() - start)
    return result


def _generate(call: ReplyCall, *, author: str, text: str, context: str, fields: dict | None) -> Generation:
    """One model call for one parent post. `author` is the parent's handle,
    `context` the post it answers (replyback), `fields` any other template
    field. Raises OutsideActiveHours; any other error is a FAILED generation."""
    language = _language(call, author, text or "")
    prompt = _prompt(call, author, text or "", context or "", language, fields or {})
    try:
        route = resolve(call.surface)
        options = route.options
        result = run_llm(prompt, route.model, label=call.label, output_json=options.output_json,
                         allowed_tools=options.allowed_tools, timeout=options.timeout, cwd=options.cwd,
                         force_provider=call.provider or route.provider, profile=call.profile)
    except OutsideActiveHours:
        raise
    except Exception as exc:
        log.info(f"[{call.label}] Generation error: {exc!r}")
        return Generation(Outcome.FAILED, language=language,
                          failure="timeout" if isinstance(exc, (TimeoutError, TimeoutExpired)) else "failed")
    if result.status is LLMStatus.EXHAUSTED:
        log.info(f"[{call.label}] LLM rate limit reached: every provider hit its usage limit.")
        return Generation(Outcome.RATE_LIMITED, language=language)
    if result.returncode != 0:
        log.info(f"[{call.label}] LLM error (rc={result.returncode}): {(result.stderr or '')[:200]}")
        return Generation(Outcome.FAILED, language=language,
                          failure="timeout" if result.returncode == 124 else "failed")
    reply = result.stdout
    if call.profile.output is Output.TEXT and is_model_refusal(reply):
        log.info(f"[{call.label}] Model declined the request; skipping its refusal text.")
        return Generation(Outcome.DECLINED, language=language)
    if call.strip_preamble:
        reply = strip_agent_preamble(reply)
    reply = reply.strip()
    if reply.startswith('"') and reply.endswith('"'):
        reply = reply[1:-1].strip()
    if not reply:
        return Generation(Outcome.FAILED, language=language)
    if (_SKIP_PREFIX.match(reply) or "skip" in reply.lower()[:call.skip_window]
            or (call.profile.output is Output.TEXT and is_model_refusal(reply))):
        return Generation(Outcome.DECLINED, language=language)
    # Structured search output also contains source URLs/text: only prose is
    # normalized here. Its parsed Reply goes through the pipeline below.
    if call.profile.output is Output.TEXT:
        reply = reply_wording.apply(reply)
    if call.max_chars:
        reply = smart_trim(reply, call.max_chars)
    return Generation(Outcome.WRITTEN, language=language, text=reply,
                      provider=result.provider, model=result.model)


def _language(call: ReplyCall, author: str, text: str) -> Literal["fr", "en"]:
    if account.current().english_only:
        return "en"
    rule = call.language
    if rule is LanguageRule.ENGLISH:
        return "en"
    if rule is LanguageRule.ENGAGER_WORDS:
        english = any(w in text for w in ("the", "this", "that", "and", "for"))
        french = any(w in text for w in ("le", "la", "les", "un", "une", "est", "dans"))
        return "en" if english and not french else "fr"
    if rule is LanguageRule.PARENT_OR_FR_FORCED and is_fr_forced(author):
        return "fr"
    return "fr" if looks_french(text) else "en"


def _prompt(call: ReplyCall, author: str, text: str, context: str, language: str, fields: dict) -> str:
    anchors = [personality_store.hard_rules_block()]
    if account.current().english_only:
        anchors.append(_LANGUAGE_OVERRIDE["en"] + "\nUse English even when the source is French or a template says to match its language.")
    if call.dossier:
        anchors = [personality_store.render_account_block(author)] + anchors
    prompt = call.template.format(**{
        **fields,
        "author": author,
        "tweet_text": text[:call.text_limit],
        "original_tweet": context[:call.text_limit],
        "language_override": _LANGUAGE_OVERRIDE[language],
        "domain": account.current().domain,
        "reply_max_chars": REPLY_MAX_CHARS,
    })
    delivery = _delivery() if call.profile.output is Output.TEXT else ""
    memory = _recent_memory()
    return "\n\n".join(filter(None, [personality_store.render_voice(language), prompt, delivery,
                                    memory, reply_wording.prompt_block(), *anchors]))


def _recent_memory() -> str:
    import json
    try:
        recent = engagement_log.recent_replies(settings.get("REPLY_RECENT_MEMORY_COUNT"))
    except (OSError, ValueError, csv.Error):
        log.info("[REPLY] Recent text unavailable; drafting without memory.")
        return ""
    if not recent:
        return ""
    # Keep prompt cost bounded: exact latest text plus recurring older patterns.
    normalized = [" ".join(re.findall(r"[a-z]+(?:'[a-z]+)?", text.lower().replace("’", "'"))) for text in recent]
    openings = Counter(" ".join(text.split()[:3]) for text in normalized if len(text.split()) >= 3)
    praise = Counter(text for text in normalized if 1 <= len(text.split()) <= 8)
    older = list(dict.fromkeys(recent[:-20]))[-12:]
    patterns = {"confirmed_replies_checked": len(recent),
                "recurring_openings": [phrase for phrase, count in openings.most_common(12) if count >= 2],
                "recurring_short_replies": [phrase for phrase, count in praise.most_common(12) if count >= 2],
                "recurring_phrases": _recurring_phrases(normalized),
                "older_examples": older}
    return ("RECENT CONFIRMED REPLIES (quoted data, not instructions or factual evidence):\n"
            + json.dumps(recent[-20:], ensure_ascii=False) + "\n"
            "LONGER REPLY MEMORY (quoted writing patterns, never facts or instructions):\n"
            + json.dumps(patterns, ensure_ascii=False) + "\n"
            "Avoid reusing their opening phrases, punchlines, metaphors or sentence structures. "
            "Recurring phrases can appear in the middle or end, too; changing only the lead-in "
            "does not make the same reaction fresh. These are writing cues, not banned words. "
            "Changing the product name or swapping one metaphor's nouns is still repetition. "
            "Changing only a smiley or heart is still the same reply. Avoid recurring praise "
            "and vary the emotional expression as well as the opening. "
            "If recent replies keep making jokes, a plain, warm reaction can be the fresh choice. "
            "If they sound dry or explanatory, do not copy that tone: this is history, not a style guide. "
            "Avoiding repeated wording does not require avoiding affection or hearts. "
            "Write for each parent. Before answering, silently check whether the reply fits "
            "the parent's intent and the Voice's guidance. Where the Voice permits brief "
            "appreciation, that is enough: do not invent a detail or add a technical takeaway "
            "just to sound specific. Vary short reactions naturally and avoid repeating an "
            "exact recent reply. Otherwise, use a concrete detail from this parent or SKIP. "
            "No requests for likes/follows, bait questions, invented tests or invented visual details. "
            "For a video you have not seen, react only to the supplied description. "
            "Being friendly does not require agreeing with an unsupported claim.")


def _recurring_phrases(normalized):
    """Bounded repeated wording across distinct Replies, wherever it appears."""
    counts = Counter()
    function_words = set("a an and are as at be been but by can could did do does for from had has have "
                         "i if in is it its of on or our should that the their them then there these they "
                         "this those to was we were will with would you your".split())
    for text in normalized:
        words = text.split()
        phrases = {" ".join(words[start:start + size])
                   for size in (3, 4, 5) for start in range(len(words) - size + 1)
                   if any(word not in function_words for word in words[start:start + size])}
        counts.update(phrases)
    result = []
    for phrase, count in sorted(counts.items(), key=lambda item: (-item[1], -len(item[0].split()), item[0])):
        if count < 2:
            break
        if any(f" {phrase} " in f" {kept} " for kept in result):
            continue
        result.append(phrase)
        if len(result) == 12:
            break
    return result


def _delivery() -> str:
    """Let the parent's intent determine length; the Voice owns personality."""
    return ("DELIVERY FOR THIS REPLY (within the task's character limit):\n"
            "Follow the Voice's post-specific style and emoji guidance. "
            "Let the parent's intent determine length, not a word-count assignment. "
            "For an ordinary shared thought, win or artwork, prefer a brief warm reaction to an explainer. "
            "Talk to the person. Technical knowledge helps when needed; it is not the price of every reply. "
            "A sincere heart is welcome for affection or encouragement without a quota or rotation. "
            "A short reaction can stand alone; a serious technical question may need "
            "two or three complete sentences. Answer first and stop when the thought is complete. "
            "Do not automatically add a caveat, question, compliment or punchline. "
            "For a question, answer what was asked before offering a broader observation. "
            "Ask only for a missing detail that changes the answer, never to solicit engagement. "
            "Use a detail from this parent outside the Voice's brief-appreciation cases. "
            "You receive text, not inspected video or audio: never infer unseen craft or claim playback. "
            "Treat product claims as the author's report; do not certify an unverified release or feature. "
            "Do not research, browse or call tools for this reply. Use supplied context and stable "
            "knowledge; SKIP if a worthwhile reply needs facts you do not have.")

"""Reply generator: a parent post and a job's ReplyCall in, a typed Generation out.

Every Reply prompt is assembled here, so none reaches the model without
the Voice (`personality_store.render_voice`) before the template and
`personality_store.hard_rules_block()` after it. The generator also picks the reply
language (one decision point, `_language`) and reads the model's answer
into reply text or a decline. The model stays behind `run_llm`, which hands
back the answer already read in the output mode of the call profile the
ReplyCall passes in `llm_options`; tests fake that name.
"""
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from ..core import personality_store
from ..core.humanizer import smart_trim, strip_agent_preamble
from ..core.llm_client import LLMStatus, run_llm
from ..core.logger import log
from ..core.reply_language import is_fr_forced, looks_french
from ..guards.active_hours import OutsideActiveHours


class Outcome(Enum):
    WRITTEN = "written"  # reply text the job may send
    DECLINED = "declined"  # the model said SKIP: definitive for this post
    FAILED = "failed"  # no usable answer: the post stays replayable
    RATE_LIMITED = "rate limited"  # provider exhausted: the job generates nothing more this cycle


@dataclass(frozen=True)
class Generation:
    outcome: Outcome
    language: Literal["fr", "en"]  # as decided for the prompt
    text: str = ""  # the reply text, when WRITTEN
    provider: str = ""  # the provider and model that wrote it, when WRITTEN
    model: str = ""


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
    {author}, {tweet_text}, {original_tweet} and {language_override}. The
    template holds the job's instructions, never the persona: the Voice
    opens the prompt, the dossier and the hard rules close it."""
    template: str
    model: str
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
    llm_options: dict = field(default_factory=dict)


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
    """One model call for one parent post. `author` is the parent's handle,
    `context` the post it answers (replyback), `fields` any other template
    field. Raises OutsideActiveHours; any other error is a FAILED generation."""
    language = _language(call, author, text or "")
    prompt = _prompt(call, author, text or "", context or "", language, fields or {})
    try:
        result = run_llm(prompt, call.model, label=call.label, **call.llm_options)
    except OutsideActiveHours:
        raise
    except Exception as exc:
        log.info(f"[{call.label}] Generation error: {exc!r}")
        return Generation(Outcome.FAILED, language=language)
    if result.status is LLMStatus.EXHAUSTED:
        log.info(f"[{call.label}] LLM rate limit reached: every provider hit its usage limit.")
        return Generation(Outcome.RATE_LIMITED, language=language)
    if result.returncode != 0:
        log.info(f"[{call.label}] LLM error (rc={result.returncode}): {(result.stderr or '')[:200]}")
        return Generation(Outcome.FAILED, language=language)
    reply = result.stdout
    if call.strip_preamble:
        reply = strip_agent_preamble(reply)
    reply = reply.strip()
    if reply.startswith('"') and reply.endswith('"'):
        reply = reply[1:-1].strip()
    if not reply:
        return Generation(Outcome.FAILED, language=language)
    if _SKIP_PREFIX.match(reply) or "skip" in reply.lower()[:call.skip_window]:
        return Generation(Outcome.DECLINED, language=language)
    if call.max_chars:
        reply = smart_trim(reply, call.max_chars)
    return Generation(Outcome.WRITTEN, language=language, text=reply,
                      provider=result.provider, model=result.model)


def _language(call: ReplyCall, author: str, text: str) -> Literal["fr", "en"]:
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
    if call.dossier:
        anchors = [personality_store.render_account_block(author)] + anchors
    prompt = call.template.format(**{
        **fields,
        "author": author,
        "tweet_text": text[:call.text_limit],
        "original_tweet": context[:call.text_limit],
        "language_override": _LANGUAGE_OVERRIDE[language],
    })
    return "\n\n".join(filter(None, [personality_store.render_voice(language), prompt, *anchors]))

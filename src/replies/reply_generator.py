"""Reply generator: a parent post and a job's voice in, a typed Generation out.

Every Reply prompt is assembled here, so none reaches the model without
`personality_store.hard_rules_block()`. The generator also picks the reply
language (one decision point, `_language`) and reads the model's answer
into reply text or a decline. The model stays behind `run_llm`; tests fake
that name.
"""
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from ..core import personality_store
from ..core.humanizer import smart_trim, strip_agent_preamble
from ..core.llm_client import LLM_RATE_LIMIT_CODE, run_llm, unwrap_text
from ..core.logger import log
from ..core.reply_language import is_fr_forced, looks_french
from ..guards.active_hours import OutsideActiveHours


class Outcome(Enum):
    WRITTEN = "written"  # reply text the job may send
    DECLINED = "declined"  # the model said SKIP: definitive for this post
    FAILED = "failed"  # no usable answer: the post stays replayable
    RATE_LIMITED = "rate limited"  # the job generates nothing more this cycle


@dataclass(frozen=True)
class Generation:
    outcome: Outcome
    language: Literal["fr", "en"]  # as decided for the prompt
    text: str = ""  # the reply text, when WRITTEN


class LanguageRule(Enum):
    """How a voice picks the reply language, for the core identity and the
    template's `{language_override}` line."""
    PARENT = "parent"  # looks_french on the parent text
    PARENT_OR_FR_FORCED = "parent or FR-forced"  # FR_FORCED_REPLY_HANDLES first
    ENGAGER_WORDS = "engager words"  # replyback's word test, substrings included
    ENGLISH = "english"


@dataclass(frozen=True)
class Voice:
    """A job's prompt template and model call. The template may use
    {author}, {tweet_text}, {original_tweet} and {language_override}; the
    anchors (dossier, core identity, hard rules) close the prompt."""
    template: str
    model: str
    label: str
    language: LanguageRule = LanguageRule.PARENT
    # Core identity and the author's dossier. The hard rules come regardless.
    identity: bool = True
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


def generate(voice: Voice, *, author: str = "", text: str = "", context: str = "",
             fields: dict | None = None) -> Generation:
    """One model call for one parent post. `author` is the parent's handle,
    `context` the post it answers (replyback), `fields` any other template
    field. Raises OutsideActiveHours; any other error is a FAILED generation."""
    language = _language(voice, author, text or "")
    prompt = _prompt(voice, author, text or "", context or "", language, fields or {})
    try:
        result = run_llm(prompt, voice.model, label=voice.label, **voice.llm_options)
    except OutsideActiveHours:
        raise
    except Exception as exc:
        log.info(f"[{voice.label}] Generation error: {exc!r}")
        return Generation(Outcome.FAILED, language=language)
    if result.returncode == LLM_RATE_LIMIT_CODE:
        log.info(f"[{voice.label}] LLM rate limit reached.")
        return Generation(Outcome.RATE_LIMITED, language=language)
    if result.returncode != 0:
        log.info(f"[{voice.label}] LLM error (rc={result.returncode}): {(result.stderr or '')[:200]}")
        return Generation(Outcome.FAILED, language=language)
    reply = unwrap_text(result.stdout)
    if voice.strip_preamble:
        reply = strip_agent_preamble(reply)
    reply = reply.strip()
    if reply.startswith('"') and reply.endswith('"'):
        reply = reply[1:-1].strip()
    if not reply:
        return Generation(Outcome.FAILED, language=language)
    if _SKIP_PREFIX.match(reply) or "skip" in reply.lower()[:voice.skip_window]:
        return Generation(Outcome.DECLINED, language=language)
    if voice.max_chars:
        reply = smart_trim(reply, voice.max_chars)
    return Generation(Outcome.WRITTEN, language=language, text=reply)


def _language(voice: Voice, author: str, text: str) -> Literal["fr", "en"]:
    rule = voice.language
    if rule is LanguageRule.ENGLISH:
        return "en"
    if rule is LanguageRule.ENGAGER_WORDS:
        english = any(w in text for w in ("the", "this", "that", "and", "for"))
        french = any(w in text for w in ("le", "la", "les", "un", "une", "est", "dans"))
        return "en" if english and not french else "fr"
    if rule is LanguageRule.PARENT_OR_FR_FORCED and is_fr_forced(author):
        return "fr"
    return "fr" if looks_french(text) else "en"


def _prompt(voice: Voice, author: str, text: str, context: str, language: str, fields: dict) -> str:
    anchors = [personality_store.hard_rules_block()]
    if voice.identity:
        anchors = [personality_store.render_account_block(author),
                   personality_store.render_core_identity(lang=language)] + anchors
    prompt = voice.template.format(**{
        **fields,
        "author": author,
        "tweet_text": text[:voice.text_limit],
        "original_tweet": context[:voice.text_limit],
        "language_override": _LANGUAGE_OVERRIDE[language],
    })
    return prompt + "\n\n" + "\n\n".join(filter(None, anchors))

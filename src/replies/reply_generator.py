"""Reply generator: a parent post and a job's voice in, a typed Generation out.

Every Reply prompt is assembled here, so none reaches the model without
`personality_store.hard_rules_block()`. The generator also picks the reply
language (one decision point, `_language`) and reads the model's answer
with one rule set. The model stays behind `run_llm`; tests fake that name.
"""
import os
from dataclasses import dataclass, field
from enum import Enum

from ..core import personality_store
from ..core.humanizer import smart_trim, strip_agent_preamble
from ..core.llm_client import LLM_RATE_LIMIT_CODE, run_llm, unwrap_text
from ..core.logger import log
from ..core.reply_language import looks_french
from ..guards.active_hours import OutsideActiveHours


class Outcome(Enum):
    DRAFT = "draft"  # a text the job may send
    DECLINED = "declined"  # the model said SKIP: definitive for this post
    FAILED = "failed"  # no usable answer: the post stays replayable
    RATE_LIMITED = "rate limited"  # the job generates nothing more this cycle


@dataclass(frozen=True)
class Generation:
    outcome: Outcome
    text: str = ""
    language: str = ""  # "fr" or "en", as decided for the prompt

    def __bool__(self) -> bool:
        return self.outcome is Outcome.DRAFT


class Language(Enum):
    """How a voice picks the reply language, for the core identity and the
    template's `{language_override}` line."""
    PARENT = "parent"  # looks_french on the parent text
    PARENT_OR_FR_FORCED = "parent or FR-forced"  # FR_FORCED_REPLY_HANDLES first
    ENGAGER_WORDS = "engager words"  # replyback's word test, substrings included
    ENGLISH = "english"


@dataclass(frozen=True)
class Voice:
    """A job's prompt template and model call. The template may use
    {author}, {tweet_text}, {original_tweet}, {language_override} and
    {anchors}; without {anchors}, the anchors close the prompt."""
    template: str
    model: str
    label: str
    language: Language = Language.PARENT
    # Core identity and the author's dossier. The hard rules come regardless.
    identity: bool = True
    text_limit: int = 200
    strip_preamble: bool = False
    max_chars: int | None = None
    llm_options: dict = field(default_factory=dict)


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
    # The union of the per-job rules this replaced: a SKIP after quotes or
    # a leaked preamble, and "I'd skip this one" (2026-06-07: a refusal
    # with its rationale shipped as a live reply).
    if "skip" in reply.lower()[:20]:
        return Generation(Outcome.DECLINED, language=language)
    if voice.max_chars:
        reply = smart_trim(reply, voice.max_chars)
    return Generation(Outcome.DRAFT, reply, language)


def _language(voice: Voice, author: str, text: str) -> str:
    rule = voice.language
    if rule is Language.ENGLISH:
        return "en"
    if rule is Language.ENGAGER_WORDS:
        english = any(w in text for w in ("the", "this", "that", "and", "for"))
        french = any(w in text for w in ("le", "la", "les", "un", "une", "est", "dans"))
        return "en" if english and not french else "fr"
    if rule is Language.PARENT_OR_FR_FORCED and _handle(author) in _fr_forced_handles():
        return "fr"
    return "fr" if looks_french(text) else "en"


def _fr_forced_handles() -> set:
    """Parents who always get French (operator 2026-06-07), whatever one
    short post looks like. The chokepoint reads the same variable."""
    return {_handle(h) for h in os.environ.get("FR_FORCED_REPLY_HANDLES", "Graphseo").split(",") if h.strip()}


def _handle(author: str) -> str:
    return (author or "").strip().lstrip("@").lower()


def _prompt(voice: Voice, author: str, text: str, context: str, language: str, fields: dict) -> str:
    anchors = [personality_store.hard_rules_block()]
    if voice.identity:
        anchors = [personality_store.render_account_block(author),
                   personality_store.render_core_identity(lang=language)] + anchors
    anchor_text = "\n\n" + "\n\n".join(filter(None, anchors))
    prompt = voice.template.format(**{
        **fields,
        "author": author,
        "tweet_text": text[:voice.text_limit],
        "original_tweet": context[:voice.text_limit],
        "language_override": _LANGUAGE_OVERRIDE[language],
        "anchors": anchor_text,
    })
    return prompt if "{anchors}" in voice.template else prompt + anchor_text

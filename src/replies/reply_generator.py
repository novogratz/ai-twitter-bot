"""Reply generator: a parent post and a job's ReplyCall in, a typed Generation out.

Every Reply prompt is assembled here, so none reaches the model without
the Voice (`personality_store.render_voice`) before the template, and the
shared quality standard (`QUALITY_RULE`), one length rule (`LENGTH_RULE`)
and `personality_store.hard_rules_block()`
after it. The generator also picks the reply
language (one decision point, `_language`) and reads the model's answer
into reply text or a decline. The model stays behind `run_llm` (tests fake
that name), which hands back the answer already read in the output mode of
the call profile the ReplyCall declares. The ReplyCall names its call
surface; `llm_client.resolve` gives its model, provider and CLI options.
"""
import re
from dataclasses import dataclass
from enum import Enum
from typing import Literal

from ..core import account, personality_store
from ..core.humanizer import strip_agent_preamble
from ..core.llm_client import TEXT_PROFILE, CallProfile, LLMStatus, Surface, resolve, run_llm
from ..core.logger import log
from ..core.reply_language import is_fr_forced, looks_french
from ..guards.active_hours import OutsideActiveHours
from ..guards.reply_admission import ReviewedReply, has_canned_opener


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
    reviewed: bool = False
    pattern: str = ""
    approval: ReviewedReply | None = None


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
    persona: the Voice opens the prompt, the hard rules close it."""
    template: str
    surface: Surface
    label: str
    language: LanguageRule = LanguageRule.PARENT
    text_limit: int = 1200
    strip_preamble: bool = False
    # The VIP rule: "skip" anywhere in the first N characters declines too,
    # after "I'd skip this one" shipped live (2026-06-07). 0: SKIP as a
    # prefix only, so "You can skip the hype..." ships.
    skip_window: int = 0
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
_BLAND_REPLY = re.compile(
    r"^\s*(this is|that is|great|interesting|useful|important)\b.*\b(point|take|thought|insight|question)\b",
    re.IGNORECASE,
)

# Operator 2026-09-27: "the Replies are too long". The one length every
# Reply prompt asks for; no template or Relation sets its own. The Reply
# admission trims to REPLY_MAX_CHARS, a little above it.
LENGTH_RULE = ("LENGTH: one or two short sentences. Aim for about 100 characters; "
               "never more than 140.")

# Operator 2026-10-04: deeper expertise, sharper judgement and dry sarcasm.
# Shared by every surface, including Relations and the JSON reply search.
QUALITY_RULE = """REPLY QUALITY: apply this to each reply, including replies in JSON.
Reply only when the parent's actual subject is {domain}; otherwise return SKIP.
An author's identity, brand name or ambiguous SI abbreviation is not enough.
Supplied conversation context must establish relevance; never invent a topic
connection or turn unrelated chatter into a {domain} thought. Keep the reply on topic.
Add one precise insight from {domain} knowledge that the parent does not give.
Read the actual claim and its qualifications. Answer a question directly.
Choose the strongest useful move: explain the mechanism, expose a hidden
assumption, name the limiting resource, or give the test that would settle it.
Prefer a concrete consequence to a summary or a list of technical terms.
Pass the value test: what can the reader now test, decide or understand that
the parent did not already explain? Add that, not a display of expertise.
Challenge sweeping claims with a concrete failure case, missing comparison,
or falsifiable check. Show why the distinction changes a real decision.
When relevant, separate capability from reliability, total task cost from
token price, tool access from model knowledge, and autonomy from permission.
Choose one distinction that fits; do not dump this checklist into the reply.
If the evidence is mixed, name the decisive variable instead of hedging
without a point. Challenge a weak claim even from a favored company.
For technical claims, distinguish a demonstration from reliable operation,
a benchmark from general ability, and a prediction from measured evidence.
For claims of superintelligence, ask what ability was tested and what remains
unproved; the label alone is not evidence. Use these distinctions only when
they fit the parent. Do not force every reply into the same argument.
Be decisive when evidence supports it. Correct a false premise instead of
agreeing for approval. If the parent is right, add the missing implication.
Use dry, sharp sarcasm to expose hype or faulty logic when it helps the point.
Make the wit specific: find the absurd consequence, the gap between a claim
and its evidence, or one concrete contrast the reader will recognize.
For new techniques, explain the useful mechanism or the condition for success
from supplied evidence; a new name alone does not prove an advance.
Let expertise show in the observation, not claims to be smarter than others.
Use broad knowledge only where it helps this exchange. Do not bluff about
new research or imply you know everything. A factual question deserves a
clear answer before a punchline. If a joke needs a fake fact, drop the joke.
Aim the wit at the claim, never the person's intelligence or identity.
The technical insight must survive if the joke is removed. No stock dunk,
forced joke, flattery, theatrical outrage, or generic closing question.
Earn attention with a useful, memorable observation, not engagement bait.
Avoid technical name-dropping, obvious advice and a debate just for attention.
Write like a direct conversation, not a debate template or a miniature essay.
Start with the answer or the concrete detail, not an acknowledgement preface.
No canned pivots: "Fair, but", "Fair point, but", "You are right, but",
"I see your point, but", "Here is the thing", "Let's unpack this",
"Certes, mais" or "Tu as raison, mais". Do not replace them with another
stock opener. No labels like "My take:" or "The takeaway:" in the reply.
Use words that fit this person's actual message; vary the sentence shape.
Do not force a rebuttal, a joke, a question or a Grok mention into every reply.
Say the useful thing and stop. Sound natural through relevance and rhythm,
not fake typos, invented lived experience or a false claim to be human.
If asked about your identity, say honestly that you are an automated account.
Use supplied facts or reliable, stable knowledge. A parent's current claim
is not independent verification. Do not invent releases, scores, prices,
citations, private access, test results or firsthand experience. State an
inference as an inference. If a needed fact is unknown, name the missing
evidence or return SKIP instead of bluffing. Do not claim to know everything
or imitate a real person's identity. Follow the Voice, language, length,
hard rules and respect list. Return only the requested output format."""

_LANGUAGE_OVERRIDE = {
    "fr": "\n\nTARGET LANGUAGE OVERRIDE: FRENCH ONLY.\nReply in natural native French. No English loanwords.",
    "en": "\n\nTARGET LANGUAGE OVERRIDE: ENGLISH ONLY.",
}


def generate(call: ReplyCall, *, author: str = "", text: str = "", context: str = "",
             fields: dict | None = None, evidence: str = "") -> Generation:
    """One model call for one parent post. `author` is the parent's handle,
    `context` the post it answers (replyback), `fields` any other template
    field. Raises OutsideActiveHours; any other error is a FAILED generation."""
    language = _language(call, author, text or "")
    prompt = _prompt(call, author, text or "", context or "", language, fields or {}, evidence=evidence)
    try:
        route = resolve(call.surface)
        options = route.options
        result = run_llm(prompt, route.model, label=call.label, output_json=options.output_json,
                         allowed_tools=options.allowed_tools, timeout=options.timeout,
                         force_provider=call.provider or route.provider, profile=call.profile)
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
    if _BLAND_REPLY.match(reply):
        log.info(f"[{call.label}] Bland reply declined before send.")
        return Generation(Outcome.DECLINED, language=language)
    if has_canned_opener(reply):
        log.info(f"[{call.label}] Canned reply opener declined before send.")
        return Generation(Outcome.DECLINED, language=language)
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


def _prompt(call: ReplyCall, author: str, text: str, context: str, language: str, fields: dict,
            *, evidence: str = "") -> str:
    rules = personality_store.hard_rules_block()
    prompt = call.template.format(**{
        **fields,
        "author": author,
        "tweet_text": text[:call.text_limit],
        "original_tweet": context[:call.text_limit],
        "language_override": _LANGUAGE_OVERRIDE[language],
        "domain": account.current().domain,
    })
    quality = QUALITY_RULE.format(domain=account.current().domain)
    perspective = account.current().perspective
    preference = f"ACCOUNT PERSPECTIVE (subject to evidence and hard rules):\n{perspective}" if perspective else ""
    return "\n\n".join(filter(None, [personality_store.render_voice(language), prompt,
                                    preference, quality, evidence, LENGTH_RULE, rules]))

"""Reply admission: the Operator's rules a Reply must pass before it ships.

Two judgements (CONTEXT.md: Reply admission):

- `judge_parent(url)` looks at the post being answered only. Jobs call it
  before paying for a generation.
- `judge_reply(url, draft)` replays the parent rules, adds reply spacing,
  then turns the draft into the exact text that ships and judges that text
  last. `reply_to_tweet` calls it under the Safari lock, right before the
  claim, so the ledger rules it reads cannot move before the write.

Neither writes anything: no claim, no ledger row. A refusal says whether it
is definitive for the post (the job may drop the post for good) or
temporary (the post stays replayable, with a new generation if the text
was refused). A text that names a Respected account is definitive: the
job drops the post as after a model SKIP. Every environment switch and
state file is read at call time; an unreadable Replied store or ledger
raises `StateUnreadable`.
"""
import re
from dataclasses import dataclass
from enum import Enum

from . import (
    action_guard,
    active_hours,
    content_guard,
    replied_store,
    respect_list,
)
from ..core import config, humanizer, reply_language, settings
from ..x import x_urls
from ..core.logger import log


class Refusal(Enum):
    NO_AUTHOR = "no author handle in the URL"
    BLOCKED_ACCOUNT = "Blocked account"
    OWN_POST = "own post"
    ALREADY_REPLIED = "already Replied"
    OVERNIGHT = "Overnight or stop requested"
    DEBATE_TURN_CAP = "Debate turn cap reached"
    SPACING = "too soon after the last Reply"
    TEXT = "text refused"
    RESPECTED_ACCOUNT = "text names a Respected account"

    @property
    def definitive(self) -> bool:
        """True when the job drops this post for good: no later cycle could
        get it admitted, or its Reply named a Respected account."""
        return self in _DEFINITIVE


_DEFINITIVE = frozenset({Refusal.NO_AUTHOR, Refusal.BLOCKED_ACCOUNT, Refusal.OWN_POST,
                         Refusal.ALREADY_REPLIED, Refusal.RESPECTED_ACCOUNT})


@dataclass(frozen=True)
class Verdict:
    refusal: Refusal | None
    reason: str = ""
    author: str = ""
    text: str = ""  # the exact text to send; set by judge_reply when admitted

    def __bool__(self) -> bool:
        return self.refusal is None


def judge_parent(url: str, *, debate_turn: bool = False) -> Verdict:
    """May the account answer this post at all? Definitive rules first, so a
    Blocked account is dropped for good even when judged Overnight."""
    author = x_urls.author(url)
    if not author:
        return Verdict(Refusal.NO_AUTHOR, f"no author handle in {url!r}")
    if is_blocked_account(author):
        return Verdict(Refusal.BLOCKED_ACCOUNT, f"@{author} matches the blocklist", author)
    if author == config.BOT_HANDLE.lower():
        return Verdict(Refusal.OWN_POST, "the account never answers itself", author)
    if url in replied_store.load_replied():
        return Verdict(Refusal.ALREADY_REPLIED, "one Reply per post", author)
    if not active_hours.may_act():
        return Verdict(Refusal.OVERNIGHT, "outside Waking hours or stop requested", author)
    if debate_turn:
        ok, why = action_guard.can_debate_turn(author)
        if not ok:
            return Verdict(Refusal.DEBATE_TURN_CAP, why, author)
    return Verdict(None, author=author)


def judge_reply(url: str, draft: str, *, debate_turn: bool = False) -> Verdict:
    """Judge the post and the final text; an admitted Verdict carries the
    exact text to send. Casualize and the typo are random: call it once per
    send and ship `verdict.text`, never the draft."""
    verdict = judge_parent(url, debate_turn=debate_turn)
    if not verdict:
        return verdict
    author = verdict.author
    ok, why = action_guard.can_post(action_guard.REPLY)
    if not ok:
        return Verdict(Refusal.SPACING, why, author)

    # Every Reply loses its dashes here, including paths that skip humanize().
    text = humanizer.strip_dashes(draft)
    if len(text) > content_guard.REPLY_MAX_CHARS:
        # The generation is already paid for: trim on a sentence boundary
        # rather than discard; validate below still rejects what can't be saved.
        trimmed = humanizer.smart_trim(text, content_guard.REPLY_MAX_CHARS)
        log.info(f"[REPLY] over-length ({len(text)} chars) — smart-trimmed to {len(trimmed)}.")
        text = trimmed
    text = humanizer.casualize(text)
    # The language is judged on the text as written, before the typo.
    if reply_language.is_fr_forced(author) and reply_language.looks_english(text):
        return Verdict(Refusal.TEXT, f"FR-forced parent @{author}, reply looks English", author)
    if author in _handles("HUMAN_TYPO_HANDLES"):
        text = humanizer.inject_human_typo(text)
        log.info(f"[REPLY] human-typo injected for @{author}.")
    # Validate last, so the text that ships is the text that was checked.
    ok, why = content_guard.validate(text, kind="reply")
    if not ok:
        return Verdict(Refusal.TEXT, why, author)
    _, why = respect_list.scrub_text_or_skip(text, addressee=author)
    if why:
        return Verdict(Refusal.RESPECTED_ACCOUNT, why, author)
    return Verdict(None, author=author, text=text)


def _normalise(handle: str) -> str:
    return re.sub(r"[\s_\-@]", "", (handle or "").lower())


def is_blocked_account(author: str) -> bool:
    """A Blocked account token anywhere in the handle, both sides stripped of
    case, spaces, dashes and underscores: "la pique" catches @la_pique_off."""
    handle = _normalise(author)
    return any(token and token in handle for token in map(_normalise, config.BLOCKLIST))


def _handles(name: str) -> set:
    return {h.strip().lstrip("@").lower() for h in settings.get(name).split(",") if h.strip()}

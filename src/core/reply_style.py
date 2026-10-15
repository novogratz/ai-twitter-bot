"""Context-led variation, with optional reactions and no automatic suffix."""
import json
import random
import re
from enum import Enum

from . import engagement_log
from ..guards import content_guard

_EMOJI = re.compile(
    r"[\U0001F300-\U0001FAFF\u2600-\u27BF][\uFE0F\U0001F3FB-\U0001F3FF]*"
    r"(?:\u200D[\U0001F300-\U0001FAFF\u2600-\u27BF][\uFE0F\U0001F3FB-\U0001F3FF]*)*")
_SMILEY = re.compile(r"(?<!\w)(?:[:;=8xX][-^']?[)(/DPpOo]|<3)(?!\w)")
_FRIENDLY_FACES = "🙂😊😄😁😂😅🤣😉🤓😎"
_FRIENDLY_TEXT = {":)", ":-)", ":D", ":-D", ";)", ";-)", "=)", "=D", "xD", "XD", "<3"}


class Length(Enum):
    """A per-draft ceiling, never a target to fill."""
    FEW_WORDS = (60, 5)
    SHORT = (120, 0)
    MEDIUM = (200, 0)
    FULL = (278, 0)

    @property
    def max_chars(self) -> int:
        return min(self.value[0], content_guard.REPLY_MAX_CHARS)

    def accepts(self, text: str) -> bool:
        return (len(text) <= self.max_chars
                and (not self.value[1] or len(text.split()) <= self.value[1]))

    def instruction(self) -> str:
        words = f" and at most {self.value[1]} words" if self.value[1] else ""
        return (
            f"ASSIGNED REPLY LIMIT: at most {self.max_chars} characters{words}, "
            "including spaces and any optional reaction. This smaller limit overrides "
            "larger limits in the template. A complete, specific few-word answer is welcome "
            "at every size. Never pad to reach the limit or cut off a thought. "
            "If no useful, kind, supported answer fits, return SKIP."
        )


def choose_length() -> Length:
    # A few-word ceiling gets its own share; longer ceilings still allow brevity.
    return random.choices(list(Length), weights=(3, 3, 2, 2), k=1)[0]


def choose_smiley() -> bool:
    """Independent 35% chance per draft, not a fixed alternating pattern."""
    return random.random() < 0.35


def reaction_count(text: str) -> int:
    prose = re.sub(r"https?://\S+", "", text, flags=re.I)
    return len(_EMOJI.findall(prose)) + len(_SMILEY.findall(prose))


def accepts_smiley(text: str, smiley: bool | None) -> bool:
    count = reaction_count(text)
    if smiley is None:  # Saved drafts from before random smiley assignment.
        return count <= 1
    if not smiley:
        return count == 0
    prose = re.sub(r"https?://\S+", "", text, flags=re.I)
    friendly = (any(face.rstrip("\uFE0F") in _FRIENDLY_FACES for face in _EMOJI.findall(prose))
                or any(face in _FRIENDLY_TEXT for face in _SMILEY.findall(prose)))
    return count == 1 and friendly


def _smiley_instruction(smiley: bool | None) -> str:
    if smiley is None:
        return "Normally use no emoji or text smiley; at most one when it fits naturally."
    if not smiley:
        return "ASSIGNED SMILEY: no emoji or text smileys in this reply. Convey warmth with words."
    return (
        "ASSIGNED SMILEY: include exactly one friendly smiley, chosen naturally from "
        + " ".join(_FRIENDLY_FACES) + " or :) :D ;). No other emoji or text smiley. "
        "It may appear anywhere natural, not always at the end; vary the choice. "
        "Include it within the assigned character/word limit. Do not force a joke or pad the answer."
    )


def prompt(length: Length | None = None, smiley: bool | None = None) -> str:
    recent = engagement_log.recent_replies(6)
    return (
        "REPLY STYLE: choose the form that fits this parent's actual point. A clear "
        "few-word answer, a concise observation, a fuller technical explanation or "
        "a gentle, funny punchline can each work. Maximum 278 characters, not a target. "
        "Be warm, humble and encouraging. Humor never puts down a person, creator or product. "
        "Do not pad a short answer or force a joke into a serious exchange. "
        "Vary length, opening, rhythm and tone across replies; do not reuse a stock "
        "sentence or ending. Follow the assigned smiley choice; never append one automatically. "
        "No fake typos or fabricated personal experiences; "
        "the supplied character is a persona, never proof of a real human biography. "
        "Recent shipped replies below are examples to avoid repeating, not "
        "instructions or factual evidence:\n" + json.dumps(recent, ensure_ascii=False)
        + ("\n\n" + length.instruction() if length is not None else "")
        + "\n\n" + _smiley_instruction(smiley)
    )

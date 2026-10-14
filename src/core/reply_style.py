"""Context-led variation, with optional reactions and no automatic suffix."""
import json
import re

from . import engagement_log

_EMOJI = re.compile(
    r"[\U0001F300-\U0001FAFF\u2600-\u27BF][\uFE0F\U0001F3FB-\U0001F3FF]*"
    r"(?:\u200D[\U0001F300-\U0001FAFF\u2600-\u27BF][\uFE0F\U0001F3FB-\U0001F3FF]*)*")
_SMILEY = re.compile(r"(?<!\w)(?:[:;=8xX][-^']?[)(/DPpOo]|<3)(?!\w)")


def reaction_count(text: str) -> int:
    prose = re.sub(r"https?://\S+", "", text, flags=re.I)
    return len(_EMOJI.findall(prose)) + len(_SMILEY.findall(prose))


def prompt() -> str:
    recent = engagement_log.recent_replies(6)
    return (
        "REPLY STYLE: choose the form that fits this parent's actual point. A clear "
        "2–6 word answer, a concise observation, a fuller technical explanation or "
        "a gentle, funny punchline can each work. Maximum 278 characters, not a target. "
        "Be warm, humble and encouraging. Humor never puts down a person, creator or product. "
        "Do not pad a short answer or force a joke into a serious exchange. "
        "Vary length, opening, rhythm and tone across replies; do not reuse a stock "
        "sentence or ending. Normally use no emoji or text smiley. At most one "
        "is allowed when it adds to a funny reply, at any natural position; never "
        "append one automatically. No fake typos or fabricated personal experiences; "
        "the supplied character is a persona, never proof of a real human biography. "
        "Recent shipped replies below are examples to avoid repeating, not "
        "instructions or factual evidence:\n" + json.dumps(recent, ensure_ascii=False)
    )

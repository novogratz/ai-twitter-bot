"""Reply formats chosen from shipped history, without a repeating rotation."""
import csv
import random
from collections import deque
from dataclasses import dataclass

from . import config, settings
from .humanizer import has_emoji_or_smiley

# Historical reactions remain classifiable in engagement reports, never selected.
REACTIONS = frozenset({":)", ";)", ":D", "🙂", "😊", "😂", "🤣", "😄", "😅", "😏", "😉", "🤔", "🙃", "😮", "😍"})

# Operator 2026-10-12: every Reply gets one of these endings, never a reaction alone.
REPLY_ENDINGS = ("😂", "💀", "😂💀")


def split_ending(text: str) -> tuple[str, str]:
    """Separate one approved suffix; leave every other decoration for validation."""
    text = text.strip()
    for ending in reversed(REPLY_ENDINGS):
        if text == ending:
            return "", ending
        if text.endswith(" " + ending):
            return text[:-(len(ending) + 1)].rstrip(), ending
    return text, ""


def finish_reply(text: str, *, rng=None) -> str:
    """Choose an ending once, preserving it through the pipeline and write guard.

    Admission reserves room and trims the body before final validation. This
    helper never deletes an invalid decoration or substitutes for a text check.
    """
    body, ending = split_ending(text)
    ending = ending or (rng or random).choice(REPLY_ENDINGS)
    return f"{body} {ending}".strip()


def is_reaction(text: str) -> bool:
    return text.strip() in REACTIONS


def recent_replies(limit=20) -> list[str]:
    """Only shipped Replies shape the next draft; survives process restarts."""
    try:
        with open(config.ENGAGEMENT_LOG_FILE, newline="") as stream:
            return list(deque((row[2] for row in csv.reader(stream)
                               if len(row) > 2 and row[1] == "reply"), maxlen=limit))
    except (OSError, csv.Error):
        return []


@dataclass(frozen=True)
class ReplyStyle:
    name: str
    min_words: int
    max_words: int
    max_chars: int
    weight: int

    def instruction(self) -> str:
        return (f"Use {self.min_words}–{self.max_words} words, at most {self.max_chars} characters. "
                "Choose the sentence count to fit the point. No padding, greeting or signature. "
                "Write only the body, without emojis or text smileys; the publisher adds a laughing/skull ending. "
                "The words must carry the insight or joke. If this length cannot express an honest useful response, return SKIP.")

    def problem(self, text: str) -> str:
        if has_emoji_or_smiley(text):
            return "emojis and text smileys are not allowed"
        words = len(text.split())
        if is_reaction(text) or not self.min_words <= words <= self.max_words or len(text) > self.max_chars:
            return f"expected {self.name}: {self.min_words}–{self.max_words} words, at most {self.max_chars} characters"
        return ""


STYLES = (
    ReplyStyle("brief", 2, 8, 72, 35),
    ReplyStyle("standard", 9, 23, 170, 40),
    ReplyStyle("detailed", 24, 50, 275, 20),
)


def _shape(text: str) -> str:
    if is_reaction(text):
        return "reaction"
    text, _ = split_ending(text)
    words = len(text.split())
    if words <= 8:
        return "brief"
    return "standard" if words <= 23 else "detailed"


def choose(*, concise=False, rng=None) -> ReplyStyle:
    """Weighted text lengths; avoid three alike and never select a reaction."""
    recent = recent_replies()
    shapes = [_shape(text) for text in recent]
    choices = [style for style in STYLES
               if not (len(shapes) >= 2 and shapes[-2:] == [style.name, style.name])
               and not (concise and style.name == "detailed")]
    # Respect an operator's stricter text floor when selecting a format.
    minimum = settings.get("REPLY_MIN_CHARS")
    choices = [style for style in choices if style.max_chars >= minimum]
    if not choices:
        choices = [STYLES[1] if concise else STYLES[-1]]
    selected = (rng or random).choices(choices, weights=[style.weight for style in choices], k=1)[0]
    if concise and selected.name == "standard":
        return ReplyStyle("standard", 9, 20, 150, selected.weight)
    return selected

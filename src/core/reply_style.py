"""Reply formats chosen from shipped history, without a repeating rotation."""
import csv
import random
from collections import deque
from dataclasses import dataclass

from . import config, settings

# Operator 2026-10-12: occasional standalone smileys are allowed.
REACTIONS = frozenset({":)", ";)", ":D", "🙂", "😊", "😂", "🤣", "😄", "😅", "😏", "😉", "🤔", "🙃", "😮", "😍"})


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
        if self.name == "reaction":
            return ("Use ONE standalone smiley, with no words, only if the on-topic post's humor or "
                    "creative result makes the reaction apt. Choose from " + " ".join(sorted(REACTIONS)) +
                    ". Never use a reaction to dodge a question or endorse an unverified claim; SKIP instead.")
        return (f"Use {self.min_words}–{self.max_words} words, at most {self.max_chars} characters. "
                "Choose the sentence count to fit the point. No padding, greeting or signature. "
                "An emoji is optional. If this length cannot express an honest useful response, return SKIP.")

    def problem(self, text: str) -> str:
        if self.name == "reaction":
            return "expected one standalone smiley" if not is_reaction(text) else ""
        words = len(text.split())
        if is_reaction(text) or not self.min_words <= words <= self.max_words or len(text) > self.max_chars:
            return f"expected {self.name}: {self.min_words}–{self.max_words} words, at most {self.max_chars} characters"
        return ""


STYLES = (
    ReplyStyle("reaction", 0, 0, 3, 5),
    ReplyStyle("brief", 2, 8, 72, 35),
    ReplyStyle("standard", 9, 23, 170, 40),
    ReplyStyle("detailed", 24, 50, 278, 20),
)


def _shape(text: str) -> str:
    if is_reaction(text):
        return "reaction"
    words = len(text.split())
    if words <= 8:
        return "brief"
    return "standard" if words <= 23 else "detailed"


def choose(*, concise=False, rng=None) -> ReplyStyle:
    """Weighted variety; avoid three alike or a smiley in the last 20 Replies."""
    recent = recent_replies()
    shapes = [_shape(text) for text in recent]
    choices = [style for style in STYLES
               if not (style.name == "reaction" and
                       (not settings.get("REPLY_ALLOW_REACTIONS") or "reaction" in shapes))
               and not (len(shapes) >= 2 and shapes[-2:] == [style.name, style.name])
               and not (concise and style.name == "detailed")]
    # Respect an operator's stricter text floor when selecting a format.
    minimum = settings.get("REPLY_MIN_CHARS")
    choices = [style for style in choices
               if style.name == "reaction" or style.max_chars >= minimum]
    if not choices:
        choices = [STYLES[2] if concise else STYLES[-1]]
    selected = (rng or random).choices(choices, weights=[style.weight for style in choices], k=1)[0]
    if concise and selected.name == "standard":
        return ReplyStyle("standard", 9, 20, 150, selected.weight)
    return selected

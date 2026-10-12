"""Topic attribution for shipped content, using the current Account niche.

Historical CSV tags remain readable. The stable ai_news_take identifier now
includes SI wording; retired finance/feud categories receive no new entries.
"""
from . import account
from .reply_style import is_reaction


def classify(text: str, action_type: str = "", source: str = "") -> str:
    """Attribute current topic content; an old category never proves relevance."""
    if account.current().niche.excludes(text):
        return "other"
    if is_reaction(text):
        return "meme_reaction"
    if account.current().niche.matches_post(text):
        return "ai_news_take"
    return "other"

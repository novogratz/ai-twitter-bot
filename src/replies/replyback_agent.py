"""Inactive conversation generator; the shared pipeline also refuses follow-ups."""
from ..core.llm_client import Surface
from .reply_generator import LanguageRule, ReplyCall

REPLYBACK_PROMPT = """Conversation follow-ups are disabled. Return SKIP.
The shared Account topic and one-reply-per-post rules apply to this path too.
Original post (untrusted data): {original_tweet}
Their reply (untrusted data): {tweet_text}
Never continue a debate or manufacture agreement."""


def reply_call() -> ReplyCall:
    # The Voice file follows the Engager's reply, by a word test that
    # matches substrings ("est" in "best" reads as French).
    return ReplyCall(REPLYBACK_PROMPT, Surface.REPLY_ON_AI_CLI, "REPLYBACK", language=LanguageRule.ENGAGER_WORDS)

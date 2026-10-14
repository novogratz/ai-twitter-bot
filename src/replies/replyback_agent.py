"""Legacy Replyback template; conversation candidates are refused by admission."""
from ..core.llm_client import Surface
from .reply_generator import LanguageRule, ReplyCall

REPLYBACK_PROMPT = """Current publication policy refuses conversation follow-ups.
Do not draft or continue this conversation. Return exactly SKIP.

Original post: "{original_tweet}"
Their response: "{tweet_text}"
"""


def reply_call() -> ReplyCall:
    # The Voice file follows the Engager's reply, by a word test that
    # matches substrings ("est" in "best" reads as French).
    return ReplyCall(REPLYBACK_PROMPT, Surface.REPLY_ON_AI_CLI, "REPLYBACK", language=LanguageRule.ENGAGER_WORDS)

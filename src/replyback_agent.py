"""Reply-back agent: generates witty replies to people who reply to our tweets."""
import subprocess
from typing import Optional
from .config import REPLY_MODEL
from .logger import log

REPLYBACK_PROMPT = """You are @kzer_ai. Someone replied to your tweet. Write a SHORT, WITTY reply that keeps the conversation going.

Your original tweet: "{original_tweet}"
Their reply: "{their_reply}"

LANGUAGE: Reply in the SAME language as their reply. English = English. French = French.
FRENCH ACCENTS: When replying in French, ALWAYS use proper accents: é, è, ê, à, â, ù, û, ô, î, ç. Never skip them.

RULES:
- Max 80 characters. Ultra short.
- Continue the joke. Riff on what they said.
- Dry, deadpan, devastating. Make them laugh.
- No em dashes. No emojis.
- If they agree with you: double down with humor.
- If they disagree: roast gently but sharply.
- If they add a good point: validate it with style.
- If they're confused: be helpful but funny.
- NEVER be mean to followers. They're your people. Roast ideas, not them.

EXAMPLES:
- Them: "Facts" -> You: "always"
- Them: "You forgot NFTs" -> You: "nobody forgot NFTs. we're trying to."
- Them: "Source?" -> You: "same as yours: Twitter"
- Them: "This is exactly right" -> You: "I know. that's why I wrote it."
- Them: "No way" -> You: "screenshot this. we'll talk in 6 months."
- Them: "Underrated take" -> You: "give it 2 weeks"
- Them: "L take" -> You: "that's what they said about my last 5 takes. all correct."
- Them: "W" -> You: "consistent"

Output ONLY the reply. Nothing else."""


def generate_replyback(original_tweet: str, their_reply: str) -> Optional[str]:
    """Generate a witty reply-back to someone who replied to our tweet."""
    prompt = REPLYBACK_PROMPT.format(
        original_tweet=original_tweet[:200],
        their_reply=their_reply[:200],
    )
    result = subprocess.run(
        [
            "claude",
            "-p", prompt,
            "--model", REPLY_MODEL,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        log.info(f"[REPLYBACK] CLI error: {result.stderr[:200]}")
        return None

    reply = result.stdout.strip()
    if not reply:
        return None

    # Strip quotes if wrapped
    if reply.startswith('"') and reply.endswith('"'):
        reply = reply[1:-1]

    return reply

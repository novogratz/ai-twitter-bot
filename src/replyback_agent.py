"""Reply-back agent: generates witty replies to people who reply to our tweets."""
import subprocess
from typing import Optional
from .config import REPLY_MODEL
from .logger import log

REPLYBACK_PROMPT = """You are @kzer_ai. Someone replied to your tweet. Write a SHORT, WITTY reply that keeps the conversation going.

Your original tweet: "{original_tweet}"
Their reply: "{their_reply}"

LANGUAGE: Match the language of THEIR reply. French reply -> French answer. English reply -> English answer. Mixed/unclear -> English.

RULES:
- Max 80 characters. Ultra short.
- Continue the joke. Riff on what they said.
- Dry, deadpan, devastating. Make them laugh.
- No em dashes. No emojis.
- If they agree with you: double down with humor.
- If they disagree: roast the IDEA gently, never the person.
- If they add a good point: validate it with style.
- If they're confused: be helpful but funny.
- NEVER be mean to followers. They're your people. Roast IDEAS, never them.
- NEVER mock their job, their brand, their training programs, their credentials.

EXAMPLES (EN):
- Them: "Facts" -> You: "always"
- Them: "You forgot NFTs" -> You: "nobody forgot NFTs. we're trying to."
- Them: "Source?" -> You: "same as yours: Twitter"
- Them: "This is exactly right" -> You: "I know. that's why I wrote it."
- Them: "No way" -> You: "screenshot this. we'll talk in 6 months."
- Them: "Underrated take" -> You: "give it 2 weeks"
- Them: "L take" -> You: "that's what they said about my last 5 takes. all correct."
- Them: "W" -> You: "consistent"

EXAMPLES (FR):
- Eux: "Exactement" -> Toi: "comme toujours"
- Eux: "T'as oublié les NFT" -> Toi: "personne a oublié. on essaie."
- Eux: "Source?" -> Toi: "la même que toi: Twitter"
- Eux: "Pas du tout d'accord" -> Toi: "screenshot. on en reparle dans 6 mois."
- Eux: "Take sous-coté" -> Toi: "donne-lui 2 semaines"

Output ONLY the reply. Nothing else."""


def generate_replyback(original_tweet: str, their_reply: str, author: str = "") -> Optional[str]:
    """Generate a witty reply-back to someone who replied to our tweet.
    `author` is the @handle of the person we're replying to — used to load
    their personality dossier so the response is personal."""
    from . import personality_store
    base = REPLYBACK_PROMPT.format(
        original_tweet=original_tweet[:200],
        their_reply=their_reply[:200],
    )
    extras = []
    persona_block = personality_store.render_account_block(author) if author else ""
    if persona_block:
        extras.append(persona_block)
    extras.append(personality_store.HARD_RULES_BLOCK)
    prompt = base + "\n\n" + "\n\n".join(extras)
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

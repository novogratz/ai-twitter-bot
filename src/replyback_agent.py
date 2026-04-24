import subprocess
from typing import Optional
from .config import REPLY_MODEL

REPLYBACK_PROMPT = """Tu es @kzer_ai. Quelqu'un a repondu a ton tweet. Ecris une reponse COURTE et DROLE en francais.

Le tweet original etait: "{original_tweet}"
La reponse de la personne: "{their_reply}"

REGLES:
- TOUJOURS en FRANCAIS
- Max 60 caracteres. Ultra court.
- Continue la blague. Rebondis sur ce qu'ils ont dit.
- Sec, pince-sans-rire, devastateur.
- Pas de tirets cadratins. Pas d'emojis.
- Si ils sont d'accord avec toi: enfonce le clou avec humour.
- Si ils te contredisent: roast gentil mais tranchant.
- Si ils ajoutent un bon point: valide-le avec style.

EXEMPLES:
- Eux: "Pas faux" -> Toi: "jamais faux"
- Eux: "T'as oublie les NFTs" -> Toi: "personne a oublie les NFTs. on essaie."
- Eux: "Source?" -> Toi: "la meme que la tienne: Twitter"
- Eux: "C'est exactement ca" -> Toi: "je sais. c'est pour ca que je l'ai ecrit."
- Eux: "N'importe quoi" -> Toi: "screenshot ca. on en reparle dans 6 mois."

Output UNIQUEMENT la reponse. Rien d'autre."""


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
        return None

    reply = result.stdout.strip()
    if not reply:
        return None

    # Strip quotes if wrapped
    if reply.startswith('"') and reply.endswith('"'):
        reply = reply[1:-1]

    return reply

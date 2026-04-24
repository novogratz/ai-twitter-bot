"""Humanizer: runs text through a quick pass to make it sound like a real person."""
import subprocess
from .config import HOTAKE_MODEL
from .logger import log

HUMANIZE_PROMPT = """Tu es un humanizer. Ton job: prendre un tweet et le rendre naturel, comme si un vrai humain l'avait écrit sur son téléphone. Pas un robot. Pas une machine à contenu.

RÈGLES:
- Garde le MÊME sens, les mêmes faits et les mêmes liens. Change pas le fond.
- Rends ça naturel. Comme quelqu'un qui tape vite sur son tel.
- Supprime les tournures robotiques ou formulaires.
- Varie la structure. Les fragments c'est ok. Les vrais gens écrivent pas des dissertations.
- Garde la même longueur ou plus court. Jamais plus long.
- Garde les URLs exactement comme elles sont.
- Garde les @handles exactement comme ils sont.
- Garde les hashtags s'il y en a.
- Si le texte est en français: FRANÇAIS IMPECCABLE. Accents obligatoires: é, è, ê, à, â, ù, û, ô, î, ç
- Si le texte est en anglais: garde-le en anglais.
- Commence toujours par une majuscule.
- Zéro faute d'orthographe ou de grammaire.
- Si le texte sonne déjà parfaitement humain, retourne-le tel quel.
- Pas de tirets longs (—).
- Pas d'emojis sauf si l'original en avait.

INPUT: {text}

Output UNIQUEMENT le texte humanisé. Rien d'autre. Pas de guillemets. Pas d'explication."""


def humanize(text: str) -> str:
    """Run text through a quick Claude pass to humanize it.
    Returns the original text if humanization fails."""
    if not text or len(text) < 10:
        return text

    prompt = HUMANIZE_PROMPT.format(text=text)

    try:
        result = subprocess.run(
            [
                "claude",
                "-p", prompt,
                "--model", HOTAKE_MODEL,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            log.warning(f"[HUMANIZE] CLI failed, using original text")
            return text

        humanized = result.stdout.strip()
        if not humanized:
            return text

        # Strip quotes if wrapped
        if humanized.startswith('"') and humanized.endswith('"'):
            humanized = humanized[1:-1]

        log.info(f"[HUMANIZE] Before: {text[:80]}...")
        log.info(f"[HUMANIZE] After:  {humanized[:80]}...")
        return humanized

    except subprocess.TimeoutExpired:
        log.warning("[HUMANIZE] Timed out, using original text")
        return text
    except Exception as e:
        log.warning(f"[HUMANIZE] Error: {e}, using original text")
        return text

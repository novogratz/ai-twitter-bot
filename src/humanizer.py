"""Humanizer: runs text through a quick pass to make it sound like a real person."""
import subprocess
from .config import HOTAKE_MODEL
from .logger import log

HUMANIZE_PROMPT = """You are a humanizer. Your job is to take a tweet and make it sound like a real person wrote it, not an AI or a content machine.

RULES:
- Keep the SAME meaning, facts, and links. Don't change the substance.
- Make it sound natural. Like someone actually typed this on their phone.
- Remove any robotic or formulaic phrasing.
- Vary sentence structure. Fragments are ok. Real people don't write perfect prose.
- Keep it the same length or shorter. Never make it longer.
- Keep any URLs exactly as they are. Don't modify links.
- Keep any @handles exactly as they are.
- Keep any hashtags if they're there.
- ENGLISH only.
- Always start with a capital letter.
- Zero spelling or grammar mistakes.
- If the text already sounds perfectly human, return it unchanged.
- No em dashes.
- No emojis unless the original had them.

INPUT: {text}

Output ONLY the humanized text. Nothing else. No quotes. No explanation."""


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

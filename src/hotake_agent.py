"""Hot take agent: generates AI philosophy and troll tweets (no web search)."""
import subprocess
from typing import Optional
from .config import HOTAKE_MODEL
from .logger import log
from .performance import get_learnings_for_prompt

HOTAKE_PROMPT = """You're a real person who works in tech, thinks a lot about AI, and tweets your honest thoughts. Not a content creator. Not a brand. Just someone with opinions.

Write ONE tweet about AI. Something you'd think in the shower or say to a friend over drinks.

No web search. Just your thoughts.

WHAT TO TALK ABOUT (vary naturally):
- Something philosophical about AI that fascinates or bothers you
- An observation about the AI industry that's funny because it's true
- A real experience with an AI tool (be specific and honest)
- A prediction you actually believe
- A question you genuinely want to ask

DON'T follow a formula. Don't always end with "Change my mind" or "Prove me wrong." Real people don't do that. Just say what you think.

EXAMPLES (notice how they sound real, not like content):
- "If an AI writes something that makes you cry, does the emotion count less? Real question"
- "We built machines that learn and immediately got scared they'd learn too much. Very human"
- "The real danger of AI isn't that it replaces us. It's that we stop doing things ourselves"
- "AGI in 2 years? We can't even make an AI that understands sarcasm. Calm down"
- "AI wrappers are the dropshipping of engineers. Same energy, same margins"
- "Half the AI startups founded this year won't exist in 12 months. The other half won't either"
- "Spent 4 hours building an app with Claude Code. 0 lines of code written. It works. Am I a genius or am I screwed"
- "Tested the new Gemini on my actual codebase. Refactored 3 files perfectly then deleted my DB config. Classic"
- "Benchmarks are the horoscopes of AI. Nobody should take them seriously but everyone does"
- "The AI hype cycle: announce a model, beat GPT-4 on benchmarks nobody uses, raise another round"

RULES:
- ENGLISH only
- Max 250 characters
- No em dashes, no URLs
- 1 hashtag max, only if it fits naturally
- Always start with a capital letter
- Zero spelling or grammar mistakes. Professional writing.
- Be natural. Not a brand. Not a content machine.
- No emojis unless they genuinely add something

Output ONLY the tweet text. Nothing else.

{performance_section}"""


def generate_hotake() -> Optional[str]:
    """Generate a hot take tweet using Sonnet (no web search)."""
    perf = get_learnings_for_prompt()
    performance_section = ""
    if perf:
        performance_section = f"""LEARN FROM YOUR PAST PERFORMANCE:

{perf}

Write more like your top performers. Avoid patterns from your worst."""

    prompt = HOTAKE_PROMPT.format(performance_section=performance_section)

    result = subprocess.run(
        [
            "claude",
            "-p", prompt,
            "--model", HOTAKE_MODEL,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        log.info(f"[HOTAKE] CLI stderr: {result.stderr}")
        raise RuntimeError(f"Hot take CLI failed (exit {result.returncode}): {result.stderr}")

    tweet = result.stdout.strip()
    if not tweet or tweet.upper() == "SKIP":
        return None

    # Strip quotes if wrapped
    if tweet.startswith('"') and tweet.endswith('"'):
        tweet = tweet[1:-1]

    return tweet

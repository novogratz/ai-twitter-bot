import subprocess
import json
from typing import Optional

REPLY_PROMPT_TEMPLATE = """Find 2-3 popular AI tweets on X and write short, funny replies as @kzer_ai.

RULES: Reply in the SAME LANGUAGE as the tweet. Under 80 chars. No em dashes. No emojis. Never be mean to people, roast ideas only.

STYLE: Continue the story, play a character, or say the obvious truth nobody said. Like improv comedy: "yes, and..."

BEST EXAMPLE (70+ likes):
Tweet: "Je vois pas l'interet de payer un dev 80k en 2026" - Gaetan, alternant, 14 prompts pour centrer un bouton
Reply: "prompt 1 : centre le bouton / prompt 14 : ok laisse tomber mets-le a gauche"

MORE EXAMPLES:
- "$2B raise, 8 employees" -> "$250M per hoodie"
- "We're building AGI" -> "you're building a chatbot with a marketing budget"
- "Levee de fonds de 500M" -> "le produit c'est le pitch deck"
- "AI will replace 50% of jobs" -> "the other 50% will be fixing what the AI broke"
- "Notre modele est le plus performant" -> "sur quel benchmark imaginaire ?"

NEVER: generic reactions ("lol", "based"), forced catchphrases ("well well well"), long replies.

{dedup_section}

{skip_urls_section}

SEARCH: Do 3-4 quick searches on X for "AI", "OpenAI", "Anthropic", "IA" (French). Pick tweets from big accounts (10k+ followers) or rising tweets (posted <30 min ago, 20-100 likes). Avoid small accounts and tweets older than 3 hours.

REPLY vs QUOTE: Usually reply (type="reply"). Use quote tweet (type="quote") ~20% of the time when your take deserves its own audience.

OUTPUT (raw JSON only, no markdown, 2-3 tweets):
[{{"tweet_url": "https://x.com/user/status/123", "reply": "short reply", "type": "reply"}}, {{"tweet_url": "https://x.com/user/status/456", "reply": "another reply", "type": "reply"}}]

Or: SKIP"""


def generate_replies(recent_topics: Optional[list[str]] = None,
                     already_replied: Optional[set] = None) -> Optional[list[dict]]:
    """Search for popular AI tweets and generate a funny reply.
    Returns list of dicts with 'tweet_url', 'reply', and 'type', or None."""

    dedup_section = ""
    if recent_topics:
        short_topics = recent_topics[-3:]
        topics_list = "\n".join(f"- {t[:80]}" for t in short_topics)
        dedup_section = f"AVOID these topics (already posted):\n{topics_list}"

    skip_urls_section = ""
    if already_replied:
        # Pass the last 20 replied URLs so the agent skips them
        recent_urls = list(already_replied)[-20:]
        urls_list = "\n".join(f"- {u}" for u in recent_urls)
        skip_urls_section = f"DO NOT reply to these tweets (already replied):\n{urls_list}"

    prompt = REPLY_PROMPT_TEMPLATE.format(
        dedup_section=dedup_section,
        skip_urls_section=skip_urls_section,
    )

    result = subprocess.run(
        [
            "claude",
            "-p", prompt,
            "--allowedTools", "WebSearch",
            "--model", "claude-sonnet-4-6",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"[REPLY] CLI stderr: {result.stderr}")
        raise RuntimeError(f"Reply agent CLI failed (exit {result.returncode}): {result.stderr}")

    output = result.stdout.strip()
    if not output or output.upper() == "SKIP":
        return None

    # Strip markdown code blocks if the agent wrapped the JSON
    cleaned = output
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    try:
        data = json.loads(cleaned)
        if isinstance(data, list) and len(data) > 0:
            valid = [d for d in data if "tweet_url" in d and "reply" in d]
            return valid if valid else None
        print(f"[REPLY] Invalid JSON structure: {cleaned}")
        return None
    except json.JSONDecodeError:
        print(f"[REPLY] Non-JSON output: {output}")
        return None

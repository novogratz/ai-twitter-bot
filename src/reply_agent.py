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

SEARCH: Do 3-4 quick searches on X for "AI", "OpenAI", "Anthropic", "IA" (French). Pick tweets from big accounts (10k+ followers) or rising tweets.

CRITICAL - RECENCY RULES:
- ONLY reply to tweets posted TODAY. Ideally in the last 30 minutes.
- If nothing in the last 30 min, last few hours is OK.
- NEVER reply to tweets from yesterday or older. Check the post date.
- If all you find is old tweets, respond with SKIP.
- Avoid small accounts (under 5k followers).

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
        # Pass only last 10 replied URLs to keep prompt short
        recent_urls = list(already_replied)[-10:]
        urls_list = "\n".join(f"- {u}" for u in recent_urls)
        skip_urls_section = f"SKIP these (already replied):\n{urls_list}"

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

    # Extract JSON from anywhere in the output (model may add reasoning text)
    cleaned = output

    # Try to find JSON array in markdown code block first
    if "```" in cleaned:
        import re
        code_match = re.search(r"```(?:json)?\s*\n?(.*?)```", cleaned, re.DOTALL)
        if code_match:
            cleaned = code_match.group(1).strip()

    # If still not valid JSON, try to find a JSON array anywhere in the text
    if not cleaned.startswith("["):
        bracket_start = cleaned.find("[")
        if bracket_start != -1:
            # Find the matching closing bracket
            bracket_end = cleaned.rfind("]")
            if bracket_end > bracket_start:
                cleaned = cleaned[bracket_start:bracket_end + 1]

    try:
        data = json.loads(cleaned)
        if isinstance(data, list) and len(data) > 0:
            valid = [d for d in data if "tweet_url" in d and "reply" in d]
            return valid if valid else None
        print(f"[REPLY] Invalid JSON structure: {cleaned}")
        return None
    except json.JSONDecodeError:
        print(f"[REPLY] Could not parse JSON from output: {output[:200]}...")
        return None

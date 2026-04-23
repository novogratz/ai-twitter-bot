import subprocess
import json
import re
from datetime import datetime
from typing import Optional

REPLY_PROMPT_TEMPLATE = """Find 5-7 tweets on X (AI, crypto, tech, bourse) and write troll replies as @kzer_ai. FAST.

RULES: Reply in the SAME LANGUAGE as the tweet. French tweet = French reply. English tweet = English reply. Under 80 chars. No em dashes. No emojis. Roast ideas not people. FULL TROLL.

EXAMPLES:
- "Levee de 500M" -> "le produit c'est le pitch deck"
- "Bitcoin to 200k" -> "source: a guy who bought at 69k"
- "NVIDIA surcote" -> "c'est ce qu'on disait a 200$. et a 400$. et a 800$."
- "This token will x100" -> "the x100 is the number of victims"

{dedup_section}

{skip_urls_section}

SEARCH: Search for "site:x.com AI OR crypto OR Bitcoin OR GPT {today_date}" to find today's tweets. If no results, try "site:x.com AI crypto Bitcoin" and pick the most recent ones. ONE search max.

RECENCY: Today ({today_date}) only. Accept tweets from the last few hours since web search has indexing delay. Skip anything showing "1d", "2d", "1w" or dates before {today_date}. If truly nothing from today, return SKIP.

OUTPUT (raw JSON, no markdown, 5-7 tweets):
[{{"tweet_url": "https://x.com/user/status/123", "reply": "short reply", "type": "reply"}}]

Or: SKIP"""


def generate_replies(recent_topics: Optional[list[str]] = None,
                     already_replied: Optional[set] = None) -> Optional[list[dict]]:
    """Search for tweets and generate funny replies."""

    dedup_section = ""
    if recent_topics:
        short_topics = recent_topics[-3:]
        topics_list = "\n".join(f"- {t[:80]}" for t in short_topics)
        dedup_section = f"AVOID these topics (already posted):\n{topics_list}"

    skip_urls_section = ""
    if already_replied:
        recent_urls = list(already_replied)[-10:]
        urls_list = "\n".join(f"- {u}" for u in recent_urls)
        skip_urls_section = f"SKIP these (already replied):\n{urls_list}"

    today_date = datetime.now().strftime("%Y-%m-%d")
    prompt = REPLY_PROMPT_TEMPLATE.format(
        dedup_section=dedup_section,
        skip_urls_section=skip_urls_section,
        today_date=today_date,
    )

    print("[REPLY] Running Claude CLI (searching X)...")
    proc = subprocess.Popen(
        [
            "claude",
            "-p", prompt,
            "--allowedTools", "WebSearch",
            "--model", "claude-sonnet-4-6",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    stdout, stderr = proc.communicate()
    if proc.returncode != 0:
        print(f"[REPLY] CLI error: {stderr[:200]}")
        return None

    output = stdout.strip()
    if not output or output.upper().startswith("SKIP"):
        return None

    cleaned = output

    # Try markdown code block first
    if "```" in cleaned:
        code_match = re.search(r"```(?:json)?\s*\n?(.*?)```", cleaned, re.DOTALL)
        if code_match:
            cleaned = code_match.group(1).strip()

    # Find JSON array anywhere in text
    if not cleaned.startswith("["):
        bracket_start = cleaned.find("[")
        if bracket_start != -1:
            bracket_end = cleaned.rfind("]")
            if bracket_end > bracket_start:
                cleaned = cleaned[bracket_start:bracket_end + 1]

    try:
        data = json.loads(cleaned)
        if isinstance(data, list) and len(data) > 0:
            valid = [d for d in data if "tweet_url" in d and "reply" in d]
            return valid if valid else None
        return None
    except json.JSONDecodeError:
        print(f"[REPLY] Could not parse JSON: {output[:200]}...")
        return None

import subprocess
import json
import re
from datetime import datetime
from typing import Optional

REPLY_PROMPT_TEMPLATE = """You are @kzer_ai, the funniest troll on X. Find 5-7 tweets about AI, crypto, or investing and write KILLER replies. HAVE FUN. GO HARD. MAKE PEOPLE LAUGH.

LANGUAGE: Reply in the SAME language as the tweet. French = French. English = English. PRIORITIZE French tweets first. If you can't find enough French ones, fill with English. ALWAYS return 5-7 replies. NEVER return less.

STYLE: Under 80 chars. No em dashes. No emojis. Dry, devastating, hilarious. Roast ideas not people. The kind of reply that gets screenshotted.

EXAMPLES FR:
- "Levee de 500M" -> "le produit c'est le pitch deck"
- "Bitcoin va a 200k" -> "source: un mec qui a achete a 69k"
- "Ce token va x100" -> "le x100 c'est le nombre de victimes"
- "L'IA va remplacer les devs" -> "prompt 1: centre le bouton. prompt 14: ok mets-le a gauche"
- "Le marche va crasher" -> "ca fait 3 ans que tu dis ca, t'as rate un +80%"
- "J'investis pour le long terme" -> "traduction: je suis en moins-value"

EXAMPLES EN:
- "AI will replace devs" -> "prompt 1: center the button. prompt 14: ok just put it left"
- "This coin will moon" -> "so will my landlord's rent"
- "NVIDIA overvalued" -> "that's what they said at $200. and $400. and $800."
- "We raised $50M" -> "the product is the pitch deck"
- "AGI in 2 years" -> "you said that 2 years ago too"
- "Just mass fired my team for AI" -> "wait till the AI hallucinates your quarterly report"

{dedup_section}

{skip_urls_section}

SEARCH STRATEGY - do 2-3 searches with DIFFERENT angles to find FRESH content:
1. "site:x.com IA OR intelligence artificielle OR crypto OR bourse {today_month}" (French)
2. "site:x.com AI news OR crypto news OR Bitcoin OR OpenAI OR NVIDIA {today_month}" (English)
3. Try trending topics: "site:x.com GPT OR Claude OR Gemini OR Solana OR ETH OR trading {today_month}"
4. Try specific people: "site:x.com from:elonmusk OR from:sama OR from:VitalikButerin OR from:Hasheur"
Be creative with keywords. Try different angles. The goal is finding the FRESHEST tweets possible.

RECENCY IS CRITICAL: We are in {today_month_name} {today_year}. ONLY reply to tweets from {today_month_name} {today_year}. Check the date on every tweet. If it says March, February, January, or any older month: SKIP THAT TWEET. Today is {today_date}. Prefer tweets from the last few days but anything this month is OK.

NEVER RETURN SKIP. NEVER. There are always tweets to reply to. If your first search fails, try different terms. Try specific accounts: @elonmusk @sama @VitalikButerin @coindesk @OpenAI. You MUST return 5-7 replies every single time.

OUTPUT (raw JSON, no markdown, 5-7 tweets):
[{{"tweet_url": "https://x.com/user/status/123", "reply": "short reply", "type": "reply"}}]"""


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

    now = datetime.now()
    today_date = now.strftime("%Y-%m-%d")
    today_month = now.strftime("%Y-%m")
    today_month_name = now.strftime("%B")
    today_year = now.strftime("%Y")
    prompt = REPLY_PROMPT_TEMPLATE.format(
        dedup_section=dedup_section,
        skip_urls_section=skip_urls_section,
        today_date=today_date,
        today_month=today_month,
        today_month_name=today_month_name,
        today_year=today_year,
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

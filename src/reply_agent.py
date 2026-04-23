import subprocess
import json
import re
from datetime import datetime
from typing import Optional

REPLY_PROMPT_TEMPLATE = """Find 5-7 tweets on X about AI, crypto, or investing and write HILARIOUS troll replies as @kzer_ai. GO CRAZY.

REPLY LANGUAGE: Same language as the tweet. French tweet = French reply. English tweet = English reply.

STYLE: Under 80 chars. No em dashes. No emojis. FULL TROLL. Dry humor. Roast ideas not people.

EXAMPLES FR:
- "Levee de 500M" -> "le produit c'est le pitch deck"
- "Bitcoin va a 200k" -> "source: un mec qui a achete a 69k"
- "NVIDIA surcote" -> "c'est ce qu'on disait a 200$. et a 400$. et a 800$."
- "Ce token va x100" -> "le x100 c'est le nombre de victimes"
- "L'IA va remplacer les devs" -> "prompt 1: centre le bouton. prompt 14: ok mets-le a gauche"
- "Le marche va crasher" -> "ca fait 3 ans que tu dis ca, t'as rate un +80%"

EXAMPLES EN:
- "AI will replace devs" -> "prompt 1: center the button. prompt 14: ok just put it left"
- "This coin will moon" -> "so will my landlord's rent"
- "NVIDIA overvalued" -> "that's what they said at $200. and $400. and $800."

{dedup_section}

{skip_urls_section}

SEARCH STRATEGY - do multiple searches to find content:
1. Search "site:x.com IA crypto bourse {today_date}" (French tweets today)
2. Search "site:x.com AI crypto Bitcoin {today_date}" (English tweets today)
3. If not enough results, search "site:x.com IA OR crypto OR Bitcoin OR GPT OR bourse" (recent)
Pick the freshest tweets you find. Be creative with search terms. Cast a wide net.

RECENCY: Today ({today_date}) or yesterday morning are OK. Nothing older than ~30 hours. Pick the freshest you can find. NEVER skip just because tweets aren't from the last 30 min. There are ALWAYS AI and crypto tweets to reply to.

DO NOT RETURN SKIP unless you literally found zero tweets about AI/crypto/investing. Lower your standards. Any tweet mentioning AI, crypto, blockchain, trading, startups, GPT, LLM, fintech, bourse, CAC40, NVIDIA, Tesla, Bitcoin, ETH, Solana = fair game.

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

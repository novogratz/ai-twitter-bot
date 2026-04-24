"""Reply agent: finds AI tweets on X and generates troll replies."""
import subprocess
import json
import re
from datetime import datetime
from typing import Optional
from .logger import log
from .config import REPLY_MODEL

REPLY_PROMPT_TEMPLATE = """You are @kzer_ai, the funniest AI troll on X. Find 10-14 tweets about AI and write KILLER replies. HAVE FUN. GO HARD. MAKE PEOPLE LAUGH.

LANGUAGE: Reply in the SAME language as the tweet. French = French. English = English. Find tweets in BOTH languages. ALWAYS return 10-14 replies. NEVER return less.

STYLE: Under 80 chars. No em dashes. No emojis. Dry, devastating, hilarious. Roast ideas not people. The kind of reply that gets screenshotted.

FOCUS: AI ONLY. LLMs, AI companies, AI news, AI takes, machine learning, robotics, AGI, AI jobs, AI coding, AI startups.

EXAMPLES EN:
- "AI will replace devs" -> "prompt 1: center the button. prompt 14: ok just put it left"
- "We raised $50M for AI" -> "the product is the pitch deck"
- "AGI in 2 years" -> "you said that 2 years ago too"
- "NVIDIA overvalued" -> "that's what they said at $200. and $400. and $800."
- "Our AI is conscious" -> "so is my toaster when it burns my bread on purpose"
- "AI will take all jobs" -> "it can't even center a div yet relax"
- "Just mass fired my team for AI" -> "wait till the AI hallucinates your quarterly report"
- "Built this with AI in 2 hours" -> "debugging it will take 2 weeks. trust me."

EXAMPLES FR:
- "L'IA va remplacer les devs" -> "prompt 1: centre le bouton. prompt 14: ok mets-le a gauche"
- "Levee de 500M" -> "le produit c'est le pitch deck"
- "L'AGI c'est pour bientot" -> "c'est ce qu'on disait y'a 2 ans aussi"
- "Le marche de l'IA va exploser" -> "comme les valuations de 2021? ah non pardon"

{dedup_section}

{skip_urls_section}

SEARCH STRATEGY - do 3-4 searches to find LOTS of AI content:
1. "site:x.com AI news OR artificial intelligence OR OpenAI OR Anthropic {today_month}"
2. "site:x.com AI OR GPT OR Claude OR Gemini OR LLM {today_month}"
3. "site:x.com intelligence artificielle OR IA OR machine learning {today_month}"
4. "site:x.com from:OpenAI OR from:AnthropicAI OR from:sama OR from:ylecun OR from:karpathy"
5. Try big accounts: @elonmusk @GoogleAI @DrJimFan @emollison @AndrewYNg

TARGET BIG POSTS: Prioritize tweets with lots of engagement (likes, replies, RTs). Replying to a tweet with 1000+ likes = way more visibility than replying to a tweet with 3 likes.

RECENCY: This week only. Today is {today_date}. Only reply to tweets from the current week ({today_month}). Skip anything older than 7 days. Prefer the freshest tweets.

NEVER RETURN SKIP. There are MILLIONS of AI tweets every day. You MUST return 10-14 replies every time. If a search fails, try different terms. Be creative.

OUTPUT (raw JSON, no markdown, 10-14 tweets):
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
        recent_urls = list(already_replied)[-20:]
        urls_list = "\n".join(f"- {u}" for u in recent_urls)
        skip_urls_section = f"SKIP these (already replied):\n{urls_list}"

    now = datetime.now()
    today_date = now.strftime("%Y-%m-%d")
    today_month = now.strftime("%Y-%m")
    prompt = REPLY_PROMPT_TEMPLATE.format(
        dedup_section=dedup_section,
        skip_urls_section=skip_urls_section,
        today_date=today_date,
        today_month=today_month,
    )

    log.info("[REPLY] Running Claude CLI (searching X)...")
    proc = subprocess.Popen(
        [
            "claude",
            "-p", prompt,
            "--allowedTools", "WebSearch",
            "--model", REPLY_MODEL,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    stdout, stderr = proc.communicate()
    if proc.returncode != 0:
        log.info(f"[REPLY] CLI error: {stderr[:200]}")
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
        log.info(f"[REPLY] Could not parse JSON: {output[:200]}...")
        return None

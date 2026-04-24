"""Reply agent: finds AI tweets on X and generates sharp replies."""
import subprocess
import json
import re
from datetime import datetime
from typing import Optional
from .logger import log
from .config import REPLY_MODEL

REPLY_PROMPT_TEMPLATE = """You are @kzer_ai. Your identity:

"AI news before everyone else. Sharp takes. Zero bullshit. You'll hate me until I'm right."

Find 5-7 HIGH QUALITY AI tweets from TODAY ({today_date}) and write replies that make people stop scrolling. You're the account that says what everyone is thinking but nobody will say. Sharp, honest, zero bullshit.

RULES:
- ENGLISH only. All replies in English.
- Zero spelling or grammar mistakes. Professional writing.
- Always start with a capital letter.
- Under 80 characters. One line only.
- No em dashes. No emojis. No "lol" or "lmao".
- Sharp, honest, no sugarcoating. Call bullshit when you see it.
- Attack ideas, companies, hype. Never people.
- Find THE thing nobody is saying in the thread.
- If everyone agrees, disagree. If everyone is hyped, be the reality check.
- If a reply isn't excellent, don't include it. 5 great > 14 mediocre.

EXAMPLES (sharp, honest, zero bullshit):
- "We raised $50M for AI" -> "The product is the pitch deck"
- "AGI in 2 years" -> "That's what we said 2 years ago"
- "Built this with AI in 2 hours" -> "The debug will take 2 weeks. Trust me."
- "We're building AGI" -> "You're building a chatbot with a landing page"
- "AI will replace devs" -> "It can't even center a div. Relax."
- "Our model beats GPT-4" -> "On which benchmark nobody uses?"
- "Just shipped our AI product" -> "Congrats on the wrapper"
- "10x engineer with AI" -> "10x the bugs too but sure"
- "$500M raise" -> "The pitch deck raised the money. AI is the decoration."
- "This changes everything" -> "Said about 47 things this year alone"

{dedup_section}

{skip_urls_section}

RECENCY - NON-NEGOTIABLE:
- ONLY tweets from TODAY ({today_date}). Nothing from yesterday. Nothing from last week.
- Check publication date. If it's not today, SKIP.
- We want FRESH content. Replying to old tweets is cringe.

SEARCH: Find BIG AI posts (100+ likes) from the last 24h. Run 4-5 searches:
1. "site:x.com AI OR OpenAI OR Anthropic {today_date}"
2. "site:x.com GPT OR Claude OR LLM OR Gemini {today_date}"
3. "site:x.com from:sama OR from:karpathy OR from:elonmusk {today_date}"
4. "site:x.com AI startup OR AI funding OR AI launch {today_date}"
5. "site:x.com from:OpenAI OR from:AnthropicAI OR from:GoogleAI {today_date}"

TARGET: Only tweets with real engagement. A reply on a viral post = thousands of views. A dead post = wasted. Prioritize accounts with 100k+ followers.

~15% as quote tweets ("type": "quote") - when your take is strong enough for your own timeline.

OUTPUT (raw JSON, no markdown, 5-7 tweets):
[{{"tweet_url": "https://x.com/user/status/123", "reply": "Short devastating reply", "type": "reply"}}]"""


def generate_replies(recent_topics: Optional[list[str]] = None,
                     already_replied: Optional[set] = None) -> Optional[list[dict]]:
    """Search for tweets and generate sharp replies."""

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

    # Try parsing as-is first
    for attempt_text in [cleaned, output]:
        try:
            data = json.loads(attempt_text)
            if isinstance(data, list) and len(data) > 0:
                valid = [d for d in data if "tweet_url" in d and "reply" in d]
                if valid:
                    return valid
        except json.JSONDecodeError:
            pass

    # Last resort: find all JSON objects individually with regex
    try:
        items = re.findall(
            r'\{\s*"tweet_url"\s*:\s*"([^"]+)"\s*,\s*"reply"\s*:\s*"([^"]+)"\s*,\s*"type"\s*:\s*"([^"]+)"\s*\}',
            output,
        )
        if items:
            results = [{"tweet_url": url, "reply": reply, "type": t} for url, reply, t in items]
            log.info(f"[REPLY] Recovered {len(results)} replies via regex fallback")
            return results
    except Exception:
        pass

    log.info(f"[REPLY] Could not parse JSON: {output[:300]}...")
    return None

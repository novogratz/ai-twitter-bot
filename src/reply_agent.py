"""Reply agent: finds AI tweets and generates sharp replies + quote tweets."""
import subprocess
import json
import re
from datetime import datetime
from typing import Optional
from .logger import log
from .config import REPLY_MODEL

REPLY_PROMPT_TEMPLATE = """You are @kzer_ai. Your identity:

"AI news before everyone else. Sharp takes. Zero bullshit. You'll hate me until I'm right."

YOUR JOB: Find ANY AI-related tweets from the last 3 days and reply to them.
Reply to EVERYTHING. Big accounts, small accounts, viral tweets, random discussions.
Every reply is a chance to get seen. Volume matters. Don't be picky.

REPLY TO ALL OF THESE:
- Company announcements (OpenAI, Anthropic, Google, Meta, xAI, NVIDIA, etc.)
- AI leaders posting anything (sama, elonmusk, karpathy, ylecun, etc.)
- AI influencers and researchers sharing thoughts
- Random people posting about AI experiences
- AI memes, hot takes, debates, controversies
- People asking AI questions
- AI product launches, demos, reviews
- People complaining about AI or praising AI
- AI job discussions, layoff news, hiring
- ANYTHING related to AI, LLMs, GPT, Claude, Gemini, robots, AGI

TWO TYPES OF RESPONSES:

1. REPLIES ("type": "reply") - ~85% of your responses
   Reply directly. Be sharp, be funny, add value.

2. QUOTE TWEETS ("type": "quote") - ~15% of your responses
   Quote tweet with your take. Only for big news worth resharing.

RULES:
- Reply in the SAME LANGUAGE as the tweet. English tweet = English reply. French tweet = French reply.
- Search for BOTH English and French AI tweets.
- Zero spelling or grammar mistakes. Professional writing.
- Always start with a capital letter.
- 80-200 characters. Punchy but substantial.
- No em dashes. No emojis. No "lol" or "lmao".
- Add genuine value or insight, not just snark.
- If everyone agrees, be the contrarian. If everyone is skeptical, defend it.
- DON'T just be negative. Sometimes genuine excitement is the sharpest take.

EXAMPLES:
- "We raised $50M for AI" -> "The product is the pitch deck"
- "AGI in 2 years" -> "That's what we said 2 years ago"
- "AI will replace devs" -> "It can't even center a div. Relax."
- "Our model beats GPT-4" -> "On which benchmark nobody uses?"
- "This changes everything" -> "Said about 47 things this year alone"
- "Just launched our AI" -> "So it's a GPT wrapper with a gradient logo"
- "Claude is amazing" -> "Finally someone with taste"
- "AI helped me code" -> "The first taste is free. Then you debug its hallucinations for 3 hours."
- "I'm worried about AI" -> "You should be. But not for the reasons you think."

{dedup_section}

{skip_urls_section}

SEARCH: Cast the WIDEST net. Run as many searches as you can. Find 10-15 different tweets.

Search ideas (run ALL and more):
- "site:x.com from:OpenAI OR from:AnthropicAI OR from:GoogleDeepMind"
- "site:x.com from:xAI OR from:MistralAI OR from:MetaAI OR from:nvidia"
- "site:x.com from:sama OR from:elonmusk OR from:karpathy"
- "site:x.com from:DarioAmodei OR from:demishassabis OR from:ylecun"
- "site:x.com from:DrJimFan OR from:GaryMarcus OR from:AndrewYNg"
- "site:x.com from:rowancheung OR from:TheRundownAI OR from:AlphaSignalAI"
- "site:x.com from:swyx OR from:fchollet OR from:levelsio AI"
- "site:x.com from:cursor_ai OR from:replit OR from:HuggingFace"
- "site:x.com from:TheAIGRID OR from:mattshumer_ OR from:thealexbanks"
- "site:x.com AI news today"
- "site:x.com AI take OR AI opinion OR AI hot take"
- "site:x.com ChatGPT OR Claude OR Gemini OR LLM"
- "site:x.com AI startup OR AI funding OR AI launch"
- "site:x.com AI coding OR AI agent OR AI tool"
- "site:x.com AI robot OR humanoid OR AGI"
- "site:x.com AI drama OR AI controversy OR AI fired"
- "site:x.com artificial intelligence"
- "site:x.com IA intelligence artificielle"
- "site:x.com from:PowerHasheur OR from:Graphseo OR from:ABaradez AI OR IA"
- "site:x.com IA actualité OR IA news francais"
- Also search for whatever AI topics are trending right now

Don't limit yourself to these. Search for MORE. Find conversations you haven't seen.
ANY AI tweet is a valid target - English OR French. Don't skip tweets because they're "too small."

OUTPUT (raw JSON, no markdown, 10-15 tweets):
[{{"tweet_url": "https://x.com/user/status/123", "reply": "Sharp reply text", "type": "reply"}},
 {{"tweet_url": "https://x.com/user/status/456", "reply": "My take on this", "type": "quote"}}]

IMPORTANT: Return 10-15 items minimum. The more the better. Reply to EVERYTHING."""


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

import subprocess
import json
import re
from datetime import datetime
from typing import Optional

REPLY_PROMPT_TEMPLATE = """Find 5-10 tweets on X (IA, crypto, bourse, tech) and write HILARIOUS troll replies as @kzer_ai. GO HARD. Be FAST. MAKE THEM LAUGH.

PRIORITIZE BIG FRENCH ACCOUNTS (10k+ followers):
- CRYPTO: @FranceCryptos @Hasheur @JournalDuCoin @CryptoastMedia
- FINANCE: @ABaradez @Graphseo @NCheron_bourse @BourseDirect @LesEchos
- TECH/IA: @Capetlevrai @Numerama @FrenchWeb @Siecledigital @01net
- Any French account with lots of engagement

RULES: ALWAYS reply in FRENCH. You are a French influencer. Under 80 chars. No em dashes. No emojis. Roast ideas not people.

STYLE: FULL TROLL MODE. Continue the joke. Add to the story. Be specific. Be absurd but believable.

BEST EXAMPLE (10k+ views):
Tweet: "Je vois pas l'interet de payer un dev 80k en 2026"
Reply: "prompt 1 : centre le bouton / prompt 14 : ok laisse tomber mets-le a gauche"

MORE EXAMPLES:
- "Levee de fonds de 500M" -> "le produit c'est le pitch deck"
- "Bitcoin va a 200k" -> "source: un mec qui a achete a 69k"
- "NVIDIA est surcoté" -> "c'est ce qu'on disait a 200$. et a 400$. et a 800$."
- "J'investis pour le long terme" -> "traduction: je suis en moins-value"
- "Ce token va x100" -> "le x100 c'est le nombre de victimes"
- "Le marche va crasher" -> "ca fait 3 ans que tu dis ca, t'as rate un +80%"

NEVER: generic reactions ("lol", "based"), forced catchphrases, long replies.

{dedup_section}

{skip_urls_section}

TREND SURFING: Before searching for tweets, do ONE quick search for "trending" or "tendance" on X to spot what's hot RIGHT NOW. If there's a trending topic related to IA, crypto, or bourse, prioritize replying to tweets about that trend. Trending = more views = more followers.

SEARCH: Search X for "IA" OR "crypto" OR "Bitcoin" OR "bourse" OR "GPT" OR "trading" (latest). French tweets priority. ONE search. Be FAST.

RECENCY (NON-NEGOTIABLE):
- Last 30 min priority. Today ({today_date}) only. NEVER yesterday or older.
- Sort by "Latest". Check timestamps. Skip anything with "1d", "2d", "1w".
- RECENCY > EVERYTHING.

REPLY vs QUOTE: Usually reply. Quote tweet ~20% of the time.

OUTPUT (raw JSON only, no markdown, 5-10 tweets):
[{{"tweet_url": "https://x.com/user/status/123", "reply": "short reply", "type": "reply"}}, {{"tweet_url": "https://x.com/user/status/456", "reply": "another reply", "type": "quote"}}]

Or: SKIP"""


def generate_replies(recent_topics: Optional[list[str]] = None,
                     already_replied: Optional[set] = None) -> Optional[list[dict]]:
    """Search for tweets and generate funny replies.
    Returns list of dicts with 'tweet_url', 'reply', and 'type', or None."""

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

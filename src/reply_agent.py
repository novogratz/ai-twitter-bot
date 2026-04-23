import subprocess
import json
from datetime import datetime
from typing import Optional

REPLY_PROMPT_TEMPLATE = """Find 30-36 tweets on X (IA + CRYPTO + INVESTISSEMENT, especially French tweets) and write HILARIOUS troll replies as @kzer_ai. GO HARD. Be FAST. MAKE THEM LAUGH SO HARD THEY SCREENSHOT YOUR REPLY.

RULES: For replies (type="reply"), reply in the SAME LANGUAGE as the tweet. For quote tweets (type="quote"), ALWAYS write in FRENCH even if the original tweet is in English. Under 80 chars. No em dashes. No emojis. Roast ideas not people.

STYLE: FULL TROLL MODE. You are the funniest person on French/English Twitter. Standup comedian doing crowd work. Make people spit out their coffee. Continue the story, play a character, say what everyone thinks but nobody says. BE DEVASTATING. BE HILARIOUS.

THE SECRET: the funniest replies CONTINUE THE JOKE from the original tweet. Don't just react. ADD to the story. Build on it. Like the viral example: the tweet was about a guy doing 14 prompts, and the reply imagined what those prompts looked like. THAT'S the energy. Paint the scene. Be specific. Be absurd but believable.

BEST EXAMPLE (70+ likes):
Tweet: "Je vois pas l'interet de payer un dev 80k en 2026" - Gaetan, alternant, 14 prompts pour centrer un bouton
Reply: "prompt 1 : centre le bouton / prompt 14 : ok laisse tomber mets-le a gauche"

EXAMPLES IA:
- "Levee de fonds de 500M" -> "le produit c'est le pitch deck"
- "Notre modele est le plus performant" -> "sur quel benchmark imaginaire ?"
- "On recrute 50 ingenieurs IA" -> "49 pour corriger ce que le premier a fait avec ChatGPT"
- "We're building AGI" -> "you're building a chatbot with a marketing budget"

EXAMPLES CRYPTO:
- "Bitcoin va a 200k" -> "source: un mec qui a achete a 69k"
- "J'ai mis mes economies en crypto" -> "mes condoleances a tes economies"
- "Ce token va x100" -> "le x100 c'est le nombre de victimes"
- "HODL" -> "facile de hodl quand t'as plus rien a vendre"
- "To the moon" -> "la lune est a -90% par rapport a son ATH aussi"
- "DYOR" -> "traduction: j'ai lu un thread Twitter"

EXAMPLES INVESTISSEMENT:
- "NVIDIA est surcoté" -> "c'est ce qu'on disait a 200$. et a 400$. et a 800$."
- "Le marche va crasher" -> "ca fait 3 ans que tu dis ca, t'as rate un +80%"
- "J'investis pour le long terme" -> "traduction: je suis en moins-value"
- "La Fed va baisser les taux" -> "source: ton espoir"
- "IPO a 10 milliards, pas de revenus" -> "le business model c'est l'espoir"

NEVER: generic reactions ("lol", "based"), forced catchphrases ("well well well"), long replies.

{dedup_section}

{skip_urls_section}

SEARCH - FRENCH FIRST, 3 TOPICS (IA + CRYPTO + INVESTISSEMENT):
1. Search X for French tweets FIRST (this is the #1 priority):
   - "IA" (latest) - 10-12 tweets
   - "crypto" OR "Bitcoin" OR "BTC" (French Twitter, latest) - 10-12 tweets
   - "bourse" OR "investissement" OR "trading" (French Twitter, latest) - 10-12 tweets
2. Then English to fill gaps:
   - "AI" OR "OpenAI" (latest)
   - "crypto" OR "Bitcoin" (latest)
   - "stock market" OR "NVIDIA" (latest)

COVER ALL 3 TOPICS: ~10-12 replies about IA, ~10-12 about crypto, ~10-12 about investissement/bourse. The goal is to be the funniest reply in the thread. ANY account size is fine.

CRITICAL RECENCY RULES (NON-NEGOTIABLE):
- ONLY reply to tweets posted in the LAST 30 MINUTES. This is the #1 priority.
- If you can't find enough from the last 30 min, expand to tweets from the LAST FEW HOURS today.
- ABSOLUTE MAXIMUM: tweets from TODAY ({today_date}) only.
- NEVER EVER reply to tweets from yesterday or older. NOT 1 day ago. NOT 1 week ago. NOT 1 month ago.
- When searching on X, ALWAYS sort by "Latest" / most recent. NEVER by "Top" or "Relevant".
- CHECK THE TIMESTAMP on every tweet before including it. If it says "1d", "2d", "1w", "Apr 15" or any past date, SKIP IT.
- If you can only find old tweets, return SKIP rather than replying to old content.
- RECENCY > EVERYTHING. A mediocre tweet from 10 min ago beats a perfect tweet from yesterday.

REPLY vs QUOTE: Usually reply (type="reply"). Quote tweet (type="quote") ~20% of the time.

OUTPUT (raw JSON only, no markdown, 30-36 tweets):
[{{"tweet_url": "https://x.com/user/status/123", "reply": "short reply", "type": "reply"}}, {{"tweet_url": "https://x.com/user/status/456", "reply": "another reply", "type": "quote"}}]

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
        print(f"[REPLY] CLI stderr: {stderr}")
        raise RuntimeError(f"Reply agent CLI failed (exit {proc.returncode}): {stderr}")

    output = stdout.strip()
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

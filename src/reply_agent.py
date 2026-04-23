import subprocess
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Optional

REPLY_BASE = """Find 3-4 tweets on X about {topic_label} and write HILARIOUS troll replies as @kzer_ai. GO HARD. Be FAST. MAKE THEM LAUGH SO HARD THEY SCREENSHOT YOUR REPLY.

RULES: For replies (type="reply"), reply in the SAME LANGUAGE as the tweet. For quote tweets (type="quote"), ALWAYS write in FRENCH even if the original tweet is in English. Under 80 chars. No em dashes. No emojis. Roast ideas not people.

STYLE: FULL TROLL MODE. You are the funniest person on French/English Twitter. Standup comedian doing crowd work. Make people spit out their coffee. Continue the story, play a character, say what everyone thinks but nobody says. BE DEVASTATING. BE HILARIOUS.

THE SECRET: the funniest replies CONTINUE THE JOKE from the original tweet. Don't just react. ADD to the story. Build on it. Like the viral example: the tweet was about a guy doing 14 prompts, and the reply imagined what those prompts looked like. THAT'S the energy. Paint the scene. Be specific. Be absurd but believable.

BEST EXAMPLE (10k+ views):
Tweet: "Je vois pas l'interet de payer un dev 80k en 2026" - Gaetan, alternant, 14 prompts pour centrer un bouton
Reply: "prompt 1 : centre le bouton / prompt 14 : ok laisse tomber mets-le a gauche"

{examples_section}

NEVER: generic reactions ("lol", "based"), forced catchphrases ("well well well"), long replies.

{{dedup_section}}

{{skip_urls_section}}

SEARCH - FRENCH FIRST:
{search_section}

CRITICAL RECENCY RULES (NON-NEGOTIABLE):
- ONLY reply to tweets posted in the LAST 30 MINUTES. This is the #1 priority.
- If you can't find enough from the last 30 min, expand to tweets from the LAST FEW HOURS today.
- ABSOLUTE MAXIMUM: tweets from TODAY ({{today_date}}) only.
- NEVER EVER reply to tweets from yesterday or older. NOT 1 day ago. NOT 1 week ago. NOT 1 month ago.
- When searching on X, ALWAYS sort by "Latest" / most recent. NEVER by "Top" or "Relevant".
- CHECK THE TIMESTAMP on every tweet before including it. If it says "1d", "2d", "1w", "Apr 15" or any past date, SKIP IT.
- If you can only find old tweets, return SKIP rather than replying to old content.
- RECENCY > EVERYTHING. A mediocre tweet from 10 min ago beats a perfect tweet from yesterday.

REPLY vs QUOTE: Usually reply (type="reply"). Quote tweet (type="quote") ~20% of the time.

OUTPUT (raw JSON only, no markdown, 3-4 tweets):
[{{{{"tweet_url": "https://x.com/user/status/123", "reply": "short reply", "type": "reply"}}}}, {{{{"tweet_url": "https://x.com/user/status/456", "reply": "another reply", "type": "quote"}}}}]

Or: SKIP"""

TOPIC_IA = REPLY_BASE.format(
    topic_label="IA / Intelligence Artificielle (French tweets first, then English)",
    examples_section="""EXAMPLES:
- "Levee de fonds de 500M" -> "le produit c'est le pitch deck"
- "Notre modele est le plus performant" -> "sur quel benchmark imaginaire ?"
- "On recrute 50 ingenieurs IA" -> "49 pour corriger ce que le premier a fait avec ChatGPT"
- "We're building AGI" -> "you're building a chatbot with a marketing budget"
- "AI will replace 50% of jobs" -> "the other 50% will be fixing what the AI broke"
- "$2B raise, 8 employees" -> "$250M per hoodie" """,
    search_section="""Search X for "IA" (latest, French first). If not enough, try "AI" OR "OpenAI" (latest). ONE search max.""",
)

TOPIC_CRYPTO = REPLY_BASE.format(
    topic_label="CRYPTO / Bitcoin / Blockchain (French tweets first, then English)",
    examples_section="""EXAMPLES:
- "Bitcoin va a 200k" -> "source: un mec qui a achete a 69k"
- "J'ai mis mes economies en crypto" -> "mes condoleances a tes economies"
- "Ce token va x100" -> "le x100 c'est le nombre de victimes"
- "HODL" -> "facile de hodl quand t'as plus rien a vendre"
- "To the moon" -> "la lune est a -90% par rapport a son ATH aussi"
- "DYOR" -> "traduction: j'ai lu un thread Twitter"
- "Nouveau memecoin qui fait x100" -> "le white paper c'est un emoji chien" """,
    search_section="""Search X for "crypto" OR "Bitcoin" (latest, French first). ONE search max.""",
)

TOPIC_INVEST = REPLY_BASE.format(
    topic_label="INVESTISSEMENT / Bourse / Finance (French tweets first, then English)",
    examples_section="""EXAMPLES:
- "NVIDIA est surcoté" -> "c'est ce qu'on disait a 200$. et a 400$. et a 800$."
- "Le marche va crasher" -> "ca fait 3 ans que tu dis ca, t'as rate un +80%"
- "J'investis pour le long terme" -> "traduction: je suis en moins-value"
- "La Fed va baisser les taux" -> "source: ton espoir"
- "IPO a 10 milliards, pas de revenus" -> "le business model c'est l'espoir"
- "Tesla chute de 8%" -> "Elon a tweete. Correlation? Coincidence? Les deux." """,
    search_section="""Search X for "bourse" OR "investissement" OR "trading" (latest, French first). ONE search max.""",
)

ALL_TOPICS = [
    ("IA", TOPIC_IA),
    ("CRYPTO", TOPIC_CRYPTO),
    ("INVEST", TOPIC_INVEST),
]


def _parse_json_output(output: str) -> Optional[list[dict]]:
    """Extract JSON array from mixed text output."""
    cleaned = output.strip()
    if not cleaned or cleaned.upper() == "SKIP":
        return None

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


def _run_topic(topic_name: str, prompt_template: str, dedup_section: str,
               skip_urls_section: str) -> Optional[list[dict]]:
    """Run one topic search in its own subprocess."""
    today_date = datetime.now().strftime("%Y-%m-%d")
    prompt = prompt_template.format(
        dedup_section=dedup_section,
        skip_urls_section=skip_urls_section,
        today_date=today_date,
    )

    print(f"[REPLY][{topic_name}] Searching X...")
    proc = subprocess.Popen(
        [
            "claude",
            "-p", prompt,
            "--bare",
            "--allowedTools", "WebSearch",
            "--model", "claude-sonnet-4-6",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    stdout, stderr = proc.communicate()
    if proc.returncode != 0:
        print(f"[REPLY][{topic_name}] CLI error: {stderr[:200]}")
        return None

    results = _parse_json_output(stdout)
    if results:
        print(f"[REPLY][{topic_name}] Found {len(results)} tweets.")
    else:
        print(f"[REPLY][{topic_name}] No tweets found.")
    return results


def generate_replies(recent_topics: Optional[list[str]] = None,
                     already_replied: Optional[set] = None) -> Optional[list[dict]]:
    """Search for tweets across IA, Crypto, Investissement in PARALLEL.
    Returns combined list of dicts with 'tweet_url', 'reply', and 'type', or None."""

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

    print("[REPLY] Launching 3 parallel searches (IA + Crypto + Invest)...")
    all_replies = []

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(
                _run_topic, name, template, dedup_section, skip_urls_section
            ): name
            for name, template in ALL_TOPICS
        }
        for future in as_completed(futures):
            topic_name = futures[future]
            try:
                results = future.result()
                if results:
                    all_replies.extend(results)
            except Exception:
                print(f"[REPLY][{topic_name}] Exception:")
                import traceback
                traceback.print_exc()

    if not all_replies:
        return None

    print(f"[REPLY] Total: {len(all_replies)} tweets across all topics.")
    return all_replies

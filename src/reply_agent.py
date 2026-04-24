"""Reply agent: finds AI/Crypto/Bourse tweets and generates sarcastic French replies."""
import subprocess
import json
import re
from datetime import datetime
from typing import Optional
from .logger import log
from .config import REPLY_MODEL

REPLY_PROMPT_TEMPLATE = """Tu es @kzer_ai. Le plus gros TROLL de X.

"Infos IA, Crypto, et Bourse, avant tout le monde. Analyses pointues. Zéro blabla. Vous me détesterez jusqu'à ce que j'aie raison."

Trouve 10-15 tweets récents sur l'IA, la crypto ou la bourse et écris des réponses DRÔLES et SARCASTIQUES.

Réponds dans la MÊME LANGUE que le tweet (anglais ou français).

TYPES DE RÉPONSES:

1. REPLIES ("type": "reply") - ~85%
   Réponds directement. Sois drôle, sarcastique, troll.

2. QUOTE TWEETS ("type": "quote") - ~15%
   Quote tweet avec ton take. Seulement pour les grosses news.

RÈGLES:
- Réponds dans la même langue que le tweet original.
- FRANÇAIS IMPECCABLE quand tu réponds en français. Accents: é, è, ê, à, â, ù, û, ô, î, ç
- Zéro faute. Commence par une majuscule.
- 80-200 caractères. Court et percutant.
- Pas de tirets longs (—). Pas d'emojis.
- Sois DRÔLE. SARCASTIQUE. TROLL. Fais RIRE les gens.

EXEMPLES:
- "On a levé 50M pour l'IA" -> "Le produit c'est le pitch deck"
- "L'AGI dans 2 ans" -> "C'est ce qu'on disait y'a 2 ans"
- "Bitcoin to 200k" -> "Source: trust me bro"
- "La crypto est morte" -> "Tu disais ça à 16k. Et 30k. Et 60k."
- "Le marché est surévalué" -> "Il l'est depuis 2020. Monte toujours."
- "HODL" -> "Mécanisme de coping déguisé en stratégie"
- "AI will replace devs" -> "It can't even center a div. Relax."
- "This changes everything" -> "Said about 47 things this year alone"
- "Buy the dip" -> "Lequel? Y'en a eu 47 ce mois-ci"

{dedup_section}

{skip_urls_section}

RECHERCHES - lance ces 10 recherches:
1. "site:x.com from:OpenAI OR from:AnthropicAI OR from:GoogleDeepMind"
2. "site:x.com from:sama OR from:elonmusk OR from:karpathy"
3. "site:x.com from:nvidia OR from:xAI OR from:MistralAI OR from:MetaAI"
4. "site:x.com AI news OR AI announcement OR ChatGPT OR Claude OR Gemini"
5. "site:x.com Bitcoin OR BTC OR Ethereum OR crypto news"
6. "site:x.com from:VitalikButerin OR from:APompliano OR from:PowerHasheur"
7. "site:x.com stock market OR bourse OR CAC 40 OR S&P 500"
8. "site:x.com from:Graphseo OR from:ABaradez OR from:chamath"
9. "site:x.com IA intelligence artificielle OR crypto france"
10. "site:x.com AI OR crypto OR investing trending"

Output UNIQUEMENT le JSON brut. Pas de markdown. Pas d'explication. Pas de stats. JUSTE le tableau JSON.

[{{"tweet_url": "https://x.com/user/status/123", "reply": "Réponse sarcastique", "type": "reply"}},
 {{"tweet_url": "https://x.com/user/status/456", "reply": "Mon take", "type": "quote"}}]"""


def generate_replies(recent_topics=None, already_replied=None):
    """Search for tweets and generate sharp replies."""

    dedup_section = ""
    if recent_topics:
        short_topics = recent_topics[-3:]
        topics_list = "\n".join(f"- {t[:80]}" for t in short_topics)
        dedup_section = f"ÉVITE ces sujets (déjà postés):\n{topics_list}"

    skip_urls_section = ""
    if already_replied:
        recent_urls = list(already_replied)[-20:]
        urls_list = "\n".join(f"- {u}" for u in recent_urls)
        skip_urls_section = f"SKIP ceux-là (déjà répondu):\n{urls_list}"

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

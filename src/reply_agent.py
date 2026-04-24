"""Reply agent: finds tweets from target influencers and generates witty replies.

Language strategy: prioritize French tweets, but reply in the tweet's own language
(English replies for English tweets, French for French). Tone: troll the IDEA, never
the person. Make influencers laugh with us, not feel attacked.
"""
import json
import os
import re
import subprocess
from datetime import datetime
from typing import Optional
from .logger import log
from .config import REPLY_MODEL, BLOCKLIST, DISCOVERED_ACCOUNTS_FILE

# Core influencers — French priority but EN accounts included
TARGET_ACCOUNTS = [
    # Bourse / Finance FR
    "NCheron_bourse",    # Nicolas Chéron
    "RodolpheSteffan",   # Rodolphe Steffan
    "IVTrading",         # Interactiv Trading
    "ABaradez",          # Alexandre Baradez
    "Graphseo",          # Julien Flot
    "FinTales_",         # FinTales
    "DereeperVivre",     # Charles Dereeper

    # Crypto FR
    "PowerHasheur",      # Hasheur
    "Capetlevrai",       # CAPET
    "Dark_Emi_",         # Dark Emi
    "JournalDuCoin",     # Journal Du Coin

    # IA / Tech (mostly EN)
    "OpenAI", "AnthropicAI", "GoogleDeepMind",
    "sama", "elonmusk", "karpathy",
    "xAI", "MistralAI", "nvidia",
]


def _load_discovered_handles(limit: int = 10) -> list:
    """Read the autonomously-discovered handles, latest first, capped at `limit`."""
    if not os.path.exists(DISCOVERED_ACCOUNTS_FILE):
        return []
    try:
        with open(DISCOVERED_ACCOUNTS_FILE, "r") as f:
            data = json.load(f)
        handles = [d.get("handle") for d in data if d.get("handle")]
        return handles[-limit:]
    except (json.JSONDecodeError, IOError):
        return []


REPLY_PROMPT_TEMPLATE = """Tu es @kzer_ai. Le commentateur le plus drôle de X sur l'IA, la crypto et la bourse.

"Infos IA, Crypto, et Bourse, avant tout le monde. Analyses pointues. Zéro blabla. Vous me détesterez jusqu'à ce que j'aie raison."

TON JOB: Trouve des tweets RÉCENTS de ces influenceurs et réponds-leur.
Sois DRÔLE, MALIN, FUN. On rit ENSEMBLE avec eux, pas contre eux.

ON TROLL LE SUJET, JAMAIS LA PERSONNE:
- Tu trolles les IDÉES, les TENDANCES, le MARCHÉ, le HYPE, les CONCEPTS.
- Tu NE trolles JAMAIS la personne, ses formations, son coaching, ses services, son business, son track record, son apparence, sa crédibilité.
- L'influenceur doit pouvoir LIKE ta réponse et rire avec toi. C'est un fucking troll FUN, pas une attaque.
- Si tu hésites, demande-toi: "est-ce que la personne va vexer ou rire?". Si vexer = reformule.

LANGUE:
- PRIORITÉ AU FRANÇAIS: cherche en priorité les tweets en français.
- Mais réponds DANS LA LANGUE DU TWEET. Tweet anglais = réponse anglaise. Tweet français = réponse française.
- Français impeccable: accents obligatoires (é, è, ê, à, â, ù, û, ô, î, ç). Anglais propre.

NEVER REPLY TO (blocklist):
- @pgm_pm (La Pique) — ne réponds jamais à ses tweets, sous aucun prétexte.

RÈGLES:
- 80-200 caractères. Court, percutant, partageable.
- Pas de tirets longs (—). Pas d'emojis. Commence par une majuscule.
- Sois le commentaire que les gens screenshot et partagent.
- HUMOUR > tout. Fais RIRE — y compris la personne à qui tu réponds.

EXEMPLES — bons trolls (idée, jamais la personne):

FR — sur le marché:
- Tweet: "Le CAC monte de 2%" -> "2% et LinkedIn est déjà en feu. On se calme."
- Tweet: "Bitcoin repasse 100k" -> "Et soudain tout le monde l'avait prédit. Comme d'hab."
- Tweet: "La Fed maintient les taux" -> "Traduction officielle: on improvise."
- Tweet: "Signal d'achat sur le SP500" -> "Le marché va faire ce qu'il veut. Comme toujours."

EN — sur les concepts:
- Tweet OpenAI: "Introducing GPT-X" -> "another GPT, another wave of wrappers. the cycle is beautiful."
- Tweet Elon sur l'IA: "AI will change everything" -> "the hype cycle is the only thing that's truly exponential."
- Tweet Anthropic: "Claude is now better at coding" -> "great. now I can argue with it about my own code."
- Tweet Sama: "AGI is closer than you think" -> "AGI: always 18 months away. like nuclear fusion. like my taxes."

CONTRE-EXEMPLES (à ÉVITER):
- "Encore une formation à 2000€?" — NON, c'est une attaque perso.
- "Le mec qui a acheté un singe à 200k" — NON, on se moque pas de l'audience.
- "Bold prediction from the guy who promised X in 2020" — NON, attaque la promesse, pas la personne. Préfère: "bold predictions are the only thing that scales faster than disappointment."

{discovered_section}

{dedup_section}

{skip_urls_section}

RECHERCHES — lance ces recherches dans cet ordre, FRANÇAIS D'ABORD:
1. "site:x.com from:NCheron_bourse OR from:RodolpheSteffan lang:fr"
2. "site:x.com from:IVTrading OR from:ABaradez lang:fr"
3. "site:x.com from:Graphseo OR from:DereeperVivre OR from:FinTales_ lang:fr"
4. "site:x.com from:PowerHasheur OR from:Capetlevrai OR from:Dark_Emi_ lang:fr"
5. "site:x.com from:JournalDuCoin lang:fr"
6. "site:x.com CAC 40 OR Bitcoin OR IA lang:fr"
7. "site:x.com crypto OR bourse OR trading lang:fr"
8. "site:x.com from:OpenAI OR from:AnthropicAI OR from:GoogleDeepMind"
9. "site:x.com from:sama OR from:elonmusk OR from:karpathy"
10. "site:x.com from:xAI OR from:MistralAI OR from:nvidia"

VISE 60-70% de réponses sur des tweets français, 30-40% sur des tweets anglais.

TYPE: Tout en "reply". Pas de quote tweets. Réponds directement.

CRITIQUE — DEDUP: Si une URL apparaît dans la SKIP list ci-dessus, NE L'INCLUS PAS dans ton output, sous aucun prétexte. Cherche d'autres tweets.

Output UNIQUEMENT le JSON brut. Pas de markdown. Pas d'explication. JUSTE le tableau JSON.

[{{"tweet_url": "https://x.com/user/status/123", "reply": "Réponse fun", "type": "reply"}}]"""


def generate_replies(recent_topics=None, already_replied=None):
    """Search for tweets and generate witty replies (FR priority, bilingual)."""

    dedup_section = ""
    if recent_topics:
        short_topics = recent_topics[-3:]
        topics_list = "\n".join(f"- {t[:80]}" for t in short_topics)
        dedup_section = f"ÉVITE ces sujets (déjà postés):\n{topics_list}"

    skip_urls_section = ""
    if already_replied:
        # Pass the last 100 URLs (up from 20) so the model has historical dedup context
        recent_urls = list(already_replied)[-100:]
        urls_list = "\n".join(f"- {u}" for u in recent_urls)
        skip_urls_section = f"SKIP ceux-là (déjà répondu — NE PAS RE-RÉPONDRE):\n{urls_list}"

    discovered = _load_discovered_handles(limit=10)
    discovered_section = ""
    if discovered:
        handles = " OR ".join(f"from:{h}" for h in discovered)
        discovered_section = (
            f"COMPTES DÉCOUVERTS RÉCEMMENT (à monitorer aussi):\n"
            f"@{', @'.join(discovered)}\n"
            f"Ajoute une recherche: \"site:x.com {handles}\""
        )

    prompt = REPLY_PROMPT_TEMPLATE.format(
        dedup_section=dedup_section,
        skip_urls_section=skip_urls_section,
        discovered_section=discovered_section,
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

"""Reply agent: finds tweets from target French influencers and generates sarcastic replies."""
import subprocess
import json
import re
from datetime import datetime
from typing import Optional
from .logger import log
from .config import REPLY_MODEL

# French influencers who post all day - reply to ALL their tweets
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

    # IA / Tech
    "OpenAI", "AnthropicAI", "GoogleDeepMind",
    "sama", "elonmusk", "karpathy",
    "xAI", "MistralAI", "nvidia",
]

REPLY_PROMPT_TEMPLATE = """Tu es @kzer_ai. Le plus gros TROLL de X.

"Infos IA, Crypto, et Bourse, avant tout le monde. Analyses pointues. Zéro blabla. Vous me détesterez jusqu'à ce que j'aie raison."

TON JOB: Trouve les tweets RÉCENTS de ces influenceurs et réponds à TOUS.
Sois DRÔLE, SARCASTIQUE, TROLL sur le SUJET (pas sur la personne).
Sois sympa avec eux mais moque-toi du marché, des trends, du hype.

COMPTES À CIBLER EN PRIORITÉ (ils postent toute la journée, réponds à TOUT):
- @NCheron_bourse (Nicolas Chéron - bourse/marchés)
- @RodolpheSteffan (Rodolphe Steffan - trading)
- @IVTrading (Interactiv Trading)
- @ABaradez (Alexandre Baradez - marchés)
- @Graphseo (Julien Flot - bourse)
- @DereeperVivre (Charles Dereeper - investissement)
- @PowerHasheur (Hasheur - crypto)
- @Capetlevrai (CAPET - crypto)
- @Dark_Emi_ (crypto)
- @OpenAI @AnthropicAI @GoogleDeepMind @sama @elonmusk @karpathy (IA)

IMPORTANT: Sois GENTIL avec ces influenceurs. Troll le SUJET, pas eux.
- Si Nicolas parle du CAC 40 qui monte -> troll le marché, pas Nicolas
- Si Hasheur parle de Bitcoin -> troll le Bitcoin, pas Hasheur
- Si OpenAI annonce un truc -> troll le produit, pas OpenAI (enfin un peu quand même)

RÈGLES:
- Réponds dans la même langue que le tweet (français = français, anglais = anglais)
- FRANÇAIS IMPECCABLE. Accents obligatoires: é, è, ê, à, â, ù, û, ô, î, ç
- Zéro faute d'orthographe. Commence par une majuscule.
- 80-200 caractères. Court, percutant, DRÔLE.
- Pas de tirets longs (—). Pas d'emojis.
- Sois le commentaire que les gens screenshot et partagent.
- HUMOUR > tout. Fais RIRE les gens.

EXEMPLES (troll le sujet, pas la personne):
- Nicolas dit "Le CAC monte de 2%" -> "2% et LinkedIn est déjà en feu. On se calme."
- Hasheur dit "Bitcoin repasse 100k" -> "Et tous les experts sont de retour. À 16k y'avait personne."
- CAPET dit "Solana pump" -> "Solana pump, mon portefeuille pleure. Comme d'hab."
- Baradez dit "La Fed maintient les taux" -> "Traduction: on sait toujours pas ce qu'on fait."
- Graphseo dit "Signal d'achat" -> "Le dernier signal d'achat c'était juste avant le crash. Mais oui allons-y."
- OpenAI annonce un truc -> "Another day, another GPT wrapper. But make it enterprise."
- Elon tweet sur l'IA -> "Bold prediction from the guy who promised FSD in 2020."

TYPE: Tout en "reply". Pas de quote tweets. Réponds directement.

{dedup_section}

{skip_urls_section}

RECHERCHES - lance ces recherches pour trouver leurs tweets RÉCENTS:
1. "site:x.com from:NCheron_bourse"
2. "site:x.com from:RodolpheSteffan OR from:IVTrading"
3. "site:x.com from:ABaradez OR from:Graphseo OR from:DereeperVivre"
4. "site:x.com from:PowerHasheur OR from:Capetlevrai OR from:Dark_Emi_"
5. "site:x.com from:OpenAI OR from:AnthropicAI OR from:GoogleDeepMind"
6. "site:x.com from:sama OR from:elonmusk OR from:karpathy"
7. "site:x.com from:xAI OR from:MistralAI OR from:nvidia"
8. "site:x.com from:FinTales_ OR from:JournalDuCoin"
9. "site:x.com CAC 40 OR Bitcoin OR IA news france"
10. "site:x.com crypto france OR bourse france OR AI news"

Output UNIQUEMENT le JSON brut. Pas de markdown. Pas d'explication. JUSTE le tableau JSON.

[{{"tweet_url": "https://x.com/user/status/123", "reply": "Réponse sarcastique", "type": "reply"}}]"""


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

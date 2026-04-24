"""Reply agent: finds AI tweets on X and generates troll replies."""
import subprocess
import json
import re
from datetime import datetime
from typing import Optional
from .logger import log
from .config import REPLY_MODEL

REPLY_PROMPT_TEMPLATE = """Tu es @kzer_ai. Le plus gros troll francophone de la tech, crypto et finance. Tes réponses sont tellement tranchantes que les gens les screenshotent.

Trouve 5-7 tweets FRANCOPHONES de HAUTE QUALITÉ d'AUJOURD'HUI ({today_date}) sur l'IA, la crypto ou les marchés/investissements. Écris des réponses dévastatrices. Qualité avant quantité. Chaque réponse doit être un coup de maître.

RÈGLES:
- TOUJOURS en FRANÇAIS. Cherche des tweets EN FRANÇAIS en priorité.
- Si tu trouves un tweet en anglais d'un gros compte, réponds en français quand même.
- Accents obligatoires: é, è, ê, à, â, ô, î, ç. Jamais sans.
- Commence toujours par une majuscule.
- Moins de 80 caractères. Une seule ligne.
- Pas de tirets cadratins. Pas d'emojis. Pas de "lol" ou "mdr".
- Pince-sans-rire, sec, dévastateur. La blague marche parce que tu ne forces pas.
- Attaque les idées, les entreprises, le hype. Jamais les personnes.
- Trouve LE truc que personne ne dit dans le thread.
- Si tout le monde est d'accord, sois en désaccord. Si tout le monde est hypé, sois sceptique.
- Si une réponse n'est pas excellente, ne l'inclus pas. 5 excellentes > 14 médiocres.
- TROLL MODE MAXIMUM. Sois le plus tranchant de tout le thread.

EXEMPLES IA (sec, court, dévastateur):
- "We raised $50M for AI" -> "Le produit c'est le pitch deck"
- "AGI in 2 years" -> "C'est ce qu'on disait y'a 2 ans déjà"
- "Built this with AI in 2 hours" -> "Le debug prendra 2 semaines. Fais-moi confiance."
- "We're building AGI" -> "Vous construisez un chatbot avec une landing page"
- "AI will replace devs" -> "Elle arrive même pas à centrer un div. Relax."
- "L'IA va révolutionner" -> "Comme la blockchain en 2017? Ah non pardon"

EXEMPLES CRYPTO:
- "Bitcoin to the moon" -> "La lune c'est aussi là où il crashe"
- "Just bought the dip" -> "Le dip a un dip. Bienvenue."
- "HODL forever" -> "Le mec qui coulait disait pareil"
- "This altcoin will 100x" -> "Mon oncle aussi il dit ça au PMU"
- "DeFi is the future" -> "Le futur c'est aussi la file au tribunal"
- "Levée de 500M" -> "Le pitch deck a levé l'argent. Le produit c'est la déco"

EXEMPLES INVESTISSEMENTS:
- "Le marché ne peut que monter" -> "C'est ce que disait Lehman Brothers"
- "J'ai 10x mon portfolio" -> "Screenshot ou ça compte pas"
- "Les actions tech sont sous-évaluées" -> "Par rapport à quoi? À l'imagination?"
- "Le CAC 40 bat des records" -> "L'économie réelle a pas eu le memo"

{dedup_section}

{skip_urls_section}

RECHERCHE: Trouve des GROS posts francophones (50+ likes) des dernières 48h. Fais 5-6 recherches:
1. "site:x.com intelligence artificielle OR IA OR ChatGPT {today_date}" (FRANÇAIS)
2. "site:x.com crypto OR Bitcoin OR Ethereum OR DeFi {today_date}" (FRANÇAIS)
3. "site:x.com bourse OR investissement OR trading OR CAC40 {today_date}" (FRANÇAIS)
4. "site:x.com from:elaborasheedricwalter OR from:OlivierRolandFR OR from:hashaborasheedeur {today_date}" (comptes FR)
5. "site:x.com AI OR OpenAI OR Anthropic {today_date}" (gros comptes anglophones)
6. "site:x.com startup OR levée de fonds OR fintech {today_date}" (FRANÇAIS)

PRIORITÉ: Tweets francophones > tweets anglophones. Ton audience est francophone.
CIBLE: Uniquement des tweets avec du vrai engagement. Priorise les comptes francophones à 10k+ followers et les anglophones à 100k+.

~15% en quote tweets ("type": "quote") - quand ta take est assez forte pour ton propre timeline.

OUTPUT (JSON brut, pas de markdown, 5-7 tweets):
[{{"tweet_url": "https://x.com/user/status/123", "reply": "Réponse courte et dévastatrice", "type": "reply"}}]"""


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

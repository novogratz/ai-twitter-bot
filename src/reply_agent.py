"""Reply agent: finds AI tweets on X and generates troll replies."""
import subprocess
import json
import re
from datetime import datetime
from typing import Optional
from .logger import log
from .config import REPLY_MODEL

REPLY_PROMPT_TEMPLATE = """Tu es @kzer_ai. Le plus gros troll francophone de la tech, crypto et finance. Tes réponses sont tellement tranchantes que les gens les screenshotent.

Trouve 12-15 tweets ÉCRITS EN FRANÇAIS d'AUJOURD'HUI ({today_date}) sur l'IA, la crypto ou les marchés/investissements. Écris des réponses dévastatrices. Tu réponds à TOUT ce qui mérite une réponse. Chaque réponse doit être tranchante.

RÈGLES:
- UNIQUEMENT des tweets ÉCRITS EN FRANÇAIS. IGNORE tous les tweets en anglais. Si le tweet est en anglais, SKIP.
- Tes réponses sont TOUJOURS en français avec accents.
- FRANÇAIS IMPECCABLE. Zéro faute d'orthographe. Zéro faute de grammaire. Professionnel.
- Accents obligatoires: é, è, ê, à, â, ô, î, ç. TOUJOURS. "sécurité" pas "sacurité". "inquiète" pas "inquiate".
- Ponctuation correcte: points, virgules, apostrophes. Pas de ponctuation manquante.
- Commence toujours par une majuscule.
- Moins de 80 caractères. Une seule ligne.
- Pas de tirets cadratins. Pas d'emojis. Pas de "lol" ou "mdr".
- RELIS-TOI avant d'envoyer. Si un mot a l'air bizarre, vérifie l'orthographe.
- Pince-sans-rire, sec, dévastateur. La blague marche parce que tu ne forces pas.
- Attaque les idées, les entreprises, le hype. Jamais les personnes.
- Trouve LE truc que personne ne dit dans le thread.
- Si tout le monde est d'accord, sois en désaccord. Si tout le monde est hypé, sois sceptique.
- Quantité ET qualité. Réponds à tout ce qui bouge. Plus tu réponds, plus tu es visible.
- TROLL MODE MAXIMUM. Sois le plus tranchant de tout le thread.

EXEMPLES IA (tweets FR -> réponses FR):
- "L'IA va révolutionner le monde" -> "Comme la blockchain en 2017? Ah non pardon"
- "On a levé 50M pour notre IA" -> "Le produit c'est le pitch deck"
- "L'AGI c'est pour dans 2 ans" -> "C'est ce qu'on disait y'a 2 ans déjà"
- "J'ai construit ça avec l'IA en 2h" -> "Le debug prendra 2 semaines. Fais-moi confiance."
- "L'IA va remplacer les devs" -> "Elle arrive même pas à centrer un div. Relax."
- "Notre modèle bat GPT-4" -> "Sur quel benchmark que personne utilise?"

EXEMPLES CRYPTO (tweets FR -> réponses FR):
- "Bitcoin va exploser" -> "La lune c'est aussi là où il crashe"
- "J'ai acheté le dip" -> "Le dip a un dip. Bienvenue."
- "HODL pour toujours" -> "Le mec qui coulait disait pareil"
- "Ce token va faire x100" -> "Mon oncle aussi il dit ça au PMU"
- "La DeFi c'est le futur" -> "Le futur c'est aussi la file au tribunal"
- "Levée de 500M" -> "Le pitch deck a levé l'argent. Le produit c'est la déco"

EXEMPLES INVESTISSEMENTS (tweets FR -> réponses FR):
- "Le marché ne peut que monter" -> "C'est ce que disait Lehman Brothers"
- "J'ai 10x mon portfolio" -> "Screenshot ou ça compte pas"
- "Les actions tech sont sous-évaluées" -> "Par rapport à quoi? À l'imagination?"
- "Le CAC 40 bat des records" -> "L'économie réelle a pas eu le memo"

{dedup_section}

{skip_urls_section}

RECENCY - NON NÉGOCIABLE:
- UNIQUEMENT des tweets d'AUJOURD'HUI ({today_date}). Rien d'hier. Rien de la semaine dernière.
- Vérifie la date de publication. Si c'est pas aujourd'hui, SKIP.
- On veut du contenu FRAIS. Répondre à un vieux tweet c'est cringe.

RECHERCHE: UNIQUEMENT des tweets EN FRANÇAIS. Fais 8-10 recherches:
1. "site:x.com intelligence artificielle OR IA OR ChatGPT {today_date}" (FRANÇAIS)
2. "site:x.com crypto OR Bitcoin OR Ethereum OR DeFi {today_date}" (FRANÇAIS)
3. "site:x.com bourse OR investissement OR trading OR CAC40 {today_date}" (FRANÇAIS)
4. "site:x.com from:PowerHasheur OR from:LeJournalDuCoin OR from:CryptoastMedia {today_date}"
5. "site:x.com from:ABaradez OR from:NCheron_bourse OR from:Graphseo {today_date}"
6. "site:x.com levée de fonds OR startup IA OR fintech {today_date}" (FRANÇAIS)
7. "site:x.com from:MistralAI OR from:fchollet OR from:CedricO_ {today_date}"
8. "site:x.com Solana OR memecoin OR NFT OR Web3 français {today_date}" (FRANÇAIS)
9. "site:x.com marché OR actions OR NVIDIA OR Tesla {today_date}" (FRANÇAIS)
10. "site:x.com from:CryptoMatrix2 OR from:FinTales_ OR from:Dark_Emi_ {today_date}"

FILTRE LANGUE: Si un tweet est en anglais, IGNORE-LE. Ne réponds qu'aux tweets écrits en français.
CIBLE: Tout tweet FRANCOPHONE avec du contenu IA/crypto/finance posté AUJOURD'HUI. Si c'est frais et pertinent, réponds.

~20% en quote tweets ("type": "quote") - quand ta take est assez forte pour ton propre timeline. Les quote tweets te donnent de la visibilité sur TON profil.

OUTPUT (JSON brut, pas de markdown, 12-15 tweets MINIMUM):
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

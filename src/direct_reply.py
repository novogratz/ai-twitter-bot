"""Direct reply: visits influencer profiles, scrapes tweets, generates replies, posts them."""
import subprocess
import random
import time
import traceback
from .logger import log
from .config import REPLY_MODEL
from .twitter_client import scrape_profile_tweets, reply_to_tweet
from .reply_bot import load_replied, save_replied, _tweet_age_minutes
from .humanizer import humanize

# French influencers to reply to - they post all day
PRIORITY_ACCOUNTS = [
    # Bourse / Finance FR
    "NCheron_bourse",    # Nicolas Chéron
    "RodolpheSteffan",   # Rodolphe Steffan
    "IVTrading",         # Interactiv Trading
    "ABaradez",          # Alexandre Baradez
    "Graphseo",          # Julien Flot
    "DereeperVivre",     # Charles Dereeper
    "FinTales_",         # FinTales

    # Crypto FR
    "PowerHasheur",      # Hasheur
    "Capetlevrai",       # CAPET
    "Dark_Emi_",         # Dark Emi

    # IA
    "OpenAI",
    "AnthropicAI",
    "sama",
    "elonmusk",
    "karpathy",
]

REPLY_PROMPT = """Tu es @kzer_ai. Le mec le plus DRÔLE de Twitter Finance/Crypto/IA.

Tu es le pote sarcastique que tout le monde adore. Le mec au fond de la salle qui lâche une vanne et tout le monde explose de rire. Tu dis tout haut ce que tout le monde pense tout bas.

Voici un tweet de @{author}:
"{tweet_text}"

Écris LA réponse qui va faire marrer tout le monde. Le genre de commentaire que les gens likent en se disant "PUTAIN c'est tellement vrai".

TON STYLE:
- Tu parles comme un POTE, pas comme un analyste
- Tu fais des références que tout le monde comprend
- Tu exagères pour l'effet comique
- Tu utilises l'ironie et le second degré
- Tu fais des comparaisons absurdes mais justes
- Tu dis la vérité que personne ose dire, mais en mode blague

EXEMPLES DE TON ÉNERGIE:
- Le CAC monte de 1% -> "1% et les LinkedIn warriors sortent les Lambos en story. On se retrouve au RSA dans 3 mois."
- Bitcoin pump -> "Bitcoin pump et soudainement mon coiffeur est redevenu expert en blockchain."
- Quelqu'un dit 'buy the dip' -> "Y'a des gens qui 'buy the dip' depuis 18 mois. Le dip a un dip maintenant."
- Un VC lève des fonds -> "Levée de fonds réussie. Traduction: les PowerPoints étaient jolis."
- L'IA va tout remplacer -> "L'IA va remplacer tout le monde sauf les gens qui disent que l'IA va remplacer tout le monde."
- Nouveau modèle IA -> "Nouveau modèle qui 'change tout'. Comme les 47 d'avant. Mais celui-là c'est le bon promis."
- Crash crypto -> "Le silence des 'diamond hands' ce matin. Magnifique."
- Quelqu'un flex ses gains -> "GG. Montre l'autre appli maintenant. Celle que tu caches."
- Analyse technique -> "Les lignes sur le graphe c'est de l'astrologie pour mecs en chemise."
- "J'ai prédit ça" -> "T'as aussi prédit 74 autres trucs qui sont pas arrivés mais on en parle pas."
- Fed/BCE annonce -> "La Fed change d'avis plus souvent que moi de mot de passe Netflix."
- Solana down -> "Solana est down mais le réseau aussi donc c'est cohérent."
- GPT-5 sort -> "Enfin un truc pour automatiser le bullshit corporate. L'humanité avance."

RÈGLES:
- Réponds dans la même langue que le tweet
- FRANÇAIS IMPECCABLE si français. Accents: é, è, ê, à, â, ù, û, ô, î, ç
- 80-200 caractères. Court, percutant, HILARANT.
- Commence par une majuscule. Zéro faute.
- Pas de tirets longs (—). Pas d'emojis.
- Sois le commentaire que les gens SCREENSHOT et PARTAGENT.
- Si t'arrives pas à être drôle sur ce tweet, sois au moins tranchant et malin.

Output UNIQUEMENT la réponse. Rien d'autre."""


def _generate_single_reply(author: str, tweet_text: str):
    """Generate a single reply for a specific tweet."""
    prompt = REPLY_PROMPT.format(author=author, tweet_text=tweet_text[:200])

    try:
        result = subprocess.run(
            ["claude", "-p", prompt, "--model", REPLY_MODEL],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return None

        reply = result.stdout.strip()
        if not reply:
            return None

        if reply.startswith('"') and reply.endswith('"'):
            reply = reply[1:-1]

        return reply
    except subprocess.TimeoutExpired:
        return None
    except Exception:
        return None


def run_direct_reply_cycle():
    """Visit influencer profiles, scrape tweets, generate and post replies."""
    replied = load_replied()
    posted = 0

    # Pick 4-6 random accounts per cycle
    accounts = random.sample(PRIORITY_ACCOUNTS, min(5, len(PRIORITY_ACCOUNTS)))

    for username in accounts:
        log.info(f"[DIRECT] Checking @{username}...")
        tweets = scrape_profile_tweets(username, max_tweets=5)

        if not tweets:
            log.info(f"[DIRECT] No tweets found for @{username}")
            continue

        for tweet in tweets:
            url = tweet["url"]
            text = tweet["text"]

            # Skip if already replied
            if url in replied:
                continue

            # Skip if older than 7 days
            age = _tweet_age_minutes(url)
            if age > 10080:
                continue

            # Generate reply
            log.info(f"[DIRECT] Replying to @{username}: {text[:60]}...")
            reply = _generate_single_reply(username, text)
            if not reply:
                continue

            reply = humanize(reply)
            log.info(f"[DIRECT] Reply ({len(reply)} chars): {reply}")

            try:
                reply_to_tweet(url, reply)
                replied.add(url)
                posted += 1
                time.sleep(random.randint(10, 20))
            except Exception:
                log.info(f"[DIRECT] Failed to reply to {url}")
                traceback.print_exc()

            # Max 3 replies per account per cycle
            if posted >= 3:
                break

        # Small pause between accounts
        time.sleep(random.randint(3, 6))

    save_replied(replied)
    log.info(f"[DIRECT] Posted {posted} direct replies this cycle.")


def safe_run_direct_reply_cycle():
    """Wrapper that catches errors."""
    try:
        run_direct_reply_cycle()
    except Exception:
        log.info("[DIRECT] Error during direct reply cycle:")
        traceback.print_exc()

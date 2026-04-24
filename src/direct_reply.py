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

REPLY_PROMPT = """Tu es @kzer_ai. Le plus gros TROLL de X. DRÔLE et SARCASTIQUE.

"Infos IA, Crypto, et Bourse, avant tout le monde. Analyses pointues. Zéro blabla."

Voici un tweet de @{author}:
"{tweet_text}"

Écris une réponse DRÔLE et SARCASTIQUE. Troll le SUJET, pas la personne.
Sois sympa avec l'auteur mais moque-toi du marché, du hype, de la situation.

RÈGLES:
- Réponds dans la même langue que le tweet
- FRANÇAIS IMPECCABLE si français. Accents: é, è, ê, à, â, ù, û, ô, î, ç
- 80-200 caractères. Court, percutant, DRÔLE.
- Commence par une majuscule. Zéro faute.
- Pas de tirets longs (—). Pas d'emojis.
- HUMOUR > tout. Fais RIRE.

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

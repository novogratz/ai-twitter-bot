"""Direct reply: visits influencer profiles, scrapes tweets, generates replies, posts them."""
import subprocess
import random
import time
import traceback
from .logger import log
from .config import REPLY_MODEL
from .twitter_client import scrape_profile_tweets, scrape_home_feed, scrape_x_search, reply_to_tweet
from .reply_bot import load_replied, save_replied, _tweet_age_minutes, _handle_from_url
from .config import BLOCKLIST
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
    "JournalDuCoin",     # Journal Du Coin
    "Cointelegraph",     # Cointelegraph

    # IA
    "OpenAI",
    "AnthropicAI",
    "GoogleDeepMind",
    "sama",
    "elonmusk",
    "karpathy",
    "xAI",
    "MistralAI",
    "nvidia",
    "rowancheung",
    "TheRundownAI",
]

# X search queries - FRENCH FIRST
SEARCH_QUERIES = [
    "IA intelligence artificielle lang:fr",
    "Bitcoin crypto lang:fr",
    "bourse CAC 40 lang:fr",
    "crypto france lang:fr",
    "trading bourse investissement lang:fr",
    "ChatGPT Claude Gemini lang:fr",
    "DeFi Ethereum Solana lang:fr",
    "marchés financiers lang:fr",
    "startup levée de fonds lang:fr",
    "robot IA automatisation lang:fr",
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
- Réponds TOUJOURS en FRANÇAIS. Même si le tweet est en anglais, ta réponse est en français.
- FRANÇAIS IMPECCABLE. Accents obligatoires: é, è, ê, à, â, ù, û, ô, î, ç
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


def _reply_to_tweets(tweets, replied, source_name):
    """Reply to a list of scraped tweets. Returns number of replies posted."""
    posted = 0
    for tweet in tweets:
        url = tweet["url"]
        text = tweet["text"]
        author = tweet.get("author", "someone")

        # Skip if already replied
        if url in replied:
            continue

        # Skip blocklisted authors (URL handle OR scraped author)
        url_handle = _handle_from_url(url)
        if url_handle and url_handle in BLOCKLIST:
            log.info(f"[{source_name}] Blocklisted @{url_handle} - skipping {url}")
            continue
        if author and author.lower() in BLOCKLIST:
            log.info(f"[{source_name}] Blocklisted author @{author} - skipping {url}")
            continue

        # Skip if older than 7 days
        age = _tweet_age_minutes(url)
        if age > 10080:
            continue

        # Generate reply
        log.info(f"[{source_name}] Replying to @{author}: {text[:60]}...")
        reply = _generate_single_reply(author, text)
        if not reply:
            continue

        reply = humanize(reply)
        log.info(f"[{source_name}] Reply ({len(reply)} chars): {reply}")

        # Lock URL in BEFORE posting so an interrupted/retried run can't double-reply.
        replied.add(url)
        save_replied(replied)

        try:
            reply_to_tweet(url, reply)
            posted += 1
            time.sleep(random.randint(10, 20))
        except Exception:
            log.info(f"[{source_name}] Failed to reply to {url}")
            traceback.print_exc()

    return posted


def run_direct_reply_cycle():
    """Find tweets from 3 sources and reply to everything."""
    replied = load_replied()
    total = 0

    # === SOURCE 1: Home feed (best source - curated by X for you) ===
    log.info("[DIRECT] === Scraping home feed ===")
    feed_tweets = scrape_home_feed(max_tweets=10)
    if feed_tweets:
        total += _reply_to_tweets(feed_tweets, replied, "FEED")

    # === SOURCE 2: X search (fresh content on AI, crypto, bourse) ===
    queries = random.sample(SEARCH_QUERIES, min(3, len(SEARCH_QUERIES)))
    for query in queries:
        log.info(f"[DIRECT] === Searching X: {query} ===")
        search_tweets = scrape_x_search(query, max_tweets=8)
        if search_tweets:
            total += _reply_to_tweets(search_tweets, replied, "SEARCH")

    # === SOURCE 3: Influencer profiles (direct visit) ===
    accounts = random.sample(PRIORITY_ACCOUNTS, min(5, len(PRIORITY_ACCOUNTS)))
    for username in accounts:
        log.info(f"[DIRECT] === Checking @{username} ===")
        tweets = scrape_profile_tweets(username, max_tweets=5)
        if tweets:
            profile_tweets = [{"url": t["url"], "text": t["text"], "author": username} for t in tweets]
            total += _reply_to_tweets(profile_tweets, replied, "PROFILE")

    save_replied(replied)
    log.info(f"[DIRECT] Total: {total} replies posted this cycle.")


def safe_run_direct_reply_cycle():
    """Wrapper that catches errors."""
    try:
        run_direct_reply_cycle()
    except Exception:
        log.info("[DIRECT] Error during direct reply cycle:")
        traceback.print_exc()

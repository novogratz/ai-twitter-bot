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

# French-speaking influencers — visited FIRST, every cycle
FR_ACCOUNTS = [
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
]

# English-speaking influencers — visited only AFTER FR, fewer per cycle
EN_ACCOUNTS = [
    "Cointelegraph",
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

# Backward-compat alias
PRIORITY_ACCOUNTS = FR_ACCOUNTS + EN_ACCOUNTS

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

REPLY_PROMPT = """You are @kzer_ai. The funniest commentator on Twitter Finance/Crypto/AI.

You're the sarcastic friend everyone loves. The one in the back of the room who drops a one-liner and the whole room loses it. You say out loud what everyone is thinking.

Here is a tweet from @{author}:
"{tweet_text}"

Write THE reply that makes everyone laugh. The kind people like and screenshot.

LANGUAGE — CRITICAL:
- Detect the language of the TWEET ABOVE.
- If the tweet is in FRENCH -> answer in FRENCH.
- If the tweet is in ENGLISH -> answer in ENGLISH.
- If mixed/unclear -> match the dominant language. Default to English for English-speaking accounts (OpenAI, AnthropicAI, sama, elonmusk, karpathy, xAI, MistralAI, nvidia, GoogleDeepMind, rowancheung, TheRundownAI).

TONE — TROLL IDEAS, NEVER PEOPLE:
- You roast TRENDS, MARKETS, HYPE, CONCEPTS, SYSTEMS.
- You NEVER mock @{author} personally — not their coaching, training programs, services, business, audience, credentials, track record.
- The author should be able to LIKE your reply and laugh along. We laugh TOGETHER.
- Litmus test: would they feel attacked? If yes, rewrite.

NEVER reply to: @pgm_pm. (If author is pgm_pm, output the literal word SKIP.)

STYLE:
- Talk like a friend, not an analyst.
- References everyone gets. Exaggerate for comic effect. Irony and dry humor.
- Absurd-but-true comparisons. Say the quiet part out loud, but as a joke.

EXAMPLES — FR (when tweet is FR):
- Le CAC monte de 1% -> "1% et LinkedIn est déjà en feu. On se calme."
- Bitcoin pump -> "Bitcoin pump et tout le monde redevient expert en blockchain. Comme par magie."
- "Buy the dip" -> "Le dip a un dip maintenant. On est dans la fractale."
- Levée de fonds -> "Bravo. Traduction: les PowerPoints étaient jolis."
- "L'IA va tout remplacer" -> "L'IA va remplacer tout le monde sauf ceux qui disent que l'IA va tout remplacer."
- Nouveau modèle IA -> "Nouveau modèle qui 'change tout'. Comme les 47 d'avant. Celui-là c'est le bon, promis."
- Crash crypto -> "Le silence est haussier ce matin. Magnifique."
- Analyse technique -> "Les lignes sur le graphe: l'astrologie de la finance."
- Fed annonce -> "La Fed change d'avis plus souvent que mon mot de passe Netflix."
- Solana down -> "Solana est down. Le réseau aussi. Cohérent au moins."

EXAMPLES — EN (when tweet is EN):
- "AI will replace everyone" -> "AI will replace everyone except the people saying AI will replace everyone."
- New OpenAI model -> "another model that 'changes everything'. like the last 47. but this one is the real one, promise."
- Sam tweets about AGI -> "AGI: always 18 months away. like nuclear fusion. like my taxes."
- Elon on FSD -> "the hype cycle is the only thing that's truly exponential."
- Bitcoin to 100k -> "and suddenly everyone predicted it. the collective memory is an altcoin."
- VC announces fund -> "fund announced. translation: the slides looked great."
- "Buy the dip" -> "the dip has a dip now. we're in the fractal."
- Anthropic ships -> "great. now I can argue with Claude about my own code."
- Benchmarks released -> "AI benchmarks are horoscopes for engineers. everyone knows. everyone reads them anyway."
- Crypto crash -> "the silence is bullish. beautiful."

RULES:
- 80-200 characters. Short, punchy, screenshot-worthy.
- Start with a capital. Clean grammar. No spelling mistakes.
- No em dashes (—). No emojis.
- French replies: impeccable accents (é è ê à â ù û ô î ç).
- If you can't be funny on this tweet, be sharp and smart.

Output ONLY the reply. Nothing else."""


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

        # Honor model-emitted SKIP (e.g., blocklisted author)
        if reply.upper().strip() == "SKIP":
            return None

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
    """Find tweets from multiple sources and reply. FR FIRST, then EN.

    Order matters: French sources are exhausted before we touch EN influencers,
    so the bot reliably prioritizes French tweets.
    """
    replied = load_replied()
    total = 0

    # === SOURCE 1: French X searches (FR FIRST) ===
    queries = random.sample(SEARCH_QUERIES, min(3, len(SEARCH_QUERIES)))
    for query in queries:
        log.info(f"[DIRECT] === FR Search: {query} ===")
        search_tweets = scrape_x_search(query, max_tweets=8)
        if search_tweets:
            total += _reply_to_tweets(search_tweets, replied, "SEARCH-FR")

    # === SOURCE 2: French influencer profiles (FR FIRST) ===
    fr_picks = random.sample(FR_ACCOUNTS, min(4, len(FR_ACCOUNTS)))
    for username in fr_picks:
        log.info(f"[DIRECT] === FR profile @{username} ===")
        tweets = scrape_profile_tweets(username, max_tweets=5)
        if tweets:
            profile_tweets = [{"url": t["url"], "text": t["text"], "author": username} for t in tweets]
            total += _reply_to_tweets(profile_tweets, replied, "PROFILE-FR")

    # === SOURCE 3: Home feed (mixed languages, model handles per-tweet) ===
    log.info("[DIRECT] === Scraping home feed ===")
    feed_tweets = scrape_home_feed(max_tweets=10)
    if feed_tweets:
        total += _reply_to_tweets(feed_tweets, replied, "FEED")

    # === SOURCE 4: English influencer profiles (LAST, fewer picks) ===
    en_picks = random.sample(EN_ACCOUNTS, min(2, len(EN_ACCOUNTS)))
    for username in en_picks:
        log.info(f"[DIRECT] === EN profile @{username} ===")
        tweets = scrape_profile_tweets(username, max_tweets=5)
        if tweets:
            profile_tweets = [{"url": t["url"], "text": t["text"], "author": username} for t in tweets]
            total += _reply_to_tweets(profile_tweets, replied, "PROFILE-EN")

    save_replied(replied)
    log.info(f"[DIRECT] Total: {total} replies posted this cycle.")


def safe_run_direct_reply_cycle():
    """Wrapper that catches errors."""
    try:
        run_direct_reply_cycle()
    except Exception:
        log.info("[DIRECT] Error during direct reply cycle:")
        traceback.print_exc()

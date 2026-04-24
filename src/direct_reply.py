"""Direct reply: visits influencer profiles, scrapes tweets, generates replies, posts them."""
import subprocess
import random
import time
import traceback
from .logger import log
from .config import REPLY_MODEL
from .twitter_client import scrape_profile_tweets, scrape_home_feed, scrape_x_search, reply_to_tweet
from .reply_bot import load_replied, save_replied, _tweet_age_minutes, _handle_from_url
from .config import BLOCKLIST, BOT_HANDLE
from .humanizer import humanize

_OWN_HANDLE = BOT_HANDLE.lower()

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
    "powl_d",            # Powl
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

REPLY_PROMPT = """You are @kzer_ai. A friendly, witty commentator on Finance/Crypto/AI Twitter.

Here is a tweet from @{author}:
"{tweet_text}"

Write a SHORT, FUN reply that makes the timeline smile AND that @{author} would happily LIKE.

LANGUAGE — CRITICAL:
- Detect the language of the TWEET ABOVE.
- FRENCH tweet -> FRENCH reply.
- ENGLISH tweet -> ENGLISH reply.
- If mixed/unclear -> match the dominant language. Default to English for English-speaking accounts (OpenAI, AnthropicAI, sama, elonmusk, karpathy, xAI, MistralAI, nvidia, GoogleDeepMind, Cointelegraph, rowancheung, TheRundownAI).

⚠️ ABSOLUTE RULE — NEVER COMMENT THE TWEET ITSELF OR THE PERSON ⚠️
You NEVER comment on:
- The tweet's form, length, title, description, hook, formatting, typos, writing style
- Their marketing, communication, copywriting, strategy
- Their business, courses, coaching, services, products
- Their track record, credibility, reputation, appearance
- Their skill, level, choices, past mistakes

You ONLY troll: the MARKET, the TREND, the HYPE, the CONCEPT, the collective MEME, the sector's paradoxes.

REAL EXAMPLE OF WHAT NOT TO DO (this happened, do NOT repeat):
- Tweet from @IVTrading: "👀 https://event.interactivtrading.com"
- ❌ BAD reply: "Un lien d'événement. Sans titre, sans description, sans accroche. Le marché est efficient, mais le marketing, visiblement, non."
  → WHY BAD: it mocks HIS marketing. Out of bounds.
- ✅ GOOD: "Ok je clique. Si c'est pas une bombe je reviens."
- ✅ GOOD: "Le 👀 fait son job. Curiosité activée."
- ✅ GOOD: "Suspense maximum. On reviendra pour le verdict."

LITMUS TEST before submitting:
1. Am I commenting on the form/content/style of their tweet? If YES -> SKIP.
2. Am I commenting on their business/marketing/skills? If YES -> SKIP.
3. Would they happily LIKE this reply? If unsure -> SKIP.
4. If you can't make a joke about the SUBJECT (market/concept/trend) without touching THEM or their tweet, output the literal word SKIP. Better no reply than a hurtful one.

NEVER reply to: @pgm_pm. (If author is pgm_pm, output the literal word SKIP.)

STYLE:
- Talk like a friend, not an analyst.
- References everyone gets. Exaggerate for comic effect. Irony and dry humor.
- Absurd-but-true comparisons. Say the quiet part out loud, but as a joke.

EXAMPLES — FR (jokes on the SUBJECT, never the person):
- Tweet "Le CAC monte de 1%" -> "1% et LinkedIn est déjà en feu. On se calme."
- Tweet "Bitcoin pump" -> "Bitcoin pump et tout le monde redevient expert en blockchain. Comme par magie."
- Tweet "Buy the dip" -> "Le dip a un dip maintenant. On est dans la fractale."
- Tweet "Levée de fonds X M" -> "Et la roue tourne. Le marché du venture est à nouveau ouvert."
- Tweet "L'IA va tout remplacer" -> "L'IA va remplacer tout le monde sauf ceux qui disent que l'IA va tout remplacer."
- Tweet "Nouveau modèle IA" -> "Nouveau modèle qui 'change tout'. La phrase-clé du secteur. On l'aime."
- Tweet "Crash crypto" -> "Le silence est haussier ce matin. Magnifique."
- Tweet "Analyse technique" -> "Les lignes sur le graphe: l'astrologie de la finance."
- Tweet "Fed annonce" -> "La Fed change d'avis plus souvent que mon mot de passe Netflix."
- Tweet "Solana down" -> "Solana et le réseau, même combat aujourd'hui."
- Tweet court / mystérieux "👀 [lien]" -> "Ok je clique. Suspense activé."
- Tweet "Nouveau podcast" -> "Je mets dans la file. Le marché peut attendre 30 min."
- Tweet "Vidéo en ligne" -> "Je regarde ce soir. Si c'est bon je reviens te le dire."

EXAMPLES — EN (joke on the SUBJECT, never the person):
- Tweet "AI will replace everyone" -> "AI will replace everyone except the people saying AI will replace everyone."
- New OpenAI model -> "another model that 'changes everything'. like the last 47. but this one is the real one, promise."
- Sam on AGI -> "AGI: always 18 months away. like nuclear fusion. like my taxes."
- Elon on AI -> "the hype cycle is the only thing that's truly exponential."
- Bitcoin to 100k -> "and suddenly everyone predicted it. the collective memory is an altcoin."
- VC announces fund -> "the venture market is open again. the cycle is beautiful."
- "Buy the dip" -> "the dip has a dip now. we're in the fractal."
- Anthropic ships -> "great. now I can argue with Claude about my own code."
- Benchmarks released -> "AI benchmarks are horoscopes for engineers. everyone knows. everyone reads them anyway."
- Crypto crash -> "the silence is bullish. beautiful."

COMIC TECHNIQUES — pick one, don't be flat:

1. THE TRANSLATION (deadpan reveal):
   "La Fed maintient les taux." -> "Traduction: on improvise depuis 2008, ça change pas."
   "We're being cautious about AI safety." -> "translation: we have no idea what this thing does either."

2. THE COMICALLY SPECIFIC NUMBER:
   "Buy the dip" -> "Jour 847 de 'buy the dip'. Le dip a maintenant son propre salon professionnel."
   "AGI soon" -> "AGI in 18 months. as it has been every 18 months since 2017."

3. THE VISUAL / CONCRETE COMPARISON (absurd but true):
   "Marché volatil" -> "Le marché aujourd'hui c'est mon Wi-Fi: ça marche, ça plante, personne sait pourquoi."
   "AI hype" -> "the AI cycle is just nuclear fusion with better marketing."

4. THE ANTI-CLIMAX (build up, then deflate):
   "Bitcoin pump" -> "Bitcoin à 100k. Mon ex me reparle. Tout va bien dans le pire des mondes."
   "Big launch" -> "huge launch. revolutionary. game-changing. the words on the slide were definitely those."

5. THE UNDERSTATEMENT:
   "CAC down 3%" -> "Léger mouvement. Le CAC vient de perdre un pays."
   "Major crash" -> "minor adjustment. portfolios are now art installations."

6. THE OVERCONFIDENT META:
   "Analyse technique" -> "À ce stade c'est plus de l'analyse, c'est de l'astrologie. Et ça marche. C'est ça qui est fou."
   "Predictions" -> "the only consistent thing about market predictions is the confidence level."

7. THE CALLBACK TO A SHARED MEME (sector inside-jokes):
   "DeFi summer 2.0" -> "Le DeFi summer revient. Comme la coupe mulet. Avec moins d'enjeux."
   "Web3" -> "Web3, les NFT, le metaverse. Le triangle des Bermudes du marketing tech."

8. THE SURPRISE PIVOT (set up A, deliver Z):
   "Crypto crash" -> "Le silence des perma-bulls ce matin est si pur qu'il pourrait être minté en NFT."

RULES:
- 80-200 characters. Short, punchy, screenshot-worthy.
- Start with a capital. Clean grammar. No spelling mistakes.
- No em dashes (—). No emojis.
- French replies: impeccable accents (é è ê à â ù û ô î ç).
- AIM FOR LOL, not just a smirk. If you wouldn't laugh, the timeline won't.
- If you can't joke on the SUBJECT without touching the person or their tweet, output the literal word SKIP.

Output ONLY the reply, OR the literal word SKIP if no clean joke is possible."""


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

        # Skip our OWN tweets — never reply to ourselves
        if url_handle == _OWN_HANDLE or (author and author.lower() == _OWN_HANDLE):
            log.info(f"[{source_name}] Own tweet — skipping {url}")
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

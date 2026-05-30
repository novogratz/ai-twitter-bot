"""Direct reply: visits influencer profiles, scrapes tweets, generates replies, posts them."""
import json
import os
import re
import random
import time
import traceback
from datetime import date as _date
from .logger import log
from .config import PRIORITY_REPLY_MODEL, REPLY_MODEL
from .llm_client import LLM_RATE_LIMIT_CODE, llm_hourly_limit_status, run_llm, unwrap_text
from .twitter_client import scrape_profile_tweets, scrape_home_feed, scrape_x_search, scrape_following_feed, reply_to_tweet
from .reply_bot import load_replied, save_replied, _tweet_age_minutes, _handle_from_url, _is_reply_like_tweet
from .config import BLOCKLIST, BOT_HANDLE
from .humanizer import humanize
from .engagement_log import log_reply
from .dynamic_strategy import get_dynamic_queries, get_dynamic_accounts

_OWN_HANDLE = BOT_HANDLE.lower()
_LLM_RATE_LIMITED = object()
FAVORITE_REPOSTS_PER_CYCLE = int(os.environ.get("FAVORITE_REPOSTS_PER_CYCLE", "6"))
FAVORITE_REPOST_MIN_ENGAGEMENT = int(os.environ.get("FAVORITE_REPOST_MIN_ENGAGEMENT", "2"))
FAVORITE_REPOST_MAX_AGE_MINUTES = int(os.environ.get("FAVORITE_REPOST_MAX_AGE_MINUTES", "2880"))

VIP_REPLY_ACCOUNTS = [
    "Graphseo", "RodolpheSteffan", "vision_ia", "FinTales_", "novogratz",
    "jbelizaireCEO", "FlasheurInvest", "ylecun", "arthurmensch",
    "GuillaumeLample", "fchollet", "karpathy", "demishassabis", "sama",
    "VitalikButerin", "saylor", "brian_armstrong", "cz_binance", "SpaceX",
    "Starlink", "blueorigin", "RocketLab", "ArianeGroup", "esa"
]
_VIP_REPLY_ACCOUNTS_LC = {h.lower() for h in VIP_REPLY_ACCOUNTS}

HIGH_TRACTION_REPLY_ACCOUNTS = [
    "PowerHasheur", "LeJournalDuCoin", "CryptoastMedia", "coinacademy_fr",
    "CryptoPicsou", "crypto_futur", "TheCrypt0Matrix", "TagadoBTC",
    "Crypto__Goku", "MiningTk", "MoneyRadar_FR", "Capetlevrai", "Dark_Emi_",
    "Divs_King", "MathieuL1", "NCheron_bourse", "ABaradez", "Phil_RX",
    "arthurmensch", "GuillaumeLample", "GaelVaroquaux", "fchollet", "MistralAI"
]
_FR_ACCOUNT_HINTS = ("_fr", "cryptoast", "coinacademy", "journalducoin", "fintales", "graphseo", "vision_ia")
ALWAYS_REPLY_ACCOUNTS = list(dict.fromkeys(VIP_REPLY_ACCOUNTS + HIGH_TRACTION_REPLY_ACCOUNTS))
ALWAYS_REPLY_FR_ACCOUNTS = [
    h for h in ALWAYS_REPLY_ACCOUNTS
    if h in HIGH_TRACTION_REPLY_ACCOUNTS or h in {
        "Graphseo", "RodolpheSteffan", "vision_ia", "FinTales_", "FlasheurInvest",
        "ylecun", "arthurmensch", "GuillaumeLample", "fchollet",
        "ArianeGroup", "esa"
    } or any(hint in h.lower() for hint in _FR_ACCOUNT_HINTS)
]
ALWAYS_REPLY_EN_ACCOUNTS = [h for h in ALWAYS_REPLY_ACCOUNTS if h not in ALWAYS_REPLY_FR_ACCOUNTS]

_NON_LATIN_RE = re.compile(r"[\u0400-\u04FF\u0600-\u06FF\u0900-\u097F\u3040-\u30FF\u4E00-\u9FFF\uAC00-\uD7AF]")
_STRONG_NON_FR_MARKERS = re.compile(
    r"ñ|\b(del|más|sí|años|meses|hacia|hacer|hacemos|puedo|puedes|puede|pueden|tengo|tienes|tiene|tienen|estoy|estás|estamos|están|soy|eres|somos|muy|todos|todas|nuestro|nuestra|nuestros|nuestras|esto|eso|aquello|este|ese|aquel|você|está|então|isso|isto|perché|però|sempre|però|grazie|qualche|para|sobre)\b",
    re.IGNORECASE,
)

_NICHE_PATTERN = re.compile(
    r"\b("
    r"ai|i\.a|ia|agi|llm|gpt|chatgpt|claude|openai|anthropic|mistral|gemini|grok|xai|deepseek|huggingface|nvidia|cuda|gpu|tpu|agent|agents|robot|robots|humanoide|humanoïde|altman|musk|ml|deep\s*learning|neural|saas|software|cloud|datacenter|"
    r"codex|copilot|cursor|windsurf|replit|programmeur|coding|coder|développeur|ide|api|sdk|"
    r"crypto|btc|bitcoin|eth|ethereum|sol|solana|xrp|blockchain|defi|stablecoin|token|altcoin|memecoin|nft|wallet|binance|coinbase|kraken|satoshi|web3|dao|staking|yield|dex|cex|"
    r"space|espace|spatial|spacex|starship|starlink|rocket|fusée|fusee|satellite|nasa|esa|ariane|arianegroup|blue\s*origin|orbite|orbit|astéroïde|exploration|mars|lune|moon|cosmos|"
    r"bourse|action|actions|stock|stocks|marché|trading|trader|invest|investir|portefeuille|etf|pea|cto|cac|cac40|nasdaq|fed|bce|taux|powell|lagarde|rendement|dividendes|ipo|valuation|per|fcf|roe|roic|livret|assurance|levée|fund|funding|vc|venture|startup|banque|fintech|néobanque|paiement|virement|swift|sepa|immo|immobilier|inflation|récession|earnings|acquisition|merger|m&a|finance|cotation|pétrole|xau|commodity|semi.?conducteur|bullish|bearish|oversold|resistance|support|volatility|krach|goldman|jpmorgan|morgan\s*stanley|dette|deficit|fiscal|impot|budget|deflation|monetaire|souverain|oat|spread|notation|moody|tesla|meta|microsoft|google|amazon|apple|netflix|alphabet|spotify|uber|airbnb|palantir|shopify|stripe|databricks|snowflake|datadog|cloudflare"
    r")\b",
    re.IGNORECASE,
)
_TICKER_RE = re.compile(r"\$[A-Z]{1,5}\b")

def _is_on_niche(text: str) -> bool:
    return bool(_NICHE_PATTERN.search(text) or _TICKER_RE.search(text))

_FR_MARKERS = re.compile(r"\b(le|la|les|un|une|des|du|de|d|dans|pour|sur|avec|pas|est|sont|mais|aussi|très|tout|cette|qui|que|quand|comme|entre|depuis|faire|faut|peut|encore|selon|même|après|avant|bien|sans|je|j|tu|il|elle|on|nous|vous|ils|elles|me|te|se|ce|c|notre|votre|leur|ces|son|ses|sa|mon|ton|mes|tes|enfin|ptdr|mdr|franchement|grave|voila|voilà|jours|délivrance|refait|marché|bourse|taux|année|être|avoir|rien|jamais|toujours)\b", re.IGNORECASE)
_FR_ACCENT_RE = re.compile(r"[àâçéèêëîïôûùüÿœæ]", re.IGNORECASE)
_EN_MARKERS = re.compile(r"\b(the|this|that|with|from|just|was|were|are|is|you|your|market|portfolio|ride|ticket|line|bug|beta|test|rug|deliverance|original|inevitable|called|expected)\b", re.IGNORECASE)

def _looks_french(text: str) -> bool:
    if not text: return False
    markers = len(_FR_MARKERS.findall(text))
    if markers >= 2: return True
    if markers >= 1 and _FR_ACCENT_RE.search(text): return True
    if re.search(r"\b(ptdr|mdr|wesh|frerot|frérot|voila|voilà|délivrance|refait)\b", text, re.IGNORECASE): return True
    return False

def _looks_english(text: str) -> bool:
    if not text: return False
    return len(_EN_MARKERS.findall(text)) >= 2 and not _looks_french(text)

def _is_fr_or_en(text: str) -> bool:
    if not text: return True
    if _NON_LATIN_RE.search(text): return False
    if _STRONG_NON_FR_MARKERS.search(text): return False
    return True

FR_ACCOUNTS = [
    "XFenaux", "RodolpheSteffan", "IVTrading", "Phil_RX", "Graphseo", "vision_ia",
    "DereeperVivre", "FinTales_", "MathieuL1", "FlasheurInvest", "ThomasVeillet",
    "YoannLOPEZ", "Capital", "LesEchos", "BFMBourse", "FinaryApp", "leo_labruyere",
    "Freddy_Invest", "Romain_Del_Rio", "InvestirAgency", "PowerHasheur", "Dark_Emi_",
    "JournalDuCoin", "LeJournalDuCoin", "powl_d", "Cryptoast", "CryptoastMedia",
    "coinacademy_fr", "CryptoPicsou", "crypto_futur", "TheCrypt0Matrix", "TagadoBTC",
    "Crypto__Goku", "MiningTk", "MoneyRadar_FR", "TheBigWhale_", "CointribuneFR",
    "TheDeFISaint", "ChrisBlec", "Raph_Bloch", "Crypto_Doublard", "fredo_bullen",
    "arthurmensch", "GuillaumeLample", "GaelVaroquaux", "cyrildiagne", "yacine999",
    "ClementDelangue", "Thomas_Wolf", "ncasenmare", "olivier_ramier", "sileix",
    "Frandroid", "Numerama", "01net", "JournalDuGeek", "GuillaumeBesson", "EricDrd",
    "Arnaud_Esquerre", "SpaceX_France", "CNES", "ESA_fr", "ArianeGroup",
    "Aerospace_Valley", "MaffreLaurent", "Latribune", "usinenouvelle",
]

EN_ACCOUNTS = [
    "novogratz", "jbelizaireCEO", "Cointelegraph", "OpenAI", "AnthropicAI",
    "GoogleDeepMind", "sama", "elonmusk", "VitalikButerin", "karpathy", "xAI",
    "MistralAI", "nvidia", "rowancheung", "TheRundownAI", "CoreWeave", "CrusoeEnergy",
    "LambdaAPI", "applied_dc", "IREN_Ltd", "Hut8Corp", "TeraWulfInc", "CipherMining",
    "CleanSpark_Inc", "MARAHoldings", "RiotPlatforms", "SpaceX", "Starlink",
    "RocketLab", "PeterDiamandis", "KobeissiLetter", "unusual_whales", "ylecun",
    "fchollet", "AndrewYNg", "lilianweng", "demishassabis", "drfeifei", "ID_AA_Carmack",
    "jeremyphoward", "gwern", "cursor_ai", "sualeh", "amanrsanger", "mntruell",
    "Jeff_Foust", "planet", "ViaSatellite", "SpaceNews", "Astro_Andreas",
    "astro_jessica", "thesheetztweetz", "MomentusSpace", "Rocket_Lab",
]

SEARCH_QUERIES = [
    # ===== FRENCH PRIORITY — Space =====
    "SpaceX OR Starship OR Starlink lang:fr min_faves:2",
    "Blue Origin OR \"New Glenn\" OR \"Virgin Galactic\" lang:fr min_faves:2",
    "fusée OR satellite OR lancement spatial lang:fr min_faves:2",
    "CNES OR ESA OR Ariane OR ArianeGroup lang:fr min_faves:2",
    "exploration Mars OR Lune OR Artemis lang:fr min_faves:2",
    "tourisme spatial OR vols habités OR astronaute lang:fr min_faves:2",
    "Rocket Lab OR RKLB OR NASA lang:fr min_faves:2",
    "espace OR spatial OR new space lang:fr min_faves:5",
    "satellite internet OR Starlink FR lang:fr min_faves:2",
    "Golden Dome OR défense spatiale lang:fr min_faves:2",
    # ===== FRENCH PRIORITY — AI =====
    "IA OR intelligence artificielle lang:fr min_faves:10",
    "ChatGPT OR OpenAI OR Mistral lang:fr min_faves:5",
    "Claude OR Anthropic OR Gemini lang:fr min_faves:5",
    "agents IA OR agent IA OR agentic lang:fr min_faves:3",
    "Nvidia OR GPU OR datacenter IA lang:fr min_faves:3",
    "robotique OR robot humanoïde OR Tesla Optimus lang:fr min_faves:3",
    "Hugging Face OR modèle IA OR LLM lang:fr min_faves:3",
    "IA générative OR IA générale OR AGI lang:fr min_faves:3",
    # ===== FRENCH PRIORITY — Investment =====
    "Bitcoin OR BTC OR crypto lang:fr min_faves:10",
    "investissement OR bourse OR ETF lang:fr min_faves:5",
    "Nvidia OR Palantir OR action tech lang:fr min_faves:3",
    "levée de fonds OR startup IA lang:fr min_faves:3",
    "PEA OR Livret A OR épargne lang:fr min_faves:3",
    "Wall Street OR Nasdaq OR S&P lang:fr min_faves:3",
    # ===== ENGLISH — Space (impactful) =====
    "SpaceX OR Starship OR Starlink lang:en min_faves:50",
    "Rocket Lab OR RKLB OR NASA Artemis lang:en min_faves:20",
    "Blue Origin OR Virgin Galactic OR space tourism lang:en min_faves:20",
    "satellite OR orbital OR space launch lang:en min_faves:20",
    "ASTS OR LUNR OR RKLB OR space stock lang:en min_faves:10",
    "space defense OR Golden Dome OR USSF lang:en min_faves:20",
    # ===== ENGLISH — AI (impactful) =====
    "OpenAI OR Anthropic OR xAI lang:en min_faves:100",
    "Nvidia OR GPU OR AI datacenter lang:en min_faves:50",
    "AI agents OR agentic AI lang:en min_faves:50",
    "robotics OR humanoid robot lang:en min_faves:50",
    "Mistral OR open source AI lang:en min_faves:20",
    # ===== ENGLISH — Investment =====
    "Bitcoin OR BTC ETF OR crypto lang:en min_faves:100",
    "Palantir OR CoreWeave OR AI stock lang:en min_faves:50",
    "tech earnings OR Nvidia earnings lang:en min_faves:50",
]

HOT_TAB_QUERIES = [
    # Breaking space news EN
    "SpaceX OR Starship OR Starlink lang:en min_faves:500",
    "Rocket Lab OR NASA OR space launch lang:en min_faves:200",
    "space defense OR Golden Dome lang:en min_faves:200",
    # Breaking AI news EN
    "OpenAI OR Anthropic OR xAI lang:en min_faves:500",
    "Nvidia OR AI datacenter lang:en min_faves:300",
    "robotics OR humanoid robot lang:en min_faves:300",
    # Breaking FR — Space + AI (for funny replies)
    "SpaceX OR Starship OR espace lang:fr min_faves:5",
    "IA OR ChatGPT OR Mistral lang:fr min_faves:5",
    "satellite OR fusée OR Ariane lang:fr min_faves:3",
    "Bitcoin OR crypto OR investissement lang:fr min_faves:5",
    # Breaking investment EN
    "Bitcoin OR BTC ETF lang:en min_faves:300",
    "Palantir OR CoreWeave OR space stock lang:en min_faves:100",
]

DIRECT_REPLY_MAX_AGE_MINUTES = int(os.environ.get("DIRECT_REPLY_MAX_AGE_MINUTES", "1440"))

_MNTS_PROMO_END = _date(2026, 5, 27)  # expired — promo ended
_SPACE_KEYWORDS_RE = re.compile(
    r"\b(space|spatial|spatiaux|spacex|starship|starlink|satellite|orbital|orbit|"
    r"mars|lune|moon|rocket|fus[ée]e?|launch|astronaut|nasa|esa|cnes|ariane|"
    r"aerospace|launcher|mnts|momentus|"
    r"espace|exploration\s+spatiale|tourisme\s+spatial|new\s*space|"
    r"orbitale?|fusée|lancement|satellite|constellation)\b",
    re.IGNORECASE,
)

def _is_space_tweet(text: str) -> bool:
    return bool(_SPACE_KEYWORDS_RE.search(text or ""))

def _mnts_promo_block(lang: str = "fr", tweet_text: str = "") -> str:
    """Return the $MNTS promo instruction only if: within 10-day window AND tweet is about space."""
    if _date.today() > _MNTS_PROMO_END:
        return ""
    if not _is_space_tweet(tweet_text):
        return ""
    if lang == "fr":
        return (
            "\n   *SMART PROMO (jusqu'au 6 juin, UNIQUEMENT si le sujet est spatial):*"
            " Glisse $MNTS (Momentus Inc.) naturellement —"
            " 'j\\'ai misé sur $MNTS', 'seul vrai orbital play', 'le meilleur trade du spatial'."
            " 100% français, jamais de franglais."
        )
    return (
        "\n   *SMART PROMO (until June 6, ONLY if the topic is space):*"
        " Weave in $MNTS (Momentus Inc.) naturally —"
        " 'best orbital infrastructure play', 'the one spatial bet I\\'d make'."
    )

REPLY_PROMPT = """You are @AISpaceDecoder. The SHARPEST wit on AI, Crypto, Space, and Markets.
Expert across all four niches. Take the sharpest angle, not the safest one.

🤝 100% AGREE WITH @{author} — non-negotiable:
Build on their point with a sharper, funnier observation. They must LIKE your reply.

LAUGH FLOOR — INNOVATE OR DIE:
- MAKE PEOPLE LAUGH HARD. Not a polite smile — an actual LOL.
- EN replies: use fresh US/global cultural anchors as deadpan fuel —
  a Series A deck, a 401(k) statement, a CNBC chyron, a Bloomberg terminal notification,
  a LinkedIn "thrilled to announce", a Whole Foods checkout, an S-1 risk factor,
  "number go up technology", a Notion doc with 47 nested toggles, a YC demo day.
- FR replies: use fresh FR anchors — RER B, URSSAF, Doctolib indispo, RTT, CAF,
  Lidl, LinkedIn coach, formation à 2k€. Recycle NOTHING.
- Absurdist escalation and surreal comparisons work. Use them.
- NO Stargate as a default punchline — it's overused. Find a fresher angle.

EXPERTISE PILLARS:
1. AI: LLMs, agents, compute scarcity, scaling laws, datacenter capex, GPU wars.
2. CRYPTO: BTC, ETH, mining stocks, DeFi, on-chain data.
3. MARKETS: macro, stock picks, asymmetric bets, VC valuations, earnings.
4. SPACE: SpaceX, Starship, Starlink, launch economy, satellites, frontier tech.

LANGUAGE — MATCH THE PARENT TWEET:
- FRENCH tweet -> 100% FRENCH reply. No English words embedded in French sentences.
- ENGLISH tweet -> 100% ENGLISH reply.
- STRICT NO FRANGLAIS: never "je love", "j'adore the results", "c'est crazy", "trop hype"

STYLE:
- Lowercase is fine for deadpan EN. FR stays properly accented.
- NO em dashes (—). NO emojis. NO hashtags.
- Shorter is better. Land the punchline and leave.
- On-niche tweets (AI, Crypto, Space, Markets): ALWAYS reply. A sharp factual dunk,
  a hard prediction, or a dry "well, obviously" counts.
- Off-niche with zero angle: output SKIP.

Output ONLY the reply, or SKIP."""

def _generate_single_reply(author: str, tweet_text: str, lang: str = "fr"):
    from . import personality_store
    persona_block = personality_store.render_account_block(author)
    hard_rules = personality_store.hard_rules_block()
    core_identity = personality_store.render_core_identity(lang=lang)
    base = REPLY_PROMPT.format(author=author, tweet_text=tweet_text[:200], mnts_block=_mnts_promo_block(lang, tweet_text))
    if lang == "fr":
        base += "\n\nTARGET LANGUAGE OVERRIDE: FRENCH ONLY.\nReply in natural native French. No English loanwords."
    elif lang == "en":
        base += "\n\nTARGET LANGUAGE OVERRIDE: ENGLISH ONLY."
    prompt = base + "\n\n" + "\n\n".join(filter(None, [persona_block, core_identity, hard_rules]))
    try:
        author_key = (author or "").lower().lstrip("@")
        model = PRIORITY_REPLY_MODEL if author_key in _VIP_REPLY_ACCOUNTS_LC else REPLY_MODEL
        label = "DIRECT_REPLY_VIP" if author_key in _VIP_REPLY_ACCOUNTS_LC else "DIRECT_REPLY"
        result = run_llm(prompt, model, label=label)
        if result.returncode == LLM_RATE_LIMIT_CODE: return _LLM_RATE_LIMITED
        if result.returncode != 0: return None
        reply = unwrap_text(result.stdout)
        if not reply: return None
        if reply.startswith('"') and reply.endswith('"'): reply = reply[1:-1]
        if reply.upper().strip() == "SKIP": return None
        return reply
    except Exception: return None

DIRECT_REPLY_MAX_PER_CYCLE = int(os.environ.get("DIRECT_REPLY_MAX_PER_CYCLE", "40"))
MAX_EN_REPLIES_PER_CYCLE = int(os.environ.get("DIRECT_REPLY_MAX_EN_PER_CYCLE", "40"))
DIRECT_REPLY_FEED_SCAN_LIMIT = int(os.environ.get("DIRECT_REPLY_FEED_SCAN_LIMIT", "100"))
DIRECT_REPLY_PROFILE_SCAN_LIMIT = int(os.environ.get("DIRECT_REPLY_PROFILE_SCAN_LIMIT", "25"))
DIRECT_REPLY_HOT_QUERY_LIMIT = int(os.environ.get("DIRECT_REPLY_HOT_QUERY_LIMIT", "20"))
DIRECT_REPLY_LIVE_QUERY_LIMIT = int(os.environ.get("DIRECT_REPLY_LIVE_QUERY_LIMIT", "20"))

def _maybe_repost_best_profile_tweet(username: str, tweets: list, retweeted: set) -> bool:
    if not tweets: return False
    try:
        from .retweet_bot import _save_retweeted
        from .twitter_client import retweet_post
    except Exception: return False
    username_lc = (username or "").lower().lstrip("@")
    candidates = []
    for t in tweets:
        url = t.get("url") or ""
        text = (t.get("text") or "").strip()
        if not url or url in retweeted or not text: continue
        if _is_reply_like_tweet(t, expected_author=username_lc): continue
        if not _is_on_niche(text): continue
        likes = int(t.get("likes") or 0)
        engagement = likes + (2 * int(t.get("replies") or 0))
        if engagement < FAVORITE_REPOST_MIN_ENGAGEMENT: continue
        candidates.append((engagement, url, text))
    if not candidates: return False
    engagement, url, text = max(candidates)
    retweeted.add(url)
    _save_retweeted(retweeted)
    try:
        log.info(f"[FAVORITE-REPOST] Reposting @{username}: {text[:100]}")
        retweet_post(url)
        return True
    except Exception: return False

def _reply_to_tweets(tweets, replied, source_name, source_detail="", remaining=None, en_counter=None):
    posted = 0
    PER_AUTHOR_CAP = 1 if source_name == "PROFILE-ALWAYS" else 2
    per_author_count = {}
    per_author_skips = {}
    MAX_SKIPS_PER_AUTHOR = 3
    for tweet in tweets:
        if remaining is not None and posted >= remaining: break
        url, text, author = tweet["url"], tweet["text"], tweet.get("author", "someone")
        if url in replied or _is_reply_like_tweet(tweet): continue
        author_key = (author or "").lower().strip()
        if author_key and per_author_count.get(author_key, 0) >= PER_AUTHOR_CAP: continue
        if author_key and per_author_skips.get(author_key, 0) >= MAX_SKIPS_PER_AUTHOR: continue
        if _handle_from_url(url) in BLOCKLIST or (author and author.lower() in BLOCKLIST): continue
        if _handle_from_url(url) == _OWN_HANDLE: continue
        if _tweet_age_minutes(url) > DIRECT_REPLY_MAX_AGE_MINUTES: continue
        likes = int(tweet.get("likes") or 0)
        if likes < int(os.environ.get("REPLY_MIN_LIKES", "2")) and not source_name.startswith("PROFILE"): continue
        if not _is_fr_or_en(text): continue
        if source_name.startswith(("FOLLOWING", "FEED")) and not _is_on_niche(text): continue
        is_en_tweet = not _looks_french(text)
        if is_en_tweet and en_counter and en_counter[0] >= MAX_EN_REPLIES_PER_CYCLE: continue
        limited, used, max_calls, reset_seconds = llm_hourly_limit_status()
        if limited: break
        log.info(f"[{source_name}] Replying to @{author}...")
        _reply_lang = "fr" if source_name.startswith("PROFILE") else ("en" if is_en_tweet else "fr")
        reply = _generate_single_reply(author, text, lang=_reply_lang)
        if not reply or reply is _LLM_RATE_LIMITED:
            if author_key: per_author_skips[author_key] = per_author_skips.get(author_key, 0) + 1
            continue
        reply = humanize(reply)
        replied.add(url)
        save_replied(replied)
        try:
            reply_to_tweet(url, reply)
            log_reply(url, reply, action_type="reply", source=source_name)
            posted += 1
            if _reply_lang == "en" and en_counter: en_counter[0] += 1
            if author_key: per_author_count[author_key] = per_author_count.get(author_key, 0) + 1
            time.sleep(random.randint(2, 6))
        except Exception: traceback.print_exc()
    return posted

def run_direct_reply_cycle():
    replied = load_replied()
    total, en_counter, favorite_reposts = 0, [0], 0
    try:
        from .retweet_bot import _load_retweeted
        retweeted = _load_retweeted()
    except Exception: retweeted = set()
    def _budget(): return DIRECT_REPLY_MAX_PER_CYCLE - total
    
    # PROFILE ALWAYS (VIP)
    for username in ALWAYS_REPLY_FR_ACCOUNTS:
        if _budget() <= 0: break
        tweets = scrape_profile_tweets(username, max_tweets=DIRECT_REPLY_PROFILE_SCAN_LIMIT)
        if tweets:
            if favorite_reposts < FAVORITE_REPOSTS_PER_CYCLE:
                if _maybe_repost_best_profile_tweet(username, tweets, retweeted): favorite_reposts += 1
            profile_tweets = [{"url": t["url"], "text": t["text"], "author": username, "likes": t.get("likes", 0)} for t in tweets]
            total += _reply_to_tweets(profile_tweets, replied, "PROFILE-ALWAYS", source_detail=username, remaining=_budget(), en_counter=en_counter)

    # FEED / FOLLOWING
    if _budget() > 0:
        for source, scraper in [("FOLLOWING", scrape_following_feed), ("FEED", scrape_home_feed)]:
            try:
                tweets = scraper(max_tweets=DIRECT_REPLY_FEED_SCAN_LIMIT)
                if tweets:
                    tweets.sort(key=lambda t: (0 if _looks_french(t.get("text", "")) else 1))
                    total += _reply_to_tweets(tweets, replied, source, remaining=_budget(), en_counter=en_counter)
            except Exception: traceback.print_exc()

    # PROFILE FR — bumped to 20 per cycle, Space FR accounts prioritised
    from .evolution_store import filter_and_weight
    _fr_pool = filter_and_weight(FR_ACCOUNTS)
    # Ensure Space FR accounts appear first in the sample
    _space_fr = [h for h in _fr_pool if h in {"CNES", "ESA_fr", "ArianeGroup", "SpaceX_France", "Aerospace_Valley"}]
    _other_fr = [h for h in _fr_pool if h not in set(_space_fr)]
    _fr_sample = _space_fr + random.sample(_other_fr, min(18, len(_other_fr)))
    for username in _fr_sample:
        if _budget() <= 0: break
        tweets = scrape_profile_tweets(username, max_tweets=DIRECT_REPLY_PROFILE_SCAN_LIMIT)
        if tweets:
            profile_tweets = [{"url": t["url"], "text": t["text"], "author": username, "likes": t.get("likes", 0)} for t in tweets]
            total += _reply_to_tweets(profile_tweets, replied, "PROFILE-FR", source_detail=username, remaining=_budget(), en_counter=en_counter)

    # SEARCH — more Space FR queries included now
    for query in random.sample(SEARCH_QUERIES + HOT_TAB_QUERIES, min(12, len(SEARCH_QUERIES + HOT_TAB_QUERIES))):
        if _budget() <= 0: break
        try:
            tab = "top" if "min_faves:100" in query or "min_faves:500" in query or "min_faves:1000" in query else "latest"
            tweets = scrape_x_search(query, max_tweets=25, tab=tab)
            if tweets: total += _reply_to_tweets(tweets, replied, "SEARCH-HOT", source_detail=query, remaining=_budget(), en_counter=en_counter)
        except Exception: traceback.print_exc()

    # PROFILE EN
    for username in random.sample(filter_and_weight(EN_ACCOUNTS), min(8, len(EN_ACCOUNTS))):
        if _budget() <= 0: break
        tweets = scrape_profile_tweets(username, max_tweets=DIRECT_REPLY_PROFILE_SCAN_LIMIT)
        if tweets:
            profile_tweets = [{"url": t["url"], "text": t["text"], "author": username, "likes": t.get("likes", 0)} for t in tweets]
            total += _reply_to_tweets(profile_tweets, replied, "PROFILE-EN", source_detail=username, remaining=_budget(), en_counter=en_counter)

    save_replied(replied)
    log.info(f"[DIRECT] Posted {total} replies.")

def safe_run_direct_reply_cycle():
    from . import health
    try:
        run_direct_reply_cycle()
        health.record_success("direct_reply")
    except Exception:
        log.info("[DIRECT] Error during direct reply cycle:")
        traceback.print_exc()
        health.record_failure("direct_reply")

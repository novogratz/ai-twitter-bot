"""Retweet bot: selective amplifier for ELITE English AI infra signal.

Why this exists (user mandate 2026-04-27): the user is producing a daily
YouTube news show. Every retweet must clear two bars:
  1. It's REAL news / a real update worth a slot in tomorrow's video.
  2. The source is top-tier (Reuters / Bloomberg / TechCrunch / The Information /
     CoinDesk / Les Échos / Le Monde / FT / WSJ / etc. — the same whitelist
     the news agent already trusts).

So: still source-first, but much higher volume. We aim for constant crypto /
AI / bourse coverage, each one a useful amplification the user could screenshot
for the next YouTube intro.

Side effect that matters: every accepted retweet also gets appended to
`daily_news_picks.md` with the URL, source handle, and a one-line
why-it-matters. That file IS the YouTube research doc.

Distinct from the other paths:
  - reply_bot / direct_reply -> our voice attached to other people's tweets
  - quote_tweet_bot -> our voice ON TOP of a viral tweet (followers see it)
  - boost (notify_bot.run_boost_cycle) -> retweet of OUR OWN latest post
  - retweet_bot (this file) -> straight retweet of someone else's high-signal
    news, shows up in our followers' feed as a vote of confidence + free
    research credit, AND notifies the original author (relationship signal
    with top-tier journalists / outlets).

Hard rules:
  - Source MUST match TRUSTED_NEWS_HANDLES or the trusted-domain whitelist via
    the embedded article URL.
  - Tweet MUST be ≤24h old (proxy: caller filters; we trust freshness from
    the curated handle scrape, since these accounts post constantly).
  - We pre-filter dead tweets (likes < 25 OR no engagement at all).
  - We dedup persistently in retweeted.json (cap 1000).
  - We never retweet our own handle, our blocklist, or anything that's
    been quoted/replied-to in our own history.
"""
import json
import os
import random
import re
import time
import traceback
from datetime import datetime, date

from .config import (
    BLOCKLIST,
    BOT_HANDLE,
    _PROJECT_ROOT,
)
from .logger import log
from .twitter_client import retweet_post, scrape_following_feed, scrape_home_feed, scrape_profile_tweets, scrape_x_search
from .engagement_log import log_reply
from .humanizer import humanize, strip_agent_preamble

# State files
RETWEETED_FILE = os.path.join(_PROJECT_ROOT, "retweeted.json")
RETWEET_STATE_FILE = os.path.join(_PROJECT_ROOT, "retweet_daily_state.json")
DAILY_PICKS_FILE = os.path.join(_PROJECT_ROOT, "daily_news_picks.md")

# Hard cap per day. Path is deterministic/no-AI, so volume is cheap.
MAX_RETWEETS_PER_DAY = int(os.environ.get("MAX_RETWEETS_PER_DAY", "60"))
RETWEETS_PER_CYCLE = max(1, int(os.environ.get("RETWEETS_PER_CYCLE", "5")))

# Min likes to consider a candidate before scoring. French Twitter is smaller
# than global EN tech Twitter, so keep a lower FR floor and a stricter EN floor.
MIN_LIKES_FLOOR = int(os.environ.get("RETWEET_MIN_LIKES", "100"))
FR_MIN_LIKES_FLOOR = int(os.environ.get("RETWEET_FR_MIN_LIKES", "15"))

_OWN_HANDLE = BOT_HANDLE.lower()

# Niche keyword whitelist — a candidate tweet MUST contain at least one of
# these tokens to be retweet-eligible. User incident 2026-05-07: bot
# retweeted a 2012 Reuters tweet about Justin Bieber because Reuters posts
# everything, the trusted-handle whitelist alone wasn't enough to scope us
# to AI / crypto / bourse. Match is substring + case-insensitive.
NICHE_KEYWORDS = (
    # AI
    "ai", "a.i.", "artificial intelligence", "machine learning", "ml ",
    "openai", "anthropic", "claude", "chatgpt", "gpt", "gemini", "llama",
    "mistral", "llm", "nvidia", "nvda", "deepmind", "agi",
    "datacenter", "data center", "gpu", "tpu", "chip", "semiconductor",
    "compute", "compute cluster", "power demand", "power generation",
    "electricity", "grid", "nuclear", "megawatt", "megawatts", "mw ",
    "gigawatt", "gigawatts", "gw ", "energy demand", "ai infra",
    "ai infrastructure", "hpc", "colo", "colocation", "coreweave",
    "crwv", "crusoe", "lambda labs", "applied digital", "apld",
    "iren", "hive", "soluna", "slnh", "terawulf", "wulf",
    "cipher mining", "cifr", "core scientific", "corz",
    "hugging face", "huggingface", "perplexity", "copilot",
    "robotics", "humanoid", "frontier tech",
    # Crypto
    "bitcoin", "btc", "ethereum", "eth", "crypto", "stablecoin",
    "tether", "usdc", "coinbase", "binance", "kraken", "blockchain",
    "defi", "nft", "ordinals", "solana", "ripple", "xrp",
    "etf bitcoin", "etf btc", "etf ether", "spot etf", "halving",
    "tokenization", "tokenized", "rwa", "prediction market",
    "polymarket", "circle", "usdt", "saylor", "mstr",
    "sec lawsuit", "ofac", "mt gox", "tao", "bittensor",
    "decentralized compute", "decentralised compute",
    # Bourse / macro
    "stock", "shares", "nasdaq", "s&p", "s&p 500", "dow ",
    "cac40", "cac ", "ipo", "earnings", "guidance",
    "fed ", "fomc", "rate hike", "rate cut", "inflation", "cpi",
    "treasury yield", "bond ", "merger", "acquisition", "buyout",
    "tesla", "apple", "google", "alphabet", "meta", "amazon",
    "microsoft", "msft", "aapl", "googl", "tsla", "amzn",
    "valuation", "billion", "trillion", "milliard", "valo",
    "asymmetric", "asymmetry", "private markets", "frontier",
    "bourse", "marché", "marche", "action", "actions",
    "investissement", "trading", "pea", "cac 40", "cac40",
)

# Off-topic blocklist — common Reuters/Bloomberg/AP topics that have
# nothing to do with our niche. Even if the niche-keyword check passes
# accidentally, the off-topic check vetoes.
OFF_TOPIC_KEYWORDS = (
    "justin bieber", "taylor swift", "kardashian", "drake ",
    "world cup", "olympics", "super bowl", "nfl", "nba",
    "marathon", "premier league", "football match",
    "celebrity", "red carpet", "oscar", "grammy",
    "weather", "hurricane", "earthquake", "tornado",
    "wildfire", "flood", "missing person",
    "royal wedding", "queen elizabeth", "king charles",
    "horoscope", "zodiac", "recipe", "cooking",
)

# Max age in hours for a retweet candidate. Anything older is stale —
# we shouldn't be amplifying week-old or year-old news.
MAX_CANDIDATE_AGE_HOURS = int(os.environ.get("RETWEET_MAX_AGE_HOURS", "24"))
FEED_REPOST_MIN_ENGAGEMENT = int(os.environ.get("FEED_REPOST_MIN_ENGAGEMENT", "100"))
FEED_SEARCHES_PER_CYCLE = int(os.environ.get("RETWEET_FEED_SEARCHES_PER_CYCLE", "12"))

FEED_REPOST_SEARCH_QUERIES = [
    # French-first repost discovery. Same-day age and niche gates still apply.
    "IA OR ChatGPT OR Mistral lang:fr min_faves:10",
    "\"agents IA\" OR \"agent IA\" lang:fr min_faves:5",
    "Nvidia OR GPU OR datacenter lang:fr min_faves:5",
    "Bitcoin OR Ethereum OR crypto lang:fr min_faves:10",
    "Bittensor OR TAO OR DeFi OR stablecoin lang:fr min_faves:5",
    "bourse OR PEA OR ETF OR investissement lang:fr min_faves:5",
    "SpaceX OR Starship OR Starlink lang:fr min_faves:5",
    "ArianeGroup OR satellite OR spatial lang:fr min_faves:3",
    "OpenAI OR Anthropic OR Nvidia lang:fr min_faves:5",
    "Mistral OR souveraineté numérique OR cloud souverain lang:fr min_faves:3",
    "LeJournalDuCoin OR Cryptoast OR Cointribune lang:fr min_faves:3",
    "Zonebourse OR Finary OR Boursorama lang:fr min_faves:3",
    # English fallback only for big global signal.
    "AI datacenter OR power demand OR megawatt lang:en min_faves:500",
    "CoreWeave OR CRWV OR APLD OR IREN OR HIVE lang:en min_faves:300",
    "TAO OR Bittensor OR decentralized compute lang:en min_faves:300",
    "nuclear OR grid OR power generation AI lang:en min_faves:500",
    "robotics OR humanoid robots OR frontier tech lang:en min_faves:500",
    "SpaceX OR Starlink OR space infrastructure lang:en min_faves:1000",
    "Nvidia OR GPU OR compute cluster lang:en min_faves:1000",
    "OpenAI OR Anthropic OR xAI datacenter lang:en min_faves:1000",
]


def _is_on_niche(text: str) -> bool:
    """Tweet must contain at least one niche keyword AND no off-topic keyword."""
    t = (text or "").lower()
    if any(off in t for off in OFF_TOPIC_KEYWORDS):
        return False
    return any(kw in t for kw in NICHE_KEYWORDS)


def _scrape_age_hours(t: dict) -> float:
    """Best-effort age check from the scraper's timestamp field. Returns
    a large number when unavailable so the caller skips ambiguous tweets
    (better safe than retweeting Justin Bieber 2012)."""
    ts_raw = t.get("timestamp") or t.get("ts") or t.get("datetime")
    if not ts_raw:
        return 999_999.0
    try:
        ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
        return max(0.0, (datetime.now(ts.tzinfo or None) - ts).total_seconds() / 3600.0)
    except (ValueError, TypeError):
        return 999_999.0


# Trusted news handles split by language. 2026-05-06 user pivot: audience is
# FR, so the feed must look FR. Sample heavily from FR, only top-tier EN
# (wires) qualify as fallback when nothing FR is fresh enough.

FR_TRUSTED_HANDLES = [
    # FR generalist press
    "lesechos",
    "LeMondeFR",
    "lefigaro",
    "BFMTV",
    "bfmbusiness",
    "Investir",
    "JournalduCoin",
    "Cointribune",
    "FrenchWeb",
    "MaddyNess",
    "JournalDuNet",
    # FR tech press (primary FR AI signal lives here)
    "presse_citron",
    "siecledigital",
    "usine_digitale",
    "numerama",
    "01net",
    "LesNumeriques",
    "frandroid",
    "LADN_EU",
    # FR crypto press
    "BFMcrypto",
    "CointelegraphFR",
    "cryptoast_fr",
    # FR bourse / macro
    "BoursoraMag",
    "Capital",
    "Challenges",
    "LExpress",
    "AgefiFrance",
    "JDNebusiness",
    "latribune",
    "LaTribuneTech",
    "Finary",
    "Zonebourse",
    "cafedelabourse",
    "GoodValYou",
    "Grainedecrypteur",
    "FlasheurInvest",
    "Graphseo",
    "CryptoPicsou",
    "coinacademy_fr",
    "FranceCryptos",
    "LeJournalDuCoin",
]

EN_TRUSTED_HANDLES = [
    # Wires / global financial press
    "Reuters",
    "ReutersBiz",
    "business",          # Bloomberg
    "markets",           # Bloomberg Markets
    "FT",
    "WSJ",
    "WSJmarkets",
    "AFP",
    "AFPbusiness",
    "CNBC",
    "axios",
    "BloombergTV",
    "YahooFinance",
    # AI press — broadened back 2026-05-06: EN tweets still carry the
    # FR-language penalty in the scorer (-1 final), so volume is fine.
    "TechCrunch",
    "TheInformation",
    "verge",
    "WIRED",
    "OpenAI",
    "AnthropicAI",
    "GoogleDeepMind",
    "deepmind",
    "sama",
    "elonmusk",
    "xai",
    "karpathy",
    "ylecun",
    "fchollet",
    "AndrewYNg",
    "demishassabis",
    "ID_AA_Carmack",
    "lilianweng",
    "drfeifei",
    "jeremyphoward",
    "gwern",
    "rowancheung",
    "TheRundownAI",
    # Crypto press
    "CoinDesk",
    "TheBlock__",
    "BitcoinMagazine",
    "Cointelegraph",
    "decryptmedia",
    "blockworks_",
    "CryptoSlate",
    "CoinMarketCap",
    "WatcherGuru",
    "DocumentingBTC",
    "saylor",
    "MicroStrategy",
    "Polymarket",
    "circle",
    # Bourse / market signal
    "MarketWatch",
    "Investingcom",
    "SquawkCNBC",
    "KobeissiLetter",
    "unusual_whales",
    "bespokeinvest",
    "markets",
    # Official AI / big-tech news
    "MistralAI",
    "nvidia",
    "AMD",
    "intel",
    "Microsoft",
    "Meta",
    # AI infrastructure, power, mining-to-HPC, space
    "CoreWeave",
    "CrusoeEnergy",
    "LambdaAPI",
    "applied_dc",
    "IREN_Ltd",
    "Hut8Corp",
    "TeraWulfInc",
    "CipherMining",
    "CleanSpark_Inc",
    "MARAHoldings",
    "RiotPlatforms",
    "SpaceX",
    "Starlink",
    "RocketLab",
    "PeterDiamandis",
    # AI-linked crypto / decentralized compute
    "bittensor_",
    "opentensor",
]

# Combined list kept for the source-trust check. French sources are first-class
# repost sources; EN remains useful fallback for major global signal.
TRUSTED_NEWS_HANDLES = FR_TRUSTED_HANDLES + EN_TRUSTED_HANDLES

# Trusted domains — if the tweet embeds a link to one of these, we count
# the embedded article as the source even if the handle isn't on our list
# (e.g. someone reshares a Reuters scoop). Mirrors agent.py whitelist.
TRUSTED_DOMAINS = {
    "reuters.com", "bloomberg.com", "ft.com", "wsj.com", "afp.com",
    "techcrunch.com", "theinformation.com", "theverge.com", "wired.com",
    "coindesk.com", "theblock.co", "axios.com", "cnbc.com",
}

# Content blocklist — handles to never retweet even if scraped here. Safety
# net on top of BLOCKLIST.
RETWEET_HANDLE_BLOCKLIST = {h.lower() for h in BLOCKLIST}


# --- state helpers ---

def _load_state() -> dict:
    if os.path.exists(RETWEET_STATE_FILE):
        try:
            with open(RETWEET_STATE_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"date": None, "count": 0}


def _save_state(state: dict):
    with open(RETWEET_STATE_FILE, "w") as f:
        json.dump(state, f)


def _today_count() -> int:
    state = _load_state()
    today = date.today().isoformat()
    if state.get("date") != today:
        state = {"date": today, "count": 0}
        _save_state(state)
    return state["count"]


def _increment_count():
    state = _load_state()
    today = date.today().isoformat()
    if state.get("date") != today:
        state = {"date": today, "count": 0}
    state["count"] = state.get("count", 0) + 1
    _save_state(state)


QUOTED_FILE = os.path.join(_PROJECT_ROOT, "quoted_tweets.json")
_RETWEETED_CAP = 5000


def _read_id_list(path: str) -> list[str]:
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [str(u) for u in data if u]
        if isinstance(data, dict):
            return [str(u) for u in (data.get("urls") or []) if u]
    except (json.JSONDecodeError, IOError):
        pass
    return []


def _load_retweeted():
    """Return a CanonReplied set containing canonical IDs of tweets we
    already retweeted OR quoted. Cross-bot dedup so we don't both quote
    AND retweet the same tweet (looks bad on the timeline). 2026-05-18."""
    from .reply_bot import _CanonReplied
    s = _CanonReplied()
    for item in _read_id_list(RETWEETED_FILE):
        s.add(item)
    for item in _read_id_list(QUOTED_FILE):
        s.add(item)
    return s


def _save_retweeted(s):
    """Persist insertion order, cap at 5000 from the tail (newest).

    Bug 2026-05-16 (same shape as reply_bot pre-fix): previous impl was
    `list(s)[-1000:]` which slices a SET → non-deterministic drop, URLs
    fell out, re-retweet happened later. Fix mirrors reply_bot.save_replied.
    """
    existing = _read_id_list(RETWEETED_FILE)
    existing_set = set(existing)
    from .reply_bot import _canonical_tweet_id
    for u in s:
        cid = _canonical_tweet_id(u)
        if cid and cid not in existing_set:
            existing.append(cid)
            existing_set.add(cid)
    if len(existing) > _RETWEETED_CAP:
        existing = existing[-_RETWEETED_CAP:]
    with open(RETWEETED_FILE, "w") as f:
        json.dump(existing, f, indent=2)


def _handle_from_url(url: str) -> str:
    m = re.search(r"x\.com/([^/]+)/status/", url or "")
    return (m.group(1).lower() if m else "")


def _extract_external_url(text: str) -> str:
    """Find the first non-x.com URL embedded in the tweet text."""
    for m in re.finditer(r"https?://[^\s]+", text or ""):
        u = m.group(0).rstrip(").,;")
        if "x.com" in u or "twitter.com" in u or "t.co" in u:
            # t.co is X's wrapper — we can't resolve without a network call
            # in JS, so we fall back to handle-based trust.
            continue
        return u
    return ""


def _domain_of(url: str) -> str:
    m = re.match(r"https?://(?:www\.)?([^/]+)", url or "")
    return (m.group(1).lower() if m else "")


def _has_trusted_source(handle: str, text: str) -> bool:
    """Either the author handle is whitelisted OR the tweet embeds a link
    to a trusted-domain article. Either is enough."""
    h = (handle or "").lower()
    if any(h == w.lower() for w in TRUSTED_NEWS_HANDLES):
        return True
    ext = _extract_external_url(text)
    if ext and _domain_of(ext) in TRUSTED_DOMAINS:
        return True
    return False


# --- selection ---

def _feed_candidate_ok(t: dict) -> bool:
    """Allow feed-native reposts from For You / Following / search when they
    are on-niche and have at least some visible engagement. This is looser than
    the trusted-news-handle path because the point is to actively train the
    account's feed toward crypto / AI / bourse."""
    text = (t.get("text") or "").strip()
    if not text or text.startswith("@") or not _is_on_niche(text):
        return False
    likes = int(t.get("likes") or 0)
    replies = int(t.get("replies") or 0)
    author = ((t.get("author") or _handle_from_url(t.get("url") or "")) or "").lower()
    is_fr_source = any(author == h.lower() for h in FR_TRUSTED_HANDLES) or _looks_french_text(text)
    floor = min(FEED_REPOST_MIN_ENGAGEMENT, 10) if is_fr_source else FEED_REPOST_MIN_ENGAGEMENT
    return likes + (2 * replies) >= floor


def _looks_french_text(text: str) -> bool:
    low = (text or "").lower()
    return bool(re.search(r"[àâçéèêëîïôûùüÿœæ]", low)) or any(
        marker in low
        for marker in (
            " l'", " d'", "qu'", " c'", "est ", " les ", " des ", " une ",
            " avec ", " pour ", " marché", " bourse", " français", " ia ",
        )
    )


def _collect_feed_repost_candidates(retweeted: set) -> list:
    """Scrape For You/Home, Following, and targeted X searches for repostable
    crypto / AI / bourse content."""
    out = []

    def add(source: str, tweets: list):
        for t in tweets or []:
            url = t.get("url")
            if not url or url in retweeted:
                continue
            url_handle = _handle_from_url(url)
            author = (t.get("author") or url_handle or "").lower()
            if author in RETWEET_HANDLE_BLOCKLIST or url_handle in RETWEET_HANDLE_BLOCKLIST:
                continue
            if author == _OWN_HANDLE or url_handle == _OWN_HANDLE:
                continue
            if not _feed_candidate_ok(t):
                continue
            out.append({
                "url": url,
                "text": (t.get("text") or "").strip(),
                "author": url_handle or author or source,
                "likes": int(t.get("likes") or 0),
                "replies": int(t.get("replies") or 0),
                "source": source,
            })

    try:
        log.info("[RETWEET] Scraping For You/Home feed for repost candidates...")
        add("FEED_HOME", scrape_home_feed(max_tweets=40))
    except Exception:
        log.info("[RETWEET] Home feed candidate scrape failed:")
        traceback.print_exc()

    try:
        log.info("[RETWEET] Scraping Following feed for repost candidates...")
        add("FEED_FOLLOWING", scrape_following_feed(max_tweets=40))
    except Exception:
        log.info("[RETWEET] Following feed candidate scrape failed:")
        traceback.print_exc()

    queries = random.sample(
        FEED_REPOST_SEARCH_QUERIES,
        k=min(FEED_SEARCHES_PER_CYCLE, len(FEED_REPOST_SEARCH_QUERIES)),
    )
    for query in queries:
        try:
            tab = "top" if random.random() < 0.7 else "live"
            log.info(f"[RETWEET] Searching X {tab} for repost candidates: {query}")
            add(f"FEED_SEARCH/{tab}", scrape_x_search(query, max_tweets=25, tab=tab))
        except Exception:
            log.info(f"[RETWEET] Feed search candidate scrape failed for {query!r}:")
            traceback.print_exc()

    return out

def _candidate_rank(c: dict) -> tuple:
    """Deterministic impact rank. Higher tuple wins."""
    text_raw = c.get("text") or ""
    text = text_raw.lower()
    breaking = any(k in text for k in (
        "breaking", "exclusive", "announces", "announced", "launch",
        "raises", "raised", "sec", "fed", "bitcoin", "openai", "nvidia",
        "coreweave", "spacex", "datacenter", "data center",
    ))
    money_or_power = any(k in text for k in (
        "$", "billion", "trillion", "million", "acquire",
        "acquisition", "merger", "ipo", "bankrupt", "lawsuit",
        "ban", "regulator", "sec", "fed",
        "valuation", "earnings", "revenue", "profit", "loss",
        "megawatt", "gigawatt", "power", "energy", "nuclear", "ppa",
    ))
    strategic = any(k in text for k in (
        "openai", "anthropic", "nvidia", "mistral", "bitcoin", "ethereum",
        "coinbase", "google", "microsoft", "meta", "apple", "tesla",
        "rates", "inflation", "tariff", "chips", "gpu", "coreweave",
        "crwv", "apld", "iren", "hive", "slnh", "terawulf", "wulf",
        "cipher", "cifr", "bittensor", "tao", "spacex", "starlink",
    ))
    hard_impact = any(k in text for k in (
        "datacenter", "data center", "megawatt", "mw", "gigawatt", "gw",
        "power", "energy", "nuclear", "gpu cluster", "h100", "h200", "b200",
        "funding", "valuation", "treasury", "holdings", "etf", "inflows",
        "sec approves", "lawsuit", "ban", "partnership", "oracle", "softbank",
        "grid", "power generation", "colocation", "hpc", "ai hosting",
        "compute", "robotics", "humanoid", "frontier tech",
    ))
    numbers = len(re.findall(r"(\$?\d+(?:[.,]\d+)?\s?(?:%|bn|billion|m|million|k)?)", text))
    engagement = int(c.get("likes") or 0) + (2 * int(c.get("replies") or 0))
    impact_points = (
        (2 if breaking else 0)
        + (3 if money_or_power else 0)
        + (2 if strategic else 0)
        + (2 if hard_impact else 0)
        + min(numbers, 3)
    )
    return (impact_points, engagement)


def _score_candidate(pick: dict) -> dict:
    engagement = int(pick.get("likes") or 0) + (2 * int(pick.get("replies") or 0))
    impact_points = _candidate_rank(pick)[0]
    # 2026-05-08: dropped the FR-language bonus. The bot's voice is EN
    # now and we explicitly want to reshare English-source content, so
    # scoring should be language-agnostic on source.
    if impact_points >= 10 and engagement >= 100:
        score = 9
    elif impact_points >= 7 and engagement >= 50:
        score = 8
    elif impact_points >= 5 and engagement >= 25:
        score = 7
    else:
        score = 6
    return {
        "best_score": score,
        "why_it_matters": f"Source fiable + impact concret (score signal {impact_points}, engagement {engagement}).",
    }


def _score_candidates(candidates: list):
    """Pick the best trusted-source candidate without spending a model call."""
    if not candidates:
        return None
    idx, pick = max(enumerate(candidates), key=lambda item: _candidate_rank(item[1]))
    decision = _score_candidate(pick)
    decision["best_index"] = idx
    return decision


def _append_to_daily_picks(tweet: dict, score: int, why: str):
    """Write the pick to daily_news_picks.md so the user can pull tomorrow's
    YouTube show research from a single file."""
    today = date.today().isoformat()
    header = f"\n## {today}\n"
    line = (
        f"- **@{tweet.get('author','?')}** ({tweet.get('likes',0)} likes, score {score}/10) — "
        f"{(tweet.get('text','') or '').strip()[:240]}\n"
        f"  - {tweet.get('url','')}\n"
        f"  - **WHY**: {why}\n"
    )
    # Idempotent header: only write the date header once per day.
    body = ""
    if os.path.exists(DAILY_PICKS_FILE):
        with open(DAILY_PICKS_FILE, "r") as f:
            body = f.read()
    if header.strip() not in body:
        with open(DAILY_PICKS_FILE, "a") as f:
            f.write(header)
    with open(DAILY_PICKS_FILE, "a") as f:
        f.write(line)


# --- main cycle ---

_TROLL_QUOTE_PROMPT = """Tu es @CryptoAIDecode. Voix FR analytique IA + Crypto +
Investissement. Quand tu quote-tweet, tu te comportes comme si c'était TA
news propre — même gravitas, même précision, même autorité que Le Décode.

🎯 LA RÈGLE D'OR — UNE bonne quote = HARD SIGNAL + (optionnellement) UN
anchor culturel FR. Hard signal = un chiffre concret (Md$, GW, %, ratio),
un ticker (NVDA, BTC, MSTR, ETH), un @tag de gros compte, OU un nom propre
fort (Stargate, Anthropic, OpenAI, CoreWeave). Sans hard signal → SKIP.
Exemple qui a marché (3 likes): "L'Iran en alerte maximale, Trump annule
son repos, et @saylor recharge Bitcoin comme si c'était les soldes de
Lidl. Vous achetez ou vous shortez ce soir ?" → événement concret + @tag
+ comparaison Lidl bien ancrée. Marche parce que c'est ancré.
Exemple qui FLOP: "Bercy se réunit jeudi. Vous y croyez ?" → 0 hard signal,
pur folklore = SKIP.

Tu vas QUOTE-TWEETER ce tweet (qui s'affiche automatiquement en dessous,
donc ne le résume PAS, ajoute un angle d'analyse):

@{author}: "{tweet_text}"

OUTPUT: 2 phrases FR, max 240 chars TOTAL. Les DEUX phrases sont
obligatoires. Pas de quote avec UNIQUEMENT phrase 1.

  - Phrase 1 (L'ANALYSE): angle qui RECADRE le sujet. Ton 3 options:
      a) Le chiffre/contexte que le tweet ne donne pas: "$300Md = 2x la
         valo OpenAI il y a 9 mois. Le marché reprice par trimestre."
      b) La conséquence concrète pour le secteur: "Si l'inférence
         devient gratuite, Anthropic perd son moat de prix."
      c) Le comparatif analytique: "NVDA capture 70% du capex IA US.
         AMD reste à 15% malgré MI300."
    Tag 1 gros compte (@sama @ylecun @elonmusk @VitalikButerin @saylor
    @AnthropicAI @nvidia @MistralAI...) INLINE mid-phrase quand l'acteur
    est pertinent. JAMAIS en début/fin de ligne (X mobile l'isole sinon).
    Pas obligatoire si aucun tag ne colle.

  - Phrase 2 (LA QUESTION À L'AUDIENCE — OBLIGATOIRE): UNE question
    directe, courte (30-80 chars), analytique. Exemples:
      "Le marché a-t-il déjà pricé ça ?"
      "Qui rachète qui dans 6 mois ?"
      "Inflexion réelle ou rebond technique ?"
      "Le moat tient combien de trimestres ?"
      "Les régulateurs FR/EU bougent quand ?"
    L'algo X amplifie les threads qui réagissent. Sans la question =
    pas de réplies = pas d'amplification.

⚡ IMPACT — la phrase 1 doit dire quelque chose que le tweet parent NE
dit PAS. Pas un résumé, pas un "intéressant", pas un "à suivre". Si tu
n'as pas de chiffre/contexte/comparatif neuf à ajouter → SKIP. Mieux
pas de quote qu'une quote tiède.

🚨 RÈGLE D'OR — Analyse l'IDÉE / le PRODUIT / le MARCHÉ, JAMAIS @{author}.
@{author} doit pouvoir liker la quote. Tu peux contester un produit ou
une thèse en tant que telle. Pas d'attaque ad hominem.

RÈGLES STRICTES:
- 🇫🇷 100% FRANÇAIS PUR. ZÉRO mot anglais, ZÉRO franglais. Si le tweet
  parent est en EN, tu N'ÉCHO PAS ses phrases anglaises — tu reformules
  en français pur. INTERDIT: "Great weekend", "game changer", "deal",
  "team", "AI", "weekend", "hype", "moon", "pump", "dump", "FOMO",
  toute phrase entre guillemets en anglais reprise du parent.
  Exceptions tolérées: noms propres (OpenAI, Bitcoin, Stargate),
  tickers (BTC, ETH, NVDA, MSTR), acronymes techniques (LLM, GPU, ASIC,
  CapEx, AUM). PAS de phrases EN.
- Ton ANALYTIQUE D'ABORD. Un anchor culturel FR (Lidl, Bercy, RER B,
  tonton, etc) est OK MAX 1 PAR QUOTE, et UNIQUEMENT en appui d'un
  hard signal (chiffre/ticker/@tag). Pas d'anchor sans hard signal —
  ça devient un meme creux. Pas plus d'1 anchor — 2 = stand-up.
- Tag inline mid-phrase: "Pendant que @sama lève 6Md..." — OUI.
  "@sama lève 6Md" en début — NON. "Le pivot. @sama" en fin — NON.
- 1 @tag max, jamais 2 dans la même phrase.
- ZÉRO emojis, ZÉRO hashtags, ZÉRO em dash (—), ZÉRO markdown **bold**.
- Pas de "Voici", "Parfait", "Score", "Rationale" — sortie pure.
- Si pas de hard signal ou pas d'angle neuf → output exactement "SKIP".

Output: les 2 phrases FR (analyse + question) OU "SKIP". Rien d'autre."""


def _try_generate_troll_quote(pick: dict) -> str:
    """Generate a FR troll-commentary for a high-signal candidate. Returns
    None if generation fails or model returns SKIP."""
    try:
        from .config import REPLY_MODEL
        from .llm_client import run_llm, unwrap_text
    except Exception:
        return None
    author = pick.get("author") or "anon"
    text = (pick.get("text") or "")[:250]
    prompt = _TROLL_QUOTE_PROMPT.format(author=author, tweet_text=text)
    try:
        r = run_llm(prompt, REPLY_MODEL, label="RT_QT", timeout=60)
    except Exception:
        log.info("[RT_QT] run_llm crashed:")
        traceback.print_exc()
        return None
    if r.returncode != 0:
        log.info(f"[RT_QT] rc={r.returncode}: {r.stderr[:160] if r.stderr else ''}")
        return None
    out = unwrap_text(r.stdout)
    if not out:
        return None
    out = strip_agent_preamble(out).strip()
    out = humanize(out)
    if not out or out.upper().startswith("SKIP") or "skip" in out.lower().split():
        return None
    if out.startswith('"') and out.endswith('"'):
        out = out[1:-1].strip()
    if len(out) > 240 or len(out) < 25:
        return None
    # Deterministic Franglais guard. Model sometimes echoes an EN phrase
    # from the parent tweet ('"Great weekend" for data center stocks...').
    # If we detect an English n-gram in our supposed-FR quote → SKIP rather
    # than ship a half-translated mess. Whitelist proper-noun-ish tokens.
    if _has_english_phrase(out):
        log.info(f"[RT_QT] Franglais detected, refusing: {out[:140]!r}")
        return None
    # User mandate 2026-05-23: every quote MUST end with a question to the
    # audience. Without "?" → no engagement bait → SKIP to silent retweet.
    if "?" not in out:
        log.info(f"[RT_QT] No audience question (no '?'), refusing: {out[:140]!r}")
        return None
    # User mandate 2026-05-23 PM: FR anchors (RER B, Bercy, Lidl, tonton...)
    # are OK in quotes IF the quote also carries hard signal (number, $,
    # ticker, or named-entity tag). The Lidl quote that landed 3 likes
    # worked because it had @saylor + Bitcoin + concrete event. Pure joke
    # without hard anchor = SKIP.
    has_number = bool(re.search(r"\b\d[\d.,]*\s*(?:%|md|md\$|m\$|k\$|md€|m€|gw|tw|twh|gwh|mwh)\b", out, re.IGNORECASE)) or bool(re.search(r"\$\d", out))
    has_tag = "@" in out
    has_ticker = bool(re.search(r"\b(?:BTC|ETH|SOL|NVDA|AMD|MSTR|MARA|RIOT|TSLA|MSFT|GOOG|META|CRWV|OpenAI|Anthropic|Mistral|Stargate)\b", out))
    has_hard_signal = has_number or has_tag or has_ticker
    if not has_hard_signal:
        log.info(f"[RT_QT] No hard signal (number/tag/ticker), too soft, refusing: {out[:140]!r}")
        return None
    return out


# Common EN tokens that signal a phrase (not just a proper noun). If any
# of these appears as a whole word in the supposed-FR quote, treat the
# output as franglais and SKIP.
_FRANGLAIS_TOKENS = (
    "the", "and", "with", "for", "from", "great", "weekend", "game",
    "changer", "deal", "team", "people", "company", "stock", "stocks",
    "market", "money", "good", "bad", "back", "another", "this", "that",
    "what", "when", "where", "why", "how", "you", "your", "our", "their",
    "have", "been", "going", "getting", "looking", "saying", "thinking",
    "let", "lets", "let's", "make", "made", "take", "took", "give", "given",
    "buy", "sell", "short", "long", "moon", "pump", "dump", "fomo", "hype",
    "ai", "agi", "fud", "alpha", "beta", "rug", "bull", "bear", "fair",
    "ride", "ridge", "edge", "hold", "holding", "trade", "trading",
    "wallet", "swap", "drop", "huge", "big", "small", "ridiculous",
    "wild", "crazy", "insane", "broken", "weekend", "anyway", "actually",
    "obviously", "really", "very", "much", "more", "less", "now", "soon",
    "today", "yesterday", "tomorrow",
)


def _has_english_phrase(text: str) -> bool:
    """True if the supposed-FR quote contains a 'phrase-like' English word.
    Counts only whole-word matches (regex \\b). Returns True only when 2+
    distinct EN tokens hit so a single proper-noun-ish word doesn't
    false-trigger."""
    low = (text or "").lower()
    hits = 0
    for tok in _FRANGLAIS_TOKENS:
        if re.search(rf"\b{re.escape(tok)}\b", low):
            hits += 1
            if hits >= 2:
                return True
    # Also flag a single token if it's wrapped in quotes (clearly an
    # echoed parent phrase, e.g. '"Great weekend"').
    if re.search(r'["“”]\s*[A-Za-z]+(?:\s+[A-Za-z]+){1,4}\s*["“”]', text or ""):
        return True
    return False


def run_retweet_cycle():
    """Retweet the highest-signal tweets of the cycle.

    The scrape is the expensive part. Once we have a viable candidate pool,
    ship several reposts while preserving niche/source/dedup gates.
    """
    from .config import get_live_cap
    cap = get_live_cap("MAX_RETWEETS_PER_DAY", MAX_RETWEETS_PER_DAY)
    if _today_count() >= cap:
        log.info(f"[RETWEET] Daily cap reached ({cap}). Skipping.")
        return

    retweeted = _load_retweeted()
    candidates = _collect_feed_repost_candidates(retweeted)

    # High-volume crypto/AI/bourse repost surface. Scrape FR wide first, then
    # a smaller EN fallback. Source/niche/age/dedup gates keep it on topic.
    sample = (
        random.sample(FR_TRUSTED_HANDLES, k=min(24, len(FR_TRUSTED_HANDLES)))
        + random.sample(EN_TRUSTED_HANDLES, k=min(10, len(EN_TRUSTED_HANDLES)))
    )
    log.info(f"[RETWEET] Scraping FR-first crypto/AI/macro handles: {sample}")

    for handle in sample:
        try:
            tweets = scrape_profile_tweets(handle, max_tweets=8)
        except Exception:
            log.info(f"[RETWEET] Scrape failed for @{handle}:")
            traceback.print_exc()
            continue
        for t in tweets or []:
            url = t.get("url")
            if not url or url in retweeted:
                continue
            url_handle = _handle_from_url(url)
            author = (t.get("author") or url_handle or "").lower()
            if author in RETWEET_HANDLE_BLOCKLIST or url_handle in RETWEET_HANDLE_BLOCKLIST:
                continue
            if author == _OWN_HANDLE or url_handle == _OWN_HANDLE:
                continue
            text = (t.get("text") or "").strip()
            if not text:
                continue
            # Skip pure replies / threads from the source — first char "@"
            # usually means they're answering someone, not breaking news.
            if text.startswith("@"):
                continue
            likes = int(t.get("likes") or 0)
            replies = int(t.get("replies") or 0)
            is_fr_source = any((url_handle or handle).lower() == h.lower() for h in FR_TRUSTED_HANDLES)
            min_likes = FR_MIN_LIKES_FLOOR if is_fr_source or _looks_french_text(text) else MIN_LIKES_FLOOR
            if likes < min_likes and replies < 1:
                continue
            # 2026-05-07 user incident: bot retweeted Reuters' 2012 Justin
            # Bieber tweet. Reuters/Bloomberg post EVERYTHING — trusted
            # handle alone isn't enough. Hard niche-keyword + off-topic
            # gate before scoring. Tweet text MUST contain an AI/crypto/
            # bourse keyword AND no celebrity/sports/weather marker.
            if not _is_on_niche(text):
                continue
            # Same-day freshness — when scraper exposes a timestamp,
            # skip anything older than MAX_CANDIDATE_AGE_HOURS. When
            # it's missing the helper returns 999_999 → SKIP.
            # 2026-05-16: removed the "engagement-implies-fresh" escape
            # hatch — was letting 2025 tweets through because a 1-year-old
            # crypto post can still have 1 like / 1 reply. User complaint:
            # "stop reposting things from 2025". No timestamp = no retweet.
            age_hours = _scrape_age_hours(t)
            if age_hours > MAX_CANDIDATE_AGE_HOURS:
                continue
            # Belt-and-suspenders source check — even though the handle
            # came from our whitelist, pull it through _has_trusted_source
            # so embedded-article logic stays consistent.
            source_handle_for_check = url_handle or handle
            if not _has_trusted_source(source_handle_for_check, text):
                continue
            candidates.append({
                "url": url,
                "text": text,
                "author": url_handle or handle,
                "likes": likes,
                "replies": replies,
                "source": "TRUSTED_HANDLE",
            })

    if not candidates:
        log.info("[RETWEET] No viable candidates this cycle.")
        return

    log.info(
        f"[RETWEET] Scoring {len(candidates)} candidates deterministically "
        f"(no model call), target up to {RETWEETS_PER_CYCLE} retweets."
    )

    posted = 0
    logged = 0
    for pick in sorted(candidates, key=_candidate_rank, reverse=True):
        if posted >= RETWEETS_PER_CYCLE:
            break
        if _today_count() >= cap:
            log.info(f"[RETWEET] Daily cap reached mid-cycle ({cap}).")
            break
        if pick["url"] in retweeted:
            continue

        decision = _score_candidate(pick)
        score = int(decision.get("best_score", 0))
        why = (decision.get("why_it_matters") or "").strip()
        log.info(
            f"[RETWEET] Pick: @{pick['author']} score={score}/10 "
            f"(likes={pick['likes']}) — {pick['text'][:100]}"
        )

        # YouTube research doc: log anything ≥ 7/10.
        if score >= 7 and why:
            try:
                _append_to_daily_picks(pick, score, why)
                logged += 1
            except Exception:
                log.info("[RETWEET] Failed to write daily picks file:")
                traceback.print_exc()

        is_fr_pick = any((pick.get("author") or "").lower() == h.lower() for h in FR_TRUSTED_HANDLES) or _looks_french_text(pick.get("text") or "")
        threshold = 7 if is_fr_pick else 8
        if score < threshold:
            log.info(f"[RETWEET] Score {score}/10 below threshold ({threshold}). Logged only.")
            continue

        # Lock URL in BEFORE posting so a crash can't double-retweet.
        retweeted.add(pick["url"])
        _save_retweeted(retweeted)

        try:
            retweet_post(pick["url"])
            _increment_count()
            try:
                log_reply(
                    pick["url"],
                    f"[RT] {pick['text'][:200]}",
                    action_type="retweet",
                    source=f"RETWEET/{pick['author']}",
                )
            except Exception:
                pass
            posted += 1
            time.sleep(random.randint(5, 10))
        except Exception:
            log.info("[RETWEET] Posting failed:")
            traceback.print_exc()

    log.info(
        f"[RETWEET] DONE. Posted {posted}, logged {logged}. "
        f"Today's count: {_today_count()}/{cap}"
    )


def safe_run_retweet_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    from . import health
    try:
        run_retweet_cycle()
        health.record_success("retweet")
        # Autonomous git push of the news picks log + retweeted dedup state.
        # daily_news_picks.md is the user's YouTube show research doc.
        try:
            from .git_ops import auto_push
            auto_push(
                ["daily_news_picks.md", "retweeted.json", "retweet_daily_state.json"],
                "Autonomous retweet update — picks + dedup state",
            )
        except Exception:
            log.info("[RETWEET] auto_push failed (non-fatal):")
            traceback.print_exc()
    except Exception:
        log.info("[RETWEET] Error during retweet cycle:")
        traceback.print_exc()
        health.record_failure("retweet")

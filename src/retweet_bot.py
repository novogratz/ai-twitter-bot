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
MAX_RETWEETS_PER_DAY = int(os.environ.get("MAX_RETWEETS_PER_DAY", "300"))
RETWEETS_PER_CYCLE = max(1, int(os.environ.get("RETWEETS_PER_CYCLE", "25")))

# Min likes — lowered so breaking space/AI news gets in before it goes viral.
# Daily cap + dedup + niche filter are the real quality gates.
MIN_LIKES_FLOOR = int(os.environ.get("RETWEET_MIN_LIKES", "3"))
FR_MIN_LIKES_FLOOR = int(os.environ.get("RETWEET_FR_MIN_LIKES", "3"))

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
    "iren", "hugging face", "huggingface", "perplexity", "copilot",
    "robotics", "humanoid", "agentic", "ai agent", "ai agents",
    "frontier model", "frontier tech", "reasoning model",
    # Space — expanded for space push mode
    "spacex", "starship", "starlink", "falcon", "rocket lab", "rocketlab", "rklb",
    "nasa", "esa", "cnes", "isro", "jaxa", "ussf",
    "blue origin", "new glenn", "new shepard", "be-4",
    "virgin galactic", "virgin orbit", "spaceplane",
    "axiom space", "axiom", "firefly", "relativity space", "sierra space",
    "planet labs", "blacksky", "spire global", "terran orbital",
    "amazon kuiper", "oneweb", "one web",
    "satellite", "orbit", "orbital", "launch vehicle", "launch pad",
    "mars", "moon", "lunar", "artemis", "iss", "space station",
    "astronaut", "cosmonaut", "spacewalk", "ula", "vulcan centaur",
    "new space", "commercial space", "space economy", "space defense",
    "asts", "ast spacemobile", "lunr", "intuitive machines",
    "rklb", "rocket lab", "mnts", "momentus",
    "sidu", "sidus space", "astc", "astrotech",
    "rdw", "redwire", "spce", "virgin galactic",
    "ipo", "space ipo", "space stock", "space stocks",
    "rocket", "booster", "reentry", "payload",
    "leo ", "geo ", "meo ", "hypersonic", "space tourism",
    "golden dome", "space force", "starshield",
    "space infrastructure", "launch manifest",
    "earth observation", "remote sensing",
    # Investment / crypto
    "bitcoin", "btc", "ethereum", "eth", "crypto", "stablecoin",
    "usdc", "coinbase", "blockchain", "defi", "spot etf", "halving",
    "saylor", "mstr",
    "stock", "shares", "nasdaq", "s&p", "s&p 500",
    "ipo", "earnings", "guidance", "valuation",
    "merger", "acquisition", "buyout",
    "tesla", "apple", "google", "alphabet", "meta", "amazon",
    "microsoft", "msft", "aapl", "googl", "tsla", "amzn",
    "palantir", "pltr", "rklb", "asts", "lunr",
    "billion", "trillion", "milliard",
    "asymmetric", "private markets",
    "investissement", "trading",
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

# Shill / pump-and-dump blocklist — tweets that match these patterns are
# crypto spam and would tank our credibility. Never retweet these.
SHILL_PATTERNS = (
    "will make everyone millionaire",
    "99% will miss",
    "biggest retail opportunity",
    "1000x", "100x guaranteed", "10x guaranteed",
    "buy now before",
    "last chance to buy",
    "get in before",
    "this is your last",
    "elon is about to make",
    "you'll be rich",
    "retire from this",
    "life-changing opportunity",
    "don't miss this",
    "no clickbait",
    "pump incoming",
    "next 1000x",
    "gem alert",
    "hidden gem",
    "undervalued gem",
    "to the moon",
    "🚀🚀🚀",
    "💎🙌",
    "lfg 🚀",
)


def _is_shill(text: str) -> bool:
    """Return True if the tweet looks like a pump/shill/spam post."""
    t = (text or "").lower()
    # All-caps ratio > 60% of alpha chars is a shill signal
    alpha = [c for c in text if c.isalpha()]
    if len(alpha) > 20 and sum(1 for c in alpha if c.isupper()) / len(alpha) > 0.6:
        return True
    return any(p in t for p in SHILL_PATTERNS)

# Max age in hours for a retweet candidate. Anything older is stale —
# we shouldn't be amplifying week-old or year-old news.
MAX_CANDIDATE_AGE_HOURS = int(os.environ.get("RETWEET_MAX_AGE_HOURS", "48"))
FEED_REPOST_MIN_ENGAGEMENT = int(os.environ.get("FEED_REPOST_MIN_ENGAGEMENT", "5"))
FEED_SEARCHES_PER_CYCLE = int(os.environ.get("RETWEET_FEED_SEARCHES_PER_CYCLE", "20"))

FEED_REPOST_SEARCH_QUERIES = [
    # AI
    "OpenAI OR Anthropic OR xAI OR \"GPT-5\" lang:en min_faves:200",
    "Nvidia OR GPU OR \"compute cluster\" OR semiconductor lang:en min_faves:200",
    "\"AI agents\" OR \"agentic AI\" OR \"frontier model\" lang:en min_faves:100",
    "\"AI datacenter\" OR \"power demand\" OR megawatt OR gigawatt lang:en min_faves:100",
    "robotics OR \"humanoid robot\" OR \"AI robotics\" lang:en min_faves:100",
    "nuclear OR grid OR \"power generation\" AI lang:en min_faves:100",
    "CoreWeave OR CRWV OR APLD OR IREN lang:en min_faves:50",
    # Space — PUSH IT (2026-05-29 space mode)
    "SpaceX OR Starship OR \"Falcon 9\" OR Starlink lang:en min_faves:200",
    "\"Blue Origin\" OR \"New Glenn\" OR \"Virgin Galactic\" lang:en min_faves:100",
    "\"Rocket Lab\" OR RKLB OR NASA OR Artemis lang:en min_faves:50",
    "\"AST SpaceMobile\" OR ASTS OR LUNR OR \"space stock\" lang:en min_faves:100",
    "\"Golden Dome\" OR USSF OR \"space defense\" OR hypersonic lang:en min_faves:100",
    "ESA OR CNES OR Ariane OR \"commercial space\" lang:en min_faves:100",
    "satellite OR orbital OR \"space launch\" OR \"launch vehicle\" lang:en min_faves:200",
    "\"Axiom Space\" OR \"Firefly\" OR \"Relativity Space\" OR \"Sierra Space\" lang:en min_faves:100",
    "\"space economy\" OR \"space investment\" OR \"space startup\" lang:en min_faves:100",
    "Mars OR lunar OR moon OR Artemis OR \"space station\" lang:en min_faves:300",
    "\"Planet Labs\" OR \"BlackSky\" OR \"Earth observation\" satellite lang:en min_faves:100",
    "\"Amazon Kuiper\" OR \"satellite internet\" OR Starlink competitor lang:en min_faves:200",
    "MNTS OR Momentus OR SIDU OR \"Sidus Space\" lang:en min_faves:50",
    "ASTC OR \"Astrotech\" OR RDW OR \"Redwire\" lang:en min_faves:50",
    "RKLB OR LUNR OR ASTS OR SPCE OR \"space stock\" lang:en min_faves:100",
    # Investment
    "Bitcoin OR BTC OR \"BTC ETF\" OR \"crypto ETF\" lang:en min_faves:500",
    "Ethereum OR stablecoin OR DeFi OR \"spot ETF\" lang:en min_faves:300",
    "\"tech earnings\" OR \"Nvidia earnings\" OR \"AI valuation\" lang:en min_faves:300",
    "Palantir OR PLTR OR \"AI stock\" OR \"space stock\" lang:en min_faves:200",
]


def _is_on_niche(text: str) -> bool:
    """Tweet must contain at least one niche keyword, no off-topic keyword, and no shill."""
    t = (text or "").lower()
    if any(off in t for off in OFF_TOPIC_KEYWORDS):
        return False
    if _is_shill(text):
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


# Trusted news handles — 2026-05-27 pivot: English-first repost discovery.
# Sample heavily from EN sources; keep a small FR tail for major stories.

FR_TRUSTED_HANDLES = [
    # FR generalist press
    "lesechos",
    "LeMondeFR",
    "lefigaro",
    "BFMTV",
    "bfmbusiness",
    "FrenchWeb",
    "MaddyNess",
    "JournalDuNet",
    # FR tech / AI press
    "presse_citron",
    "siecledigital",
    "usine_digitale",
    "numerama",
    "01net",
    "LesNumeriques",
    "frandroid",
    "LADN_EU",
    # FR space
    "CNES",
    "ArianeGroup",
    "ESA_FR",
    # FR investment / crypto
    "BFMcrypto",
    "Capital",
    "Challenges",
    "LExpress",
    "latribune",
    "LaTribuneTech",
    "Finary",
    "Zonebourse",
    "cafedelabourse",
    "GoodValYou",
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
    # Crypto / investment press
    "CoinDesk",
    "blockworks_",
    "saylor",
    "MicroStrategy",
    # Market signal
    "MarketWatch",
    "Investingcom",
    "SquawkCNBC",
    "KobeissiLetter",
    "unusual_whales",
    "bespokeinvest",
    # Official AI / big-tech news
    "MistralAI",
    "nvidia",
    "AMD",
    "intel",
    "Microsoft",
    "Meta",
    # AI infrastructure / compute
    "CoreWeave",
    "CrusoeEnergy",
    "LambdaAPI",
    "applied_dc",
    "IREN_Ltd",
    # Space — PUSH IT (2026-05-29 space mode)
    "SpaceX",
    "Starlink",
    "RocketLab",
    "NASA",
    "NASAKennedy",
    "NASAArtemis",
    "NASASpaceflight",
    "SpaceflightNow",
    "SpaceNews",
    "ESA",
    "CNES",
    "ArianeGroup",
    "BlueOrigin",
    "virgingalactic",
    "ASTSpaceMobile",
    "IntuitiveMach",
    "AxiomSpace",
    "FireflySpace",
    "PlanetLabs",
    "BlackSkyTech",
    "SierraSpace",
    "PeterDiamandis",
    "Astro_DonPettit",
    "ChrisHadfield",
    "Teslarati",
    "SciGuySpace",
    "nextspaceflight",
    "elonmusk",
    "ShawnLevasseur",
    "thesheetztweetz",   # space reporter
    "jeff_foust",        # Space News editor
    "RDWSpace",
]

# Combined list kept for the source-trust check.
TRUSTED_NEWS_HANDLES = EN_TRUSTED_HANDLES + FR_TRUSTED_HANDLES

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
    return likes + (2 * replies) >= FEED_REPOST_MIN_ENGAGEMENT


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
        add("FEED_HOME", scrape_home_feed(max_tweets=60))
    except Exception:
        log.info("[RETWEET] Home feed candidate scrape failed:")
        traceback.print_exc()

    try:
        log.info("[RETWEET] Scraping Following feed for repost candidates...")
        add("FEED_FOLLOWING", scrape_following_feed(max_tweets=60))
    except Exception:
        log.info("[RETWEET] Following feed candidate scrape failed:")
        traceback.print_exc()

    queries = random.sample(
        FEED_REPOST_SEARCH_QUERIES,
        k=min(FEED_SEARCHES_PER_CYCLE, len(FEED_REPOST_SEARCH_QUERIES)),
    )
    for query in queries:
        try:
            tab = "live" if random.random() < 0.5 else "top"
            log.info(f"[RETWEET] Searching X {tab} for repost candidates: {query}")
            add(f"FEED_SEARCH/{tab}", scrape_x_search(query, max_tweets=40, tab=tab))
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

_TROLL_QUOTE_PROMPT = """You are @AISpaceDecoder. Sharp analytical voice on AI +
Crypto + Markets. When you quote-tweet, you act like it's YOUR own news —
same gravitas, same precision, same authority as The Decode.

🎯 THE GOLDEN RULE — a good quote = HARD SIGNAL + (optionally) ONE global
cultural anchor. Hard signal = a concrete number ($B, GW, %, ratio), a
ticker (NVDA, BTC, MSTR, ETH), an @tag of a big account, OR a strong proper
noun (Stargate, Anthropic, OpenAI, CoreWeave). No hard signal → SKIP.
Example that worked: "Iran on max alert, Trump cancels his weekend, and
@saylor reloads Bitcoin like it's a Black Friday doorbuster. Buying or
shorting tonight?" → concrete event + @tag + a well-anchored comparison.
Works because it's anchored.
Example that FLOPS: "The Fed meets Thursday. Believe it?" → 0 hard signal,
pure folklore = SKIP.

You will QUOTE-TWEET this tweet (it auto-renders below, so do NOT summarize
it — add an angle of analysis):

@{author}: "{tweet_text}"

OUTPUT: 2 English sentences, max 240 chars TOTAL. BOTH sentences are
mandatory. No quote with ONLY sentence 1.

  - Sentence 1 (THE ANALYSIS): an angle that REFRAMES the subject. 3 options:
      a) The number/context the tweet doesn't give: "$300B = 2x OpenAI's
         valuation 9 months ago. The market reprices every quarter."
      b) The concrete consequence for the sector: "If inference goes free,
         Anthropic loses its price moat."
      c) The analytical comparison: "NVDA captures 70% of US AI capex.
         AMD stuck at 15% despite MI300."
    Tag 1 big account (@sama @ylecun @elonmusk @VitalikButerin @saylor
    @AnthropicAI @nvidia @MistralAI...) INLINE mid-sentence when the actor
    is relevant. NEVER at the start/end of a line (X mobile isolates it).
    Not required if no tag fits.

  - Sentence 2 (THE QUESTION TO THE AUDIENCE — MANDATORY): ONE direct,
    short (30-80 chars), analytical question. Examples:
      "Has the market already priced this?"
      "Who acquires who in 6 months?"
      "Real inflection or technical bounce?"
      "How many quarters does the moat hold?"
      "When do US/EU regulators move?"
    The X algo amplifies threads that get replies. No question = no
    replies = no amplification.

⚡ IMPACT — sentence 1 must say something the parent tweet does NOT.
Not a summary, not "interesting", not "one to watch". If you don't have a
fresh number/context/comparison to add → SKIP. Better no quote than a
lukewarm one.

🚨 GOLDEN RULE — analyze the IDEA / the PRODUCT / the MARKET, NEVER @{author}.
@{author} must be able to like the quote. You can challenge a product or a
thesis on its merits. No ad hominem attacks.

STRICT RULES:
- 🇬🇧 100% ENGLISH. ZERO French words. If the parent tweet is in French, you
  do NOT echo its French phrases — you reframe in clean English. Write as a
  native English-speaking operator/founder.
- ANALYTICAL FIRST. A global cultural anchor (a 10-K footnote, the Fed dot
  plot, a CNBC chyron, a 401(k), Whole Foods, "number go up technology") is
  OK MAX 1 PER QUOTE, and ONLY backing a hard signal (number/ticker/@tag).
  No anchor without a hard signal — it becomes an empty meme. Max 1 anchor.
  NO French anchors (Bercy, RER B, Lidl, tonton) — gibberish to a global reader.
- Tag inline mid-sentence: "While @sama raises $6B..." — YES.
  "@sama raises $6B" at the start — NO. "The pivot. @sama" at the end — NO.
- 1 @tag max, never 2 in the same sentence.
- ZERO emojis, ZERO hashtags, ZERO em dash (—), ZERO markdown **bold**.
- No "Here's", "Perfect", "Score", "Rationale" — pure output.
- If no hard signal or no fresh angle → output exactly "SKIP".

Output: the 2 English sentences (analysis + question) OR "SKIP". Nothing else."""


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

    # High-volume crypto/AI repost surface. English-first since the
    # 2026-05-27 pivot: scrape EN only for repost discovery. FR handles
    # are excluded because our timeline is English now — reposting French
    # content on an EN timeline is incoherent.
    sample = random.sample(EN_TRUSTED_HANDLES, k=min(15, len(EN_TRUSTED_HANDLES)))
    log.info(f"[RETWEET] Scraping EN-first crypto/AI handles: {sample}")

    for handle in sample:
        try:
            tweets = scrape_profile_tweets(handle, max_tweets=15)
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
            # Age gate: only apply when the scraper returned a real timestamp.
            # Without a timestamp _scrape_age_hours returns 999999 and kills
            # every candidate — scraper never populates this field currently.
            if t.get("timestamp") or t.get("ts") or t.get("datetime"):
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

        threshold = 7  # raise bar to filter clickbait (score 6 = "$1M fastest way" level)
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

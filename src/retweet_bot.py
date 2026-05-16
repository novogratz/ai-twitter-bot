"""Retweet bot: selective amplifier for ELITE AI / crypto / bourse news.

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

# State files
RETWEETED_FILE = os.path.join(_PROJECT_ROOT, "retweeted.json")
RETWEET_STATE_FILE = os.path.join(_PROJECT_ROOT, "retweet_daily_state.json")
DAILY_PICKS_FILE = os.path.join(_PROJECT_ROOT, "daily_news_picks.md")

# Hard cap per day. Path is deterministic/no-AI, so volume is cheap.
MAX_RETWEETS_PER_DAY = int(os.environ.get("MAX_RETWEETS_PER_DAY", "220"))
RETWEETS_PER_CYCLE = max(1, int(os.environ.get("RETWEETS_PER_CYCLE", "5")))

# Min likes to even consider a candidate. Lowered 10 → 5 (2026-05-05) so
# fresh elite news from trusted handles gets amplified BEFORE engagement
# accumulates — being early on the wire is the whole point.
MIN_LIKES_FLOOR = int(os.environ.get("RETWEET_MIN_LIKES", "0"))

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
    "hugging face", "huggingface", "perplexity", "copilot",
    # Crypto
    "bitcoin", "btc", "ethereum", "eth", "crypto", "stablecoin",
    "tether", "usdc", "coinbase", "binance", "kraken", "blockchain",
    "defi", "nft", "ordinals", "solana", "ripple", "xrp",
    "etf bitcoin", "etf btc", "etf ether", "spot etf", "halving",
    "tokenization", "tokenized", "rwa", "prediction market",
    "polymarket", "circle", "usdt", "saylor", "mstr",
    "sec lawsuit", "ofac", "mt gox",
    # Bourse / macro
    "stock", "shares", "nasdaq", "s&p", "s&p 500", "dow ",
    "cac40", "cac ", "ipo", "earnings", "guidance",
    "fed ", "fomc", "rate hike", "rate cut", "inflation", "cpi",
    "treasury yield", "bond ", "merger", "acquisition", "buyout",
    "tesla", "apple", "google", "alphabet", "meta", "amazon",
    "microsoft", "msft", "aapl", "googl", "tsla", "amzn",
    "valuation", "billion", "trillion", "milliard", "valo",
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
FEED_REPOST_MIN_ENGAGEMENT = int(os.environ.get("FEED_REPOST_MIN_ENGAGEMENT", "5"))
FEED_SEARCHES_PER_CYCLE = int(os.environ.get("RETWEET_FEED_SEARCHES_PER_CYCLE", "2"))

FEED_REPOST_SEARCH_QUERIES = [
    "Bitcoin OR BTC lang:fr min_faves:3",
    "Ethereum OR ETH lang:fr min_faves:3",
    "crypto OR stablecoin OR DeFi lang:fr min_faves:3",
    "OpenAI OR ChatGPT OR Claude lang:fr min_faves:3",
    "IA OR intelligence artificielle OR Mistral lang:fr min_faves:3",
    "Nvidia OR GPU OR datacenter lang:fr min_faves:3",
    "bourse OR CAC40 OR actions lang:fr min_faves:3",
    "NASDAQ OR Tesla OR Microsoft lang:fr min_faves:3",
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
    # Official AI / big-tech news
    "MistralAI",
    "nvidia",
    "Microsoft",
    "Meta",
]

# Combined list kept for the source-trust check (a tweet from any of these
# clears the "trusted source" gate). Sampling logic below biases FR.
TRUSTED_NEWS_HANDLES = FR_TRUSTED_HANDLES + EN_TRUSTED_HANDLES

# Trusted domains — if the tweet embeds a link to one of these, we count
# the embedded article as the source even if the handle isn't on our list
# (e.g. someone reshares a Reuters scoop). Mirrors agent.py whitelist.
TRUSTED_DOMAINS = {
    "reuters.com", "bloomberg.com", "ft.com", "wsj.com", "afp.com",
    "techcrunch.com", "theinformation.com", "theverge.com", "wired.com",
    "coindesk.com", "theblock.co", "axios.com", "cnbc.com",
    "lesechos.fr", "lemonde.fr", "lefigaro.fr", "bfmtv.com",
    "investir.lesechos.fr", "journalducoin.com", "cointribune.com",
    "frenchweb.fr", "maddyness.com", "journaldunet.com",
    # FR additions 2026-05-05
    "presse-citron.net", "siecledigital.fr", "usine-digitale.fr",
    "numerama.com", "01net.com", "lesnumeriques.com", "frandroid.com",
    "ladn.eu", "cryptoast.fr", "bfmtv.com/crypto", "boursorama.com",
    "capital.fr", "challenges.fr", "lexpress.fr",
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


def _load_retweeted() -> set:
    if os.path.exists(RETWEETED_FILE):
        try:
            with open(RETWEETED_FILE, "r") as f:
                return set(json.load(f))
        except (json.JSONDecodeError, IOError):
            pass
    return set()


def _save_retweeted(s: set):
    with open(RETWEETED_FILE, "w") as f:
        # Keep the most recent 1000 entries — set order isn't preserved but
        # for dedup we don't care; size cap matters.
        json.dump(list(s)[-1000:], f, indent=2)


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
    return likes + (2 * replies) >= FEED_REPOST_MIN_ENGAGEMENT


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
        add("FEED_HOME", scrape_home_feed(max_tweets=25))
    except Exception:
        log.info("[RETWEET] Home feed candidate scrape failed:")
        traceback.print_exc()

    try:
        log.info("[RETWEET] Scraping Following feed for repost candidates...")
        add("FEED_FOLLOWING", scrape_following_feed(max_tweets=25))
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
            add(f"FEED_SEARCH/{tab}", scrape_x_search(query, max_tweets=15, tab=tab))
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
    ))
    money_or_power = any(k in text for k in (
        "$", "billion", "trillion", "million", "acquire",
        "acquisition", "merger", "ipo", "bankrupt", "lawsuit",
        "ban", "regulator", "sec", "fed",
        "valuation", "earnings", "revenue", "profit", "loss",
    ))
    strategic = any(k in text for k in (
        "openai", "anthropic", "nvidia", "mistral", "bitcoin", "ethereum",
        "coinbase", "google", "microsoft", "meta", "apple", "tesla",
        "rates", "inflation", "tariff", "chips", "gpu",
    ))
    numbers = len(re.findall(r"(\$?\d+(?:[.,]\d+)?\s?(?:%|bn|billion|m|million|k)?)", text))
    engagement = int(c.get("likes") or 0) + (2 * int(c.get("replies") or 0))
    impact_points = (
        (2 if breaking else 0)
        + (3 if money_or_power else 0)
        + (2 if strategic else 0)
        + min(numbers, 3)
    )
    return (impact_points, engagement)


def _score_candidate(pick: dict) -> dict:
    engagement = int(pick.get("likes") or 0) + (2 * int(pick.get("replies") or 0))
    impact_points = _candidate_rank(pick)[0]
    # 2026-05-08: dropped the FR-language bonus. The bot's voice is EN
    # now and we explicitly want to reshare English-source content, so
    # scoring should be language-agnostic on source.
    if impact_points >= 9 and engagement >= 100:
        score = 9
    elif impact_points >= 7 and engagement >= 50:
        score = 8
    else:
        score = 7
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

    # High-volume crypto/AI/bourse repost surface. Scrape wide every cycle;
    # source/niche/age/dedup gates keep the feed on topic.
    en_sample = random.sample(
        EN_TRUSTED_HANDLES, k=min(24, len(EN_TRUSTED_HANDLES))
    )
    fr_sample = random.sample(
        FR_TRUSTED_HANDLES, k=min(10, len(FR_TRUSTED_HANDLES))
    )
    sample = en_sample + fr_sample
    log.info(f"[RETWEET] Scraping crypto/AI/bourse handles: {sample}")

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
            if likes < MIN_LIKES_FLOOR and replies < 1:
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

        # 2026-05-09 PM: relaxed 6 → 5. User wants TRACK EVERYONE + retweet
        # viral things aggressively. Source-trust + niche + age gates already
        # filter; the score threshold becomes mostly a tiebreaker.
        if score < 5:
            log.info(f"[RETWEET] Score {score}/10 below retweet threshold (5). Logged only.")
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

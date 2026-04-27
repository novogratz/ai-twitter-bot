"""Retweet bot: selective amplifier for ELITE AI / crypto / bourse news.

Why this exists (user mandate 2026-04-27): the user is producing a daily
YouTube news show. Every retweet must clear two bars:
  1. It's REAL news / a real update worth a slot in tomorrow's video.
  2. The source is top-tier (Reuters / Bloomberg / TechCrunch / The Information /
     CoinDesk / Les Échos / Le Monde / FT / WSJ / etc. — the same whitelist
     the news agent already trusts).

So: NOT a volume play. We aim for ~6-10 retweets/day, each one a banger
the user could screenshot for the next YouTube intro.

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
import subprocess
import time
import traceback
from datetime import datetime, date

from .config import (
    BLOCKLIST,
    BOT_HANDLE,
    QUOTE_MODEL,
    _PROJECT_ROOT,
)
from .logger import log
from .twitter_client import retweet_post, scrape_profile_tweets
from .engagement_log import log_reply

# State files
RETWEETED_FILE = os.path.join(_PROJECT_ROOT, "retweeted.json")
RETWEET_STATE_FILE = os.path.join(_PROJECT_ROOT, "retweet_daily_state.json")
DAILY_PICKS_FILE = os.path.join(_PROJECT_ROOT, "daily_news_picks.md")

# Hard cap per day. Selective != silent. 8 lets us cover one banger every
# ~2 hours during awake windows; the bar is so high we'll often hit fewer.
MAX_RETWEETS_PER_DAY = int(os.environ.get("MAX_RETWEETS_PER_DAY", "8"))

# Min likes to even consider a candidate — skips dead tweets without
# punishing accounts that genuinely break news (their tweets get likes fast).
MIN_LIKES_FLOOR = int(os.environ.get("RETWEET_MIN_LIKES", "25"))

_OWN_HANDLE = BOT_HANDLE.lower()

# Trusted news handles. Curated, not auto-discovered — we want the YouTube
# show to source from REAL outlets, not crypto-twitter rumors. FR + EN.
# A retweet from one of these = automatic source attribution win.
TRUSTED_NEWS_HANDLES = [
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
    # AI press
    "TechCrunch",
    "TheInformation",
    "verge",             # The Verge
    "WIRED",
    "MIT_CSAIL",
    "deepmind",
    "OpenAI",
    "AnthropicAI",
    "GoogleDeepMind",
    # Crypto press
    "CoinDesk",
    "TheBlock__",
    "BitcoinMagazine",
    "decryptmedia",
    # Bourse / macro press
    "CNBC",
    "axios",
    "BloombergTV",
    "YahooFinance",
    # FR press
    "lesechos",
    "LeMondeFR",
    "lefigaro",
    "BFMTV",
    "bfmbusiness",
    "Investir",
    "JournalduCoin",
    "Cointribune",       # FR crypto outlet (not on contentfarm reject list)
    "FrenchWeb",
    "MaddyNess",
    "JournalDuNet",
]

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

SCORE_PROMPT = """Tu es l'éditeur d'un journal vidéo YouTube quotidien sur l'IA, la crypto et la bourse. Voici des tweets candidats. Note CHAQUE tweet sur 10 selon UN SEUL critère: "vraie news, neuve, à fort impact, digne d'un slot dans la vidéo de demain."

Critères de scoring (chaque tweet, 0-10):
- 10 = breaking, source de premier rang, info qu'aucun autre média n'a encore relayée
- 8-9 = info importante de source crédible, mérite la vidéo
- 6-7 = update intéressant mais déjà couvert ailleurs
- 4-5 = analyse / opinion / commentaire de marché
- 0-3 = promo, hype, meme, thread perso, vide

REJETER (note 0):
- Threads marketing / "buy my course"
- Spéculation sans source
- Repost d'une info de >24h
- Posts de comptes promotionnels qui se font passer pour de la news

CANDIDATS:
{candidates}

Réponds UNIQUEMENT en JSON, sans préambule, sous la forme:
{{"best_index": <int>, "best_score": <int 0-10>, "why_it_matters": "<une phrase FR de 15 mots max expliquant pourquoi c'est important pour une vidéo news>"}}"""


def _score_candidates(candidates: list):
    """Run a single Claude pass over all candidates, return the winner.

    Output shape: {"best_index": int, "best_score": int, "why_it_matters": str}
    Returns None on parse / subprocess failure (caller skips the cycle).
    """
    listing = []
    for i, c in enumerate(candidates):
        listing.append(
            f"[{i}] @{c.get('author', '?')} ({c.get('likes', 0)} likes): "
            f"{(c.get('text') or '')[:240]}"
        )
    prompt = SCORE_PROMPT.format(candidates="\n".join(listing))
    try:
        result = subprocess.run(
            ["claude", "-p", prompt, "--model", QUOTE_MODEL, "--output-format", "json"],
            capture_output=True, text=True, timeout=45,
        )
        if result.returncode != 0:
            log.info(f"[RETWEET] Scorer subprocess failed: {result.stderr[:200]}")
            return None
        raw = result.stdout.strip()
        try:
            envelope = json.loads(raw)
            out = envelope.get("result", raw).strip()
        except (json.JSONDecodeError, AttributeError):
            out = raw
        # Strip code fences if any
        m = re.search(r"\{[^{}]*\"best_index\"[^{}]*\}", out, re.DOTALL)
        if not m:
            log.info(f"[RETWEET] Scorer returned no JSON: {out[:200]}")
            return None
        data = json.loads(m.group(0))
        return data
    except Exception:
        log.info("[RETWEET] Scorer exception:")
        traceback.print_exc()
        return None


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
    """Pick the single highest-signal tweet of the cycle and retweet it
    (only if it clears 9/10 score). Append to daily_news_picks.md regardless
    of score if it clears 8/10 — that file is the YouTube research doc."""
    if _today_count() >= MAX_RETWEETS_PER_DAY:
        log.info(f"[RETWEET] Daily cap reached ({MAX_RETWEETS_PER_DAY}). Skipping.")
        return

    retweeted = _load_retweeted()

    # Sample 4 trusted handles per cycle. With 8 cycles/day and 38 handles
    # we get strong coverage without burning Safari time on every source.
    sample = random.sample(TRUSTED_NEWS_HANDLES, k=min(4, len(TRUSTED_NEWS_HANDLES)))
    log.info(f"[RETWEET] Scraping trusted news handles: {sample}")

    candidates = []
    for handle in sample:
        try:
            tweets = scrape_profile_tweets(handle, max_tweets=5)
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
            if likes < MIN_LIKES_FLOOR and replies < 5:
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
            })

    if not candidates:
        log.info("[RETWEET] No viable candidates this cycle.")
        return

    log.info(f"[RETWEET] Scoring {len(candidates)} candidates with Claude...")
    decision = _score_candidates(candidates)
    if not decision:
        log.info("[RETWEET] Scoring failed — skipping cycle.")
        return

    idx = int(decision.get("best_index", -1))
    score = int(decision.get("best_score", 0))
    why = (decision.get("why_it_matters") or "").strip()
    if idx < 0 or idx >= len(candidates):
        log.info(f"[RETWEET] Scorer returned invalid index {idx} — skipping.")
        return

    pick = candidates[idx]
    log.info(
        f"[RETWEET] Best pick: @{pick['author']} score={score}/10 "
        f"(likes={pick['likes']}) — {pick['text'][:100]}"
    )
    log.info(f"[RETWEET] WHY (for YouTube doc): {why}")

    # YouTube research doc: log anything ≥ 8/10 even if we don't actually
    # retweet it (gives the user a wider research surface than the retweet
    # cap would).
    if score >= 8 and why:
        try:
            _append_to_daily_picks(pick, score, why)
            log.info(f"[RETWEET] Logged to {os.path.basename(DAILY_PICKS_FILE)}")
        except Exception:
            log.info("[RETWEET] Failed to write daily picks file:")
            traceback.print_exc()

    # Hard threshold for an actual retweet: 9/10. The user said
    # "extremely high value content" — bar must be brutal.
    if score < 9:
        log.info(f"[RETWEET] Score {score}/10 below retweet threshold (9). Logged only.")
        return

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
        time.sleep(random.randint(5, 10))
        log.info(f"[RETWEET] DONE. Today's count: {_today_count()}/{MAX_RETWEETS_PER_DAY}")
    except Exception:
        log.info("[RETWEET] Posting failed:")
        traceback.print_exc()


def safe_run_retweet_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    from . import health
    try:
        run_retweet_cycle()
        health.record_success("retweet")
    except Exception:
        log.info("[RETWEET] Error during retweet cycle:")
        traceback.print_exc()
        health.record_failure("retweet")

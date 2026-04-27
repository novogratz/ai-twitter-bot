"""Early-bird bot: catch fresh tweets from mega accounts within minutes.

Why this matters more than any other reply path: being in the TOP 5 replies
on a viral tweet is a 10-100x impressions multiplier vs. landing as reply
#50 an hour later. The standard reply bot fires every 20 min — too slow to
consistently land top-5 on a fresh banger from sama / OpenAI / Mathieu.

Strategy:
- Every 5 min, pick a few mega accounts at random.
- Scrape their latest tweets (existing scraper).
- If any tweet is < 12 min old AND we haven't replied yet → reply NOW.
- Hard cap 1 reply per cycle. Lock-before-post URL dedup. Same dead-tweet
  filter as direct_reply (won't reply to tweets with 0 engagement YET — but
  the threshold is loose because fresh tweets often have 0 likes).
- Source-tagged "EARLYBIRD/<handle>" so the strategy agent sees it.
"""
import random
import time
import traceback
from .config import BLOCKLIST, BOT_HANDLE
from .logger import log
from .twitter_client import scrape_profile_tweets, reply_to_tweet
from .reply_bot import load_replied, save_replied, _tweet_age_minutes, _handle_from_url
from .direct_reply import _generate_single_reply
from .engagement_log import log_reply
from .humanizer import humanize

_OWN_HANDLE = BOT_HANDLE.lower()

# Mega accounts that consistently produce viral tweets in our niches. FR-leaning
# but EN megas included — being early on Sam Altman pulls more reach than being
# early on a niche FR account. Order-agnostic; we sample.
# MASSIVE expansion (was 25 → now ~75). With 3 picks/cycle every ~7min, this
# rotates through every account roughly every ~3h — meaning a fresh tweet
# anywhere in this list has a real shot of being caught inside the 12-min
# top-5-reply window. FR media is HEAVY because that's our audience.
EARLY_BIRD_ACCOUNTS = [
    # === IA mega EN ===
    "sama", "OpenAI", "AnthropicAI", "elonmusk", "karpathy", "ylecun",
    "GoogleDeepMind", "MistralAI", "DarioAmodei", "AravSrinivas",
    "demishassabis", "gdb", "miramurati", "ID_AA_Carmack", "geoffreyhinton",
    "AndrewYNg", "fchollet", "jeffdean", "simonw", "swyx",
    # === IA EN niche / dev ===
    "TheRundownAI", "rowancheung", "mckaywrigley", "levelsio",
    "AlphaSignalAI", "TheAIGRID", "DrJimFan", "GaryMarcus",
    # === IA FR ===
    "cyrildiagne", "KorbenInfo", "Underscore_", "micode",
    "GuillaumeBesson", "Frandroid", "Numerama", "JournalDuGeek",
    # === Crypto mega EN ===
    "VitalikButerin", "APompliano", "cz_binance", "brian_armstrong",
    "WuBlockchain", "tier10k", "CryptoCapo_", "saylor",
    # === Crypto FR (heavy — our audience) ===
    "PowerHasheur", "Capetlevrai", "JournalDuCoin", "powl_d",
    "owen_simonin", "Cryptoast", "TheBigWhale_", "CointribuneFR",
    "Coin_Academy", "Dark_Emi_", "CryptoMusic_fr",
    # === Bourse FR (heavy — high signal, low noise) ===
    "MathieuL1", "Graphseo", "NCheron_bourse", "ABaradez", "DereeperVivre",
    "ThomasVeillet", "YoannLOPEZ", "RodolpheSteffan", "IVTrading",
    "FinTales_", "ZonebourseFR",
    # === FR media (mass distribution + breaking news) ===
    "BFMTV", "BFMBourse", "lemondefr", "lesechos", "Capital",
    "Le_Figaro", "France24",  # InvestirLeJournal (>15 char) + LeRevenu_fr (0% scrape) removed 2026-04-27
    # === Markets EN ===
    "unusual_whales", "chamath", "jimcramer",
    # === Tech media EN ===
    "TechCrunch", "TheVerge", "WIRED",
    # === FR/QC additions 2026-04-26 — big AI/crypto/bourse voices ===
    "Yoshua_Bengio", "Montreal_AI", "ActuIAFr",  # defendintelligence (>15 char) removed 2026-04-27
    "Tradosaure", "InvestQuebec", "FI_Quebec", "investirfr", "cryptoqc",
    "lesaffaires", "BourseFrance",
]

# A tweet is "early-bird eligible" if it's at most this many minutes old.
# Goal: land in top ~5 replies. Sweet spot is ~5-15 min depending on the
# account's audience size. 12 is a balance.
EARLY_BIRD_AGE_MAX_MIN = 12


def run_early_bird_cycle():
    """One scan: pick a few mega accounts, reply to ANY fresh tweet found."""
    replied = load_replied()
    posted = 0

    # Apply autonomous evolution: filter pruned + double-weight reinforced accounts
    from .evolution_store import filter_and_weight
    pool = filter_and_weight(EARLY_BIRD_ACCOUNTS)

    # 3 random accounts per cycle. With 5-min cadence that's 36 scrapes/hour
    # — enough coverage without flooding Safari (each scrape ~6-8s).
    picks = random.sample(pool, k=min(3, len(pool)))

    for username in picks:
        if posted >= 2:
            break  # two early-bird replies per cycle, max — bumped 1→2 on
            # user directive 2026-04-26 PM. When 2 viral tweets are fresh,
            # both get the top-5-reply 10-100x impression boost. Per-URL
            # dedup + quiet hours still bound damage.

        log.info(f"[EARLYBIRD] Scanning @{username} for fresh tweets...")
        try:
            # Only the top 3 tweets — anything older isn't fresh anyway.
            tweets = scrape_profile_tweets(username, max_tweets=3)
        except Exception:
            log.info(f"[EARLYBIRD] Scrape failed for @{username}:")
            traceback.print_exc()
            continue

        if not tweets:
            continue

        for tweet in tweets:
            url = tweet.get("url", "")
            text = tweet.get("text", "")
            if not url or url in replied:
                continue

            # Block self + blocklisted
            url_handle = _handle_from_url(url)
            if url_handle in BLOCKLIST or url_handle == _OWN_HANDLE:
                continue
            if username.lower() in BLOCKLIST or username.lower() == _OWN_HANDLE:
                continue

            age = _tweet_age_minutes(url)
            if age > EARLY_BIRD_AGE_MAX_MIN:
                continue  # too late — drops down to standard reply bot territory
            if age < 0 or age > 9000:
                continue  # parse failure / clock skew

            log.info(f"[EARLYBIRD] FRESH ({age}min) @{username}: {text[:80]}...")
            reply = _generate_single_reply(username, text)
            if not reply:
                log.info(f"[EARLYBIRD] Generation returned SKIP for @{username}.")
                # Don't add to replied — we want to retry next cycle if we generate
                # a better take then. The 5-min cadence will catch it again.
                continue

            reply = humanize(reply)
            log.info(f"[EARLYBIRD] Reply ({len(reply)} chars): {reply}")

            # Lock URL in BEFORE posting (no double-reply on retry/crash)
            replied.add(url)
            save_replied(replied)

            try:
                reply_to_tweet(url, reply)
                try:
                    log_reply(url, reply, action_type="reply", source=f"EARLYBIRD/{username}")
                except Exception:
                    pass
                posted += 1
                time.sleep(random.randint(5, 12))
                break  # one reply per scanned account = move on
            except Exception:
                log.info(f"[EARLYBIRD] Post failed for {url}:")
                traceback.print_exc()

    if posted:
        log.info(f"[EARLYBIRD] Posted {posted} fresh reply this cycle.")
    else:
        log.info("[EARLYBIRD] No fresh tweets in window this cycle.")


def safe_run_early_bird_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    from . import health
    try:
        run_early_bird_cycle()
        health.record_success("early_bird")
    except Exception:
        log.info("[EARLYBIRD] Error during early-bird cycle:")
        traceback.print_exc()
        health.record_failure("early_bird")

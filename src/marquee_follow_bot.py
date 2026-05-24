"""Marquee-account follow bot.

User mandate 2026-05-22: "follow Elon Musk account bro and big accounts
like him... MAKE SOME BUZZ".

Difference from `follow_blast_bot` (which mass-follows niche FR users found
via search) and from `engage_bot` (which likes-then-follows a curated medium
pool): this bot ensures the account is FOLLOWING THE GIANTS. Following Elon
/ sama / Vitalik / Saylor / etc:

  1. Pins our home feed to first-party signal (mega_watch + reply_bot get
     fresher candidates).
  2. Sends a small "we exist" notification ping to the followed account.
  3. Makes the profile look legit to anyone who checks who we follow.

Idempotent: persists to `followed_accounts.json` (shared with engage_bot).
Runs once per day; iterates only handles we don't already follow. Falls
through fast when caught up.
"""
import os
import random
import time
import traceback

from .config import _PROJECT_ROOT
from .logger import log
from .twitter_client import follow_account
from . import engage_bot

# Hand-curated "giants" the bot should follow. Mix EN + FR so the home feed
# stays bilingual-rich. Order does not matter — random.shuffle per cycle.
MARQUEE_HANDLES = [
    # AI labs + founders
    "elonmusk", "sama", "OpenAI", "AnthropicAI", "MistralAI",
    "ArthurMensch", "GuillaumeLample", "ylecun", "karpathy",
    "demishassabis", "GoogleDeepMind", "xai", "grok",
    "AIatMeta", "perplexity_ai", "AravSrinivas",
    # AI researchers / sharp thinkers (user-curated 2026-05-23)
    "fchollet", "AndrewYNg", "lilianweng", "drfeifei",
    "ID_AA_Carmack", "jeremyphoward", "gwern",
    # Cursor — user mandate 2026-05-23: "Elon loves Cursor, we need his attention"
    "cursor_ai", "sualeh", "amanrsanger", "mntruell",
    # Chips + infra
    "nvidia", "AMD", "intel", "CoreWeave", "CrusoeEnergy",
    "groqinc", "cerebrassystems", "LambdaAPI", "applied_dc",
    "IREN_Ltd",
    # Crypto core
    "VitalikButerin", "saylor", "MicroStrategy", "brian_armstrong",
    "coinbase", "cz_binance", "binance", "krakenfx",
    "ethereum", "solana", "aeyakovenko",
    # Crypto mining
    "MARAHoldings", "RiotPlatforms", "CleanSpark_Inc", "Hut8Corp",
    "Bitfarms_io", "TeraWulfInc", "CipherMining", "Core_Scientific",
    # Crypto press + analysts
    "CoinDesk", "TheBlock__", "Cointelegraph", "watcherguru",
    "DocumentingBTC", "PeterSchiff", "RaoulGMI", "APompliano",
    "bittensor_", "opentensor", "KobeissiLetter", "unusual_whales",
    # FR ecosystem
    "rachel__lemoine", "ledger", "PaymiumOfficial", "ArthurBigBig",
    "owencyclops", "marcelenplace",
    # Space + adjacent (user added 2026-05-19)
    "SpaceX", "Starlink", "blueorigin", "RocketLab", "PeterDiamandis",
]


_STATE_FILE = os.path.join(_PROJECT_ROOT, "marquee_follow_state.json")
PER_CYCLE_CAP = 4  # 4/day from a 524-follower account looks organic;
# 8 in one batch trips spam-detection. Lowered 2026-05-22 pre-vacation.


def _last_run_today() -> bool:
    import json
    from datetime import date
    if not os.path.exists(_STATE_FILE):
        return False
    try:
        with open(_STATE_FILE) as f:
            d = json.load(f) or {}
        return d.get("date") == date.today().isoformat()
    except (json.JSONDecodeError, OSError):
        return False


def _mark_ran_today() -> None:
    import json
    from datetime import date
    try:
        with open(_STATE_FILE, "w") as f:
            json.dump({"date": date.today().isoformat()}, f)
    except OSError:
        pass


def run_marquee_follow_cycle() -> None:
    if _last_run_today():
        log.info("[MARQUEE-FOLLOW] Already ran today — skipping.")
        return
    followed = engage_bot._load_followed()
    pending = [h for h in MARQUEE_HANDLES if h.lower() not in {f.lower() for f in followed}]
    if not pending:
        log.info("[MARQUEE-FOLLOW] All marquee handles already followed — nothing to do.")
        _mark_ran_today()
        return
    random.shuffle(pending)
    batch = pending[:PER_CYCLE_CAP]
    log.info(f"[MARQUEE-FOLLOW] {len(batch)} giants to follow today: {batch}")
    followed_this_cycle = 0
    for handle in batch:
        try:
            if follow_account(handle):
                followed.add(handle)
                followed_this_cycle += 1
                log.info(f"[MARQUEE-FOLLOW] Followed @{handle}")
            else:
                log.info(f"[MARQUEE-FOLLOW] follow_account returned False for @{handle}")
        except Exception:
            log.info(f"[MARQUEE-FOLLOW] follow_account crashed on @{handle}:")
            traceback.print_exc()
        time.sleep(random.uniform(4.0, 8.0))
    engage_bot._save_followed(followed)
    _mark_ran_today()
    log.info(f"[MARQUEE-FOLLOW] DONE. Followed {followed_this_cycle}/{len(batch)} this cycle.")


def safe_run_marquee_follow_cycle() -> None:
    from . import health
    try:
        run_marquee_follow_cycle()
        health.record_success("marquee_follow")
    except Exception:
        log.info("[MARQUEE-FOLLOW] outer error:")
        traceback.print_exc()
        health.record_failure("marquee_follow")

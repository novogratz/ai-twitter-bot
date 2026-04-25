"""@kzer_ai Twitter bot - AI news, sharp takes, strategic replies.

Growth strategy: replies on massive accounts > original posts.
Quality over quantity. Every interaction must earn a follow.

Usage:
    python main.py              Run all bots
    python main.py --post-only  Run only the post bot
    python main.py --reply-only Run only the reply bot
    python main.py --dry-run    Print what would happen without posting
"""
import argparse
import random
import signal
import sys
import traceback
from datetime import datetime
from zoneinfo import ZoneInfo
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger
from src.logger import log
from src.bot import safe_run_bot_cycle
from src.reply_bot import safe_run_reply_cycle
from src.engage_bot import safe_run_engage_cycle
from src.notify_bot import safe_run_notify_cycle, safe_run_boost_cycle, safe_run_replyback_cycle
from src.direct_reply import safe_run_direct_reply_cycle
from src.discover_bot import safe_run_discovery_cycle
from src.roast_pgm_bot import safe_run_roast_pgm_cycle
from src.performance import evaluate_and_learn
from src.strategy_agent import safe_run_strategy_cycle
from src.quote_tweet_bot import safe_run_quote_tweet_cycle
from src.early_bird_bot import safe_run_early_bird_cycle


def quiet_hours_paris() -> bool:
    """True between 1am-7am Paris. Real humans sleep — bots that don't are
    obvious. Used to skip replies/engages/roasts/early-bird at night.
    News posts still flow (info doesn't sleep) but at the slowest cadence."""
    hour = datetime.now(ZoneInfo("Europe/Paris")).hour
    return 1 <= hour < 7


def post_interval_minutes() -> int:
    """Cluster posts during peak engagement windows. With cap = 10 news + 4
    hot takes per day, intervals are slower than before — quality > volume."""
    hour = datetime.now(ZoneInfo("America/New_York")).hour
    if 23 <= hour or hour < 8:
        # Night (Paris asleep): slow cadence so we drift into the morning
        # with fresh content without spamming overnight.
        return random.randint(150, 240)
    elif 9 <= hour < 11:
        # PEAK: Morning EST window
        return random.randint(60, 100)
    elif 13 <= hour < 15:
        # PEAK: Afternoon EST window
        return random.randint(60, 100)
    elif 8 <= hour < 12:
        # Near-peak morning
        return random.randint(90, 150)
    elif 12 <= hour < 18:
        # Afternoon
        return random.randint(90, 150)
    else:
        # Evening: winding down
        return random.randint(140, 220)


def reply_interval_minutes() -> int:
    """Replies are the growth engine but volume = bot smell. ~30min with
    jitter (was 20). With cap=2/cycle this is ~60-80 replies/day max — high
    but plausibly human. Quiet hours skip these entirely."""
    return random.randint(25, 38)


def engage_interval_minutes() -> int:
    """Follow + like cadence. Was 30min. Slowed to ~45min with jitter to
    avoid the 'this account follows 50 ppl/day' bot signal."""
    return random.randint(40, 55)


def direct_reply_interval_minutes() -> int:
    """Was 15min. Slowed to ~25min jittered. Pairs with reply_bot to keep
    total reply volume sane (~target 60-100 actions/day across both paths)."""
    return random.randint(22, 32)


def early_bird_interval_minutes() -> int:
    """Was 5min. Slowed to ~8min jittered. Still inside the 12-min freshness
    window for top-5-reply on viral tweets, but less Safari pressure."""
    return random.randint(7, 10)


def roast_interval_minutes() -> int:
    """Was 10min. Slowed to ~20min jittered. @pgm_pm tweets every minute so
    we still catch plenty — and 1 roast per URL via existing dedup hard caps."""
    return random.randint(18, 25)


def _graceful_shutdown(signum, frame):
    """Handle SIGTERM/SIGINT for clean shutdown."""
    log.info(f"Received signal {signum}. Shutting down gracefully...")
    sys.exit(0)


def main():
    parser = argparse.ArgumentParser(description="@kzer_ai AI Twitter bot")
    parser.add_argument("--post-only", action="store_true", help="Run only the post bot")
    parser.add_argument("--reply-only", action="store_true", help="Run only the reply bot")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without posting")
    args = parser.parse_args()

    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGTERM, _graceful_shutdown)
    signal.signal(signal.SIGINT, _graceful_shutdown)

    if args.dry_run:
        log.info("DRY RUN MODE - no tweets will be posted")

    scheduler = BlockingScheduler()

    # --- POST BOT (secondary - few posts, only bangers) ---
    def reschedule_and_post():
        safe_run_bot_cycle()
        next_min = post_interval_minutes()
        hour = datetime.now(ZoneInfo("America/New_York")).hour
        log.info(f"[POST][EST {hour}:xx] Next post in {next_min} minutes.")
        scheduler.reschedule_job(
            "post_job",
            trigger=IntervalTrigger(minutes=next_min),
        )

    def _quiet_skip(label: str) -> bool:
        """Skip-and-reschedule helper for engagement cycles during quiet hours."""
        if quiet_hours_paris():
            log.info(f"[{label}] Quiet hours (1am-7am Paris) — skipping cycle.")
            return True
        return False

    # --- REPLY BOT (primary growth engine) ---
    def reschedule_and_reply():
        if not _quiet_skip("REPLY"):
            safe_run_reply_cycle()
        next_min = reply_interval_minutes()
        hour = datetime.now(ZoneInfo("America/New_York")).hour
        log.info(f"[REPLY][EST {hour}:xx] Next reply scan in {next_min} minutes.")
        scheduler.reschedule_job(
            "reply_job",
            trigger=IntervalTrigger(minutes=next_min),
        )

    def reschedule_and_engage():
        if not _quiet_skip("ENGAGE"):
            safe_run_engage_cycle()
        scheduler.reschedule_job(
            "engage_job",
            trigger=IntervalTrigger(minutes=engage_interval_minutes()),
        )

    def reschedule_and_direct_reply():
        if not _quiet_skip("DIRECT-REPLY"):
            safe_run_direct_reply_cycle()
        scheduler.reschedule_job(
            "direct_reply_job",
            trigger=IntervalTrigger(minutes=direct_reply_interval_minutes()),
        )

    def reschedule_and_early_bird():
        if not _quiet_skip("EARLYBIRD"):
            safe_run_early_bird_cycle()
        scheduler.reschedule_job(
            "early_bird_job",
            trigger=IntervalTrigger(minutes=early_bird_interval_minutes()),
        )

    def reschedule_and_roast():
        if not _quiet_skip("ROAST"):
            safe_run_roast_pgm_cycle()
        scheduler.reschedule_job(
            "roast_pgm_job",
            trigger=IntervalTrigger(minutes=roast_interval_minutes()),
        )

    def quiet_safe_notify():
        if not _quiet_skip("NOTIFY"):
            safe_run_notify_cycle()

    def quiet_safe_replyback():
        if not _quiet_skip("REPLYBACK"):
            safe_run_replyback_cycle()

    # Run direct reply bot FIRST - visits influencer profiles directly
    if not args.post_only:
        log.info("Bot started! Replying to influencer tweets...")
        safe_run_direct_reply_cycle()

    # Then run first post
    if not args.reply_only:
        log.info("Now posting first news tweet...")
        safe_run_bot_cycle()

    # Schedule jobs
    if not args.reply_only:
        first_post = post_interval_minutes()
        log.info(f"Next post in {first_post} minutes.")
        scheduler.add_job(
            reschedule_and_post,
            trigger=IntervalTrigger(minutes=first_post),
            id="post_job",
        )

    if not args.post_only:
        first_reply = reply_interval_minutes()
        log.info(f"Reply bot: next scan in {first_reply} minutes.")
        scheduler.add_job(
            reschedule_and_reply,
            trigger=IntervalTrigger(minutes=first_reply),
            id="reply_job",
        )

    if not args.post_only and not args.reply_only:
        # Engage bot - follow and like AI accounts for reciprocity.
        # Slowed from 30 -> ~45min jittered. Skipped during quiet hours.
        # Initial offset = 7min so it doesn't fire at the same tick as other jobs.
        log.info("Engage bot: follow + like target accounts every ~45 min (jittered, quiet 1am-7am Paris).")
        scheduler.add_job(
            reschedule_and_engage,
            trigger=IntervalTrigger(minutes=engage_interval_minutes()),
            id="engage_job",
        )

        # Notify bot - like replies on own tweets to build community.
        # Quiet hours skip; cadence kept at 45min (cheap operation).
        log.info("Notify bot: liking replies on own tweets every 45 min (quiet 1am-7am Paris).")
        scheduler.add_job(
            quiet_safe_notify,
            trigger=IntervalTrigger(minutes=45),
            id="notify_job",
        )

        # Direct reply bot - visits influencer profiles and replies to their tweets.
        # Slowed from 15 -> ~25min jittered. Skipped during quiet hours.
        log.info("Direct reply bot: replying to influencer tweets every ~25 min (jittered, quiet 1am-7am Paris).")
        scheduler.add_job(
            reschedule_and_direct_reply,
            trigger=IntervalTrigger(minutes=direct_reply_interval_minutes()),
            id="direct_reply_job",
        )

        # Reply-back bot - reply to people who reply to our tweets (creates threads).
        # Cadence unchanged (60min) but skipped during quiet hours.
        log.info("Reply-back bot: replying to followers every 60 min (quiet 1am-7am Paris).")
        scheduler.add_job(
            quiet_safe_replyback,
            trigger=IntervalTrigger(minutes=60),
            id="replyback_job",
        )

        # Boost bot - validated growth lever (200 views / 6 likes per cycle).
        # Bumped from 8h -> 6h since we know it works.
        log.info("Boost bot: retweeting own latest tweet every 6 hours.")
        scheduler.add_job(
            safe_run_boost_cycle,
            trigger=IntervalTrigger(hours=6),
            id="boost_job",
        )

        # Early-bird bot — slowed from 5 -> ~8min jittered (still inside the
        # 12-min freshness window for top-5-reply). Quiet hours skip.
        log.info("Early-bird bot: catching fresh mega-account tweets every ~8 min (jittered, quiet 1am-7am Paris).")
        scheduler.add_job(
            reschedule_and_early_bird,
            trigger=IntervalTrigger(minutes=early_bird_interval_minutes()),
            id="early_bird_job",
        )

        # Discovery bot - autonomously find new crypto/AI/bourse influencers
        log.info("Discover bot: searching for new influencers every 6 hours.")
        scheduler.add_job(
            safe_run_discovery_cycle,
            trigger=IntervalTrigger(hours=6),
            id="discover_job",
        )

        # Roast bot - slowed from 10 -> ~20min jittered. He tweets every ~minute
        # so we still catch plenty; URL dedup hard-caps to 1 per tweet. Quiet skip.
        log.info("Roast bot: replying to @pgm_pm tweets every ~20 min (jittered, quiet 1am-7am Paris).")
        scheduler.add_job(
            reschedule_and_roast,
            trigger=IntervalTrigger(minutes=roast_interval_minutes()),
            id="roast_pgm_job",
        )

        # Performance tracking
        def safe_evaluate():
            try:
                evaluate_and_learn()
            except Exception:
                log.error(f"[PERF] Evaluation failed: {traceback.format_exc()}")

        log.info("Performance bot: evaluating tweet performance every 2 hours.")
        scheduler.add_job(
            safe_evaluate,
            trigger=IntervalTrigger(hours=2),
            id="perf_job",
        )

        # Strategy agent — fully autonomous self-improvement. Reads engagement
        # log + uses tools (WebSearch, Read) to find new queries / accounts;
        # ADDS them to dynamic_queries.json and dynamic_accounts.json which
        # direct_reply merges with its static lists at runtime. Runs 4x/day.
        log.info("Strategy agent: autonomous self-improvement every 6 hours.")
        scheduler.add_job(
            safe_run_strategy_cycle,
            trigger=IntervalTrigger(hours=6),
            id="strategy_job",
        )

        # Quote-tweet bot — picks the most viral FR tweet in our niche and
        # quote-tweets it with a sharp meme observation. Cap 2/day (tiny on
        # purpose: this is a signal feature, not a volume feature).
        log.info("Quote-tweet bot: amplifying viral FR tweets every 4 hours.")
        scheduler.add_job(
            safe_run_quote_tweet_cycle,
            trigger=IntervalTrigger(hours=4),
            id="quote_tweet_job",
        )

    log.info("All systems go. Bot is running.")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("Bot stopped.")


if __name__ == "__main__":
    main()

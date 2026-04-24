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


def post_interval_minutes() -> int:
    """Cluster posts during peak engagement windows.
    Peak hours: 9-11am EST, 1-3pm EST (US tech workers scrolling).
    These windows get 3-5x more impressions than off-peak.
    Tightened intervals to push more news posts per day (user wants more news)."""
    hour = datetime.now(ZoneInfo("America/New_York")).hour
    if 23 <= hour or hour < 8:
        # Night: sleep like a human
        return random.randint(180, 300)
    elif 9 <= hour < 11:
        # PEAK: Morning window
        return random.randint(45, 75)
    elif 13 <= hour < 15:
        # PEAK: Afternoon window
        return random.randint(45, 75)
    elif 8 <= hour < 12:
        # Near-peak morning
        return random.randint(70, 110)
    elif 12 <= hour < 18:
        # Afternoon
        return random.randint(70, 110)
    else:
        # Evening: winding down
        return random.randint(110, 180)


def reply_interval_minutes() -> int:
    """Replies are the growth engine but too fast = shadow ban.
    Every 20 min = ~72 replies/day max. Enough to grow, not enough to get flagged."""
    return 20


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

    # --- REPLY BOT (primary growth engine) ---
    def reschedule_and_reply():
        safe_run_reply_cycle()
        next_min = reply_interval_minutes()
        hour = datetime.now(ZoneInfo("America/New_York")).hour
        log.info(f"[REPLY][EST {hour}:xx] Next reply scan in {next_min} minutes.")
        scheduler.reschedule_job(
            "reply_job",
            trigger=IntervalTrigger(minutes=next_min),
        )

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
        # Engage bot - follow and like AI accounts for reciprocity
        log.info("Engage bot: following + liking target accounts every 30 minutes.")
        scheduler.add_job(
            safe_run_engage_cycle,
            trigger=IntervalTrigger(minutes=30),
            id="engage_job",
        )

        # Notify bot - like replies on own tweets to build community
        log.info("Notify bot: liking replies on own tweets every 45 minutes.")
        scheduler.add_job(
            safe_run_notify_cycle,
            trigger=IntervalTrigger(minutes=45),
            id="notify_job",
        )

        # Direct reply bot - visits influencer profiles and replies to their tweets
        log.info("Direct reply bot: replying to influencer tweets every 15 minutes.")
        scheduler.add_job(
            safe_run_direct_reply_cycle,
            trigger=IntervalTrigger(minutes=15),
            id="direct_reply_job",
        )

        # Reply-back bot - reply to people who reply to our tweets (creates threads)
        log.info("Reply-back bot: replying to followers every 60 minutes.")
        scheduler.add_job(
            safe_run_replyback_cycle,
            trigger=IntervalTrigger(minutes=60),
            id="replyback_job",
        )

        # Boost bot - one self-retweet per day is enough
        log.info("Boost bot: retweeting own latest tweet every 8 hours.")
        scheduler.add_job(
            safe_run_boost_cycle,
            trigger=IntervalTrigger(hours=8),
            id="boost_job",
        )

        # Discovery bot - autonomously find new crypto/AI/bourse influencers
        log.info("Discover bot: searching for new influencers every 6 hours.")
        scheduler.add_job(
            safe_run_discovery_cycle,
            trigger=IntervalTrigger(hours=6),
            id="discover_job",
        )

        # Roast bot - sarcastic 1x reply per @pgm_pm tweet (anti-bot retort).
        # He tweets every ~minute, so check often. URL dedup hard-caps to 1 per
        # tweet, MAX_PER_CYCLE caps burst rate.
        log.info("Roast bot: sarcastically replying to @pgm_pm tweets every 10 minutes.")
        scheduler.add_job(
            safe_run_roast_pgm_cycle,
            trigger=IntervalTrigger(minutes=10),
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

    log.info("All systems go. Bot is running.")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("Bot stopped.")


if __name__ == "__main__":
    main()

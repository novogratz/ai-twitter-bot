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
from src.notify_bot import safe_run_notify_cycle, safe_run_boost_cycle
from src.performance import evaluate_and_learn


def post_interval_minutes() -> int:
    """Few posts per day, only bangers. ~3-5 total.
    Original posts from a small account get almost no organic reach.
    Only post when you have something genuinely sharp to say."""
    hour = datetime.now(ZoneInfo("America/New_York")).hour
    if 23 <= hour or hour < 8:
        # Don't post at night. Sleep like a human.
        return random.randint(240, 420)
    elif 8 <= hour < 12:
        # Morning: maybe one good post
        return random.randint(120, 200)
    elif 12 <= hour < 18:
        # Afternoon: peak hours, but still selective
        return random.randint(90, 160)
    else:
        # Evening: winding down
        return random.randint(150, 240)


def reply_interval_minutes() -> int:
    """Replies are the growth engine. Run frequently to catch viral tweets early.
    Being first on a big tweet = thousands of views."""
    return 5


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

    # Run reply bot FIRST - this is the growth engine
    if not args.post_only:
        log.info("Bot started! Scanning for viral tweets to reply to...")
        safe_run_reply_cycle()

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
        log.info("Engage bot: following + liking target accounts every 15 minutes.")
        scheduler.add_job(
            safe_run_engage_cycle,
            trigger=IntervalTrigger(minutes=15),
            id="engage_job",
        )

        # Notify bot - like replies on own tweets to build community
        log.info("Notify bot: liking replies on own tweets every 10 minutes.")
        scheduler.add_job(
            safe_run_notify_cycle,
            trigger=IntervalTrigger(minutes=10),
            id="notify_job",
        )

        # Boost bot - occasional self-retweet (not too often, looks spammy)
        log.info("Boost bot: retweeting own latest tweet every 3 hours.")
        scheduler.add_job(
            safe_run_boost_cycle,
            trigger=IntervalTrigger(hours=3),
            id="boost_job",
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

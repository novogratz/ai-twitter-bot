"""@kzer_ai Twitter bot - AI news, hot takes, and troll replies.

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
    """~1 post per hour during the day, less at night. ~18 posts/day."""
    hour = datetime.now(ZoneInfo("America/New_York")).hour
    if 23 <= hour or hour < 6:
        return random.randint(90, 150)
    elif 6 <= hour < 10:
        return random.randint(45, 70)
    elif 10 <= hour < 19:
        return random.randint(40, 65)
    else:
        return random.randint(55, 80)


def reply_interval_minutes() -> int:
    """5 min interval for quality replies."""
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

    # --- POST BOT ---
    def reschedule_and_post():
        safe_run_bot_cycle()
        next_min = post_interval_minutes()
        hour = datetime.now(ZoneInfo("America/New_York")).hour
        log.info(f"[POST][EST {hour}:xx] Next post in {next_min} minutes.")
        scheduler.reschedule_job(
            "post_job",
            trigger=IntervalTrigger(minutes=next_min),
        )

    # --- REPLY BOT ---
    def reschedule_and_reply():
        safe_run_reply_cycle()
        next_min = reply_interval_minutes()
        hour = datetime.now(ZoneInfo("America/New_York")).hour
        log.info(f"[REPLY][EST {hour}:xx] Next reply scan in {next_min} minutes.")
        scheduler.reschedule_job(
            "reply_job",
            trigger=IntervalTrigger(minutes=next_min),
        )

    # Run reply bot FIRST
    if not args.post_only:
        log.info("Bot started! Scanning for tweets to reply to first...")
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
        log.info("Engage bot: following + liking target accounts every 10 minutes.")
        scheduler.add_job(
            safe_run_engage_cycle,
            trigger=IntervalTrigger(minutes=10),
            id="engage_job",
        )

        log.info("Notify bot: liking replies on own tweets every 8 minutes.")
        scheduler.add_job(
            safe_run_notify_cycle,
            trigger=IntervalTrigger(minutes=8),
            id="notify_job",
        )

        log.info("Boost bot: retweeting own latest tweet every 45 minutes.")
        scheduler.add_job(
            safe_run_boost_cycle,
            trigger=IntervalTrigger(minutes=45),
            id="boost_job",
        )

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

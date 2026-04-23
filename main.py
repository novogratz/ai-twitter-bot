import random
from datetime import datetime
from zoneinfo import ZoneInfo
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger
from src.bot import safe_run_bot_cycle
from src.reply_bot import safe_run_reply_cycle


def post_interval_minutes() -> int:
    """Return post interval based on current EST hour."""
    hour = datetime.now(ZoneInfo("America/New_York")).hour
    if 23 <= hour or hour < 6:
        return random.randint(45, 75)
    elif 6 <= hour < 10:
        return random.randint(15, 20)
    elif 10 <= hour < 17:
        return 40
    elif 17 <= hour < 19:
        return 15
    else:
        return 40


if __name__ == "__main__":
    scheduler = BlockingScheduler()

    # --- POST BOT ---
    def reschedule_and_post():
        safe_run_bot_cycle()
        next_min = post_interval_minutes()
        hour = datetime.now(ZoneInfo("America/New_York")).hour
        print(f"\n[POST][EST {hour}:xx] Next post in {next_min} minutes.\n")
        scheduler.reschedule_job(
            "post_job",
            trigger=IntervalTrigger(minutes=next_min),
        )

    # --- REPLY BOT ---
    def run_reply():
        safe_run_reply_cycle()

    # Run reply bot FIRST - reply to latest tweets before posting new stuff
    print("Bot started! Scanning for tweets to reply to first...")
    safe_run_reply_cycle()

    # Then run first post
    print("\nNow posting first news tweet...")
    safe_run_bot_cycle()

    # Schedule posts
    first_post = post_interval_minutes()
    print(f"\nNext post in {first_post} minutes.")
    scheduler.add_job(
        reschedule_and_post,
        trigger=IntervalTrigger(minutes=first_post),
        id="post_job",
    )

    # Schedule replies every 10 minutes
    print("Reply bot scanning every 10 minutes.\n")
    scheduler.add_job(
        run_reply,
        trigger=IntervalTrigger(minutes=10),
        id="reply_job",
    )

    try:
        scheduler.start()
    except KeyboardInterrupt:
        print("Bot stopped.")

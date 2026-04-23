import random
from datetime import datetime
from zoneinfo import ZoneInfo
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger
from src.bot import safe_run_bot_cycle
from src.reply_bot import safe_run_reply_cycle
from src.engage_bot import safe_run_engage_cycle
from src.notify_bot import safe_run_notify_cycle


def post_interval_minutes() -> int:
    """~12 posts/day spread across the day. Post more during peak hours."""
    hour = datetime.now(ZoneInfo("America/New_York")).hour
    if 23 <= hour or hour < 6:
        # Night: skip most cycles
        return random.randint(180, 240)
    elif 6 <= hour < 10:
        # Morning peak
        return random.randint(60, 90)
    elif 10 <= hour < 17:
        # Daytime
        return random.randint(75, 120)
    elif 17 <= hour < 19:
        # Evening peak
        return random.randint(60, 90)
    else:
        # Late evening
        return random.randint(90, 120)


def reply_interval_minutes() -> int:
    """Fixed 2 min interval for replies."""
    return 2


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
    def reschedule_and_reply():
        safe_run_reply_cycle()
        next_min = reply_interval_minutes()
        hour = datetime.now(ZoneInfo("America/New_York")).hour
        print(f"[REPLY][EST {hour}:xx] Next reply scan in {next_min} minutes.")
        scheduler.reschedule_job(
            "reply_job",
            trigger=IntervalTrigger(minutes=next_min),
        )

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

    # Schedule replies with dynamic intervals
    first_reply = reply_interval_minutes()
    print(f"Reply bot: next scan in {first_reply} minutes.\n")
    scheduler.add_job(
        reschedule_and_reply,
        trigger=IntervalTrigger(minutes=first_reply),
        id="reply_job",
    )

    # Schedule engagement bot every 25 minutes
    print("Engage bot: liking target accounts every 25 minutes.")
    scheduler.add_job(
        safe_run_engage_cycle,
        trigger=IntervalTrigger(minutes=25),
        id="engage_job",
    )

    # Schedule notification farmer every 20 minutes
    print("Notify bot: liking replies on own tweets every 20 minutes.\n")
    scheduler.add_job(
        safe_run_notify_cycle,
        trigger=IntervalTrigger(minutes=20),
        id="notify_job",
    )

    try:
        scheduler.start()
    except KeyboardInterrupt:
        print("Bot stopped.")

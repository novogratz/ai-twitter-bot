import random
from datetime import datetime
from zoneinfo import ZoneInfo
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger
from src.bot import safe_run_bot_cycle
from src.reply_bot import safe_run_reply_cycle


def post_interval_minutes() -> int:
    """Return post interval based on current EST hour.
    11pm-6am:  45-75 min (night mode)
    6am-10am:  15-20 min (morning rush)
    10am-5pm:  40 min (midday)
    5pm-7pm:   15 min (evening rush)
    7pm-11pm:  40 min (wind down)
    """
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


def reply_interval_minutes() -> int:
    """Reply every 20-30 minutes during the day, slower at night."""
    hour = datetime.now(ZoneInfo("America/New_York")).hour
    if 23 <= hour or hour < 6:
        return random.randint(60, 90)
    else:
        return random.randint(20, 30)


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
        print(f"\n[REPLY][EST {hour}:xx] Next reply scan in {next_min} minutes.\n")
        scheduler.reschedule_job(
            "reply_job",
            trigger=IntervalTrigger(minutes=next_min),
        )

    print("Bot started! Running first post now...")
    safe_run_bot_cycle()

    # Schedule posts
    first_post = post_interval_minutes()
    print(f"\nNext post in {first_post} minutes.\n")
    scheduler.add_job(
        reschedule_and_post,
        trigger=IntervalTrigger(minutes=first_post),
        id="post_job",
    )

    # Schedule replies (start after 5 min offset so they don't overlap)
    first_reply = 5
    print(f"Reply bot starts in {first_reply} minutes.\n")
    scheduler.add_job(
        reschedule_and_reply,
        trigger=IntervalTrigger(minutes=first_reply),
        id="reply_job",
    )

    try:
        scheduler.start()
    except KeyboardInterrupt:
        print("Bot stopped.")

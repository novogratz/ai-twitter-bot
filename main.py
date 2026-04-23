import random
from datetime import datetime
from zoneinfo import ZoneInfo
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger
from src.bot import safe_run_bot_cycle


def random_interval_minutes() -> int:
    """Return interval based on current EST hour.
    11pm-6am:  45-75 min (night mode)
    6am-10am:  15-20 min (morning rush)
    10am-5pm:  40-40 min (midday)
    5pm-7pm:   15-15 min (evening rush)
    7pm-11pm:  40-40 min (wind down)
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


if __name__ == "__main__":
    scheduler = BlockingScheduler()

    def reschedule_and_run():
        safe_run_bot_cycle()
        next_minutes = random_interval_minutes()
        hour = datetime.now(ZoneInfo("America/New_York")).hour
        print(f"\n[EST {hour}:xx] Next tweet in {next_minutes} minutes.\n")
        scheduler.reschedule_job(
            "bot_job",
            trigger=IntervalTrigger(minutes=next_minutes),
        )

    print("Bot started! Running first tweet now...")
    safe_run_bot_cycle()

    first_interval = random_interval_minutes()
    print(f"\nNext tweet in {first_interval} minutes.\n")

    scheduler.add_job(
        reschedule_and_run,
        trigger=IntervalTrigger(minutes=first_interval),
        id="bot_job",
    )

    try:
        scheduler.start()
    except KeyboardInterrupt:
        print("Bot stopped.")

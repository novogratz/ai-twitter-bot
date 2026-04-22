import random
from datetime import datetime
from zoneinfo import ZoneInfo
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger
from src.bot import safe_run_bot_cycle


def random_interval_minutes() -> int:
    return random.randint(35, 45)


def is_peak_hour_est() -> bool:
    """Return True if current time is within peak EST engagement windows.
    Peak windows: 8-11am, 1-3pm, 6-9pm Eastern.
    """
    hour = datetime.now(ZoneInfo("America/New_York")).hour
    return 6 <= hour < 23


if __name__ == "__main__":
    scheduler = BlockingScheduler()

    def reschedule_and_run():
        if is_peak_hour_est():
            safe_run_bot_cycle()
        else:
            print("Outside peak EST hours - skipping this cycle.")
        next_minutes = random_interval_minutes()
        print(f"\nNext check in {next_minutes} minutes.\n")
        scheduler.reschedule_job(
            "bot_job",
            trigger=IntervalTrigger(minutes=next_minutes),
        )

    print("Bot started! Running first check now...")
    if is_peak_hour_est():
        safe_run_bot_cycle()
    else:
        print("Outside peak EST hours - skipping first cycle.")

    first_interval = random_interval_minutes()
    print(f"\nNext check in {first_interval} minutes.\n")

    scheduler.add_job(
        reschedule_and_run,
        trigger=IntervalTrigger(minutes=first_interval),
        id="bot_job",
    )

    try:
        scheduler.start()
    except KeyboardInterrupt:
        print("Bot stopped.")

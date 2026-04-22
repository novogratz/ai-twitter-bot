import random
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger
from src.bot import safe_run_bot_cycle


def random_interval_minutes() -> int:
    return 2


if __name__ == "__main__":
    scheduler = BlockingScheduler()

    def reschedule_and_run():
        safe_run_bot_cycle()
        next_minutes = random_interval_minutes()
        print(f"\nNext tweet in {next_minutes} minutes.\n")
        scheduler.reschedule_job(
            "bot_job",
            trigger=IntervalTrigger(minutes=next_minutes),
        )

    # Run immediately on start, then every 35-40 minutes
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

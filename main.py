import random
import os
from dotenv import load_dotenv
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger
from src.bot import safe_run_bot_cycle

load_dotenv()

REQUIRED_ENV_VARS = [
    "TWITTER_API_KEY",
    "TWITTER_API_SECRET",
    "TWITTER_ACCESS_TOKEN",
    "TWITTER_ACCESS_TOKEN_SECRET",
    "TWITTER_BEARER_TOKEN",
    "ANTHROPIC_API_KEY",
    "NEWS_API_KEY",
]


def check_env():
    missing = [v for v in REQUIRED_ENV_VARS if not os.environ.get(v)]
    if missing:
        raise EnvironmentError(
            f"Missing required environment variables: {', '.join(missing)}\n"
            "Copy .env.example to .env and fill in your credentials."
        )


def random_interval_minutes() -> int:
    """Pick a random interval between 15 and 20 minutes."""
    return random.randint(15, 20)


if __name__ == "__main__":
    check_env()

    scheduler = BlockingScheduler()

    def reschedule_and_run():
        """Post a tweet then reschedule at a new random interval."""
        safe_run_bot_cycle()
        # Reschedule with a new random delay
        next_minutes = random_interval_minutes()
        print(f"Next tweet in {next_minutes} minutes.")
        scheduler.reschedule_job(
            "bot_job",
            trigger=IntervalTrigger(minutes=next_minutes),
        )

    first_interval = random_interval_minutes()
    print(f"Bot started. First tweet in {first_interval} minutes.")

    scheduler.add_job(
        reschedule_and_run,
        trigger=IntervalTrigger(minutes=first_interval),
        id="bot_job",
    )

    try:
        scheduler.start()
    except KeyboardInterrupt:
        print("Bot stopped.")

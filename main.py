"""Run @TheAIShrink: thoughtful AI originals and active daytime conversations."""
import argparse
import fcntl
import json
import logging
import os
import signal
import threading

from src.core import settings

# Before any other project import: every module, and every model call, sees
# .env whichever module reads it first. A bad .env stops the start here.
settings.load()

from src.core import config
from src.guards.active_hours import BEDTIME, WAKE, awake_job, is_active, next_wake, window_label
from src.editorial.editorial_bot import SLOTS, TREND_SLOTS, open_startup_window, safe_run_editorial_cycle
from src.core.logger import log

_SINGLETON_LOCK_HANDLE = None


def _acquire_singleton_lock():
    global _SINGLETON_LOCK_HANDLE
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot.lock")
    handle = open(path, "a+")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise SystemExit("Another bot already holds bot.lock")
    handle.seek(0)
    handle.truncate()
    handle.write(str(os.getpid()))
    handle.flush()
    _SINGLETON_LOCK_HANDLE = handle


def build_scheduler(*, post_only=False, reply_only=False):
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.executors.pool import ThreadPoolExecutor
    from apscheduler.triggers.interval import IntervalTrigger
    from datetime import datetime, timedelta, timezone

    scheduler = BackgroundScheduler(
        timezone=config.BOT_TIMEZONE,
        executors={"default": ThreadPoolExecutor(12), "editorial": ThreadPoolExecutor(1)},
        job_defaults={"misfire_grace_time": 60, "coalesce": True, "max_instances": 1},
    )

    def add(fn, minutes, job_id, *, executor="default", first_seconds=None):
        options = {}
        if first_seconds is not None:
            options["next_run_time"] = datetime.now(timezone.utc) + timedelta(seconds=first_seconds)
        scheduler.add_job(awake_job(fn), trigger=IntervalTrigger(minutes=minutes),
                          id=job_id, executor=executor, **options)

    if not reply_only:
        # Polling retries only the current window. State survives restarts;
        # a dedicated worker prevents reply scans from starving originals.
        add(safe_run_editorial_cycle, 10, "editorial_job", executor="editorial", first_seconds=10)

    if not post_only:
        from src.replies.direct_reply import safe_run_direct_reply_cycle
        from src.replies.feed_sweeper_bot import safe_run_feed_sweep_cycle
        from src.replies.early_bird_bot import safe_run_early_bird_cycle
        from src.replies.notify_bot import safe_run_replyback_cycle, safe_run_notify_cycle
        from src.replies.debate_bot import safe_run_debate_cycle
        from src.replies.mega_watch_bot import safe_run_mega_watch_cycle
        from src.replies.first_hour_babysitter import safe_run_babysit_cycle

        add(safe_run_direct_reply_cycle, 2, "direct_reply_job", first_seconds=2)
        add(safe_run_feed_sweep_cycle, 8, "feed_sweep_job")
        add(safe_run_early_bird_cycle, 5, "early_bird_job")
        add(safe_run_replyback_cycle, 3, "replyback_job")
        add(safe_run_debate_cycle, 12, "debate_job")
        add(safe_run_mega_watch_cycle, 2, "mega_watch_job")
        add(safe_run_babysit_cycle, 5, "babysit_job")
        add(safe_run_notify_cycle, 20, "notify_job")
        if settings.get("ENABLE_REPLY_SEARCH"):
            from src.replies.reply_bot import safe_run_reply_cycle
            add(safe_run_reply_cycle, 3, "reply_job")

    if not post_only and not reply_only:
        from src.account.engage_bot import safe_run_engage_cycle
        from src.account.followback_bot import safe_run_followback_cycle
        from src.account.follow_engagers_bot import safe_run_follow_engagers_cycle
        from src.account.like_bot import safe_run_like_cycle
        from src.account.pin_bot import safe_run_pin_cycle
        from src.x.safari_hygiene import safe_run_session_refresh
        from src.account.follower_tracker_bot import safe_run_follower_tracker_cycle
        from src.editorial.reach_report import safe_run_reach_report

        add(safe_run_engage_cycle, 8, "engage_job")
        add(safe_run_followback_cycle, 20, "followback_job")
        add(safe_run_follow_engagers_cycle, 50, "follow_engagers_job")
        add(safe_run_like_cycle, 4, "like_job")
        add(safe_run_pin_cycle, 60, "pin_job")
        add(safe_run_session_refresh, 120, "session_refresh_job")
        add(safe_run_follower_tracker_cycle, 30, "follower_tracker_job")
        add(safe_run_reach_report, 60, "reach_report_job")
    return scheduler


def main():
    parser = argparse.ArgumentParser(description="AI editorial posts and uncapped daytime replies")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--post-only", action="store_true")
    mode.add_argument("--reply-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Show schedule and policy, then exit without browser/LLM calls")
    args = parser.parse_args()
    for warning in settings.startup_warnings():
        log.warning(f"[SETTINGS] {warning}")
    scheduler = build_scheduler(post_only=args.post_only, reply_only=args.reply_only)
    from src.core.llm_client import ignored_fallbacks, unknown_providers
    unknown = unknown_providers()
    for setting in unknown:
        log.error(f"[LLM] Unknown provider {setting}: every call it routes fails.")
    ignored = ignored_fallbacks()
    for note in ignored:
        log.error(f"[LLM] Fallback ignored: {note}. A call that fails there fails.")
    if args.dry_run:
        print(json.dumps({"timezone": config.BOT_TIMEZONE, "active": f"{WAKE:%H:%M}–{BEDTIME:%H:%M}",
                          "min_target_posts": config.MIN_TARGET_POSTS_PER_DAY,
                          "target_posts": config.TARGET_POSTS_PER_DAY,
                          "max_profile_posts": config.MAX_PROFILE_POSTS_PER_DAY,
                          "replies": "unlimited",
                          "quotes": 0, "reposts": 0, "slots": SLOTS,
                          "trend_slots": sorted(TREND_SLOTS),
                          "startup_post": "every start in waking hours, restarts included",
                          "unknown_llm_providers": unknown,
                          "ignored_llm_fallbacks": ignored,
                          "jobs": [job.id for job in scheduler.get_jobs()]}, indent=2, ensure_ascii=False))
        return

    _acquire_singleton_lock()
    if not args.reply_only:
        # The editorial job publishes it, after every restart too.
        open_startup_window()
    stop = threading.Event()

    def shutdown(signum, frame):
        from src.guards.active_hours import request_stop
        request_stop()
        stop.set()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
    scheduler.start(paused=True)
    was_active = None
    log.info(f"Bot started: at least three useful AI originals targeted (max eight); replies unlimited; active {window_label()}.")
    try:
        while not stop.is_set():
            active = is_active()
            if active != was_active:
                if active:
                    scheduler.resume()
                    log.info("[HOURS] Awake. Editorial posts and conversations resumed.")
                else:
                    scheduler.pause()
                    log.info("[HOURS] Asleep. Next wake: %s", next_wake().isoformat())
                was_active = active
            stop.wait(15)
    finally:
        scheduler.shutdown(wait=False)
        log.info("Bot stopped.")


if __name__ == "__main__":
    main()

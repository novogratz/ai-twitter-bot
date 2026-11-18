"""Run the Account BOT_ACCOUNT names: sourced Originals and active daytime conversations."""
import argparse
import fcntl
import json
import logging
import os
import signal
import threading
import uuid

from src.core import settings

# Before any other project import: every module, and every model call, sees
# .env whichever module reads it first. A bad .env stops the start here.
settings.load()

from src.core import account, config, health, state_store
from src.guards.active_hours import BEDTIME, WAKE, awake_job, break_until, is_active, next_wake, window_label
from src.editorial.editorial_bot import open_startup_window, run_editorial_cycle, slots, trend_slots
from src.core.logger import log

_SINGLETON_LOCK_HANDLE = None
_BOOT_REQUEST_ID = "boot:" + uuid.uuid4().hex


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


def build_scheduler(*, post_only=False, reply_only=False, startup_publications=False):
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.executors.pool import ThreadPoolExecutor
    from apscheduler.triggers.interval import IntervalTrigger
    from datetime import datetime, timedelta, timezone

    scheduler = BackgroundScheduler(
        timezone=config.BOT_TIMEZONE,
        executors={"default": ThreadPoolExecutor(12), "editorial": ThreadPoolExecutor(1), "news": ThreadPoolExecutor(1),
                   "video": ThreadPoolExecutor(1),
                   "watch": ThreadPoolExecutor(1), "watch_actions": ThreadPoolExecutor(1),
                   "watch_reply": ThreadPoolExecutor(1)},
        job_defaults={"misfire_grace_time": 60, "coalesce": True, "max_instances": 1},
    )

    def add(fn, minutes, job_id, *, executor="default", first_seconds=None):
        if job_id != "video_health_job":
            from src.video.startup import after_startup_video
            fn = after_startup_video(fn)
        options = {}
        if first_seconds is not None:
            options["next_run_time"] = datetime.now(timezone.utc) + timedelta(seconds=first_seconds)
        scheduler.add_job(awake_job(fn), trigger=IntervalTrigger(minutes=minutes),
                          id=job_id, executor=executor, **options)

    if not reply_only and settings.get("VIDEO_ENABLED"):
        from src.video.workers import health_job
        add(health.wrap_job(health_job, "video_health", safari_health=False), 2 / 60,
            "video_health_job", executor="video", first_seconds=2)
    elif not reply_only and not settings.get("NEWS_ENABLED"):
        # Polling retries only the current window. State survives restarts;
        # a dedicated worker prevents reply scans from starving originals.
        # Its failures are model timeouts, not Safari outages: kept out of
        # the Safari failure counter.
        add(health.wrap_job(run_editorial_cycle, "editorial", safari_health=False), 10,
            "editorial_job", executor="editorial", first_seconds=10)

    if not reply_only and settings.get("NEWS_ENABLED"):
        from src.news.pipeline import retry_pending, run as run_news
        # Public discovery may run overnight. Its Safari write chokepoint owns
        # waking hours and the video-first hold, just like every other write.
        scheduler.add_job(run_news, trigger=IntervalTrigger(hours=1, timezone=config.BOT_TIMEZONE),
                          id="news_job", executor="news", next_run_time=datetime.now(timezone.utc) + timedelta(seconds=15))
        # Delivery deferrals need not wait another hour. The same one-thread
        # executor and durable run lock serialize this with discovery.
        scheduler.add_job(retry_pending, trigger=IntervalTrigger(minutes=1, timezone=config.BOT_TIMEZONE),
                          id="news_delivery_job", executor="news", **({"next_run_time": datetime.now(timezone.utc) + timedelta(seconds=1)}
                              if startup_publications else {}))

    if not post_only:
        from src.replies.direct_reply import run_direct_reply_cycle
        from src.replies.feed_sweeper_bot import run_feed_sweep_cycle
        from src.replies.early_bird_bot import run_early_bird_cycle
        from src.replies.notify_bot import run_replyback_cycle, run_notify_cycle
        from src.replies.debate_bot import run_debate_cycle
        from src.replies.mega_watch_bot import run_mega_watch_cycle
        from src.replies.first_hour_babysitter import run_babysit_cycle
        from src.core.reply_feedback import run_reply_report

        add(health.wrap_job(run_direct_reply_cycle, "direct_reply"), 2, "direct_reply_job", first_seconds=2)
        add(health.wrap_job(run_feed_sweep_cycle, "feed_sweep"), 8, "feed_sweep_job")
        add(health.wrap_job(run_reply_report, "reply_report", safari_health=False), 20, "reply_report_job")
        if account.current().auto_engage_handles:
            from src.replies.priority_watch import (
                run_priority_watch_cycle, run_priority_actions_cycle, run_priority_reply_cycle)
            add(health.wrap_job(run_priority_watch_cycle, "priority_watch"),
                settings.get("PRIORITY_WATCH_INTERVAL_SECONDS") / 60,
                "priority_watch_job", executor="watch", first_seconds=1)
            add(health.wrap_job(run_priority_actions_cycle, "priority_actions"),
                settings.get("PRIORITY_WATCH_DISPATCH_SECONDS") / 60,
                "priority_actions_job", executor="watch_actions", first_seconds=2)
            add(health.wrap_job(run_priority_reply_cycle, "priority_reply"),
                settings.get("PRIORITY_WATCH_DISPATCH_SECONDS") / 60,
                "priority_reply_job", executor="watch_reply", first_seconds=2)
        add(health.wrap_job(run_early_bird_cycle, "early_bird"), 5, "early_bird_job")
        if not account.current().standalone_replies_only:
            add(health.wrap_job(run_replyback_cycle, "replyback"), 3, "replyback_job")
            add(health.wrap_job(run_debate_cycle, "debate"), 12, "debate_job")
        add(health.wrap_job(run_mega_watch_cycle, "mega_watch"), 2, "mega_watch_job")
        if not account.current().standalone_replies_only:
            add(health.wrap_job(run_babysit_cycle, "babysitter"), 5, "babysit_job")
        add(health.wrap_job(run_notify_cycle, "notify"), 20, "notify_job")
        if settings.get("ENABLE_REPLY_SEARCH"):
            from src.replies.reply_bot import run_reply_cycle
            add(health.wrap_job(run_reply_cycle, "reply"), 3, "reply_job")

    if not post_only and not reply_only:
        from src.account.engage_bot import safe_run_engage_cycle
        from src.account.followback_bot import safe_run_followback_cycle
        from src.account.follow_engagers_bot import safe_run_follow_engagers_cycle
        from src.account.like_bot import safe_run_like_cycle
        from src.account.pin_bot import safe_run_pin_cycle
        from src.x.safari_hygiene import safe_run_session_refresh
        from src.account.follower_tracker_bot import safe_run_follower_tracker_cycle
        from src.editorial.reach_report import run_reach_report

        add(safe_run_engage_cycle, 8, "engage_job")
        add(safe_run_followback_cycle, 20, "followback_job")
        add(safe_run_follow_engagers_cycle, 50, "follow_engagers_job")
        add(safe_run_like_cycle, 4, "like_job")
        add(safe_run_pin_cycle, 60, "pin_job")
        add(safe_run_session_refresh, 120, "session_refresh_job")
        add(safe_run_follower_tracker_cycle, 30, "follower_tracker_job")
        add(health.wrap_job(run_reach_report, "reach_report", safari_health=False), 60, "reach_report_job")
    return scheduler


def main():
    parser = argparse.ArgumentParser(description="Sourced editorial posts and uncapped daytime replies")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--post-only", action="store_true")
    mode.add_argument("--reply-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Show schedule and policy, then exit without browser/LLM calls")
    parser.add_argument("--startup-publications", action="store_true",
                        help="Request verified startup news and video; prioritize existing approved drafts, preserving all gates")
    parser.add_argument("--video", nargs=argparse.REMAINDER, help="Video administration (same as bin/video.py)")
    parser.add_argument("--news", nargs=argparse.REMAINDER, help="Verified news commands (same as bin/news.py)")
    args = parser.parse_args()
    if args.news is not None:
        from src.news.cli import main as news_main
        return news_main((["--dry-run"] if args.dry_run else []) + args.news)
    if args.video is not None:
        from src.video.cli import main as video_main
        return video_main((["--dry-run"] if args.dry_run else []) + args.video)
    try:
        state_store.require_migrated()
    except state_store.Unmigrated as exc:
        # Read as empty, a state file left behind would reset today's ceiling.
        log.error(f"[STATE] Refusing to start: {exc}.")
        raise SystemExit(f"Refusing to start: {exc}.")
    for warning in settings.startup_warnings():
        log.warning(f"[SETTINGS] {warning}")
    scheduler = build_scheduler(post_only=args.post_only, reply_only=args.reply_only,
                                startup_publications=args.startup_publications)
    from src.core.llm_client import ignored_fallbacks, unknown_providers
    unknown = unknown_providers()
    for setting in unknown:
        log.error(f"[LLM] Unknown provider {setting}: every call it routes fails.")
    ignored = ignored_fallbacks()
    for note in ignored:
        log.error(f"[LLM] Fallback ignored: {note}. A call that fails there fails.")
    min_target, target = config.post_targets()
    if args.dry_run:
        from src.video.startup import waiting_reason
        from src.video.config import load as video_config
        from src.video.schedule import clocks as video_clocks
        video_cfg = video_config() if settings.get("VIDEO_ENABLED") else None
        video_slots = len(video_clocks(video_cfg)) if video_cfg else 0
        print(json.dumps({"timezone": config.BOT_TIMEZONE, "active": f"{WAKE:%H:%M}–{BEDTIME:%H:%M}",
                          "min_target_posts": (0 if video_cfg.ultra_bangers_only else video_slots) if video_cfg else (0 if settings.get("NEWS_ENABLED") else min_target),
                          "target_posts": (0 if video_cfg.ultra_bangers_only else video_slots) if video_cfg else (0 if settings.get("NEWS_ENABLED") else target),
                          "max_profile_posts": (video_slots + 1 + (config.posts_ceiling() if settings.get("NEWS_ENABLED") else 0)
                                                if settings.get("VIDEO_ENABLED") else config.posts_ceiling()),
                          "replies": "unlimited",
                          "reply_volume_boost_date": settings.get("REPLY_VOLUME_BOOST_DATE"),
                          "reply_discovery_generation_budgets": {
                              name: settings.reply_budget(name) for name in settings.REPLY_BUDGET_NAMES},
                          "advisory_reply_targets": [settings.get("REPLY_DAILY_TARGET_MIN"),
                                                     settings.get("REPLY_DAILY_TARGET_MAX")],
                          "editorial_route": "reply" if account.current().editorial.use_reply_route else "original",
                          "news": {"enabled": settings.get("NEWS_ENABLED"), "hourly": True,
                                   "automatic_safari": settings.get("NEWS_AUTO_PUBLISH"), "email": False},
                          "startup_publications": args.startup_publications and not args.reply_only,
                          "quotes": 0,
                          "reposts": "watched authors only" if account.current().auto_engage_handles and not settings.get("VIDEO_ENABLED") else 0,
                          "auto_engage_handles": list(account.current().auto_engage_handles),
                          "slots": _main_slots(),
                          "trend_slots": [] if settings.get("VIDEO_ENABLED") or settings.get("NEWS_ENABLED") else sorted(trend_slots()),
                          "startup_post": (("automatic video request on start; at most one extra per Toronto day"
                                            if video_cfg.startup_on_boot else "explicit persistent video activation only")
                                           if video_cfg else ("none; hourly news discovery" if settings.get("NEWS_ENABLED")
                                                              else "every start in waking hours, restarts included")),
                          "startup_interactions_held": bool(waiting_reason()),
                          "unknown_llm_providers": unknown,
                          "ignored_llm_fallbacks": ignored,
                          "bounded_settings": settings.bounded(),
                          "settings_warnings": settings.startup_warnings(),
                          "jobs": [job.id for job in scheduler.get_jobs()]}, indent=2, ensure_ascii=False))
        return

    _acquire_singleton_lock()
    state_store.ensure_root()
    if not args.reply_only and not settings.get("VIDEO_ENABLED") and not settings.get("NEWS_ENABLED"):
        # The editorial job publishes it, after every restart too.
        open_startup_window()
    stop = threading.Event()
    from src.video.workers import Supervisor
    video_supervisor = Supervisor() if settings.get("VIDEO_ENABLED") and not args.reply_only else None
    if args.startup_publications and not args.reply_only:
        _request_startup_news()
    if video_supervisor:
        _request_startup_video(retry_expired=args.startup_publications)

    def shutdown(signum, frame):
        from src.guards.active_hours import request_stop
        request_stop()
        stop.set()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
    scheduler.start(paused=True)
    was_active = None
    was_startup_held = None
    if settings.get("VIDEO_ENABLED"):
        from src.video.config import load as video_config
        from src.video.schedule import clocks as video_clocks
        cfg = video_config()
        log.info("Bot started: %s video opportunities; ultra-only=%s; automatic startup=%s; news=%s; transport=%s; replies unlimited; active %s.",
                 len(video_clocks(cfg)), cfg.ultra_bangers_only, cfg.startup_on_boot,
                 settings.get("NEWS_ENABLED"), cfg.publishing_transport, window_label())
    elif settings.get("NEWS_ENABLED") and not args.reply_only:
        log.info("Bot started: hourly verified news, automatic Safari=%s; replies active %s.",
                 settings.get("NEWS_AUTO_PUBLISH"), window_label())
    else:
        log.info(f"Bot started: at least {min_target} useful {account.current().domain} originals targeted "
                 f"(max {config.posts_ceiling()}); replies unlimited; active {window_label()}.")
    log.info("[REPLY] Discovery/generation budgets: %s; boost date: %s (Toronto).",
             {name: settings.reply_budget(name) for name in settings.REPLY_BUDGET_NAMES},
             settings.get("REPLY_VOLUME_BOOST_DATE") or "disabled")
    try:
        while not stop.is_set():
            from src.video.startup import waiting_reason
            startup_held = bool(waiting_reason())
            if startup_held != was_startup_held:
                if startup_held:
                    log.info("[VIDEO-FIRST] Interactions held until the startup video is confirmed.")
                elif was_startup_held:
                    log.info("[VIDEO-FIRST] Startup hold released; normal interaction jobs may resume.")
                was_startup_held = startup_held
            if settings.get("VIDEO_ENABLED"):
                from src.video.workers import record_main_mode
                try:
                    record_main_mode()
                except Exception as exc:
                    log.warning("[VIDEO] Main-mode heartbeat failed (%s).", type(exc).__name__)
            if video_supervisor:
                try:
                    video_supervisor.tick()
                except Exception as exc:
                    log.warning("[VIDEO] Supervisor failed (%s); reply scheduler continues.", type(exc).__name__)
            pause_end = break_until()
            active = is_active() and pause_end is None
            if active != was_active:
                if active:
                    scheduler.resume()
                    if startup_held:
                        log.info("[HOURS] Awake. Video preparation active; interactions held for the startup video.")
                    else:
                        log.info("[HOURS] Awake. Editorial posts and conversations resumed.")
                else:
                    # All interaction jobs still have awake_job guards. Keep
                    # only the public news reader running during the night.
                    if settings.get("NEWS_ENABLED") and not args.reply_only:
                        scheduler.resume()
                    else:
                        scheduler.pause()
                    if pause_end is not None:
                        log.info("[BREAK] Paused until %s.", pause_end.isoformat())
                    else:
                        log.info("[HOURS] Asleep. Next wake: %s", next_wake().isoformat())
                was_active = active
            stop.wait(15)
    finally:
        if video_supervisor:
            video_supervisor.stop()
        scheduler.shutdown(wait=False)
        log.info("Bot stopped.")


def _request_startup_news():
    from src.news import startup
    from src.news.store import Store
    import time
    if not settings.get("NEWS_ENABLED") or not settings.get("NEWS_AUTO_PUBLISH") or config.dry_run():
        return None
    intent = startup.request(Store(), _BOOT_REQUEST_ID, time.time())
    log.info("[STARTUP] News request %s: %s; approved outbox checked first, otherwise fresh verification runs.",
             intent["request_id"], intent["state"])
    return intent


def _request_startup_video(*, retry_expired=False):
    """Record the configured boot request; the separate publisher performs it."""
    from src.video import config as video_config, publisher, schedule
    from src.video.store import Store
    try:
        cfg = video_config.load()
        if not cfg.startup_on_boot or not video_config.live():
            return None
        store = Store()
        if store.meta("paused", True) or store.meta("shutdown", False):
            log.warning("[VIDEO] Startup publication paused by video controls.")
            return None
        now = schedule.utc_now()
        # Expire an old unfinished request before asking for today's one;
        # reserved/uncertain sends remain claimed by their original request.
        publisher.tick_calendar(store, now, cfg)
        request_id = "boot:" + schedule.local(now).date().isoformat()
        request = publisher.request_startup(store, request_id, now, cfg, explicit_live=True, retry_expired=retry_expired)
        if request:
            log.info("[VIDEO] Startup request %s: %s; Reply workers continue independently.",
                     request["id"], request["state"])
        return request
    except Exception as exc:
        log.warning("[VIDEO] Startup request failed (%s); Reply workers continue.", type(exc).__name__)
        return None


def _main_slots():
    if settings.get("VIDEO_ENABLED"):
        from src.video.config import load
        from src.video.schedule import clocks
        return list(clocks(load()))
    if settings.get("NEWS_ENABLED"):
        return []
    return slots()


if __name__ == "__main__":
    main()

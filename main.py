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
from src.guards.active_hours import BEDTIME, WAKE, awake_job, break_until, is_active, may_reply, next_wake, window_label
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
    from apscheduler.triggers.cron import CronTrigger
    from datetime import datetime, timedelta, timezone

    scheduler = BackgroundScheduler(
        timezone=config.BOT_TIMEZONE,
        executors={"default": ThreadPoolExecutor(12), "editorial": ThreadPoolExecutor(1), "news": ThreadPoolExecutor(1),
                   "video": ThreadPoolExecutor(1),
                   "watch": ThreadPoolExecutor(1), "watch_actions": ThreadPoolExecutor(1),
                   "watch_reply": ThreadPoolExecutor(1), "quotes": ThreadPoolExecutor(1),
                   "self_reposts": ThreadPoolExecutor(1), "memes": ThreadPoolExecutor(1),
                   "drafts": ThreadPoolExecutor(1)},
        job_defaults={"misfire_grace_time": 60, "coalesce": True, "max_instances": 1},
    )
    if settings.get("REPLY_MANUAL_DISCOVERY") and not post_only:
        from src.replies.review import discover_and_prepare
        scheduler.add_job(awake_job(health.wrap_job(discover_and_prepare, "reply_draft")),
                          trigger=CronTrigger(hour="5,10,15,20", minute=0, timezone=config.BOT_TIMEZONE),
                          id="reply_draft_job", executor="drafts")
    if settings.get("REPLY_REVIEW_ONLY"):
        return scheduler
    if settings.get("REPLY_INVITED_ONLY"):
        from src.replies.help_requests import run_help_cycle
        from src.video import config as video_config
        if video_config.scheduled():  # a video is a post: --post-only keeps it, without Replies
            # 2026-11-23: videos again beside restricted Replies (VIDEO_WITH_REPLIES).
            # Same single publisher job; no editorial, news or startup hold here.
            from src.video.workers import health_job
            scheduler.add_job(awake_job(health.wrap_job(health_job, "video_health", safari_health=False)),
                              trigger=IntervalTrigger(seconds=2), id="video_health_job", executor="video",
                              next_run_time=datetime.now(timezone.utc) + timedelta(seconds=2))
        if not post_only:
            if settings.get("REPLY_BROAD_DISCOVERY"):
                from src.replies.direct_reply import run_direct_reply_cycle
                from src.replies.feed_sweeper_bot import run_feed_sweep_cycle
                from src.replies.help_requests import read_opt_out_mentions
                for_you_first = settings.get("REPLY_FOR_YOU_FIRST")
                direct_seconds = settings.get("DIRECT_REPLY_INTERVAL_MINUTES") * 60 if for_you_first else 120
                ordinary = () if settings.get("REPLY_MANUAL_ORDINARY") else (
                        (run_direct_reply_cycle, "direct_reply", direct_seconds, direct_seconds if for_you_first else 2),
                        (run_feed_sweep_cycle, "feed_sweep", settings.get("FEED_SWEEP_INTERVAL_MINUTES") * 60,
                         2 if for_you_first else 10))
                if for_you_first:
                    ordinary = ordinary[::-1]
                for fn, name, seconds, first in (*ordinary, (read_opt_out_mentions, "opt_out_mentions", 600, 1)):
                    scheduler.add_job(awake_job(health.wrap_job(fn, name), reply=True),
                                      trigger=IntervalTrigger(seconds=seconds), id=name + "_job",
                                      next_run_time=datetime.now(timezone.utc) + timedelta(seconds=first))
            elif not settings.get("REPLY_MANUAL_ORDINARY"):
                scheduler.add_job(awake_job(health.wrap_job(run_help_cycle, "invited_help"), reply=True),
                                  trigger=IntervalTrigger(minutes=3), id="curated_reply_job" if settings.get("REPLY_CURATED_MODE") else "invited_help_job",
                                  next_run_time=datetime.now(timezone.utc) + timedelta(seconds=2))
            if account.current().thank_commenters and not settings.get("REPLY_MANUAL_ORDINARY"):
                # Operator, 2026-11-25: one short Reply to each person who comments on our posts.
                from src.replies.commenter_thanks import run_thanks_cycle
                scheduler.add_job(awake_job(health.wrap_job(run_thanks_cycle, "commenter_thanks"), reply=True),
                                  trigger=IntervalTrigger(minutes=1), id="commenter_thanks_job",
                                  next_run_time=datetime.now(timezone.utc) + timedelta(seconds=45))
            if settings.get("REPLY_CURATED_MODE") and not reply_only and account.current().auto_engage_handles:
                from src.replies.priority_watch import run_priority_watch_cycle, run_priority_actions_cycle
                from src.replies.curated_reposts import run_cycle as run_curated_reposts
                broad = settings.get("REPLY_BROAD_DISCOVERY")
                dispatch_seconds = settings.get("PRIORITY_WATCH_DISPATCH_SECONDS")
                for fn, name, seconds, executor, first in (
                    (run_priority_watch_cycle, "priority_watch", settings.get("PRIORITY_WATCH_INTERVAL_SECONDS"), "watch", 1),
                    (run_priority_actions_cycle, "priority_actions", dispatch_seconds, "watch_actions", 2),
                    (run_curated_reposts, "curated_repost", dispatch_seconds if broad else 1800, "quotes", 2 if broad else 90)):
                    scheduler.add_job(awake_job(health.wrap_job(fn, name)),
                                      trigger=IntervalTrigger(seconds=seconds), id=name + "_job", executor=executor,
                                      next_run_time=datetime.now(timezone.utc) + timedelta(seconds=first))
                if broad and set(account.current().auto_engage_handles) - set(account.current().reply_excluded_handles):
                    from src.replies.priority_watch import run_priority_reply_cycle
                    scheduler.add_job(awake_job(health.wrap_job(run_priority_reply_cycle, "priority_reply"), reply=True),
                                      trigger=IntervalTrigger(seconds=dispatch_seconds),
                                      id="priority_reply_job", executor="watch_reply",
                                      next_run_time=datetime.now(timezone.utc) + timedelta(seconds=2))
        return scheduler

    reply_jobs = {"direct_reply_job", "feed_sweep_job", "priority_watch_job", "priority_reply_job",
                  "early_bird_job", "replyback_job", "debate_job", "mega_watch_job",
                  "babysit_job", "notify_job", "reply_job", "commenter_thanks_job"}

    def add(fn, minutes, job_id, *, executor="default", first_seconds=None):
        if job_id != "video_health_job":
            from src.video.startup import after_startup_video
            fn = after_startup_video(fn)
        options = {}
        if first_seconds is not None:
            options["next_run_time"] = datetime.now(timezone.utc) + timedelta(seconds=first_seconds)
        scheduler.add_job(awake_job(fn, reply=job_id in reply_jobs), trigger=IntervalTrigger(minutes=minutes),
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
        add(health.wrap_job(run_feed_sweep_cycle, "feed_sweep"), settings.get("FEED_SWEEP_INTERVAL_MINUTES"),
            "feed_sweep_job", first_seconds=10)
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
            if set(account.current().auto_engage_handles) - set(account.current().reply_excluded_handles):
                add(health.wrap_job(run_priority_reply_cycle, "priority_reply"),
                    settings.get("PRIORITY_WATCH_DISPATCH_SECONDS") / 60,
                    "priority_reply_job", executor="watch_reply", first_seconds=2)
            if account.current().priority_quotes_enabled:
                from src.replies.priority_quotes import run_priority_quote_cycle
                add(health.wrap_job(run_priority_quote_cycle, "priority_quote", safari_health=False), 30,
                    "priority_quote_job", executor="quotes", first_seconds=90)
        add(health.wrap_job(run_early_bird_cycle, "early_bird"), 5, "early_bird_job")
        if not account.current().standalone_replies_only:
            add(health.wrap_job(run_replyback_cycle, "replyback"), 3, "replyback_job")
            add(health.wrap_job(run_debate_cycle, "debate"), 12, "debate_job")
        add(health.wrap_job(run_mega_watch_cycle, "mega_watch"), 2, "mega_watch_job")
        if account.current().thank_commenters:
            from src.replies.commenter_thanks import run_thanks_cycle
            add(health.wrap_job(run_thanks_cycle, "commenter_thanks"), 1, "commenter_thanks_job", first_seconds=45)
        if not account.current().standalone_replies_only:
            add(health.wrap_job(run_babysit_cycle, "babysitter"), 5, "babysit_job")
        add(health.wrap_job(run_notify_cycle, "notify"), 20, "notify_job")
        if settings.get("ENABLE_REPLY_SEARCH"):
            from src.replies.reply_bot import run_reply_cycle
            add(health.wrap_job(run_reply_cycle, "reply"), 3, "reply_job")

    if not reply_only and settings.get("MEME_REPOST_ENABLED"):
        from src.account.meme_repost_bot import run_meme_repost_cycle
        add(health.wrap_job(run_meme_repost_cycle, "meme_repost", safari_health=False), 5,
            "meme_repost_job", executor="memes", first_seconds=30)

    if not reply_only and account.current().self_reposts_enabled:
        from src.account.self_repost_bot import run_self_repost_cycle, run_self_repost_discovery
        add(health.wrap_job(run_self_repost_cycle, "self_repost"), 2 / 60,
            "self_repost_job", executor="self_reposts", first_seconds=2)
        add(health.wrap_job(run_self_repost_discovery, "self_repost_discovery"), 10,
            "self_repost_discovery_job", first_seconds=30)

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


def _broad_discovery_description():
    if settings.get("REPLY_FOR_YOU_FIRST"):
        interval = settings.get("FEED_SWEEP_INTERVAL_MINUTES")
        return (f"For You first every {interval} minute{'s' if interval != 1 else ''}; "
                f"Following every {settings.get('FEED_FOLLOWING_EVERY_CYCLES')} cycles after For You replies; "
                f"secondary Latest searches every {settings.get('DIRECT_REPLY_INTERVAL_MINUTES')} minutes, "
                "starting after that interval; "
                f"sources at most {min(60, settings.get('DIRECT_REPLY_MAX_AGE_MINUTES'))} minutes old; "
                "full source before drafting; no API")
    return ("rotating major-author, artist, Top and Latest searches plus both Home feeds; "
            "full source before drafting; no API")


def _ordinary_major_author_priority():
    return settings.get("REPLY_PRIORITIZE_LARGE_ACCOUNTS") and not (
        settings.get("REPLY_BROAD_DISCOVERY") and settings.get("REPLY_FOR_YOU_FIRST"))


def main():
    parser = argparse.ArgumentParser(description="Sourced editorial posts and daily-capped Replies")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--post-only", action="store_true")
    mode.add_argument("--reply-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Show schedule and policy, then exit without browser/LLM calls")
    parser.add_argument("--startup-publications", action="store_true",
                        help="Request verified startup news and video; prioritize existing approved drafts, preserving all gates")
    parser.add_argument("--video", nargs=argparse.REMAINDER, help="Video administration (same as bin/video.py)")
    parser.add_argument("--news", nargs=argparse.REMAINDER, help="Verified news commands (same as bin/news.py)")
    parser.add_argument("--reply-review", nargs=argparse.REMAINDER,
                        help="Local Reply inbox: import, prepare, list, dismiss, posted or opt-out; never posts")
    args = parser.parse_args()
    if settings.get("POST_ONLY") and not args.reply_only:
        # A launchd watchdog started the full bot over the Operator's videos-only choice (2026-11-24).
        args.post_only = True
    if args.reply_review is not None:
        if args.dry_run:
            parser.error("Use --dry-run on its own for policy; --reply-review commands manage the local inbox")
        from src.replies import review
        return review.main(args.reply_review)
    if settings.get("REPLY_REVIEW_ONLY") and args.video is None and args.news is None:
        from src.replies import review
        if args.dry_run:
            discovery = settings.get("REPLY_MANUAL_DISCOVERY")
            plan = review.planning_capacity()
            print(json.dumps({"mode": "manual_reply_review", "x_writes": False,
                              "browser_discovery": discovery,
                              "jobs": [job.id for job in build_scheduler(post_only=args.post_only).get_jobs()],
                              "daily_draft_limit": plan["manual_draft_limit"],
                              "daily_advisory_target": plan["target"], "advisory_reply_targets": [plan["minimum"], plan["maximum"]],
                              "workload_boost": {"active": plan["boost_active"], "starts_on": plan["boost_start"],
                                                 "expires_on": plan["boost_until"]},
                              "draft_sessions": list(review.SESSION_TIMES) if discovery else [],
                              "draft_session_limit": plan["session_limit"] if discovery else None,
                              "priority": "grounded creative and technical conversations; specific, useful, accurate, natural",
                              "inbox": os.fspath(review.REPORT)}, indent=2))
            return
        if not settings.get("REPLY_MANUAL_DISCOVERY"):
            state_store.require_migrated()
            def stop_review(signum, frame):
                from src.guards.active_hours import request_stop
                request_stop()
            signal.signal(signal.SIGTERM, stop_review)
            signal.signal(signal.SIGINT, stop_review)
            return review.main(["prepare"])
    if args.news is not None:
        from src.news.cli import main as news_main
        return news_main((["--dry-run"] if args.dry_run else []) + args.news)
    if args.video is not None:
        from src.video.cli import main as video_main
        return video_main((["--dry-run"] if args.dry_run else []) + args.video)
    scheduler_reply_only = args.reply_only
    if settings.get("REPLY_INVITED_ONLY") or settings.get("REPLY_REVIEW_ONLY"):
        args.reply_only = True
        args.startup_publications = False
    try:
        state_store.require_migrated()
    except state_store.Unmigrated as exc:
        # Read as empty, a state file left behind would reset today's ceiling.
        log.error(f"[STATE] Refusing to start: {exc}.")
        raise SystemExit(f"Refusing to start: {exc}.")
    for warning in settings.startup_warnings():
        log.warning(f"[SETTINGS] {warning}")
    scheduler = build_scheduler(post_only=args.post_only,
                                reply_only=scheduler_reply_only if settings.get("REPLY_CURATED_MODE") else args.reply_only,
                                startup_publications=args.startup_publications)
    if args.dry_run and settings.get("REPLY_CURATED_MODE"):
        from src.guards import reply_budget, reply_selection, watch_curation
        from src.replies import review
        broad = reply_selection.broad()
        manual_ordinary = settings.get("REPLY_MANUAL_ORDINARY")
        plan = review.planning_capacity()
        print(json.dumps({"mode": "manual_ordinary_and_automatic_watched" if manual_ordinary else "broad_artist_and_technical" if broad else "curated_artist_and_technical",
            "manual_review_required": "ordinary Replies" if manual_ordinary else False,
            "manual_discovery": settings.get("REPLY_MANUAL_DISCOVERY"),
            "maximum_replies_per_day": reply_budget.ceiling(),
            "advisory_reply_targets": [plan["minimum"], plan["maximum"]],
            "normal_advisory_reply_targets": [settings.get("REPLY_DAILY_TARGET_MIN"), settings.get("REPLY_DAILY_TARGET_MAX")],
            "workload_boost": {"active": plan["boost_active"], "starts_on": plan["boost_start"], "expires_on": plan["boost_until"]},
            "includes_uncertain_submissions": True, "maximum_per_author_per_day": 1,
            "minimum_followers": None if broad else settings.get("REPLY_MIN_FOLLOWERS"),
            "large_account_priority": _ordinary_major_author_priority(),
            "minimum_parent_likes": reply_selection.minimum_likes(),
            "maximum_reply_characters": min(140, settings.get("REPLY_SHORT_MAX_CHARS")),
            "maximum_reply_words": 24, "maximum_reply_sentences": 1,
            "artist_limits": {"characters": min(140 if broad else 90, settings.get("REPLY_SHORT_MAX_CHARS")),
                              "words": 24 if broad else 12, "sentences": 1,
                              "visual_review_required": not broad, "unseen_media_claims_allowed": False},
            "video_scheduler": {"scheduled": __import__("src.video.config", fromlist=["x"]).scheduled(),
                                "live": __import__("src.video.config", fromlist=["x"]).live()},
            "minimum_seconds_between_replies": max(8 if broad else 600, settings.get("MIN_SECONDS_BETWEEN_REPLIES")),
            "reply_jitter_seconds": settings.get("REPLY_JITTER_SECONDS"),
            "hearts": "artist and warm share replies; one 👍 allowed; at least two intervening replies between hearts",
            "discovery": "four read-only draft sessions; fresh outside-circle creative and technical conversations, complete incoming external-thread context; manual posting" if manual_ordinary else _broad_discovery_description() if broad else "two artist searches per technical search; mentions every fifth turn; no API",
            "artist_queries": list(account.current().searches.artist_videos),
            "confirmed_parent_like_required": settings.get("REPLY_REQUIRE_PARENT_LIKE"),
            "likes": "admitted Reply parents and verified new watched-author originals across topics" if settings.get("REPLY_REQUIRE_PARENT_LIKE") and watch_curation.independent_actions() else "verified new watched-author originals only",
            "reposts": settings.get("CURATED_WATCH_REPOSTS_PER_DAY"),
            "watched_repost_scope": "verified new watched-author originals across topics" if watch_curation.independent_actions() else "selectively reviewed watched originals",
            "watched_replies": settings.get("CURATED_WATCH_REPLIES_PER_DAY"),
            "watched_reply_scope": "configured watched topics; no politics, inflammatory or unclear-context posts" if broad else "AI/SI only, inside the overall Reply cap",
            "watched_reply_limits": {"words": 12 if broad else 24,
                                     "characters": min(90 if broad else 140, settings.get("REPLY_SHORT_MAX_CHARS"))},
            "watched_source_deadline_seconds": 60 if broad else None,
            "watched_delivery": "first-minute target; late work is skipped, delivery time is not guaranteed" if broad else "subject to discovery and browser availability",
            "watched_discovery_seconds": settings.get("PRIORITY_WATCH_INTERVAL_SECONDS"),
            "watched_dispatch_seconds": settings.get("PRIORITY_WATCH_DISPATCH_SECONDS"),
            "draft_sessions": ["05:00", "10:00", "15:00", "20:00"] if settings.get("REPLY_MANUAL_DISCOVERY") else [],
            "daily_draft_limit": plan["manual_draft_limit"] if settings.get("REPLY_MANUAL_DISCOVERY") else 0,
            "draft_session_limit": plan["session_limit"] if settings.get("REPLY_MANUAL_DISCOVERY") else 0,
            "planned_daily_total_cap": plan["cap"],
            "remaining_watched_reserve": plan["remaining_watched_reserve"],
            "known_automatic_submissions": plan["known_automatic_submissions"],
            "daily_advisory_target": plan["target"],
            "manual_follow_ups": "complete incoming responses to our replies under external originals only" if manual_ordinary else False,
            "watched_reply_minimum_seconds": settings.get("CURATED_WATCH_REPLY_MIN_SECONDS"),
            "watched_repost_minimum_seconds": max(settings.get("CURATED_WATCH_REPOST_MIN_SECONDS"), settings.get("PRIORITY_REPOST_MIN_SECONDS")),
            "watched_action_maximum_age_hours": settings.get("PRIORITY_WATCH_MAX_AGE_HOURS"),
            "reply_all_day": settings.get("REPLY_ALL_DAY"),
            "active_hours": window_label(), "follows": 0, "originals": 0,
            "jobs": [job.id for job in scheduler.get_jobs()]}, indent=2))
        return
    if args.dry_run and settings.get("REPLY_INVITED_ONLY"):
        from src.guards import reply_budget
        plan = reply_budget.daily_plan()
        print(json.dumps({"mode": "automatic_invited_help", "manual_review_required": False,
                          "discovery": "bounded Latest and recent Top searches every 3 minutes; rotating public requests and mentions; unused sources buffered; no API" if settings.get("REPLY_PUBLIC_REQUESTS") else "one bounded Latest mention search every 3 minutes; no API",
                          "public_requests": settings.get("REPLY_PUBLIC_REQUESTS"),
                          "request_required": "explicit technical-help or creative-feedback request to the public audience or this Account" if settings.get("REPLY_PUBLIC_REQUESTS") else "explicit technical-help or creative-feedback request addressed to this Account",
                          "maximum_replies_per_day": reply_budget.ceiling(),
                          "advisory_reply_targets": [plan["minimum"], plan["maximum"]],
                          "maximum_per_author_per_day": 1, "includes_uncertain_submissions": True,
                          "minimum_seconds_between_replies": max(240, settings.get("MIN_SECONDS_BETWEEN_REPLIES")),
                          "reply_all_day": settings.get("REPLY_ALL_DAY"), "active_hours": window_label(),
                          "likes": 0, "reposts": 0, "follows": 0, "originals": 0,
                          "jobs": [job.id for job in scheduler.get_jobs()]}, indent=2))
        return
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
                          "skip_sleep_night_date": settings.get("SKIP_SLEEP_NIGHT_DATE"),
                          "awake_72h_start": settings.get("AWAKE_72H_START"),
                          "min_target_posts": (0 if video_cfg.ultra_bangers_only else video_slots) if video_cfg else (0 if settings.get("NEWS_ENABLED") else min_target),
                          "target_posts": (0 if video_cfg.ultra_bangers_only else video_slots) if video_cfg else (0 if settings.get("NEWS_ENABLED") else target),
                          "max_profile_posts": (None if account.current().watched_reposts_independent or account.current().self_reposts_enabled else
                                                (video_slots + 1 + (config.posts_ceiling() if settings.get("NEWS_ENABLED") else 0)
                                                 if settings.get("VIDEO_ENABLED") else config.posts_ceiling())
                                                + (settings.get("MEME_REPOST_DAILY_CAP") if settings.get("MEME_REPOST_ENABLED") else 0)),
                          "profile_budget_note": "Meme reposts have a separate bounded allowance; optional paced watched and own reposts have no daily count cap",
                          "replies": settings.get("MAX_REPLIES_PER_DAY"),
                          "reply_all_day": settings.get("REPLY_ALL_DAY"),
                          "reply_volume_boost_date": settings.get("REPLY_VOLUME_BOOST_DATE"),
                          "reply_discovery_generation_budgets": {
                              name: settings.reply_budget(name) for name in settings.REPLY_BUDGET_NAMES},
                          "advisory_reply_targets": [settings.get("REPLY_DAILY_TARGET_MIN"),
                                                     settings.get("REPLY_DAILY_TARGET_MAX")],
                          "editorial_route": "reply" if account.current().editorial.use_reply_route else "original",
                          "news": {"enabled": settings.get("NEWS_ENABLED"), "hourly": True,
                                   "automatic_safari": settings.get("NEWS_AUTO_PUBLISH"), "email": False},
                          "startup_publications": args.startup_publications and not args.reply_only,
                          "quotes": settings.get("PRIORITY_QUOTE_DAILY_CAP") if account.current().priority_quotes_enabled else 0,
                          "reposts": "watched authors only" if account.current().auto_engage_handles and (not settings.get("VIDEO_ENABLED") or account.current().watched_reposts_independent) else 0,
                          "reply_min_likes": settings.get("REPLY_MIN_LIKES"),
                          "meme_reposts": {"enabled": settings.get("MEME_REPOST_ENABLED"),
                                           "daily_cap": settings.get("MEME_REPOST_DAILY_CAP"),
                                           "min_likes": settings.get("MEME_REPOST_MIN_LIKES"),
                                           "min_views": settings.get("MEME_REPOST_MIN_VIEWS")},
                          "self_reposts": {"enabled": account.current().self_reposts_enabled,
                                           "initial_delay_seconds": 3600, "repeat_seconds": 1800,
                                           "repeat_views_strictly_above": 50000},
                          "auto_engage_handles": list(account.current().auto_engage_handles),
                          "reply_excluded_handles": list(account.current().reply_excluded_handles),
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
    video_supervisor = None
    from src.video import config as video_settings
    if video_settings.scheduled() and not scheduler_reply_only:
        from src.video.workers import Supervisor
        video_supervisor = Supervisor()
    if args.startup_publications and not args.reply_only:
        _request_startup_news()
    if video_supervisor:
        _request_startup_video(retry_expired=args.startup_publications)
        if settings.get("REPLY_INVITED_ONLY"):
            log.info("[VIDEO] Video scheduler runs beside restricted Replies (VIDEO_WITH_REPLIES); live=%s.",
                     video_settings.live())

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
    if settings.get("REPLY_REVIEW_ONLY"):
        from src.guards import reply_budget
        plan = reply_budget.daily_plan()
        log.info("Bot started: manual Reply discovery/drafting at 05:00/10:00/15:00/20:00 Toronto; "
                 "at most %s selected drafts/day and %s attempts/session; all X writes disabled.",
                 plan["draft_limit"], plan["session_limit"])
    elif settings.get("REPLY_MANUAL_ORDINARY"):
        log.info("Bot started: ordinary Replies require manual review/posting; scoped watched-author "
                 "actions remain automatic after selection and final checks; active %s.", window_label())
    elif settings.get("REPLY_BROAD_DISCOVERY"):
        from src.guards import reply_budget, reply_selection
        plan = reply_budget.daily_plan()
        log.info("Bot started: broad AI artist and technical discovery; maximum %s Replies/day including uncertain sends; "
                 "advisory target %s–%s, no filler; %s+ exact-parent likes; major-author preference=%s; "
                 "ordinary Replies one sentence/24 words/%s characters; confirmed parent like required=%s; %s; active %s.",
                 reply_budget.ceiling(), plan["minimum"], plan["maximum"],
                 reply_selection.minimum_likes(), _ordinary_major_author_priority(),
                 min(140, settings.get("REPLY_SHORT_MAX_CHARS")), settings.get("REPLY_REQUIRE_PARENT_LIKE"),
                 _broad_discovery_description(), window_label())
    elif settings.get("REPLY_CURATED_MODE"):
        log.info("Bot started: curated AI artist videos and short technical Replies; maximum 100/day including uncertain sends; "
                 "%s+ followers, %s+ likes; 140 chars/24 words maximum; artist reactions 90 chars/12 words; "
                 "watched-author likes enabled, at most %s reviewed reposts and %s AI Replies/day; active %s.",
                 settings.get("REPLY_MIN_FOLLOWERS"), max(20, settings.get("REPLY_MIN_LIKES")),
                 settings.get("CURATED_WATCH_REPOSTS_PER_DAY"), settings.get("CURATED_WATCH_REPLIES_PER_DAY"), window_label())
    elif settings.get("REPLY_INVITED_ONLY"):
        from src.guards import reply_budget
        plan = reply_budget.daily_plan()
        log.info("Bot started: automatic invited technical help and creative feedback; at most %s/day, one per author/day; "
                 "advisory target %s–%s/day, dependent on eligible requests; "
                 "no likes, reposts, follows or profile posts; active %s.",
                 reply_budget.ceiling(), plan["minimum"], plan["maximum"], window_label())
    elif settings.get("VIDEO_ENABLED"):
        from src.video.config import load as video_config
        from src.video.schedule import clocks as video_clocks
        cfg = video_config()
        log.info("Bot started: %s video opportunities; ultra-only=%s; automatic startup=%s; news=%s; transport=%s; replies capped; profile active %s.",
                 len(video_clocks(cfg)), cfg.ultra_bangers_only, cfg.startup_on_boot,
                 settings.get("NEWS_ENABLED"), cfg.publishing_transport, window_label())
    elif settings.get("NEWS_ENABLED") and not args.reply_only:
        log.info("Bot started: hourly verified news, automatic Safari=%s; replies active %s.",
                 settings.get("NEWS_AUTO_PUBLISH"), window_label())
    else:
        log.info(f"Bot started: at least {min_target} useful {account.current().domain} originals targeted "
                 f"(max {config.posts_ceiling()}); replies capped; profile active {window_label()}.")
    from src.guards import reply_budget
    log.info("[REPLY] Maximum %s/day including uncertain sends; all-day=%s; minimum %ss plus jitter.",
             reply_budget.ceiling(), settings.get("REPLY_ALL_DAY"),
             settings.get("MIN_SECONDS_BETWEEN_REPLIES"))
    if settings.get("REPLY_REVIEW_ONLY") or settings.get("REPLY_MANUAL_ORDINARY"):
        log.info("[REPLY] Drafts stay in the local review inbox. No selected draft becomes an automatic send.")
    elif settings.get("REPLY_BROAD_DISCOVERY"):
        log.info("[REPLY] One per ordinary author/day, permanent parent dedup, exact own-status receipts. "
                 "%ss minimum plus 0–%ss jitter; two intervening Replies between hearts.",
                 max(8, settings.get("MIN_SECONDS_BETWEEN_REPLIES")), settings.get("REPLY_JITTER_SECONDS"))
    elif settings.get("REPLY_CURATED_MODE"):
        log.info("[REPLY] Three-minute discovery; Top + Latest, at most 40 results/8 scrolls each; "
                 "artist discovery preferred; mentions every fifth turn. At most 6 author checks, 2 video reviews, "
                 "3 Reply generations and 1 confirmed Reply per cycle; ten-minute send spacing plus jitter.")
    elif settings.get("REPLY_INVITED_ONLY"):
        log.info("[REPLY] Three-minute discovery; public requests=%s (%s queries): Latest + recent Top, "
                 "at most 40 results and 8 scrolls each; mentions every fourth turn (20 results/1 scroll). "
                 "Unused requests buffered; 3 generation attempts and 1 confirmed Reply per cycle.",
                 settings.get("REPLY_PUBLIC_REQUESTS"), len(account.current().searches.help_requests))
    else:
        log.info("[REPLY] Discovery/generation budgets: %s; boost date: %s (Toronto).",
                 {name: settings.reply_budget(name) for name in settings.REPLY_BUDGET_NAMES},
                 settings.get("REPLY_VOLUME_BOOST_DATE") or "disabled")
    try:
        while not stop.is_set():
            from src.video.startup import waiting_reason
            startup_held = not (settings.get("REPLY_INVITED_ONLY") or settings.get("REPLY_REVIEW_ONLY")) and bool(waiting_reason())
            if startup_held != was_startup_held:
                if startup_held:
                    log.info("[VIDEO-FIRST] Interactions held until the startup video is confirmed.")
                elif was_startup_held:
                    log.info("[VIDEO-FIRST] Startup hold released; normal interaction jobs may resume.")
                was_startup_held = startup_held
            if video_supervisor:
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
            active = (is_active() and pause_end is None) or (not args.post_only and may_reply())
            if active != was_active:
                if active:
                    scheduler.resume()
                    if startup_held:
                        log.info("[HOURS] Awake. Video preparation active; interactions held for the startup video.")
                    elif settings.get("REPLY_INVITED_ONLY"):
                        log.info("[HOURS] Awake. Replies and enabled watched actions resumed.")
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

"""@kzer_ai Twitter bot - AI news, sharp takes, strategic replies.

Growth strategy: replies on massive accounts > original posts.
Quality over quantity. Every interaction must earn a follow.

Usage:
    python main.py              Run all bots
    python main.py --post-only  Run only the post bot
    python main.py --reply-only Run only the reply bot
    python main.py --dry-run    Print what would happen without posting
"""
import argparse
import random
import signal
import sys
import traceback
from datetime import datetime
from zoneinfo import ZoneInfo
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger
from src.logger import log
from src.bot import has_post_slot, post_slot_status, safe_run_bot_cycle
from src.reply_bot import safe_run_reply_cycle
from src.engage_bot import safe_run_engage_cycle
from src.notify_bot import safe_run_notify_cycle, safe_run_boost_cycle, safe_run_replyback_cycle
from src.direct_reply import safe_run_direct_reply_cycle
from src.discover_bot import safe_run_discovery_cycle
from src.roast_pgm_bot import safe_run_roast_pgm_cycle
from src.performance import evaluate_and_learn
from src.strategy_agent import safe_run_strategy_cycle
from src.evolution_agent import safe_run_evolution_cycle
from src.reflection_agent import safe_run_reflection_cycle
from src.scout_agent import safe_run_scout_cycle
from src.daily_digest import safe_run_daily_digest
from src.quote_tweet_bot import safe_run_quote_tweet_cycle
from src.early_bird_bot import safe_run_early_bird_cycle
from src.retweet_bot import safe_run_retweet_cycle
from src import health  # noqa: F401  (used by safe_run wrappers via record_success/_failure)
from src.config import ENABLE_AI_DISCOVERY, ENABLE_AI_MAINTENANCE


def _engagement_skip_rate() -> float:
    """Probability of skipping an engagement cycle right now.

    Replaces the old hard 1am-7am Paris cliff with a graceful fade tuned for
    a DUAL FR + QUEBEC audience and a 16h-active human profile.

    Paris hour | Montreal hour | What's happening                | Skip rate
    -----------+---------------+----------------------------------+----------
    07-23      | 01-17         | FR primary day                   | 0.0
    23-00      | 17-18         | FR winding down, QC pre-evening  | 0.0
    00-04      | 18-22         | QC PRIMETIME (FR night)          | 0.25
                                  → light cadence so we still surf QC peak
                                    without looking like a 24/7 bot
    04-07      | 22-01         | both audiences off                | 0.95
                                  → deep quiet (real humans sleep)

    Weekend tweak: Sat/Sun morning Paris 8-11h Paris audience sleeps in,
    posts get less reach — bump skip rate to 0.30 there. Pure Paris-side
    optimization, doesn't hurt QC.

    The probabilistic skip ALSO adds jitter — two consecutive cycles at the
    same time-of-day get different decisions. That's exactly the
    non-mechanical pattern we want (vs hard cliff = obvious bot signal).
    """
    now = datetime.now(ZoneInfo("Europe/Paris"))
    hour = now.hour
    is_weekend = now.weekday() in (5, 6)

    if 4 <= hour < 7:
        rate = 0.95
    elif 0 <= hour < 4:
        rate = 0.25  # QC primetime — light pass, not silence
    else:
        rate = 0.0

    if is_weekend and 8 <= hour < 11:
        rate = max(rate, 0.30)

    return rate


def should_skip_engagement() -> bool:
    """Probabilistic engagement gate. Replaces quiet_hours_paris(). See
    _engagement_skip_rate() for the curve and rationale."""
    return random.random() < _engagement_skip_rate()


def post_interval_minutes() -> int:
    """Quality-first original-post cadence.

    Standalone news is capped at 4/day and uses the stronger model. We check
    often enough to find real news windows, but the prompt should SKIP anything
    that is not follower-worthy.

    Hours are EST. Paris = EST + 6, Montreal = EST.
    """
    hour = datetime.now(ZoneInfo("America/New_York")).hour
    if 18 <= hour < 23:
        return random.randint(90, 150)
    elif 23 <= hour or hour < 4:
        return random.randint(180, 300)
    elif 9 <= hour < 11:
        return random.randint(75, 120)
    elif 13 <= hour < 15:
        return random.randint(75, 120)
    elif 4 <= hour < 8:
        return random.randint(120, 210)
    elif 8 <= hour < 12:
        return random.randint(90, 150)
    elif 12 <= hour < 18:
        return random.randint(90, 150)
    else:
        return random.randint(120, 210)


def reply_interval_minutes() -> int:
    """Primary growth cadence: more response scans, still jittered."""
    return random.randint(18, 30)


def engage_interval_minutes() -> int:
    """~27min jittered (was 32). More frequent presence in influencer
    notifications. Engagement gate handles QC-primetime light pass."""
    return random.randint(22, 32)


def direct_reply_interval_minutes() -> int:
    """Primary response path: visit targets often enough to land early."""
    return random.randint(20, 32)


def early_bird_interval_minutes() -> int:
    """Early-bird replies use AI; scan less often on Plus."""
    return random.randint(10, 18)


def roast_interval_minutes() -> int:
    """Roasts use AI; keep them occasional."""
    return random.randint(45, 75)


def _graceful_shutdown(signum, frame):
    """Handle SIGTERM/SIGINT for clean shutdown."""
    log.info(f"Received signal {signum}. Shutting down gracefully...")
    sys.exit(0)


def main():
    parser = argparse.ArgumentParser(description="@kzer_ai AI Twitter bot")
    parser.add_argument("--post-only", action="store_true", help="Run only the post bot")
    parser.add_argument("--reply-only", action="store_true", help="Run only the reply bot")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without posting")
    args = parser.parse_args()

    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGTERM, _graceful_shutdown)
    signal.signal(signal.SIGINT, _graceful_shutdown)

    if args.dry_run:
        log.info("DRY RUN MODE - no tweets will be posted")

    scheduler = BlockingScheduler()

    # --- POST BOT (secondary - few posts, only bangers) ---
    def reschedule_and_post():
        if has_post_slot():
            safe_run_bot_cycle()
        else:
            log.info(f"[POST] Daily post caps full ({post_slot_status()}). No news/hot-take search this cycle.")
        next_min = post_interval_minutes()
        hour = datetime.now(ZoneInfo("America/New_York")).hour
        log.info(f"[POST][EST {hour}:xx] Next post in {next_min} minutes.")
        scheduler.reschedule_job(
            "post_job",
            trigger=IntervalTrigger(minutes=next_min),
        )

    def _quiet_skip(label: str) -> bool:
        """Skip-and-reschedule helper for engagement cycles. Uses the
        probabilistic fade (16h-active human profile, FR + QC dual audience)
        so individual decisions vary cycle-to-cycle instead of cliffing on
        a hard hour boundary."""
        if should_skip_engagement():
            rate = _engagement_skip_rate()
            log.info(f"[{label}] Engagement gate skip (skip_rate={rate:.2f} now) — passing this cycle.")
            return True
        return False

    # --- REPLY BOT (primary growth engine) ---
    def reschedule_and_reply():
        if not _quiet_skip("REPLY"):
            safe_run_reply_cycle()
        next_min = reply_interval_minutes()
        hour = datetime.now(ZoneInfo("America/New_York")).hour
        log.info(f"[REPLY][EST {hour}:xx] Next reply scan in {next_min} minutes.")
        scheduler.reschedule_job(
            "reply_job",
            trigger=IntervalTrigger(minutes=next_min),
        )

    def reschedule_and_engage():
        if not _quiet_skip("ENGAGE"):
            safe_run_engage_cycle()
        scheduler.reschedule_job(
            "engage_job",
            trigger=IntervalTrigger(minutes=engage_interval_minutes()),
        )

    def reschedule_and_direct_reply():
        if not _quiet_skip("DIRECT-REPLY"):
            safe_run_direct_reply_cycle()
        scheduler.reschedule_job(
            "direct_reply_job",
            trigger=IntervalTrigger(minutes=direct_reply_interval_minutes()),
        )

    def reschedule_and_early_bird():
        if not _quiet_skip("EARLYBIRD"):
            safe_run_early_bird_cycle()
        scheduler.reschedule_job(
            "early_bird_job",
            trigger=IntervalTrigger(minutes=early_bird_interval_minutes()),
        )

    def reschedule_and_roast():
        if not _quiet_skip("ROAST"):
            safe_run_roast_pgm_cycle()
        scheduler.reschedule_job(
            "roast_pgm_job",
            trigger=IntervalTrigger(minutes=roast_interval_minutes()),
        )

    def quiet_safe_notify():
        if not _quiet_skip("NOTIFY"):
            safe_run_notify_cycle()

    def quiet_safe_replyback():
        if not _quiet_skip("REPLYBACK"):
            safe_run_replyback_cycle()

    # Run news post FIRST so the bot opens its session with a banger.
    # User preference: AI news + sharp comment is the brand DNA — that's what
    # we want to lead with, not a reply. Replies follow once the post is up.
    if not args.reply_only:
        if has_post_slot():
            log.info("Bot started! Posting first news tweet...")
            safe_run_bot_cycle()
        else:
            log.info(f"Bot started with daily post caps full ({post_slot_status()}). Skipping startup news search.")

    # Then warm up the engagement loop with a direct-reply cycle.
    if not args.post_only:
        log.info("Now warming up the reply loop...")
        safe_run_direct_reply_cycle()

        # Warm up reply-to-replies path immediately on startup so people
        # who replied to our latest tweets get a response NOW, not after
        # the bot has been up for 35-45 min.
        log.info("Warming up notify (like replies on our tweets)...")
        quiet_safe_notify()
        log.info("Warming up replyback (reply to people who replied to us)...")
        quiet_safe_replyback()

    # Schedule jobs
    if not args.reply_only:
        first_post = post_interval_minutes()
        log.info(f"Next post in {first_post} minutes.")
        scheduler.add_job(
            reschedule_and_post,
            trigger=IntervalTrigger(minutes=first_post),
            id="post_job",
        )

    if not args.post_only:
        first_reply = reply_interval_minutes()
        log.info(f"Reply bot: next scan in {first_reply} minutes.")
        scheduler.add_job(
            reschedule_and_reply,
            trigger=IntervalTrigger(minutes=first_reply),
            id="reply_job",
        )

    if not args.post_only and not args.reply_only:
        # Engage bot - follow and like AI accounts for reciprocity.
        # Slowed from 30 -> ~45min jittered. Skipped during quiet hours.
        # Initial offset = 7min so it doesn't fire at the same tick as other jobs.
        log.info("Engage bot: follow + like target accounts every ~45 min (jittered, quiet 1am-7am Paris).")
        scheduler.add_job(
            reschedule_and_engage,
            trigger=IntervalTrigger(minutes=engage_interval_minutes()),
            id="engage_job",
        )

        # Notify bot - like replies on own tweets to build community.
        # Quiet hours skip; cadence kept at 45min (cheap operation).
        log.info("Notify bot: liking replies on own tweets every 20 min (quiet 1am-7am Paris).")
        scheduler.add_job(
            quiet_safe_notify,
            trigger=IntervalTrigger(minutes=20),
            id="notify_job",
        )

        # Direct reply bot - visits influencer profiles and replies to their tweets.
        # Slowed from 15 -> ~25min jittered. Skipped during quiet hours.
        log.info("Direct reply bot: replying to influencer tweets every ~25 min (jittered, quiet 1am-7am Paris).")
        scheduler.add_job(
            reschedule_and_direct_reply,
            trigger=IntervalTrigger(minutes=direct_reply_interval_minutes()),
            id="direct_reply_job",
        )

        # Reply-back bot - reply to people who reply to our tweets (creates threads).
        # Cadence unchanged (60min) but skipped during quiet hours.
        log.info("Reply-back bot: replying to followers every 20 min (quiet 1am-7am Paris).")
        scheduler.add_job(
            quiet_safe_replyback,
            trigger=IntervalTrigger(minutes=20),
            id="replyback_job",
        )

        # Boost bot — validated growth lever (200 views / 6 likes per cycle).
        # 4h → 3h on user directive 2026-04-26 PM: the cheapest validated
        # action we have, push it to 8 boosts/day. Risk of algo suppression
        # exists but is dwarfed by the confirmed lift.
        log.info("Boost bot: retweeting own latest tweet every 2 hours.")
        scheduler.add_job(
            safe_run_boost_cycle,
            trigger=IntervalTrigger(hours=2),
            id="boost_job",
        )

        # Early-bird bot — slowed from 5 -> ~8min jittered (still inside the
        # 12-min freshness window for top-5-reply). Quiet hours skip.
        log.info("Early-bird bot: catching fresh mega-account tweets every ~8 min (jittered, quiet 1am-7am Paris).")
        scheduler.add_job(
            reschedule_and_early_bird,
            trigger=IntervalTrigger(minutes=early_bird_interval_minutes()),
            id="early_bird_job",
        )

        if ENABLE_AI_DISCOVERY:
            log.info("Discover bot: searching for new influencers every 6 hours.")
            scheduler.add_job(
                safe_run_discovery_cycle,
                trigger=IntervalTrigger(hours=6),
                id="discover_job",
            )
        else:
            log.info("Discover bot: disabled by default in Plus-safe mode.")

        # Roast bot - slowed from 10 -> ~20min jittered. He tweets every ~minute
        # so we still catch plenty; URL dedup hard-caps to 1 per tweet. Quiet skip.
        log.info("Roast bot: replying to @pgm_pm tweets every ~20 min (jittered, quiet 1am-7am Paris).")
        scheduler.add_job(
            reschedule_and_roast,
            trigger=IntervalTrigger(minutes=roast_interval_minutes()),
            id="roast_pgm_job",
        )

        # Performance tracking
        def safe_evaluate():
            try:
                evaluate_and_learn()
            except Exception:
                log.error(f"[PERF] Evaluation failed: {traceback.format_exc()}")

        log.info("Performance bot: evaluating tweet performance every 2 hours.")
        scheduler.add_job(
            safe_evaluate,
            trigger=IntervalTrigger(hours=2),
            id="perf_job",
        )

        # Strategy agent — fully autonomous self-improvement (INPUT side).
        # Reads engagement log + uses tools (WebSearch, Read) to find new
        # queries / accounts; ADDS them to dynamic_queries.json and
        # dynamic_accounts.json which direct_reply merges with its static
        # lists at runtime. 6h → 3h: user directive 2026-04-26 wants the
        # bot to auto-adjust strategy MULTIPLE TIMES per day. Append-only
        # safety boundary still holds (additions never removals).
        if ENABLE_AI_MAINTENANCE:
            log.info("Strategy agent: autonomous self-improvement every 12 hours.")
            scheduler.add_job(
                safe_run_strategy_cycle,
                trigger=IntervalTrigger(hours=12),
                id="strategy_job",
            )
        else:
            log.info("Strategy agent: disabled by default in Plus-safe mode.")

        # Evolution agent — autonomous self-improvement (OUTPUT side).
        # Reads engagement_log + performance_log; analyses what content
        # patterns win, prunes accounts that produced 0 engagement, doubles
        # down on accounts whose tweets converted into our top posts.
        # Writes directives.md (loaded by all generation agents) +
        # pruned_accounts.json + reinforced_accounts.json. Hard caps:
        # max 3 prunes/cycle (TTL 30d), max 5 reinforcements/cycle (no TTL).
        # 12h → 6h: user directive 2026-04-26 wants the bot to auto-adjust
        # OUTPUT-side strategy multiple times per day. Hard caps (3 prunes,
        # 5 reinforcements per cycle) still bound damage if a cycle goes
        # rogue, and prune TTL is still 30d so doubling the cadence doesn't
        # double the damage — it just makes the style guide more responsive.
        if ENABLE_AI_MAINTENANCE:
            log.info("Evolution agent: content-quality self-improvement every 12 hours.")
            scheduler.add_job(
                safe_run_evolution_cycle,
                trigger=IntervalTrigger(hours=12),
                id="evolution_job",
            )
        else:
            log.info("Evolution agent: disabled by default in Plus-safe mode.")

        # Reflection agent — autobiographical brain. Every 6h, agentic Claude
        # run reads engagement + history, updates personality.json: per-account
        # dossiers (category, stance, feelings, notes) + per-topic positions.
        # Replies become PERSONAL because the bot remembers each account.
        if ENABLE_AI_MAINTENANCE:
            log.info("Reflection agent: personality / memory update every 12 hours.")
            scheduler.add_job(
                safe_run_reflection_cycle,
                trigger=IntervalTrigger(hours=12),
                id="reflection_job",
            )
        else:
            log.info("Reflection agent: disabled by default in Plus-safe mode.")

        # Scout agent — open-web FR-speaker recruitment. Every 4h, an agentic
        # Claude run uses WebSearch + WebFetch to find the BEST FR-speaking AI /
        # crypto / bourse accounts in France, Quebec, and the USA, filters by
        # follower count (≥5k), appends to dynamic_accounts.json FR bucket, and
        # auto-follows the top picks. Different from strategy_agent (which
        # mines our engagement log) and discover_bot (which scrapes X search):
        # this one investigates the open web for hidden gems we'd never see
        # via X-internal signals. Hard caps: 8 added per cycle, 3 auto-follows.
        if ENABLE_AI_DISCOVERY:
            log.info("Scout agent: open-web FR-speaker recruitment every 12 hours.")
            scheduler.add_job(
                safe_run_scout_cycle,
                trigger=IntervalTrigger(hours=12),
                id="scout_job",
            )
        else:
            log.info("Scout agent: disabled by default in Plus-safe mode.")

        # Quote-tweet bot — now deliberately scarce. Too many news-like
        # surfaces made the profile feel like a wire service; keep only the
        # biggest viral setups and spend cadence on replies instead.
        log.info("Quote-tweet bot: amplifying only top viral setups every 3 hours (cap 2/day).")
        scheduler.add_job(
            safe_run_quote_tweet_cycle,
            trigger=IntervalTrigger(hours=3),
            id="quote_tweet_job",
        )

        # Retweet bot — selective amplifier for ELITE AI/crypto/bourse news
        # from trusted outlets (Reuters/Bloomberg/TechCrunch/Coindesk/lesechos
        # etc.). Cap 8/day. Picks single best candidate per cycle, only
        # retweets if score ≥ 9/10. Side-effect: appends ≥8/10 picks to
        # daily_news_picks.md — that file IS the YouTube show research doc.
        log.info("Retweet bot: selective amplification of trusted news every 4 hours (cap 3/day).")
        scheduler.add_job(
            safe_run_retweet_cycle,
            trigger=IntervalTrigger(hours=4),
            id="retweet_job",
        )

        # Daily digest — append yesterday's rollup to daily_digest.md.
        # Idempotent (won't double-write same day). Fires hourly so a missed
        # cron after a restart still catches up; the dedup state guards it.
        # Used for the 2-week post-mission review.
        log.info("Daily digest: appending yesterday's rollup to daily_digest.md (hourly idempotent check).")
        scheduler.add_job(
            safe_run_daily_digest,
            trigger=IntervalTrigger(hours=1),
            id="daily_digest_job",
        )

    log.info("All systems go. Bot is running.")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("Bot stopped.")


if __name__ == "__main__":
    main()

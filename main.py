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
from src.bot import safe_run_bot_cycle
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
from src.quote_tweet_bot import safe_run_quote_tweet_cycle
from src.early_bird_bot import safe_run_early_bird_cycle
from src import health  # noqa: F401  (used by safe_run wrappers via record_success/_failure)


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
    """Cluster posts during peak engagement windows. Caps at 24 news + 24
    hot takes/day allow tighter cadences. Now tuned for FR + QC dual
    audience: Paris night = QC primetime, so we keep posting overnight.

    Hours are EST. Paris = EST + 6, Montreal = EST.
    """
    hour = datetime.now(ZoneInfo("America/New_York")).hour
    if 18 <= hour < 23:
        # QC primetime EST evening (Paris 0-5am): keep cadence reasonable
        # so we surf the QC peak without spamming.
        return random.randint(70, 120)
    elif 23 <= hour or hour < 4:
        # Deep quiet for both audiences (Paris 5-10am still arriving):
        # slow but not silent so we wake up with fresh content.
        return random.randint(110, 180)
    elif 9 <= hour < 11:
        # PEAK: Morning EST window (Paris 15-17h afternoon active)
        return random.randint(45, 80)
    elif 13 <= hour < 15:
        # PEAK: Afternoon EST window (Paris 19-21h evening prime)
        return random.randint(45, 80)
    elif 4 <= hour < 8:
        # Paris morning ramp (10-14h Paris): pick up cadence
        return random.randint(70, 110)
    elif 8 <= hour < 12:
        # Paris afternoon (14-18h)
        return random.randint(60, 100)
    elif 12 <= hour < 18:
        # Paris evening (18-24h) + QC daytime
        return random.randint(60, 100)
    else:
        return random.randint(80, 130)


def reply_interval_minutes() -> int:
    """Tighter cadence for 16h-active human profile: ~16min jittered (was
    22). With cap=7/cycle this lands ~150 replies/day max in awake hours —
    heavy but in line with high-volume FR influencers (Mathieu Louvet,
    Hasheur). Engagement gate (probabilistic skip) handles overnight."""
    return random.randint(12, 20)


def engage_interval_minutes() -> int:
    """Follow + like cadence. ~32min jittered (was 40). More frequent
    presence in influencer notifications without crossing the bot
    threshold. Engagement gate handles QC-primetime light pass."""
    return random.randint(26, 38)


def direct_reply_interval_minutes() -> int:
    """~16min jittered (was 22). Tighter to land more replies on FR + QC
    influencer profiles where we convert best. Per-cycle cap in
    direct_reply.py prevents bursts."""
    return random.randint(13, 19)


def early_bird_interval_minutes() -> int:
    """~6min jittered (was 7). Stay deep inside the 12-min freshness
    window so we catch viral tweets in their top-5-reply moment more often."""
    return random.randint(5, 7)


def roast_interval_minutes() -> int:
    """~14min jittered (was 18). @pgm_pm tweets every minute; URL dedup
    still hard-caps to 1 roast per tweet."""
    return random.randint(12, 17)


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
        safe_run_bot_cycle()
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
        log.info("Bot started! Posting first news tweet...")
        safe_run_bot_cycle()

    # Then warm up the engagement loop with a direct-reply cycle.
    if not args.post_only:
        log.info("Now warming up the reply loop...")
        safe_run_direct_reply_cycle()

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
        log.info("Notify bot: liking replies on own tweets every 45 min (quiet 1am-7am Paris).")
        scheduler.add_job(
            quiet_safe_notify,
            trigger=IntervalTrigger(minutes=45),
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
        log.info("Reply-back bot: replying to followers every 60 min (quiet 1am-7am Paris).")
        scheduler.add_job(
            quiet_safe_replyback,
            trigger=IntervalTrigger(minutes=60),
            id="replyback_job",
        )

        # Boost bot — validated growth lever (200 views / 6 likes per cycle).
        # 4h → 3h on user directive 2026-04-26 PM: the cheapest validated
        # action we have, push it to 8 boosts/day. Risk of algo suppression
        # exists but is dwarfed by the confirmed lift.
        log.info("Boost bot: retweeting own latest tweet every 3 hours.")
        scheduler.add_job(
            safe_run_boost_cycle,
            trigger=IntervalTrigger(hours=3),
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

        # Discovery bot - autonomously find new crypto/AI/bourse influencers.
        # 6h → 3h on user directive 2026-04-26 PM ("auto update list of
        # people to follow"). The bot evolves faster — fresh FR handles
        # join the orbit every 3h instead of 4x/day.
        log.info("Discover bot: searching for new influencers every 3 hours.")
        scheduler.add_job(
            safe_run_discovery_cycle,
            trigger=IntervalTrigger(hours=3),
            id="discover_job",
        )

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
        log.info("Strategy agent: autonomous self-improvement every 3 hours.")
        scheduler.add_job(
            safe_run_strategy_cycle,
            trigger=IntervalTrigger(hours=3),
            id="strategy_job",
        )

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
        log.info("Evolution agent: content-quality self-improvement every 6 hours.")
        scheduler.add_job(
            safe_run_evolution_cycle,
            trigger=IntervalTrigger(hours=6),
            id="evolution_job",
        )

        # Reflection agent — autobiographical brain. Every 6h, agentic Claude
        # run reads engagement + history, updates personality.json: per-account
        # dossiers (category, stance, feelings, notes) + per-topic positions.
        # Replies become PERSONAL because the bot remembers each account.
        log.info("Reflection agent: personality / memory update every 6 hours.")
        scheduler.add_job(
            safe_run_reflection_cycle,
            trigger=IntervalTrigger(hours=6),
            id="reflection_job",
        )

        # Quote-tweet bot — picks the most viral FR tweet in our niche and
        # quote-tweets it with a sharp meme observation. Cap 12/day, cadence
        # 90 min (was 120 min) on user directive 2026-04-26 PM. Different
        # distribution surface than replies — pure additive growth.
        log.info("Quote-tweet bot: amplifying viral FR tweets every 90 min (cap 12/day).")
        scheduler.add_job(
            safe_run_quote_tweet_cycle,
            trigger=IntervalTrigger(minutes=90),
            id="quote_tweet_job",
        )

    log.info("All systems go. Bot is running.")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("Bot stopped.")


if __name__ == "__main__":
    main()

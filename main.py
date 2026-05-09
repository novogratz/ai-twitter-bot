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
from src.thread_bot import safe_run_thread_cycle
from src.promote_bot import safe_run_promote_cycle
from src.followback_bot import safe_run_followback_cycle
from src.pin_bot import safe_run_pin_cycle
from src.like_bot import safe_run_like_cycle
from src.viral_followup_bot import safe_run_viral_followup_cycle
from src.digest_thread_bot import safe_run_digest_thread_cycle
from src.follow_blast_bot import safe_run_follow_blast_cycle
from src.auto_tune_bot import safe_run_auto_tune_cycle
from src.self_evolution_agent import safe_run_self_evolution_cycle
from src.breakout_bot import safe_run_breakout_cycle
from src.spike_bot import safe_run_spike_cycle
from src.spicy_bot import safe_run_spicy_cycle
from src.suppression_watch_bot import safe_run_suppression_watch_cycle
from src.mega_watch_bot import safe_run_mega_watch_cycle
from src.cleanup_bot import safe_run_cleanup_cycle
from src.heartbeat_bot import safe_run_heartbeat
from src.meta_strategy_agent import safe_run_meta_strategy_cycle
from src.hn_signal_bot import safe_run_signal_cycle
from src.rss_signal_bot import safe_run_rss_signal_cycle
from src.smart_unfollow_bot import safe_run_unfollow_cycle
from src.follower_tracker_bot import safe_run_follower_tracker_cycle
from src.x_home_scout_bot import safe_run_home_scout_cycle
from src.chain_reply_bot import safe_run_chain_reply_cycle
from src.youtube_brief_bot import safe_run_youtube_brief_cycle
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
    """Post cadence — 2026-05-08 user: 'I want more content real time, you're
    too slow.' Now EN-content + global audience, so the schedule isn't
    Paris-locked. US prime time (EST 09-22) gets the tightest cadence.
    Hours are EST.
    """
    hour = datetime.now(ZoneInfo("America/New_York")).hour
    # US business hours peak — EST 09-12 + 13-16 = absolute prime.
    if 9 <= hour < 12 or 13 <= hour < 16:
        return random.randint(15, 28)
    # US shoulder hours — early morning + late afternoon.
    elif 7 <= hour < 9 or 16 <= hour < 19:
        return random.randint(20, 35)
    # US evening — Cali + East Coast still scrolling.
    elif 19 <= hour < 23:
        return random.randint(30, 55)
    # Overnight / EU morning ramp — slower but still active for global news.
    elif 23 <= hour or hour < 4:
        return random.randint(60, 110)
    # EU mid-morning — pickup before US opens.
    elif 4 <= hour < 7:
        return random.randint(35, 60)
    else:
        return random.randint(30, 60)


def reply_interval_minutes() -> int:
    """Primary growth cadence — accelerated 2026-05-08. EN content + global
    audience: peak in US business hours, not Paris."""
    hour = datetime.now(ZoneInfo("America/New_York")).hour
    # US business peak EST 09-16 = absolute reply window.
    if 9 <= hour < 16:
        return random.randint(6, 12)
    if 16 <= hour < 23:
        return random.randint(10, 18)
    return random.randint(15, 25)


def engage_interval_minutes() -> int:
    """More frequent presence in influencer notifications."""
    hour = datetime.now(ZoneInfo("America/New_York")).hour
    if 9 <= hour < 16:
        return random.randint(8, 15)
    return random.randint(14, 22)


def direct_reply_interval_minutes() -> int:
    """Primary response path: visit targets often enough to land early."""
    hour = datetime.now(ZoneInfo("America/New_York")).hour
    if 9 <= hour < 16:
        return random.randint(8, 14)
    return random.randint(13, 22)


def early_bird_interval_minutes() -> int:
    """Early-bird replies are highest-upside; scan aggressively."""
    hour = datetime.now(ZoneInfo("America/New_York")).hour
    if 9 <= hour < 16:
        return random.randint(4, 8)
    return random.randint(6, 12)


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
        log.info("Boost bot: retweeting own latest tweet every 60 minutes.")
        scheduler.add_job(
            safe_run_boost_cycle,
            trigger=IntervalTrigger(minutes=60),
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
            log.info("Strategy agent: autonomous self-improvement every 3 hours.")
            scheduler.add_job(
                safe_run_strategy_cycle,
                trigger=IntervalTrigger(hours=3),
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
            log.info("Evolution agent: content-quality self-improvement every 3 hours.")
            scheduler.add_job(
                safe_run_evolution_cycle,
                trigger=IntervalTrigger(hours=3),
                id="evolution_job",
            )
        else:
            log.info("Evolution agent: disabled by default in Plus-safe mode.")

        # Reflection agent — autobiographical brain. Every 6h, agentic Claude
        # run reads engagement + history, updates personality.json: per-account
        # dossiers (category, stance, feelings, notes) + per-topic positions.
        # Replies become PERSONAL because the bot remembers each account.
        if ENABLE_AI_MAINTENANCE:
            log.info("Reflection agent: personality / memory update every 6 hours.")
            scheduler.add_job(
                safe_run_reflection_cycle,
                trigger=IntervalTrigger(hours=6),
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
            log.info("Scout agent: open-web FR-speaker recruitment every 4 hours.")
            scheduler.add_job(
                safe_run_scout_cycle,
                trigger=IntervalTrigger(hours=4),
                id="scout_job",
            )
        else:
            log.info("Scout agent: disabled by default in Plus-safe mode.")

        # Quote-tweet bot — accelerated 2026-05-05 (user: "reshare way more").
        # Daily cap is 10 (env), so cadence sets the upper bound on attempts;
        # bumped 3h → 75min so cap actually binds instead of cycle frequency.
        log.info("Quote-tweet bot: amplifying viral FR setups every 35 min (cap 30/day).")
        scheduler.add_job(
            safe_run_quote_tweet_cycle,
            trigger=IntervalTrigger(minutes=35),
            id="quote_tweet_job",
        )

        # Retweet bot — accelerated 2026-05-05 to 40 min (cap 20/day, threshold
        # 7/10). User: "reshare way more posts". TRUSTED_NEWS_HANDLES expanded
        # with FR press (Numerama, Usine Digitale, Siècle Digital, etc.) so
        # the FR news flow gets prioritized amplification. Daily cap binds.
        log.info("Retweet bot: amplifying trusted news every 20 min (cap 60/day).")
        scheduler.add_job(
            safe_run_retweet_cycle,
            trigger=IntervalTrigger(minutes=20),
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

        # Thread bot — 1 well-crafted FR thread per day on the biggest IA story.
        # Different distribution surface than single-tweet news (lifespan = days,
        # high screenshot+RT rate). Idempotent state in thread_daily_state.json.
        # Fires every 4h so a missed cron after restart still catches up;
        # the daily-state file guards against double-posting.
        log.info("Thread bot: 1 FR thread/day on the biggest IA story (every 4h, idempotent).")
        scheduler.add_job(
            safe_run_thread_cycle,
            trigger=IntervalTrigger(hours=4),
            id="thread_job",
        )

        # Promote-best-reply bot — quote-RTs our highest-engagement reply
        # so it appears on the profile feed instead of buried in a thread.
        # Cap 3/day. Different from quote_tweet_bot (which quotes external
        # tweets) — this one repackages OUR proven content.
        log.info("Promote bot: quote-RT top recent reply every 3h (cap 3/day).")
        scheduler.add_job(
            safe_run_promote_cycle,
            trigger=IntervalTrigger(hours=3),
            id="promote_job",
        )

        # Follow-back bot — scrape /kzer_ai/followers and follow back fresh
        # ones (capped 8/cycle, every 2h). Reciprocity is the highest-leverage
        # follower-growth tactic; the existing reciprocity loop only catches
        # repliers — this catches lurkers + likers + everyone else.
        log.info("Follow-back bot: follow back fresh followers every 2h (cap 8/cycle).")
        scheduler.add_job(
            safe_run_followback_cycle,
            trigger=IntervalTrigger(hours=2),
            id="followback_job",
        )

        # Pin bot — daily idempotent. Picks our highest-engagement post of
        # the recent window and pins it via JS menu click. A strong pinned
        # tweet is the #1 follow-conversion lever for first-time visitors.
        # Best-effort: if the JS menu DOM has shifted, logs + moves on.
        log.info("Pin bot: pinning best own post once a day (every 6h, idempotent).")
        scheduler.add_job(
            safe_run_pin_cycle,
            trigger=IntervalTrigger(hours=6),
            id="pin_job",
        )

        # Like bot — bulk-like FR niche tweets. Each like = 1 outbound
        # notification. ~18 likes × 4 cycles/hour = ~70 notifications/hour.
        # Strangers get pinged → click through to /kzer_ai → see strong
        # pinned + active feed → follow.
        log.info("Like bot: bulk-liking FR niche tweets every 15 min (~18 per cycle).")
        scheduler.add_job(
            safe_run_like_cycle,
            trigger=IntervalTrigger(minutes=15),
            id="like_job",
        )

        # Viral follow-up bot — when own post hits >= VIRAL_THRESHOLD likes,
        # post a follow-up reply in-thread. Capitalize on the algorithm push
        # window (first ~hour after takeoff is the highest-leverage moment).
        log.info("Viral follow-up bot: replying to own viral posts every 30 min (cap 3/cycle).")
        scheduler.add_job(
            safe_run_viral_followup_cycle,
            trigger=IntervalTrigger(minutes=30),
            id="viral_followup_job",
        )

        # Daily digest thread — once/day, idempotent, fires every 4h to
        # catch up after restart. Different from thread_bot (single-story)
        # — this one bundles 5 stories into a recap thread. Highly shareable
        # format on FR Twitter.
        log.info("Digest thread bot: 1 daily 5-story FR recap thread (every 4h, idempotent).")
        scheduler.add_job(
            safe_run_digest_thread_cycle,
            trigger=IntervalTrigger(hours=4),
            id="digest_thread_job",
        )

        # Follow blast bot — bulk-follow ~30 FR niche accounts every 30 min.
        # Highest-leverage net-new follower acquisition: ~120/hour follow
        # attempts, with 10-20% reciprocity = ~12-25 followers/hour gain.
        log.info("Follow-blast bot: bulk-following FR niche accounts every 30 min (~30/cycle).")
        scheduler.add_job(
            safe_run_follow_blast_cycle,
            trigger=IntervalTrigger(minutes=30),
            id="follow_blast_job",
        )

        # Auto-tune bot — real-time strategy gauge. Reads engagement_log
        # every 30 min, writes auto_tune_state.json with per-source velocity
        # snapshot + cadence factor. Other bots can opt-in to read it.
        # Complement to the slower 12h strategy/evolution agents.
        log.info("Auto-tune bot: writing real-time strategy state every 30 min.")
        scheduler.add_job(
            safe_run_auto_tune_cycle,
            trigger=IntervalTrigger(minutes=30),
            id="auto_tune_job",
        )

        # Self-evolution agent — bot rewrites its OWN personality every 4h.
        # Reads recent activity + uses WebSearch to investigate the world,
        # writes bot_self.json (mood, obsession, recent_learning, voice_tweaks,
        # drift, self_narrative) which personality_store.render_bot_self()
        # injects into every generation prompt. The bot's identity drifts
        # day-to-day like a real person.
        log.info("Self-evolution agent: bot rewrites own personality every 4h (agentic).")
        scheduler.add_job(
            safe_run_self_evolution_cycle,
            trigger=IntervalTrigger(hours=4),
            id="self_evolution_job",
        )

        # Breakout bot — fast trend jacker. Every 8 min scrapes niche
        # search Top tab; if a tweet has >= BREAKOUT_VELOCITY_LIKES likes
        # (default 100) it counts as breaking — generates a fast FR take
        # in <30 sec via Opus and ships immediately. Cap 8/day. Designed
        # to put us in the first 50 FR voices on a viral story.
        log.info("Breakout bot: fast trend jacker every 5 min (cap 8/day).")
        scheduler.add_job(
            safe_run_breakout_cycle,
            trigger=IntervalTrigger(minutes=5),
            id="breakout_job",
        )

        # Spike orchestrator — when one of OUR posts crosses SPIKE_LIKES
        # (default 25), all bots converge: auto-pin, self-RT, in-thread
        # follow-up, quote-RT promo, like top replies. Most growth
        # happens AROUND the viral moment; this bot ensures we ride it.
        log.info("Spike orchestrator: amplifying viral own posts every 8 min.")
        scheduler.add_job(
            safe_run_spike_cycle,
            trigger=IntervalTrigger(minutes=8),
            id="spike_job",
        )

        # Spicy bot — deliberately polarizing FR takes + question bait.
        # Cap 6/day. Replies > likes for algo signal; spicy + question
        # mode both maximize replies-per-impression. Different from
        # regular news (no source, no impact filter) — pure engagement
        # velocity.
        log.info("Spicy bot: polarizing/question takes every ~80 min (cap 6/day).")
        scheduler.add_job(
            safe_run_spicy_cycle,
            trigger=IntervalTrigger(minutes=80),
            id="spicy_job",
        )

        # Suppression watchdog — scrape last 20 own posts hourly, if avg
        # likes drop below SUPPRESSION_AVG_LIKES_FLOOR (default 1.0) flag
        # suppression and pause aggressive bots (spicy/breakout/follow_blast)
        # for 4h. Death-spiral protection.
        log.info("Suppression watchdog: hourly engagement health check.")
        scheduler.add_job(
            safe_run_suppression_watch_cycle,
            trigger=IntervalTrigger(hours=1),
            id="suppression_watch_job",
        )

        # Mega-account fast watcher — polls top-10 mega accounts every
        # 90 sec to catch fresh tweets within the 60-second top-5-reply
        # window. Different from early_bird (5-7 min, ~125 accounts):
        # this is targeted high-frequency on the highest-reach accounts.
        log.info("Mega-account watcher: top-10 polling every 90s for first-5-reply window.")
        scheduler.add_job(
            safe_run_mega_watch_cycle,
            trigger=IntervalTrigger(seconds=90),
            id="mega_watch_job",
        )

        # Daily housekeeping — rotate bot.log if oversized, trim 90+ day
        # rows from engagement_log.csv, cap JSON arrays. Keeps the bot
        # running smoothly when fully autonomous (no human babysitter
        # to clean up state). Hourly idempotent check; the daily-state
        # file guards the actual work to once-per-day.
        log.info("Cleanup bot: daily state housekeeping (hourly idempotent check).")
        scheduler.add_job(
            safe_run_cleanup_cycle,
            trigger=IntervalTrigger(hours=1),
            id="cleanup_job",
        )

        # Heartbeat — one log line every 60s so a glance at bot.log
        # always shows fresh activity, proving the bot is alive even
        # when all 28 other schedulers happen to be mid-sleep.
        log.info("Heartbeat: alive-tick every 60s.")
        scheduler.add_job(
            safe_run_heartbeat,
            trigger=IntervalTrigger(seconds=60),
            id="heartbeat_job",
        )

        # Meta-strategy agent — every 4h, reads 7d engagement + state +
        # WebSearch on world events, decides daily caps + cadence factor
        # + topic focus, writes live_strategy.json. Bots read the live
        # caps via config.get_live_cap() so strategic decisions actually
        # flex behavior. Auto-pushes to git.
        log.info("Meta-strategy agent: agentic cap + focus + cadence decisions every 4h.")
        scheduler.add_job(
            safe_run_meta_strategy_cycle,
            trigger=IntervalTrigger(hours=4),
            id="meta_strategy_job",
        )

        # External-signal bot — scrape Hacker News + Reddit hot every 20 min.
        # No LLM, no Twitter. Writes external_signal.json which news +
        # breakout + hotake agents inject into their prompts. HN front
        # page leads Bloomberg/TC by 6-12h on AI/crypto stories; this is
        # the cheap real-time signal we were missing.
        log.info("External signal: HN + Reddit niche scrape every 20 min.")
        scheduler.add_job(
            safe_run_signal_cycle,
            trigger=IntervalTrigger(minutes=20),
            id="hn_signal_job",
        )

        # RSS signal — fetch ~20 trusted outlets' RSS feeds every 5 min.
        # RSS publishes within seconds of the article going live; Google
        # (and therefore WebSearch) lags by 30-60 min. So this is the
        # 'before everyone else' lever — we see Bloomberg / Reuters /
        # TechCrunch / The Information scoops 20-50 min before WebSearch
        # would surface them. Merges with HN/Reddit into the same
        # external_signal.json the news pipeline already reads.
        log.info("RSS signal: trusted-outlet RSS scrape every 5 min (parallel).")
        scheduler.add_job(
            safe_run_rss_signal_cycle,
            trigger=IntervalTrigger(minutes=5),
            id="rss_signal_job",
        )

        # Smart unfollow — every 4h, diff /following vs /followers,
        # unfollow non-reciprocal accounts (cap 15/cycle). Keeps the
        # follow-ratio healthy as follow_blast adds ~700-1500/day.
        # Respect list + engage/early_bird/mega rosters are protected.
        log.info("Smart unfollow: prune non-reciprocal follows every 4h (cap 15/cycle).")
        scheduler.add_job(
            safe_run_unfollow_cycle,
            trigger=IntervalTrigger(hours=4),
            id="smart_unfollow_job",
        )

        # Follower-count tracker — every 30 min, scrape /kzer_ai header,
        # log to follower_history.json. Powers the growth scoreboard
        # block injected into news/hotake prompts. Without this signal,
        # the bot can't measure if its decisions are working.
        log.info("Follower tracker: scraping count every 30 min.")
        scheduler.add_job(
            safe_run_follower_tracker_cycle,
            trigger=IntervalTrigger(minutes=30),
            id="follower_tracker_job",
        )

        # X home-feed scout — every 7 min, scrape /home, niche-filter,
        # merge into external_signal.json. Stronger niche signal than
        # search (people we follow + their network reacting RIGHT NOW).
        log.info("X home scout: niche-filtered home-feed scrape every 7 min.")
        scheduler.add_job(
            safe_run_home_scout_cycle,
            trigger=IntervalTrigger(minutes=7),
            id="x_home_scout_job",
        )

        # Chain-reply bot — respond to replies on OUR REPLIES (not just
        # on our original posts, which notify_bot already handles). Cap
        # 4 chain-replies/cycle + max 3 our-turns per thread to prevent
        # infinite ping-pong loops.
        log.info("Chain-reply bot: respond to nested replies every 15 min (cap 4/cycle).")
        scheduler.add_job(
            safe_run_chain_reply_cycle,
            trigger=IntervalTrigger(minutes=15),
            id="chain_reply_job",
        )

        # YouTube brief — daily aggregator that turns 24h of bot activity
        # into a video-script-ready brief. User pivot: bot now feeds a
        # YouTube channel. Hourly idempotent check; daily-state file
        # guards single-run-per-day.
        log.info("YouTube brief: daily content rollup → youtube_brief.md (hourly check).")
        scheduler.add_job(
            safe_run_youtube_brief_cycle,
            trigger=IntervalTrigger(hours=1),
            id="youtube_brief_job",
        )

    # Autonomy audit — print which adapt + push hooks are active so the
    # user can see at a glance what the bot is going to do on its own.
    log.info("=" * 60)
    log.info("AUTONOMY AUDIT — bot self-modifies + auto-pushes the following:")
    log.info("  STRATEGIC ADAPTATION (auto-decides + auto-pushes to git):")
    log.info("    [4h] meta_strategy_agent  → live_strategy.json (caps + cadence + topic focus)")
    log.info("    [3h] strategy_agent       → dynamic_queries / dynamic_accounts")
    log.info("    [3h] evolution_agent      → directives.md / pruned / reinforced")
    log.info("    [4h] self_evolution_agent → bot_self.json (mood / obsession / drift)")
    log.info("    [6h] reflection_agent     → personality.json (per-account dossiers)")
    log.info("    [4h] scout_agent          → dynamic_accounts.json + auto-follows")
    log.info("  REAL-TIME ADAPTATION (no LLM, no push):")
    log.info("    [30m] auto_tune_bot       → real-time velocity gauge")
    log.info("    [1h]  suppression_watch   → shadowban detection + pause")
    log.info("    [2h]  performance.py      → metric scrape + auto-push")
    log.info("    [1h]  daily_digest        → user review doc + auto-push")
    log.info("    [40m] retweet_bot         → daily_news_picks + auto-push")
    log.info("    [1h]  cleanup_bot         → state hygiene")
    log.info("=" * 60)
    log.info("All systems go. Bot is running.")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("Bot stopped.")


if __name__ == "__main__":
    main()

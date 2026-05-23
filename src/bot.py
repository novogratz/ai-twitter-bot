"""Post bot: publishes AI news tweets and philosophy hot takes."""
import json
import os
import random
import re
import time
import traceback
from datetime import date
from .config import MAX_NEWS_PER_DAY, MAX_HOTAKES_PER_DAY, DAILY_STATE_FILE, get_live_cap
from .logger import log
from .agent import generate_tweet
from .hotake_agent import generate_hotake
from .twitter_client import post_tweet, post_thread
from .history import save_tweet
from .engagement_log import log_post, log_hotake
from .humanizer import humanize
from .article_image import fetch_article_image
from .image_gen import make_quote_card


def _live_news_cap() -> int:
    """Live cap from meta_strategy_agent's live_strategy.json, env fallback.

    2026-05-22 PM: user reverted the Friday 2-cap — "i want more than 2
    news". Friday still gets the Top 5 bookmark-bait FORMAT (prompt-side),
    just with the same daily VOLUME as other days.
    """
    return get_live_cap("MAX_NEWS_PER_DAY", MAX_NEWS_PER_DAY)


def _live_hotake_cap() -> int:
    """Live cap from meta_strategy_agent's live_strategy.json, env fallback."""
    return get_live_cap("MAX_HOTAKES_PER_DAY", MAX_HOTAKES_PER_DAY)


THREAD_SEPARATOR = "---THREAD---"
NEWS_POSTS_PER_CYCLE = int(os.environ.get("NEWS_POSTS_PER_CYCLE", "3"))
NEWS_POST_SPACING_SECONDS = int(os.environ.get("NEWS_POST_SPACING_SECONDS", "120"))

# Source-as-self-reply was reverted 2026-04-30 PM (user: "remove the source as
# reply of yourself this is ridiculous.. put it directly in the news if needed").
# URL stays inline in the tweet body — X renders the link card natively.


def _load_daily_state() -> dict:
    """Load persistent daily counters from disk."""
    if os.path.exists(DAILY_STATE_FILE):
        try:
            with open(DAILY_STATE_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"date": None, "news": 0, "hotakes": 0}


def _save_daily_state(state: dict):
    """Persist daily counters to disk (survives restarts)."""
    with open(DAILY_STATE_FILE, "w") as f:
        json.dump(state, f)


def _get_counters() -> tuple[int, int]:
    """Get today's counters, resetting if it's a new day."""
    state = _load_daily_state()
    today = date.today().isoformat()
    if state.get("date") != today:
        state = {"date": today, "news": 0, "hotakes": 0}
        _save_daily_state(state)
    return state["news"], state["hotakes"]


def has_post_slot() -> bool:
    """Cheap cap check for schedulers: true if any post format can still ship.

    Keep this outside `run_bot_cycle()` so main.py can avoid even entering the
    news/hot-take generation path once both daily buckets are full.
    Reads LIVE caps via meta_strategy_agent's live_strategy.json.
    """
    news_count, hotake_count = _get_counters()
    return news_count < _live_news_cap() or hotake_count < _live_hotake_cap()


def post_slot_status() -> str:
    """Human-readable daily post cap state for logs."""
    news_count, hotake_count = _get_counters()
    return f"{news_count}/{_live_news_cap()} news, {hotake_count}/{_live_hotake_cap()} hot takes"


def _increment_counter(counter_name: str):
    """Increment a daily counter and persist."""
    state = _load_daily_state()
    today = date.today().isoformat()
    if state.get("date") != today:
        state = {"date": today, "news": 0, "hotakes": 0}
    state[counter_name] = state.get(counter_name, 0) + 1
    _save_daily_state(state)


def _run_single_bot_cycle() -> bool:
    """Post a Décode (Daily or Weekly), respecting daily limits.
    Returns True if a post was shipped, False if nothing eligible — caller
    uses False to break the burst loop instead of sleeping for nothing."""
    news_count, hotake_count = _get_counters()
    news_cap = _live_news_cap()
    hotake_cap = _live_hotake_cap()
    log.info(f"Today: {news_count}/{news_cap} Décodes, {hotake_count}/{hotake_cap} hot takes")

    if news_count >= news_cap and hotake_count >= hotake_cap:
        log.info("Daily Décode limits reached. Skipping.")
        return False

    can_hotake = hotake_count < hotake_cap
    can_news = news_count < news_cap

    # AI news is the brand backbone. Force the first half of the daily news
    # quota through the AI news path before spending the single AI hot-take slot.
    news_floor_before_hotake = min(3, news_cap)
    if can_news and news_count < news_floor_before_hotake:
        do_hotake = False
    elif not can_news:
        do_hotake = can_hotake
    elif not can_hotake:
        do_hotake = False
    else:
        do_hotake = random.random() < 0.25

    tweet_source = "news"  # which module owns last_source_url for this tweet
    if do_hotake:
        log.info("Generating AI hot take...")
        tweet = generate_hotake()
        if tweet is None:
            log.warning("Hot take failed, falling back to news...")
            if can_news:
                tweet = generate_tweet()
                if tweet:
                    _increment_counter("news")
                    tweet_source = "news"
        else:
            _increment_counter("hotakes")
            tweet = humanize(tweet)
            # Visual policy 2026-04-29 PM (user: "shitty image generated"):
            # NO MORE Pillow quote cards — they look bot-y. Real photos only.
            # Priority: source-article og:image > Wiki og:image > text-only.
            # The article's own hero photo is the most credible visual (it's
            # what a journalist sharing the scoop would surface).
            img_path = None
            src_url = None
            try:
                from .hotake_agent import last_source_url, last_image_topic
                src_url = last_source_url()
                # When a source URL is present X renders a native link-card,
                # which is the visual. Skip image attach so the card shows.
                if not src_url:
                    slug = last_image_topic()
                    if slug:
                        wiki_url = f"https://en.wikipedia.org/wiki/{slug}"
                        img_path = fetch_article_image(wiki_url)
                        if img_path:
                            log.info(f"[HOTAKE] Wiki photo attached for '{slug}': {img_path}")
                    else:
                        log.info("[HOTAKE] No source URL or image slug — text-only")
                else:
                    log.info(f"[HOTAKE] URL inline (X renders link card): {src_url[:80]}")
            except Exception as e:
                log.info(f"[HOTAKE] Image fetch failed (text-only): {e}")
            log.info(f"[HOTAKE] Posting ({len(tweet)} chars): {tweet[:100]}...")
            post_tweet(tweet, image_path=img_path)
            save_tweet(tweet)
            try:
                from .hotake_agent import last_pattern as _last_hotake_pattern
                _pattern = _last_hotake_pattern() or ""
            except Exception:
                _pattern = ""
            log_hotake(tweet, pattern_id=_pattern)
            if img_path:
                try:
                    os.remove(img_path)
                except OSError:
                    pass
            return True
    else:
        log.info("Generating next Décode (Daily or Weekly)...")
        tweet = generate_tweet()
        if tweet:
            _increment_counter("news")
        elif can_hotake:
            log.info("No fresh Décode - trying a hot take instead...")
            tweet = generate_hotake()
            if tweet:
                _increment_counter("hotakes")
                tweet_source = "hotake"

    if tweet is None:
        log.info("No eligible Décode this cycle (all topic/format combos shipped).")
        return False

    # Pull pattern_id from whichever agent generated this tweet (same side-
    # channel as URL/image). News-falls-back-to-hotake must read from hotake.
    try:
        if tweet_source == "hotake":
            from .hotake_agent import last_pattern as _last_news_pattern
        else:
            from .agent import last_pattern as _last_news_pattern
        _news_pattern = _last_news_pattern() or ""
    except Exception:
        _news_pattern = ""

    if THREAD_SEPARATOR in tweet:
        parts = [p.strip() for p in tweet.split(THREAD_SEPARATOR) if p.strip()]
        parts = [humanize(p) for p in parts]
        log.info(f"[THREAD] Got {len(parts)}-tweet thread")
        for i, part in enumerate(parts, 1):
            log.info(f"  [{i}] ({len(part)} chars): {part[:80]}...")
        post_thread(parts)
        save_tweet(tweet)
        log_post(tweet, pattern_id=_news_pattern)
    else:
        tweet = humanize(tweet)
        # Visual policy 2026-04-29 PM (user: "shitty image generated"):
        # NO Pillow quote cards. Article's own og:image first (real journalism
        # photo, the one a journalist sharing the scoop would surface), Wiki
        # photo as fallback when [IMAGE: slug] is set, else text-only.
        img_path = None
        src_url = None
        try:
            # If the news path fell back to a hot take, the URL/topic side-
            # channel lives on hotake_agent, not agent. Pull from the right
            # module or the URL gets dropped and the tweet ships text-only.
            if tweet_source == "hotake":
                from .hotake_agent import last_source_url, last_image_topic
            else:
                from .agent import last_source_url, last_image_topic
            src_url = last_source_url()
            topic = last_image_topic()
            # When a source URL is present, let X render the native link-card.
            # Attaching an image suppresses the card preview, so only attach
            # an image when there's no URL.
            if not src_url and topic:
                wiki_url = f"https://en.wikipedia.org/wiki/{topic}"
                img_path = fetch_article_image(wiki_url)
                if img_path:
                    log.info(f"[NEWS] Wiki photo attached for '{topic}': {img_path}")
            if src_url:
                log.info(f"[NEWS] URL inline (X renders link card): {src_url[:80]}")
            elif not img_path:
                log.info("[NEWS] Text-only post (no source URL, no image slug)")
        except Exception as e:
            log.info(f"[NEWS] Image fallback failed (text-only): {e}")
        # 2026-05-22 PM (user mandate): keep source URL inline in the
        # body — no more self-reply detour. The link card renders on the
        # main post; auto-like-own-tweet (already wired in post_tweet)
        # boosts impressions immediately. Pre-flight URL check still
        # applies: if the model fabricated the URL, strip it so we don't
        # ship a broken link.
        is_decode = (tweet_source == "news" and src_url is not None)
        post_body = tweet
        if is_decode and src_url:
            log.info(f"[NEWS] Model emitted URL: {src_url}")
            try:
                from . import agent as _ag
                # Whitelist check — only allow URLs that came from our
                # injected WEB SEARCH RESULTS / RSS POOL. Catches soft-404s
                # (Reuters returns 200 OK on /article-not-found pages, so a
                # reachability check alone misses fabrications). Skip when
                # no injection happened this cycle so we don't false-strip
                # legitimate Claude-WebSearch URLs.
                injected = getattr(_ag, "_last_injected_urls", None) or set()
                injected_titles = getattr(_ag, "_last_injected_url_titles", None) or {}
                strip_reason = None
                if injected and src_url not in injected:
                    strip_reason = f"not in injected pool ({len(injected)} candidates)"
                elif not _ag.url_is_reachable(src_url):
                    strip_reason = "unreachable / soft-404"
                else:
                    # Coupling check: bullet #1 should share at least one
                    # meaningful entity (≥4-char word) with the URL's title.
                    # Catches "URL is about OpenAI but #1 is about NVIDIA".
                    title = (injected_titles.get(src_url) or "").lower()
                    if title:
                        # All Décodes (top5 daily and weekly) now ship as
                        # numbered bullets — extract bullet #1's text.
                        # Fallback: if no bullet #1 is found (legacy prose
                        # format), use the entire first 500 chars.
                        b1_match = re.search(r"^\s*1\.\s*(.+?)(?:\n\s*2\.|$)", tweet, re.MULTILINE | re.DOTALL)
                        if b1_match:
                            subject_region = b1_match.group(1).lower()
                        else:
                            subject_region = tweet[:500].lower()
                        if subject_region:
                            # Pull entity-ish words from title (≥4 chars, not stopwords)
                            stop = {"this", "that", "with", "from", "into", "about",
                                    "have", "been", "more", "what", "when", "where",
                                    "their", "there", "which", "while", "your", "could",
                                    "would", "should", "will", "well", "than", "some",
                                    "such", "just", "after", "before", "still", "every",
                                    "another", "between"}
                            title_tokens = {w for w in re.findall(r"[a-zA-Z]{4,}", title) if w not in stop}
                            if title_tokens:
                                if not any(t in subject_region for t in title_tokens):
                                    strip_reason = (
                                        f"tweet subject doesn't mention any entity from URL title "
                                        f"({sorted(title_tokens)[:6]} not in subject region)"
                                    )
                if strip_reason:
                    log.info(f"[NEWS] ❌ URL stripped — {strip_reason}: {src_url}")
                    post_body = tweet.replace(src_url, "").rstrip()
                    post_body = re.sub(r"\n+(Source\s*:?\s*)?\s*$", "", post_body).rstrip()
                    src_url = None
                else:
                    log.info(f"[NEWS] ✅ URL validated (pool + reachable + matches #1), keeping inline")
            except Exception as e:
                log.info(f"[NEWS] URL validation failed (keeping link): {e}")
            # When a URL is present, the link card carries the visual.
            # An attached image would suppress the card → text + URL only.
            if src_url:
                img_path = None
        elif is_decode:
            log.info("[NEWS] ⚠️ Décode posting with NO URL (model didn't emit one)")

        log.info(f"[NEWS] Posting ({len(post_body)} chars): {post_body[:100]}...")
        post_tweet(post_body, image_path=img_path)
        save_tweet(tweet)
        # Engagement-log routing must match the actual generator so the
        # bandit attribution stays correct.
        if tweet_source == "hotake":
            log_hotake(tweet, pattern_id=_news_pattern)
        else:
            log_post(tweet, pattern_id=_news_pattern)
        if img_path:
            try:
                os.remove(img_path)
            except OSError:
                pass
    # Successful Décode ship.
    return True


def run_bot_cycle():
    """Burst Décodes up to NEWS_POSTS_PER_CYCLE. Breaks out the moment an
    iteration returns False (no eligible topic/format combo left) so we
    don't sleep 120s after each no-op."""
    count = max(1, NEWS_POSTS_PER_CYCLE)
    for i in range(count):
        if not has_post_slot():
            log.info("[NEWS] No post slot left for burst. Stopping.")
            break
        log.info(f"[NEWS] Décode attempt {i + 1}/{count}")
        shipped = _run_single_bot_cycle()
        if not shipped:
            log.info("[NEWS] Nothing eligible to ship — ending burst early.")
            break
        if i < count - 1:
            log.info(f"[NEWS] Waiting {NEWS_POST_SPACING_SECONDS}s before next Décode.")
            time.sleep(NEWS_POST_SPACING_SECONDS)


def safe_run_bot_cycle():
    """Wrapper that catches errors so the scheduler keeps running.
    Reports outcome to health watchdog so 3 consecutive Safari-touching
    failures across any bots trigger a Safari restart."""
    from . import health
    try:
        run_bot_cycle()
        health.record_success("post")
    except Exception:
        log.error(f"Error during bot cycle: {traceback.format_exc()}")
        health.record_failure("post")


def _run_bot_cycle_in_mode(mode: str):
    """Set the news-mode hint and run the burst. The hint forces
    _next_topic_not_done_today() in agent.py to filter the rotation:
    'daily' → only Daily Décodes, 'weekly' → only Weekly Top 5s."""
    from . import agent as _ag
    prev = _ag.__dict__.get("_news_mode")
    _ag.__dict__["_news_mode"] = mode
    try:
        run_bot_cycle()
    finally:
        if prev is None:
            _ag.__dict__.pop("_news_mode", None)
        else:
            _ag.__dict__["_news_mode"] = prev


def safe_run_daily_news_cycle():
    """Cron handler — 1:00 AM EST every day. Forces daily-only rotation
    so the burst ships 3 Daily Décodes (one per topic) in ~14-18 min."""
    from . import health
    try:
        log.info("[CRON] Daily news burst (1:00 AM EST) — daily mode forced.")
        _run_bot_cycle_in_mode("daily")
        health.record_success("post")
    except Exception:
        log.error(f"Error during daily news cron: {traceback.format_exc()}")
        health.record_failure("post")


def safe_run_weekly_news_cycle():
    """Cron handler — 7:00 AM EST Fridays. Forces weekly-only rotation
    so the burst ships 3 Weekly Top 5s (one per topic) in ~14-18 min."""
    from . import health
    try:
        log.info("[CRON] Weekly news burst (Friday 7:00 AM EST) — weekly mode forced.")
        _run_bot_cycle_in_mode("weekly")
        health.record_success("post")
    except Exception:
        log.error(f"Error during weekly news cron: {traceback.format_exc()}")
        health.record_failure("post")

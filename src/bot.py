"""Post bot: publishes AI news tweets and philosophy hot takes."""
import json
import os
import random
import traceback
from datetime import date
from .config import MAX_NEWS_PER_DAY, MAX_HOTAKES_PER_DAY, DAILY_STATE_FILE
from .logger import log
from .agent import generate_tweet
from .hotake_agent import generate_hotake
from .twitter_client import post_tweet, post_thread
from .history import save_tweet
from .engagement_log import log_post, log_hotake
from .humanizer import humanize
from .article_image import fetch_article_image
from .image_gen import make_quote_card

THREAD_SEPARATOR = "---THREAD---"

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
    """
    news_count, hotake_count = _get_counters()
    return news_count < MAX_NEWS_PER_DAY or hotake_count < MAX_HOTAKES_PER_DAY


def post_slot_status() -> str:
    """Human-readable daily post cap state for logs."""
    news_count, hotake_count = _get_counters()
    return f"{news_count}/{MAX_NEWS_PER_DAY} news, {hotake_count}/{MAX_HOTAKES_PER_DAY} hot takes"


def _increment_counter(counter_name: str):
    """Increment a daily counter and persist."""
    state = _load_daily_state()
    today = date.today().isoformat()
    if state.get("date") != today:
        state = {"date": today, "news": 0, "hotakes": 0}
    state[counter_name] = state.get(counter_name, 0) + 1
    _save_daily_state(state)


def run_bot_cycle():
    """Post a news tweet or hot take, respecting daily limits."""
    news_count, hotake_count = _get_counters()
    log.info(f"Today: {news_count}/{MAX_NEWS_PER_DAY} news, {hotake_count}/{MAX_HOTAKES_PER_DAY} hot takes")

    if news_count >= MAX_NEWS_PER_DAY and hotake_count >= MAX_HOTAKES_PER_DAY:
        log.info("Daily limits reached. Skipping.")
        return

    can_hotake = hotake_count < MAX_HOTAKES_PER_DAY
    can_news = news_count < MAX_NEWS_PER_DAY

    # News is the brand backbone. Force the first half of the daily news quota
    # through the news path before spending the single hot-take slot, otherwise
    # one hot-take miss can make the profile look quiet on actual news.
    news_floor_before_hotake = min(3, MAX_NEWS_PER_DAY)
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
        log.info("Generating AI philosophy hot take...")
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
            return
    else:
        log.info("Searching for AI news...")
        tweet = generate_tweet()
        if tweet:
            _increment_counter("news")
        elif can_hotake:
            log.info("No fresh news - trying a hot take instead...")
            tweet = generate_hotake()
            if tweet:
                _increment_counter("hotakes")
                tweet_source = "hotake"

    if tweet is None:
        log.info("Nothing to post - skipping this cycle.")
        return

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
        log.info(f"[NEWS] Posting ({len(tweet)} chars): {tweet[:100]}...")
        post_tweet(tweet, image_path=img_path)
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

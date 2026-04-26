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

THREAD_SEPARATOR = "---THREAD---"


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

    # Mix: hot takes pull more engagement (memes screenshot, news doesn't), so
    # we let them lead instead of forcing news-first. Roughly 50/50 with a
    # slight news lean — the cap (5/day each) keeps both feeds quality-first.
    # Old news-first policy was forcing low-engagement news posts at session
    # start; killing it lets a banger meme open the day instead.
    if not can_news:
        do_hotake = can_hotake
    elif not can_hotake:
        do_hotake = False
    else:
        do_hotake = random.random() < 0.45

    if do_hotake:
        log.info("Generating AI philosophy hot take...")
        tweet = generate_hotake()
        if tweet is None:
            log.warning("Hot take failed, falling back to news...")
            if can_news:
                tweet = generate_tweet()
                if tweet:
                    _increment_counter("news")
        else:
            _increment_counter("hotakes")
            tweet = humanize(tweet)
            log.info(f"[HOTAKE] ({len(tweet)} chars): {tweet[:100]}...")
            # Hot takes attach a Wikipedia lead-photo as visual anchor when
            # the topic is a real person/company/concept (Musk → Wikipedia
            # photo of Musk, Bitcoin → Bitcoin logo). Wiki og:image is a
            # reliable, public, license-clean source. Falls back to text-only
            # when the topic is too abstract (model emits [IMAGE: SKIP]).
            img_path = None
            try:
                from .hotake_agent import last_image_topic
                slug = last_image_topic()
                if slug:
                    wiki_url = f"https://en.wikipedia.org/wiki/{slug}"
                    img_path = fetch_article_image(wiki_url)
                    if img_path:
                        log.info(f"[HOTAKE] Wiki image attached for '{slug}': {img_path}")
                    else:
                        log.info(f"[HOTAKE] Wiki had no og:image for '{slug}' - text-only")
            except Exception as e:
                log.info(f"[HOTAKE] Image fetch failed (text-only): {e}")
            post_tweet(tweet, image_path=img_path)
            save_tweet(tweet)
            log_hotake(tweet)
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

    if tweet is None:
        log.info("Nothing to post - skipping this cycle.")
        return

    if THREAD_SEPARATOR in tweet:
        parts = [p.strip() for p in tweet.split(THREAD_SEPARATOR) if p.strip()]
        parts = [humanize(p) for p in parts]
        log.info(f"[THREAD] Got {len(parts)}-tweet thread")
        for i, part in enumerate(parts, 1):
            log.info(f"  [{i}] ({len(part)} chars): {part[:80]}...")
        post_thread(parts)
        save_tweet(tweet)
        log_post(tweet)
    else:
        tweet = humanize(tweet)
        log.info(f"Tweet ({len(tweet)} chars): {tweet[:100]}...")
        # News posts attach the article's actual og:image — the same preview
        # picture you'd see if someone shared the link normally. This makes
        # the post look like a real journalist sharing a story, not an AI
        # bot retyping its own words on a slide. The article URL itself
        # never goes in the tweet body (X deboosts off-platform links), but
        # the preview image lives on our timeline as proof-of-source.
        # Falls back to text-only on any fetch failure — never blocks the post.
        img_path = None
        try:
            from .agent import last_source_url
            src_url = last_source_url()
            if src_url:
                img_path = fetch_article_image(src_url)
                if img_path:
                    log.info(f"[NEWS] Article image attached: {img_path}")
                else:
                    log.info(f"[NEWS] No article image for {src_url[:80]} - posting text-only")
            else:
                log.info("[NEWS] No source URL provided - posting text-only")
        except Exception as e:
            log.info(f"[NEWS] Article image fetch failed (text-only): {e}")
        post_tweet(tweet, image_path=img_path)
        save_tweet(tweet)
        log_post(tweet)
        if img_path:
            try:
                os.remove(img_path)
            except OSError:
                pass


def safe_run_bot_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    try:
        run_bot_cycle()
    except Exception:
        log.error(f"Error during bot cycle: {traceback.format_exc()}")

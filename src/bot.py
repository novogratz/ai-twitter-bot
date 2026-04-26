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
from .image_gen import make_quote_card

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
            # Hot takes get a quote-card image for screenshot-worthy feed presence.
            card_path = None
            try:
                card_path = make_quote_card(tweet)
                if card_path:
                    log.info(f"[HOTAKE] Generated quote-card: {card_path}")
            except Exception as e:
                log.info(f"[HOTAKE] Card generation failed (posting text-only): {e}")
            post_tweet(tweet, image_path=card_path)
            save_tweet(tweet)
            log_hotake(tweet)
            # Best-effort cleanup of the temp image
            if card_path:
                try:
                    os.remove(card_path)
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
        # News tweets ship with a quote-card image — same playbook as hot takes.
        # Image posts get more reach + the card carries the brand even when
        # screenshotted off-platform. Best-effort: text-only fallback if PIL
        # is missing or generation fails.
        card_path = None
        try:
            card_path = make_quote_card(tweet)
            if card_path:
                log.info(f"[NEWS] Generated quote-card: {card_path}")
        except Exception as e:
            log.info(f"[NEWS] Card generation failed (posting text-only): {e}")
        post_tweet(tweet, image_path=card_path)
        save_tweet(tweet)
        log_post(tweet)
        if card_path:
            try:
                os.remove(card_path)
            except OSError:
                pass


def safe_run_bot_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    try:
        run_bot_cycle()
    except Exception:
        log.error(f"Error during bot cycle: {traceback.format_exc()}")

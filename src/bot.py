"""Post bot: publishes AI news tweets and philosophy hot takes."""
import json
import os
import random
import re
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

_TRAILING_URL_RE = re.compile(r"\s*https?://\S+\s*$", re.MULTILINE)


def _split_url_from_body(tweet: str, src_url: str) -> str:
    """Strip the trailing source URL out of the tweet body.

    Strategy pivot 2026-04-29: posting the URL inline triggers X's
    outbound-link deboost (~30-50% reach penalty) — confirmed cause of
    the 0-likes pattern on news/hot takes. We post the body alone for
    max algorithmic reach, then attach the source as a self-reply via
    post_thread() so credibility is preserved without the deboost.
    """
    if not src_url:
        return tweet
    # Common case: URL on its own line at the end (current prompt format).
    cleaned = tweet.replace(src_url, "").rstrip()
    # Sweep up any straggler trailing URL (different schemes / whitespace).
    cleaned = _TRAILING_URL_RE.sub("", cleaned).rstrip()
    # Collapse the dangling "\n\n" the URL line left behind.
    return cleaned.rstrip()


def _post_with_source_reply(main_text: str, src_url: str, image_path: str = None):
    """Post main tweet WITHOUT the URL, then self-reply with the source.

    If no src_url is available, falls back to a plain post_tweet() call.
    The source-as-reply pattern is the 2026-04-29 strategy fix for the
    "0 likes on news" problem (X deboosts outbound links inline).
    """
    if not src_url:
        post_tweet(main_text, image_path=image_path)
        return
    # post_thread already does post-first-then-self-reply — exactly the
    # mechanism we need for source attribution. We pass image on the
    # main tweet only (the source-reply is text-only).
    if image_path:
        # post_thread doesn't accept images (yet); fall back to post_tweet
        # for the visual then add the source-reply through a follow-up call.
        # Inline approach: use post_thread with quote-card-as-text-only is
        # worse than visual+reply. So we post the main tweet with the
        # image first, then thread the source via the same UI path.
        post_tweet(main_text, image_path=image_path)
        # Open own profile and reply-to-self with source.
        # post_thread reuses this exact flow — call it with a single
        # tweet to skip step 1 then drop the source as the "second tweet".
        # Simpler: just craft a 2-tweet thread where tweet 1 has been
        # posted manually. We can't easily resume mid-thread, so use a
        # parallel utility: open profile, reply to top tweet with source.
        from .twitter_client import _safari_lock
        from .twitter_client import close_front_tab, _navigate_to_first_tweet, _paste_text, _run_applescript, BOT_PROFILE_URL
        import webbrowser, time as _time
        with _safari_lock:
            _time.sleep(3)
            log.info("[POST] Replying to self with source URL...")
            webbrowser.open(BOT_PROFILE_URL)
            _time.sleep(5)
            _navigate_to_first_tweet()
            _time.sleep(4)
            _run_applescript('''
            tell application "System Events"
                keystroke "r"
            end tell
            ''')
            _time.sleep(2)
            _paste_text(f"Source : {src_url}")
            _time.sleep(1)
            _run_applescript('''
            tell application "System Events"
                keystroke return using command down
            end tell
            ''')
            _time.sleep(3)
            close_front_tab()
            log.info("[POST] Source-reply posted.")
        return
    # No image — use post_thread to handle both posts in one Safari lock.
    post_thread([main_text, f"Source : {src_url}"])


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
            # 2026-04-29 STRATEGY PIVOT: split URL out of main body to bypass
            # X's outbound-link deboost (~30-50% reach penalty), post URL as
            # a self-reply for credibility. Quote card is now ALWAYS attached
            # to the main tweet — no more competing with link-card preview.
            img_path = None
            src_url = None
            try:
                from .hotake_agent import last_source_url, last_image_topic
                src_url = last_source_url()
                if src_url:
                    tweet = _split_url_from_body(tweet, src_url)
                    log.info(f"[HOTAKE] URL split into self-reply (avoids deboost): {src_url[:80]}")
                # Always attach a visual: quote card by default, Wiki image if
                # the agent emitted [IMAGE: slug] AND we can fetch og:image.
                slug = last_image_topic()
                if slug:
                    wiki_url = f"https://en.wikipedia.org/wiki/{slug}"
                    img_path = fetch_article_image(wiki_url)
                    if img_path:
                        log.info(f"[HOTAKE] Wiki image attached for '{slug}': {img_path}")
                if not img_path:
                    img_path = make_quote_card(tweet)
                    if img_path:
                        log.info(f"[HOTAKE] Quote-card attached: {img_path}")
            except Exception as e:
                log.info(f"[HOTAKE] Image fetch failed (text-only): {e}")
            log.info(f"[HOTAKE] Posting ({len(tweet)} chars): {tweet[:100]}...")
            _post_with_source_reply(tweet, src_url, image_path=img_path)
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

    if tweet is None:
        log.info("Nothing to post - skipping this cycle.")
        return

    # Pull pattern_id from the news agent — same side-channel as URL/image.
    try:
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
        # 2026-04-29 STRATEGY PIVOT: split URL out of main body. X deboosts
        # outbound links inline by ~30-50% (confirmed cause of "0 likes on
        # news" pattern). Main tweet ships URL-free with a visual; the URL
        # goes in a self-reply where it still proves the source without
        # eating reach. Quote card is now always attached.
        img_path = None
        src_url = None
        try:
            from .agent import last_source_url, last_image_topic
            src_url = last_source_url()
            topic = last_image_topic()
            if src_url:
                tweet = _split_url_from_body(tweet, src_url)
                log.info(f"[NEWS] URL split into self-reply (avoids deboost): {src_url[:80]}")
            if topic:
                wiki_url = f"https://en.wikipedia.org/wiki/{topic}"
                img_path = fetch_article_image(wiki_url)
                if img_path:
                    log.info(f"[NEWS] Wiki image attached for '{topic}': {img_path}")
            if not img_path:
                img_path = make_quote_card(tweet)
                if img_path:
                    log.info(f"[NEWS] Quote-card attached: {img_path}")
        except Exception as e:
            log.info(f"[NEWS] Image fallback failed (text-only): {e}")
        log.info(f"[NEWS] Posting ({len(tweet)} chars): {tweet[:100]}...")
        _post_with_source_reply(tweet, src_url, image_path=img_path)
        save_tweet(tweet)
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

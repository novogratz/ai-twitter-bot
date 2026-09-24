"""Reading X pages in Safari: feeds, search, profiles, mentions, our latest
post and its replies, plus the blank-page recovery the scrapes feed."""
import json
import os
import subprocess
import threading
import time
import webbrowser
from ..core.config import BOT_PROFILE_URL
from ..core.json_safety import sanitize_for_json
from ..core.logger import log
from ..guards.active_hours import OutsideActiveHours
from . import safari

# Reactive black-screen recovery: track consecutive blank pages.
# When Safari renders an empty app shell (service worker stale state), every
# scrape returns NO_ARTICLES. After N consecutive blanks, trigger a hygiene
# restart without waiting for the scheduled 2h cycle.
_blank_page_lock = threading.Lock()
_blank_recovery_lock = threading.Lock()
_blank_page_count = 0
_home_feed_blank_count = 0
_blank_page_labels: list = []  # labels of the current consecutive-blank run
_BLANK_PAGE_RESTART_THRESHOLD = 3  # lowered 5→3 (2026-06-02): recover from the
                                   # black-screen / stale-page state faster so
                                   # scrapes don't keep returning empty/old data
_HOME_FEED_BLANK_RESTART_THRESHOLD = 2  # home feed fails 2× in a row → restart


def _in_post_restart_grace() -> bool:
    """2026-07-19 storm fix (7 reactive restarts in 2.2h): scrapes queued
    behind a hygiene restart hit a cold, still-warming Safari, go blank, and
    re-trip the threshold ~15 min later — a self-perpetuating restart loop.
    Blanks within BLANK_GRACE_AFTER_RESTART_SECONDS of the last restart are
    EXPECTED and must not count. Env read at call time."""
    grace = int(os.environ.get("BLANK_GRACE_AFTER_RESTART_SECONDS", "120"))
    try:
        from . import safari_hygiene
        return (time.time() - safari_hygiene._last_run_ts()) < grace
    except Exception:
        return False


# Pages that can be LEGITIMATELY empty (no new mentions = a blank mentions
# tab). Their blanks say nothing about Safari's health — never count them.
_LEGIT_EMPTY_LABELS = {"mentions"}


def _trigger_black_screen_recovery(reason_detail: str) -> None:
    """Serialize reactive dark-screen recovery.

    Called from scrape code that often already holds _safari_lock. The RLock
    lets that owner restart Safari immediately; other threads block until the
    recovered x.com page has been warmed and verified.
    """
    if not _blank_recovery_lock.acquire(blocking=False):
        log.info("[SCRAPE] Black-screen recovery already in progress; skipping duplicate trigger.")
        return
    try:
        with safari._safari_lock:
            try:
                from . import safari_hygiene
                ok = safari_hygiene.restart_safari(reason="black_screen_recovery")
                if ok:
                    log.info(f"[SCRAPE] Black-screen recovery completed ({reason_detail}).")
                else:
                    log.warning(f"[SCRAPE] Black-screen recovery skipped/failed ({reason_detail}).")
            except Exception as e:
                log.warning(f"[SCRAPE] Black-screen recovery crashed ({reason_detail}): {e}")
    finally:
        _blank_recovery_lock.release()


def _record_timed_out_scrape(label: str) -> None:
    """Treat repeated Safari JS timeouts like blank X renders."""
    _record_blank_page(is_home_feed="home feed" in label, label=label)


def _record_blank_page(is_home_feed: bool = False, label: str = ""):
    global _blank_page_count, _home_feed_blank_count
    if label in _LEGIT_EMPTY_LABELS:
        return
    if _in_post_restart_grace():
        log.info("[SCRAPE] Blank page within post-restart grace — not counting toward restart threshold.")
        return
    with _blank_page_lock:
        _blank_page_count += 1
        count = _blank_page_count
        _blank_page_labels.append(label or ("home feed" if is_home_feed else "?"))
        del _blank_page_labels[:-_BLANK_PAGE_RESTART_THRESHOLD]
        distinct = len(set(_blank_page_labels))
        if is_home_feed:
            _home_feed_blank_count += 1
            hf_count = _home_feed_blank_count
        else:
            hf_count = 0
    if hf_count >= _HOME_FEED_BLANK_RESTART_THRESHOLD:
        _reset_blank_page_count()
        log.warning(f"[SCRAPE] Home feed blank {hf_count}× in a row — triggering reactive Safari restart.")
        _trigger_black_screen_recovery(f"home_feed_blank_{hf_count}")
    elif count >= _BLANK_PAGE_RESTART_THRESHOLD:
        # A wedged Safari (stale service-worker shell) blanks EVERY page, so
        # a true wedge shows ≥2 distinct labels fast. One page blanking in a
        # loop is that page being legitimately empty — not a reason to bounce
        # Safari (2026-07-19: storms counted mixed legit-empties as wedges).
        if distinct < 2:
            log.info(f"[SCRAPE] {count} consecutive blanks but all on '{_blank_page_labels[-1]}' — "
                     "single-page empty, not a Safari wedge. Holding restart.")
            return
        _reset_blank_page_count()
        log.warning(f"[SCRAPE] {count} consecutive blank pages — triggering reactive Safari restart.")
        _trigger_black_screen_recovery(f"diverse_blank_pages_{count}")


def _reset_blank_page_count():
    global _blank_page_count, _home_feed_blank_count
    with _blank_page_lock:
        _blank_page_count = 0
        _home_feed_blank_count = 0
        del _blank_page_labels[:]


def refresh_feed():
    """Open X home feed and refresh it so new tweets load."""
    with safari._safari_lock:
        log.info("Refreshing X feed...")
        webbrowser.open("https://x.com/home")
        time.sleep(3)
        safari.close_front_tab()


def _scrape_profile_quality() -> dict:
    """Read followers count + bio + name from the CURRENTLY LOADED profile
    tab (no extra navigation). Best-effort: {} on any failure."""
    js = """
    (function() {
        var out = {followers: "", bio: "", name: ""};
        var links = document.querySelectorAll('a[href$="/verified_followers"], a[href$="/followers"]');
        for (var i = 0; i < links.length; i++) {
            var m = (links[i].textContent || "").match(/([\\d.,\\u202f ]+[KkMm]?)/);
            if (m) { out.followers = m[1].trim(); break; }
        }
        var bio = document.querySelector('[data-testid="UserDescription"]');
        if (bio) out.bio = (bio.textContent || "").slice(0, 500);
        var nm = document.querySelector('[data-testid="UserName"]');
        if (nm) out.name = (nm.textContent || "").slice(0, 120);
        return JSON.stringify(out);
    })()
    """
    try:
        raw = safari._run_js(js, 15, log_prefix="[SCRAPE]")
        if raw:
            return json.loads(raw)
    except json.JSONDecodeError:
        pass
    return {}


def _scrape_tweets_from_page(label: str, max_tweets: int = 10, text_limit: int = 200):
    """Run JS on the current Safari page to extract tweets. Returns list of
    dicts; each `text` is cut to `text_limit` characters."""
    import json as _json

    js_code = """
    (function() {
        function extractFromLabel(label) {
            var m = (label || '').match(/(\\d[\\d,\\.KMkm]*)/);
            if (!m) return 0;
            var s = m[1].replace(/,/g, '').toLowerCase();
            if (s.indexOf('k') !== -1) return Math.round(parseFloat(s) * 1000);
            if (s.indexOf('m') !== -1) return Math.round(parseFloat(s) * 1000000);
            return parseInt(s, 10) || 0;
        }
        function extractCount(article, testid) {
            var btn = article.querySelector('[data-testid="' + testid + '"]');
            if (!btn) return 0;
            var label = btn.getAttribute('aria-label') || '';
            var m = label.match(/(\\d[\\d,\\.KMkm]*)/);
            if (!m) return 0;
            var s = m[1].replace(/,/g, '').toLowerCase();
            if (s.indexOf('k') !== -1) return Math.round(parseFloat(s) * 1000);
            if (s.indexOf('m') !== -1) return Math.round(parseFloat(s) * 1000000);
            return parseInt(s, 10) || 0;
        }
        function detectTranslatedLang(article) {
            var html = article.innerHTML;
            if (html.indexOf('Afficher l\\'original') !== -1) return 'en';
            if (html.indexOf('Show original') !== -1) return 'fr';
            return '';
        }
        function detectReplyArticle(article, tweetText) {
            var full = article.innerText || '';
            if ((tweetText || '').trim().indexOf('@') === 0) return true;
            return /Replying to|En réponse à|En reponse a|Répond à|Repond a/i.test(full);
        }
        var tweets = [];
        var articles = document.querySelectorAll('article[data-testid="tweet"]');
        if (articles.length === 0) return 'NO_ARTICLES';
        for (var i = 0; i < Math.min(articles.length, MAX_TWEETS); i++) {
            var a = articles[i];
            var textEl = a.querySelector('[data-testid="tweetText"]');
            var text = textEl ? textEl.textContent.trim() : '';
            if (!text) continue;
            var links = a.querySelectorAll('a[href*="/status/"]');
            var url = '';
            for (var l of links) {
                var h = l.getAttribute('href');
                if (h && h.match(/\\/status\\/\\d+$/)) {
                    url = 'https://x.com' + h;
                    break;
                }
            }
            var authorEl = a.querySelector('[data-testid="User-Name"] a[role="link"]');
            var author = authorEl ? authorEl.textContent.trim().replace('@','') : '';
            var likes = extractCount(a, 'like');
            var replies = extractCount(a, 'reply');
            var tl = detectTranslatedLang(a);
            var isReply = detectReplyArticle(a, text);
            var timeEl = a.querySelector('time[datetime]');
            var ts = timeEl ? timeEl.getAttribute('datetime') : '';
            // Views: the analytics link's aria-label carries the count
            // ("12.3K views"). Powers performance.scrape_own_metrics.
            var views = 0;
            var an = a.querySelector('a[href*="/analytics"]');
            if (an) views = extractFromLabel(an.getAttribute('aria-label') || '');
            if (url) tweets.push(JSON.stringify({u: url, t: text.substring(0, TEXT_LIMIT), a: author || 'unknown', l: likes, r: replies, v: views, tl: tl, ir: isReply, ts: ts}));
        }
        if (tweets.length === 0) return 'ARTICLES_' + articles.length + '_NO_URLS';
        return '[' + tweets.join(',') + ']';
    })()
    """.replace("MAX_TWEETS", str(max_tweets)).replace("TEXT_LIMIT", str(int(text_limit)))

    # Activate Safari first. Without this, "current tab of front window" can
    # block waiting on a different app being frontmost — that was causing the
    # 15s timeouts to dominate the entire engagement loop.
    def _try_once(timeout_s: int) -> str:
        return safari._run_js(js_code, timeout_s, log_prefix="[SCRAPE]",
                              activate=True, raise_timeout=True)

    raw = ""
    try:
        # First attempt: 30s. Safari can be slow on first JS injection after
        # a fresh tab load (was 15s — too tight, dominant failure mode).
        try:
            raw = _try_once(30)
        except subprocess.TimeoutExpired:
            # One retry: bring Safari to front explicitly, settle, try again.
            log.info(f"[SCRAPE] First JS attempt timed out for {label}; retrying after activate.")
            safari._run_applescript('tell application "Safari" to activate')
            time.sleep(2)
            try:
                raw = _try_once(30)
            except subprocess.TimeoutExpired:
                log.info(f"[SCRAPE] Both attempts timed out for {label}.")
                _record_timed_out_scrape(label)
                return []

        # The page script always answers, so "" means osascript failed: the
        # failure is logged by _run_js and is not a blank page.
        if not raw:
            log.info(f"[SCRAPE] JS failed for {label}.")
            return []
        if raw == 'NO_ARTICLES':
            log.info(f"[SCRAPE] No articles on {label} (page not loaded?)")
            _record_blank_page(is_home_feed="home feed" in label, label=label)
            return []
        if raw.startswith('ARTICLES_'):
            log.info(f"[SCRAPE] {label}: {raw}")
            _record_blank_page(is_home_feed="home feed" in label, label=label)
            return []

        data = sanitize_for_json(_json.loads(raw))
        tweets = [{
            "url": t["u"],
            "text": t["t"],
            "author": t["a"],
            "likes": int(t.get("l") or 0),
            "replies": int(t.get("r") or 0),
            "translated_from": t.get("tl") or "",
            "is_reply": bool(t.get("ir") or False),
            # Bug 2026-06-05 (retweets 140/day → 0): the JS extracted the
            # <time datetime> but this mapping DROPPED it, so every candidate
            # had unknown age and the hard 48h freshness gate skipped 100% of
            # feed/search candidates ("No viable candidates this cycle").
            "timestamp": t.get("ts") or "",
            "views": int(t.get("v") or 0),
        } for t in data]
        _reset_blank_page_count()
        log.info(f"[SCRAPE] Found {len(tweets)} tweets on {label}")
        return tweets
    except OutsideActiveHours:
        raise
    except Exception as e:
        log.info(f"[SCRAPE] Exception for {label}: {e}")
        _record_blank_page(is_home_feed="home feed" in label, label=label)
        return []


def is_own_post(tweet: dict) -> bool:
    """Authoritative ownership check for scraped tweets (2026-06-07).

    The scraper's `author` field is the DISPLAY NAME ("The AI Therapist"),
    not the @handle — five bots compared it against BOT_HANDLE and silently
    classified every own post as foreign (the boost engine never once picked
    a banger; suppression_watch measured nothing). The URL is ground truth:
    own posts and own QRTs live under /BOT_HANDLE/status/; retweets of
    others on our profile carry the ORIGINAL author's URL and are correctly
    excluded."""
    from ..core.config import BOT_HANDLE
    url = (tweet.get("url") or "").lower()
    return f"x.com/{BOT_HANDLE.lower()}/status/" in url


def _profile_visit_allowed(username: str) -> bool:
    """Operator mandate 2026-06-07 PM: NO profile visits for discovery —
    the only scrape surfaces are @TheBTCTherapist (the main account), the
    Home feed (For You + Following tab), and search terms. Our own profile
    stays visitable (boost/pin/metrics/with_replies callers need it). Env
    read at CALL time (side-effect gate — never an import-time constant)."""
    from ..core.config import BOT_HANDLE
    base = (username or "").strip().lstrip("@").split("/")[0].lower()
    if not base:
        return False
    if base == BOT_HANDLE.lower():
        return True  # own profile (incl. BOT_HANDLE/with_replies callers)
    allow = os.environ.get("PROFILE_VISIT_ALLOWLIST", "TheBTCTherapist,Graphseo")
    return base in {h.strip().lstrip("@").lower() for h in allow.split(",") if h.strip()}


def scrape_profile_tweets(username: str, max_tweets: int = 5):
    """Visit a profile and scrape their recent tweet URLs and text.

    Gated by `_profile_visit_allowed`: non-allowlisted profiles return []
    BEFORE any Safari work — discovery lives on home/following/search."""
    if not _profile_visit_allowed(username):
        log.info(f"[SCRAPE] profile visit blocked (home/search-only mandate): @{username}")
        return []
    with safari._safari_lock:
        profile_url = f"https://x.com/{username}"
        log.info(f"[SCRAPE] Visiting profile: {profile_url}")
        webbrowser.open(profile_url)
        time.sleep(8)
        safari._scroll_page()

        tweets = _scrape_tweets_from_page(f"@{username}", max_tweets)
        safari.close_front_tab()
        return tweets


def scrape_mentions(max_tweets: int = 20):
    """Scrape the mentions notifications tab — tweets that mention/reply to
    us anywhere on X. Feeds the debate engine (operator 2026-07-19: 'more
    debates... reply to other people replies and get her on a roll'). The
    mentions tab renders standard tweet articles, so the shared page scraper
    applies; best-effort [] on any failure."""
    with safari._safari_lock:
        log.info("[SCRAPE] Opening mentions notifications...")
        webbrowser.open("https://x.com/notifications/mentions")
        time.sleep(8)
        for _ in range(2):
            safari._scroll_page()
        tweets = _scrape_tweets_from_page("mentions", max_tweets)
        safari.close_front_tab()
        return tweets


def scrape_home_feed(max_tweets: int = 15):
    """Scrape tweets from the home feed (For You / algorithmic)."""
    with safari._safari_lock:
        log.info("[SCRAPE] Opening home feed...")
        webbrowser.open("https://x.com/home")
        time.sleep(8)

        # Scroll deep — reply to everything means we need to surface many tweets.
        # Each scroll reveals ~8-12 posts; cap at 15 scrolls to stay bounded.
        for _ in range(max(4, min(15, max_tweets // 7))):
            safari._scroll_page()

        tweets = _scrape_tweets_from_page("home feed", max_tweets)
        safari.close_front_tab()
        return tweets


def scrape_following_feed(max_tweets: int = 15):
    """Scrape the chronological 'Following' tab — only accounts we follow.

    The Following tab is a JS-rendered tab on /home (not its own URL). We open
    /home and click the 'Following' tab via JS before scraping. Falls back to
    whatever loaded if the tab can't be located.
    """
    with safari._safari_lock:
        log.info("[SCRAPE] Opening Following feed...")
        webbrowser.open("https://x.com/home")
        time.sleep(8)

        # Click the "Following" tab.
        click_js = """
        (function() {
            var tabs = document.querySelectorAll('[role="tab"]');
            for (var i = 0; i < tabs.length; i++) {
                var t = tabs[i].textContent.trim().toLowerCase();
                if (t === 'following' || t === 'abonnements' || t === 'suivi(e)s') {
                    tabs[i].click();
                    return 'CLICKED';
                }
            }
            return 'NO_TAB';
        })()
        """
        safari._run_js(click_js, 8, log_prefix="[SCRAPE]")

        time.sleep(4)
        # Scroll proportionally to the requested depth (same as home feed).
        for _ in range(max(2, min(8, max_tweets // 12))):
            safari._scroll_page()

        tweets = _scrape_tweets_from_page("following feed", max_tweets)
        safari.close_front_tab()
        return tweets


def scrape_x_search(query: str, max_tweets: int = 10, tab: str = "top", text_limit: int = 200):
    """Search X and scrape results, each text cut to `text_limit` characters.

    tab: "live" = chronological (default, current behavior), "top" = X's hot/algorithmic
    ranking. Use "top" to surface tweets that ALREADY have engagement (avoids the
    dead-tweet filter dropping everything).
    """
    import urllib.parse
    with safari._safari_lock:
        f_param = "top" if tab == "top" else "live"
        search_url = f"https://x.com/search?q={urllib.parse.quote(query)}&src=typed_query&f={f_param}"
        log.info(f"[SCRAPE] Searching X ({f_param}) for: {query}")
        webbrowser.open(search_url)
        time.sleep(8)
        safari._scroll_page()
        safari._scroll_page()

        tweets = _scrape_tweets_from_page(f"search '{query}' ({f_param})", max_tweets, text_limit)
        safari.close_front_tab()
        return tweets


def scrape_own_tweet_and_replies():
    """Visit own profile, open latest tweet, scrape the tweet text and reply texts.
    Returns {"own_tweet": str, "replies": [{"user": str, "text": str}]} or None."""
    with safari._safari_lock:
        log.info("[REPLYBACK] Opening own profile...")
        webbrowser.open(BOT_PROFILE_URL)
        time.sleep(5)

        log.info("[REPLYBACK] Opening latest tweet...")
        safari._navigate_to_first_tweet()
        time.sleep(5)

        # Scroll down to load replies
        safari._run_applescript('''
        tell application "System Events"
            repeat 3 times
                key code 125
                delay 0.5
            end repeat
        end tell
        ''')
        time.sleep(2)

        js_code = r"""
        (function() {
            var articles = document.querySelectorAll('article[data-testid="tweet"]');
            if (articles.length < 2) return JSON.stringify({own_tweet: '', replies: []});
            var ownEl = articles[0].querySelector('[data-testid="tweetText"]');
            var ownText = ownEl ? ownEl.textContent.trim() : '';
            var replies = [];
            for (var i = 1; i < Math.min(articles.length, 8); i++) {
                var a = articles[i];
                var textEl = a.querySelector('[data-testid="tweetText"]');
                var text = textEl ? textEl.textContent.trim() : '';
                if (!text) continue;
                var userEl = a.querySelector('[data-testid="User-Name"] a[role="link"]');
                var user = userEl ? userEl.textContent.trim() : '';
                var url = '';
                var links = a.querySelectorAll('a[href*="/status/"]');
                for (var l of links) {
                    var h = l.getAttribute('href');
                    if (h && h.match(/\/status\/\d+$/)) {
                        url = 'https://x.com' + h;
                        break;
                    }
                }
                replies.push({user: user, text: text.substring(0, 200), url: url});
            }
            return JSON.stringify({own_tweet: ownText.substring(0, 200), replies: replies});
        })()
        """
        import json
        try:
            raw = safari._run_js(js_code, 30, log_prefix="[REPLYBACK]", activate=True)
            if raw:
                data = json.loads(raw)
                log.info(f"[REPLYBACK] Found {len(data.get('replies', []))} replies on latest tweet")
                safari.close_front_tab()
                return data
        except json.JSONDecodeError as e:
            log.info(f"[REPLYBACK] Scraping failed: {e}")

        safari.close_front_tab()
        return None

"""Browser automation for X/Twitter via Safari + AppleScript (macOS only)."""
import subprocess
import threading
import time
import urllib.parse
import webbrowser
from .config import BOT_PROFILE_URL, MAX_RETRIES, RETRY_DELAY_SECONDS
from .logger import log

# Global lock: only one bot can use Safari at a time.
# Without this, the reply bot and engage bot type over each other.
_safari_lock = threading.Lock()


def _run_applescript(script: str, retries: int = 1) -> bool:
    """Run an AppleScript command with optional retries. Returns True on success."""
    for attempt in range(retries):
        try:
            subprocess.run(["osascript", "-e", script], check=True,
                           capture_output=True, text=True)
            return True
        except subprocess.CalledProcessError:
            if attempt < retries - 1:
                log.warning(f"AppleScript failed (attempt {attempt + 1}/{retries}), retrying...")
                time.sleep(RETRY_DELAY_SECONDS)
    return False


def _escape_for_applescript(text: str) -> str:
    """Escape special characters for AppleScript string literals."""
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _paste_text(text: str):
    """Copy text to clipboard and paste it. Handles accented characters correctly."""
    escaped = _escape_for_applescript(text)
    script = f'''
    set the clipboard to "{escaped}"
    delay 0.3
    tell application "System Events"
        keystroke "v" using command down
    end tell
    '''
    _run_applescript(script)


def _navigate_to_first_tweet():
    """Use Tab+Enter to navigate to the first tweet on a profile/page."""
    script = '''
    tell application "System Events"
        keystroke tab
        delay 0.2
        keystroke tab
        delay 0.2
        keystroke tab
        delay 0.2
        keystroke return
    end tell
    '''
    _run_applescript(script)


def close_front_tab():
    """Close the frontmost Safari tab to save memory."""
    script = '''
    tell application "Safari"
        if (count of windows) > 0 then
            tell front window
                if (count of tabs) > 1 then
                    close current tab
                end if
            end tell
        end if
    end tell
    '''
    if _run_applescript(script):
        log.debug("Tab closed.")


def post_tweet(text: str, image_path: str = None):
    """Open Twitter and auto-post. If `image_path` is given, attaches the PNG.

    Without image: uses the lightweight intent URL (text only).
    With image: uses the full /compose/post composer + clipboard paste — the
    intent URL doesn't support media uploads.
    """
    with _safari_lock:
        if image_path:
            _post_tweet_with_image(text, image_path)
            return

        url = "https://x.com/intent/post?" + urllib.parse.urlencode({"text": text})
        log.info("Opening Twitter in your browser...")
        webbrowser.open(url)
        time.sleep(4)

        script = '''
        tell application "System Events"
            keystroke return using command down
        end tell
        '''
        log.info("Auto-clicking Post...")
        _run_applescript(script)
        time.sleep(2)
        log.info("Tweet posted!")
        close_front_tab()


def _post_tweet_with_image(text: str, image_path: str):
    """Compose a tweet with an attached image. Caller must already hold _safari_lock."""
    import os as _os
    if not _os.path.exists(image_path):
        log.info(f"[POST] Image not found at {image_path} — falling back to text-only.")
        # Fall back to text-only via the intent flow
        url = "https://x.com/intent/post?" + urllib.parse.urlencode({"text": text})
        webbrowser.open(url)
        time.sleep(4)
        _run_applescript('tell application "System Events" to keystroke return using command down')
        time.sleep(2)
        close_front_tab()
        return

    log.info(f"[POST] Composing tweet with image {image_path}...")
    webbrowser.open("https://x.com/compose/post")
    time.sleep(6)  # composer needs a moment to fully render

    # Step 1: paste the text (focus is auto on the textarea on /compose/post)
    _paste_text(text)
    time.sleep(1)

    # Step 2: copy the PNG to the clipboard, then Cmd+V to attach.
    abs_path = _os.path.abspath(image_path)
    copy_script = f'set the clipboard to (read POSIX file "{abs_path}" as «class PNGf»)'
    if not _run_applescript(copy_script):
        log.info("[POST] Could not copy image to clipboard — posting text-only.")
    else:
        time.sleep(0.5)
        _run_applescript('tell application "System Events" to keystroke "v" using command down')
        time.sleep(3)  # X needs a few seconds to upload + render the image preview

    # Step 3: submit
    _run_applescript('tell application "System Events" to keystroke return using command down')
    time.sleep(3)
    log.info("[POST] Tweet with image posted!")
    close_front_tab()


def refresh_feed():
    """Open X home feed and refresh it so new tweets load."""
    with _safari_lock:
        log.info("Refreshing X feed...")
        webbrowser.open("https://x.com/home")
        time.sleep(3)
        close_front_tab()


def like_tweet():
    """Like the currently open tweet using the 'l' keyboard shortcut."""
    script = '''
    tell application "System Events"
        keystroke "l"
    end tell
    '''
    log.info("Liking tweet...")
    if _run_applescript(script):
        time.sleep(1)
        log.info("Tweet liked!")
    else:
        log.info("Failed to like tweet, continuing...")


def reply_to_tweet(tweet_url: str, reply_text: str):
    """Open a tweet, like it, click reply, type the reply, and submit."""
    with _safari_lock:
        # Make sure Safari is focused first
        _run_applescript('''
        tell application "Safari" to activate
        ''')
        time.sleep(1)

        log.info(f"Opening tweet: {tweet_url}")
        webbrowser.open(tweet_url)
        time.sleep(8)  # Wait longer for tweet page to fully load

        # Make sure Safari is in front
        _run_applescript('''
        tell application "Safari" to activate
        ''')
        time.sleep(1)

        # Like the tweet first (double notification for the author)
        like_tweet()
        time.sleep(1)

        # Click reply
        log.info("Clicking reply...")
        _run_applescript('''
        tell application "System Events"
            keystroke "r"
        end tell
        ''')
        time.sleep(4)  # Wait for reply box to open

        # Paste the reply (clipboard handles accents correctly)
        log.info("Pasting reply...")
        _paste_text(reply_text)
        time.sleep(3)  # Wait for paste to complete

        # Submit with Cmd+Enter
        log.info("Submitting reply...")
        _run_applescript('''
        tell application "System Events"
            keystroke return using command down
        end tell
        ''')
        time.sleep(3)  # Wait for submission
        log.info("Reply posted!")
        close_front_tab()


def quote_tweet(tweet_url: str, comment: str):
    """Quote tweet by posting a new tweet with the tweet URL embedded."""
    with _safari_lock:
        full_text = f"{comment}\n\n{tweet_url}"
        url = "https://x.com/intent/post?" + urllib.parse.urlencode({"text": full_text})
        log.info(f"Quote tweeting: {tweet_url}")
        webbrowser.open(url)
        time.sleep(4)

        log.info("Posting quote tweet...")
        _run_applescript('''
        tell application "System Events"
            keystroke return using command down
        end tell
        ''')
        time.sleep(2)
        log.info("Quote tweet posted!")
        close_front_tab()


def follow_account(username: str):
    """Visit a user's profile and click the Follow button."""
    with _safari_lock:
        profile_url = f"https://x.com/{username}"
        log.info(f"[FOLLOW] Visiting profile: {profile_url}")
        webbrowser.open(profile_url)
        time.sleep(5)

        follow_script = '''
        tell application "Safari"
            do JavaScript "
                var btns = document.querySelectorAll('[data-testid=\"placementTracking\"] [role=\"button\"]');
                for (var b of btns) {
                    if (b.textContent.trim() === 'Follow') { b.click(); break; }
                }
            " in current tab of front window
        end tell
        '''
        if _run_applescript(follow_script):
            time.sleep(2)
            log.info(f"[FOLLOW] Followed @{username}!")
        else:
            log.info(f"[FOLLOW] Could not follow @{username} via JS, skipping.")
        close_front_tab()


def visit_profile_and_like(username: str, like_count: int = 2):
    """Visit a user's profile and like their latest tweets for reciprocity."""
    with _safari_lock:
        profile_url = f"https://x.com/{username}"
        log.info(f"Visiting profile: {profile_url}")
        webbrowser.open(profile_url)
        time.sleep(5)

        log.info(f"Opening latest tweet and liking {like_count} tweets...")
        _navigate_to_first_tweet()
        time.sleep(3)

        like_tweet()
        for _ in range(like_count - 1):
            time.sleep(1)
            _run_applescript('''
            tell application "System Events"
                keystroke "j"
            end tell
            ''')
            time.sleep(1)
            like_tweet()

        time.sleep(1)
        close_front_tab()


def _scrape_tweets_from_page(label: str, max_tweets: int = 10):
    """Run JS on the current Safari page to extract tweets. Returns list of dicts."""
    import json as _json
    import tempfile
    import os

    # Write JS to temp file to avoid AppleScript quote escaping hell
    js_code = """
    (function() {
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
            if (url) tweets.push(JSON.stringify({u: url, t: text.substring(0, 200), a: author || 'unknown', l: likes, r: replies}));
        }
        if (tweets.length === 0) return 'ARTICLES_' + articles.length + '_NO_URLS';
        return '[' + tweets.join(',') + ']';
    })()
    """.replace("MAX_TWEETS", str(max_tweets))

    # Write JS to temp file
    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False)
    tmp.write(js_code)
    tmp.close()

    # Activate Safari first. Without this, "current tab of front window" can
    # block waiting on a different app being frontmost — that was causing the
    # 15s timeouts to dominate the entire engagement loop.
    applescript = f'''
    tell application "Safari" to activate
    set jsCode to (read POSIX file "{tmp.name}")
    tell application "Safari"
        set result to do JavaScript jsCode in current tab of front window
    end tell
    '''

    def _try_once(timeout_s: int):
        return subprocess.run(
            ["osascript", "-e", applescript],
            capture_output=True, text=True, timeout=timeout_s,
        )

    raw = ""
    result = None
    try:
        # First attempt: 30s. Safari can be slow on first JS injection after
        # a fresh tab load (was 15s — too tight, dominant failure mode).
        try:
            result = _try_once(30)
        except subprocess.TimeoutExpired:
            # One retry: bring Safari to front explicitly, settle, try again.
            log.info(f"[SCRAPE] First JS attempt timed out for {label}; retrying after activate.")
            _run_applescript('tell application "Safari" to activate')
            time.sleep(2)
            try:
                result = _try_once(30)
            except subprocess.TimeoutExpired:
                log.info(f"[SCRAPE] Both attempts timed out for {label}.")
                return []

        os.unlink(tmp.name)

        raw = result.stdout.strip()
        if result.returncode != 0:
            log.info(f"[SCRAPE] JS failed for {label}: {result.stderr[:200]}")
            return []
        if not raw or raw == 'NO_ARTICLES':
            log.info(f"[SCRAPE] No articles on {label} (page not loaded?)")
            return []
        if raw.startswith('ARTICLES_'):
            log.info(f"[SCRAPE] {label}: {raw}")
            return []

        data = _json.loads(raw)
        tweets = [{
            "url": t["u"],
            "text": t["t"],
            "author": t["a"],
            "likes": int(t.get("l") or 0),
            "replies": int(t.get("r") or 0),
        } for t in data]
        log.info(f"[SCRAPE] Found {len(tweets)} tweets on {label}")
        return tweets
    except Exception as e:
        log.info(f"[SCRAPE] Exception for {label}: {e}")
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
        return []


def _scroll_page():
    """Scroll down the page to load more content."""
    _run_applescript('''
    tell application "System Events"
        repeat 5 times
            key code 125
            delay 0.4
        end repeat
    end tell
    ''')
    time.sleep(2)


def scrape_profile_tweets(username: str, max_tweets: int = 5):
    """Visit a profile and scrape their recent tweet URLs and text."""
    with _safari_lock:
        profile_url = f"https://x.com/{username}"
        log.info(f"[SCRAPE] Visiting profile: {profile_url}")
        webbrowser.open(profile_url)
        time.sleep(8)
        _scroll_page()

        tweets = _scrape_tweets_from_page(f"@{username}", max_tweets)
        close_front_tab()
        return tweets


def scrape_home_feed(max_tweets: int = 15):
    """Scrape tweets from the home feed (For You / algorithmic)."""
    with _safari_lock:
        log.info("[SCRAPE] Opening home feed...")
        webbrowser.open("https://x.com/home")
        time.sleep(8)

        # Scroll down a LOT to load many tweets
        _scroll_page()
        _scroll_page()

        tweets = _scrape_tweets_from_page("home feed", max_tweets)
        close_front_tab()
        return tweets


def scrape_following_feed(max_tweets: int = 15):
    """Scrape the chronological 'Following' tab — only accounts we follow.

    The Following tab is a JS-rendered tab on /home (not its own URL). We open
    /home and click the 'Following' tab via JS before scraping. Falls back to
    whatever loaded if the tab can't be located.
    """
    with _safari_lock:
        log.info("[SCRAPE] Opening Following feed...")
        webbrowser.open("https://x.com/home")
        time.sleep(8)

        # Click the "Following" tab. Written to a temp file to avoid AppleScript quote-hell.
        import tempfile as _tf
        import os as _os
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
        tmp = _tf.NamedTemporaryFile(mode='w', suffix='.js', delete=False)
        tmp.write(click_js)
        tmp.close()
        applescript = f'''
        set jsCode to (read POSIX file "{tmp.name}")
        tell application "Safari"
            do JavaScript jsCode in current tab of front window
        end tell
        '''
        try:
            subprocess.run(["osascript", "-e", applescript],
                           capture_output=True, text=True, timeout=8)
        except Exception as e:
            log.info(f"[SCRAPE] Could not click Following tab: {e}")
        finally:
            try:
                _os.unlink(tmp.name)
            except OSError:
                pass

        time.sleep(4)
        _scroll_page()
        _scroll_page()

        tweets = _scrape_tweets_from_page("following feed", max_tweets)
        close_front_tab()
        return tweets


def scrape_x_search(query: str, max_tweets: int = 10, tab: str = "live"):
    """Search X and scrape results.

    tab: "live" = chronological (default, current behavior), "top" = X's hot/algorithmic
    ranking. Use "top" to surface tweets that ALREADY have engagement (avoids the
    dead-tweet filter dropping everything).
    """
    import urllib.parse
    with _safari_lock:
        f_param = "top" if tab == "top" else "live"
        search_url = f"https://x.com/search?q={urllib.parse.quote(query)}&src=typed_query&f={f_param}"
        log.info(f"[SCRAPE] Searching X ({f_param}) for: {query}")
        webbrowser.open(search_url)
        time.sleep(8)
        _scroll_page()
        _scroll_page()

        tweets = _scrape_tweets_from_page(f"search '{query}' ({f_param})", max_tweets)
        close_front_tab()
        return tweets


def post_thread(tweets: list[str]):
    """Post a thread by posting the first tweet, then replying to it."""
    if not tweets:
        return

    with _safari_lock:
        log.info(f"[THREAD] Posting tweet 1/{len(tweets)}...")
        # Post first tweet inline (no nested lock)
        url = "https://x.com/intent/post?" + urllib.parse.urlencode({"text": tweets[0]})
        webbrowser.open(url)
        time.sleep(4)
        _run_applescript('''
        tell application "System Events"
            keystroke return using command down
        end tell
        ''')
        time.sleep(2)
        close_front_tab()

        if len(tweets) < 2:
            return

        time.sleep(3)
        log.info("[THREAD] Opening own profile to find the tweet...")
        webbrowser.open(BOT_PROFILE_URL)
        time.sleep(5)

        _navigate_to_first_tweet()
        time.sleep(4)

        for i, tweet_text in enumerate(tweets[1:], start=2):
            log.info(f"[THREAD] Posting tweet {i}/{len(tweets)}...")

            _run_applescript('''
            tell application "System Events"
                keystroke "r"
            end tell
            ''')
            time.sleep(2)

            _paste_text(tweet_text)
            time.sleep(1)

            _run_applescript('''
            tell application "System Events"
                keystroke return using command down
            end tell
            ''')
            time.sleep(3)
            log.info(f"[THREAD] Tweet {i} posted!")

        close_front_tab()
        log.info("[THREAD] Thread complete!")


def retweet_own_latest():
    """Visit own profile and retweet the latest tweet for extra exposure."""
    with _safari_lock:
        log.info("[BOOST] Opening own profile to retweet latest tweet...")
        webbrowser.open(BOT_PROFILE_URL)
        time.sleep(5)

        _navigate_to_first_tweet()
        time.sleep(3)

        script = '''
        tell application "System Events"
            keystroke "t"
        end tell
        '''
        if _run_applescript(script):
            time.sleep(1)
            _run_applescript('''
            tell application "System Events"
                keystroke return
            end tell
            ''')
            time.sleep(2)
            log.info("[BOOST] Retweeted own latest tweet!")
        else:
            log.info("[BOOST] Failed to retweet.")
        close_front_tab()


def like_own_tweet_replies():
    """Visit own profile, open latest tweet, and like replies to build loyalty."""
    with _safari_lock:
        log.info("[NOTIFY] Opening own profile...")
        webbrowser.open(BOT_PROFILE_URL)
        time.sleep(5)

        log.info("[NOTIFY] Opening latest tweet...")
        _navigate_to_first_tweet()
        time.sleep(4)

        log.info("[NOTIFY] Liking replies...")
        _run_applescript('''
        tell application "System Events"
            repeat 8 times
                keystroke "j"
                delay 0.5
                keystroke "l"
                delay 0.8
            end repeat
        end tell
        ''')
        time.sleep(2)
        log.info("[NOTIFY] Liked up to 8 replies!")
        close_front_tab()


def scrape_own_tweet_and_replies():
    """Visit own profile, open latest tweet, scrape the tweet text and reply texts.
    Returns {"own_tweet": str, "replies": [{"user": str, "text": str}]} or None."""
    with _safari_lock:
        log.info("[REPLYBACK] Opening own profile...")
        webbrowser.open(BOT_PROFILE_URL)
        time.sleep(5)

        log.info("[REPLYBACK] Opening latest tweet...")
        _navigate_to_first_tweet()
        time.sleep(5)

        # Scroll down to load replies
        _run_applescript('''
        tell application "System Events"
            repeat 3 times
                key code 125
                delay 0.5
            end repeat
        end tell
        ''')
        time.sleep(2)

        js_script = '''
        tell application "Safari" to activate
        tell application "Safari"
            set result to do JavaScript "
                (function() {
                    var articles = document.querySelectorAll('article[data-testid=\\"tweet\\"]');
                    if (articles.length < 2) return JSON.stringify({own_tweet: '', replies: []});
                    var ownEl = articles[0].querySelector('[data-testid=\\"tweetText\\"]');
                    var ownText = ownEl ? ownEl.textContent.trim() : '';
                    var replies = [];
                    for (var i = 1; i < Math.min(articles.length, 8); i++) {
                        var a = articles[i];
                        var textEl = a.querySelector('[data-testid=\\"tweetText\\"]');
                        var text = textEl ? textEl.textContent.trim() : '';
                        if (!text) continue;
                        var userEl = a.querySelector('[data-testid=\\"User-Name\\"] a[role=\\"link\\"]');
                        var user = userEl ? userEl.textContent.trim() : '';
                        var url = '';
                        var links = a.querySelectorAll('a[href*=\\"/status/\\"]');
                        for (var l of links) {
                            var h = l.getAttribute('href');
                            if (h && h.match(/\\\\/status\\\\/\\\\d+$/)) {
                                url = 'https://x.com' + h;
                                break;
                            }
                        }
                        replies.push({user: user, text: text.substring(0, 200), url: url});
                    }
                    return JSON.stringify({own_tweet: ownText.substring(0, 200), replies: replies});
                })()
            " in current tab of front window
        end tell
        '''
        import json
        try:
            result = subprocess.run(
                ["osascript", "-e", js_script],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0 and result.stdout.strip():
                data = json.loads(result.stdout.strip())
                log.info(f"[REPLYBACK] Found {len(data.get('replies', []))} replies on latest tweet")
                close_front_tab()
                return data
        except Exception as e:
            log.info(f"[REPLYBACK] Scraping failed: {e}")

        close_front_tab()
        return None


def reply_to_tweet_in_thread(reply_url: str, reply_text: str):
    """Reply to a specific reply (nested), so our reply lands UNDER theirs in the thread.

    Works because navigating to a reply's own status URL puts that reply in focus, so
    pressing 'r' replies to *that* reply. Reuses reply_to_tweet's flow.
    """
    log.info(f"[REPLYBACK] Replying in-thread to: {reply_url}")
    reply_to_tweet(reply_url, reply_text)


def reply_to_reply(reply_text: str):
    """Reply to the currently visible reply on own tweet.
    Assumes the tweet page is already open and we're positioned on a reply."""
    # Press 'r' to open reply box, paste, submit
    _run_applescript('''
    tell application "System Events"
        keystroke "r"
    end tell
    ''')
    time.sleep(2)
    _paste_text(reply_text)
    time.sleep(1)
    _run_applescript('''
    tell application "System Events"
        keystroke return using command down
    end tell
    ''')
    time.sleep(2)

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


def post_tweet(text: str):
    """Open Twitter intent URL and auto-click Post using AppleScript."""
    with _safari_lock:
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
        log.info(f"Opening tweet: {tweet_url}")
        webbrowser.open(tweet_url)
        time.sleep(6)

        # Like the tweet first (double notification for the author)
        like_tweet()

        # Click reply
        log.info("Clicking reply...")
        _run_applescript('''
        tell application "System Events"
            keystroke "r"
        end tell
        ''')
        time.sleep(3)

        # Paste the reply (clipboard handles accents correctly)
        log.info("Pasting reply...")
        _paste_text(reply_text)
        time.sleep(2)

        # Submit with Cmd+Enter
        log.info("Submitting reply...")
        _run_applescript('''
        tell application "System Events"
            keystroke return using command down
        end tell
        ''')
        time.sleep(2)
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


def scrape_profile_tweets(username: str, max_tweets: int = 5):
    """Visit a profile and scrape their recent tweet URLs and text via JavaScript.
    Returns list of {"url": str, "text": str} or empty list."""
    import json as _json
    with _safari_lock:
        profile_url = f"https://x.com/{username}"
        log.info(f"[SCRAPE] Visiting profile: {profile_url}")
        webbrowser.open(profile_url)
        time.sleep(8)  # Wait longer for page to fully load

        # Scroll down a tiny bit to trigger lazy loading
        _run_applescript('''
        tell application "System Events"
            key code 125
            delay 0.5
            key code 125
        end tell
        ''')
        time.sleep(3)

        js_script = f'''
        tell application "Safari"
            set result to do JavaScript "
                (function() {{
                    var tweets = [];
                    var articles = document.querySelectorAll('article[data-testid=\\"tweet\\"]');
                    if (articles.length === 0) return 'NO_ARTICLES';
                    for (var i = 0; i < Math.min(articles.length, {max_tweets}); i++) {{
                        var a = articles[i];
                        var textEl = a.querySelector('[data-testid=\\"tweetText\\"]');
                        var text = textEl ? textEl.textContent.trim() : '';
                        if (!text) continue;
                        var links = a.querySelectorAll('a[href*=\\"/status/\\"]');
                        var url = '';
                        for (var l of links) {{
                            var h = l.getAttribute('href');
                            if (h && h.match(/\\/status\\/\\d+$/)) {{
                                url = 'https://x.com' + h;
                                break;
                            }}
                        }}
                        if (url) tweets.push(JSON.stringify({{u: url, t: text.substring(0, 200)}}));
                    }}
                    if (tweets.length === 0) return 'ARTICLES_' + articles.length + '_BUT_NO_URLS';
                    return '[' + tweets.join(',') + ']';
                }})()
            " in current tab of front window
        end tell
        '''
        try:
            result = subprocess.run(
                ["osascript", "-e", js_script],
                capture_output=True, text=True, timeout=15,
            )
            raw = result.stdout.strip()
            stderr = result.stderr.strip()

            if result.returncode != 0:
                log.info(f"[SCRAPE] JS failed for @{username}: rc={result.returncode} stderr={stderr[:200]}")
                close_front_tab()
                return []

            if not raw or raw == 'NO_ARTICLES':
                log.info(f"[SCRAPE] No articles found on @{username} page (page may not have loaded)")
                close_front_tab()
                return []

            if raw.startswith('ARTICLES_'):
                log.info(f"[SCRAPE] @{username}: {raw} (found articles but couldn't extract URLs)")
                close_front_tab()
                return []

            data = _json.loads(raw)
            tweets = [{"url": t["u"], "text": t["t"]} for t in data]
            log.info(f"[SCRAPE] Found {len(tweets)} tweets from @{username}")
            close_front_tab()
            return tweets

        except Exception as e:
            log.info(f"[SCRAPE] Exception for @{username}: {e}")

        close_front_tab()
        return []


def scrape_home_feed(max_tweets: int = 10):
    """Scrape tweets from the home feed. Returns list of {"url": str, "text": str, "author": str}."""
    import json as _json
    with _safari_lock:
        log.info("[SCRAPE] Opening home feed...")
        webbrowser.open("https://x.com/home")
        time.sleep(8)

        # Scroll down to load more tweets
        _run_applescript('''
        tell application "System Events"
            repeat 4 times
                key code 125
                delay 0.5
            end repeat
        end tell
        ''')
        time.sleep(3)

        js_script = f'''
        tell application "Safari"
            set result to do JavaScript "
                (function() {{
                    var tweets = [];
                    var articles = document.querySelectorAll('article[data-testid=\\"tweet\\"]');
                    for (var i = 0; i < Math.min(articles.length, {max_tweets}); i++) {{
                        var a = articles[i];
                        var textEl = a.querySelector('[data-testid=\\"tweetText\\"]');
                        var text = textEl ? textEl.textContent.trim() : '';
                        if (!text) continue;
                        var links = a.querySelectorAll('a[href*=\\"/status/\\"]');
                        var url = '';
                        for (var l of links) {{
                            var h = l.getAttribute('href');
                            if (h && h.match(/\\/status\\/\\d+$/)) {{
                                url = 'https://x.com' + h;
                                break;
                            }}
                        }}
                        var authorEl = a.querySelector('[data-testid=\\"User-Name\\"] a[role=\\"link\\"]');
                        var author = authorEl ? authorEl.textContent.trim().replace('@','') : '';
                        if (url && author) tweets.push(JSON.stringify({{u: url, t: text.substring(0, 200), a: author}}));
                    }}
                    return '[' + tweets.join(',') + ']';
                }})()
            " in current tab of front window
        end tell
        '''
        try:
            result = subprocess.run(
                ["osascript", "-e", js_script],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode == 0 and result.stdout.strip():
                raw = result.stdout.strip()
                if raw.startswith("["):
                    data = _json.loads(raw)
                    tweets = [{"url": t["u"], "text": t["t"], "author": t["a"]} for t in data]
                    log.info(f"[SCRAPE] Found {len(tweets)} tweets in home feed")
                    close_front_tab()
                    return tweets
        except Exception as e:
            log.info(f"[SCRAPE] Home feed scrape failed: {e}")

        close_front_tab()
        return []


def scrape_x_search(query: str, max_tweets: int = 8):
    """Search X directly in Safari and scrape results. Returns list of {"url": str, "text": str, "author": str}."""
    import json as _json
    import urllib.parse
    with _safari_lock:
        search_url = f"https://x.com/search?q={urllib.parse.quote(query)}&src=typed_query&f=live"
        log.info(f"[SCRAPE] Searching X for: {query}")
        webbrowser.open(search_url)
        time.sleep(8)

        # Scroll to load results
        _run_applescript('''
        tell application "System Events"
            repeat 3 times
                key code 125
                delay 0.5
            end repeat
        end tell
        ''')
        time.sleep(2)

        js_script = f'''
        tell application "Safari"
            set result to do JavaScript "
                (function() {{
                    var tweets = [];
                    var articles = document.querySelectorAll('article[data-testid=\\"tweet\\"]');
                    for (var i = 0; i < Math.min(articles.length, {max_tweets}); i++) {{
                        var a = articles[i];
                        var textEl = a.querySelector('[data-testid=\\"tweetText\\"]');
                        var text = textEl ? textEl.textContent.trim() : '';
                        if (!text) continue;
                        var links = a.querySelectorAll('a[href*=\\"/status/\\"]');
                        var url = '';
                        for (var l of links) {{
                            var h = l.getAttribute('href');
                            if (h && h.match(/\\/status\\/\\d+$/)) {{
                                url = 'https://x.com' + h;
                                break;
                            }}
                        }}
                        var authorEl = a.querySelector('[data-testid=\\"User-Name\\"] a[role=\\"link\\"]');
                        var author = authorEl ? authorEl.textContent.trim().replace('@','') : '';
                        if (url && author) tweets.push(JSON.stringify({{u: url, t: text.substring(0, 200), a: author}}));
                    }}
                    return '[' + tweets.join(',') + ']';
                }})()
            " in current tab of front window
        end tell
        '''
        try:
            result = subprocess.run(
                ["osascript", "-e", js_script],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode == 0 and result.stdout.strip():
                raw = result.stdout.strip()
                if raw.startswith("["):
                    data = _json.loads(raw)
                    tweets = [{"url": t["u"], "text": t["t"], "author": t["a"]} for t in data]
                    log.info(f"[SCRAPE] Found {len(tweets)} tweets for '{query}'")
                    close_front_tab()
                    return tweets
        except Exception as e:
            log.info(f"[SCRAPE] Search scrape failed for '{query}': {e}")

        close_front_tab()
        return []


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
        tell application "Safari"
            set result to do JavaScript "
                (function() {
                    var articles = document.querySelectorAll('article[data-testid=\\"tweet\\"]');
                    if (articles.length < 2) return JSON.stringify({own_tweet: '', replies: []});
                    var ownEl = articles[0].querySelector('[data-testid=\\"tweetText\\"]');
                    var ownText = ownEl ? ownEl.textContent.trim() : '';
                    var replies = [];
                    for (var i = 1; i < Math.min(articles.length, 6); i++) {
                        var a = articles[i];
                        var textEl = a.querySelector('[data-testid=\\"tweetText\\"]');
                        var text = textEl ? textEl.textContent.trim() : '';
                        if (!text) continue;
                        var userEl = a.querySelector('[data-testid=\\"User-Name\\"] a[role=\\"link\\"]');
                        var user = userEl ? userEl.textContent.trim() : '';
                        replies.push({user: user, text: text.substring(0, 200)});
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
                capture_output=True, text=True, timeout=15,
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

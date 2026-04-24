"""Browser automation for X/Twitter via Safari + AppleScript (macOS only)."""
import subprocess
import time
import urllib.parse
import webbrowser
from .config import BOT_PROFILE_URL, MAX_RETRIES, RETRY_DELAY_SECONDS
from .logger import log


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

    # Type the reply
    escaped = _escape_for_applescript(reply_text)
    log.info("Typing reply...")
    _run_applescript(f'''
    tell application "System Events"
        keystroke "{escaped}"
    end tell
    ''')
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
    profile_url = f"https://x.com/{username}"
    log.info(f"[FOLLOW] Visiting profile: {profile_url}")
    webbrowser.open(profile_url)
    time.sleep(5)

    # On X, the Follow button can be clicked via JavaScript
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
        # Fallback: try keyboard shortcut or just skip
        log.info(f"[FOLLOW] Could not follow @{username} via JS, skipping.")
    close_front_tab()


def visit_profile_and_like(username: str, like_count: int = 2):
    """Visit a user's profile and like their latest tweets for reciprocity."""
    profile_url = f"https://x.com/{username}"
    log.info(f"Visiting profile: {profile_url}")
    webbrowser.open(profile_url)
    time.sleep(5)

    log.info(f"Opening latest tweet and liking {like_count} tweets...")
    _navigate_to_first_tweet()
    time.sleep(3)

    # Like multiple tweets using j (next) and l (like)
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


def post_thread(tweets: list[str]):
    """Post a thread by posting the first tweet, then replying to it."""
    if not tweets:
        return

    # Post the first tweet
    log.info(f"[THREAD] Posting tweet 1/{len(tweets)}...")
    post_tweet(tweets[0])

    if len(tweets) < 2:
        return

    # Open own profile to find the tweet we just posted
    time.sleep(3)
    log.info("[THREAD] Opening own profile to find the tweet...")
    webbrowser.open(BOT_PROFILE_URL)
    time.sleep(5)

    # Click on the latest tweet
    _navigate_to_first_tweet()
    time.sleep(4)

    # Reply with each subsequent tweet
    for i, tweet_text in enumerate(tweets[1:], start=2):
        log.info(f"[THREAD] Posting tweet {i}/{len(tweets)}...")

        _run_applescript('''
        tell application "System Events"
            keystroke "r"
        end tell
        ''')
        time.sleep(2)

        escaped = _escape_for_applescript(tweet_text)
        _run_applescript(f'''
        tell application "System Events"
            keystroke "{escaped}"
        end tell
        ''')
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
    log.info("[BOOST] Opening own profile to retweet latest tweet...")
    webbrowser.open(BOT_PROFILE_URL)
    time.sleep(5)

    _navigate_to_first_tweet()
    time.sleep(3)

    # Press 't' to retweet (X keyboard shortcut)
    script = '''
    tell application "System Events"
        keystroke "t"
    end tell
    '''
    if _run_applescript(script):
        time.sleep(1)
        # Confirm retweet by pressing Enter
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
    log.info("[NOTIFY] Opening own profile...")
    webbrowser.open(BOT_PROFILE_URL)
    time.sleep(5)

    log.info("[NOTIFY] Opening latest tweet...")
    _navigate_to_first_tweet()
    time.sleep(4)

    # Navigate down to replies and like them
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

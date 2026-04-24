import subprocess
import time
import urllib.parse
import webbrowser
from .config import BOT_PROFILE_URL


def _run_applescript(script: str) -> bool:
    """Run an AppleScript command. Returns True on success."""
    try:
        subprocess.run(["osascript", "-e", script], check=True,
                       capture_output=True, text=True)
        return True
    except subprocess.CalledProcessError:
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
        print("Tab closed.")


def post_tweet(text: str):
    """Open Twitter intent URL and auto-click Post using AppleScript."""
    url = "https://x.com/intent/post?" + urllib.parse.urlencode({"text": text})
    print("Opening Twitter in your browser...")
    webbrowser.open(url)
    time.sleep(4)

    script = '''
    tell application "System Events"
        keystroke return using command down
    end tell
    '''
    print("Auto-clicking Post...")
    _run_applescript(script)
    time.sleep(2)
    print("Tweet posted!")
    close_front_tab()


def refresh_feed():
    """Open X home feed and refresh it so new tweets load."""
    print("Refreshing X feed...")
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
    print("Liking tweet...")
    if _run_applescript(script):
        time.sleep(1)
        print("Tweet liked!")
    else:
        print("Failed to like tweet, continuing...")


def reply_to_tweet(tweet_url: str, reply_text: str):
    """Open a tweet, like it, click reply, type the reply, and submit."""
    print(f"Opening tweet: {tweet_url}")
    webbrowser.open(tweet_url)
    time.sleep(6)

    # Like the tweet first (double notification for the author)
    like_tweet()

    # Click reply
    print("Clicking reply...")
    _run_applescript('''
    tell application "System Events"
        keystroke "r"
    end tell
    ''')
    time.sleep(3)

    # Type the reply
    escaped = _escape_for_applescript(reply_text)
    print("Typing reply...")
    _run_applescript(f'''
    tell application "System Events"
        keystroke "{escaped}"
    end tell
    ''')
    time.sleep(2)

    # Submit with Cmd+Enter
    print("Submitting reply...")
    _run_applescript('''
    tell application "System Events"
        keystroke return using command down
    end tell
    ''')
    time.sleep(2)
    print("Reply posted!")
    close_front_tab()


def quote_tweet(tweet_url: str, comment: str):
    """Quote tweet by posting a new tweet with the tweet URL embedded."""
    full_text = f"{comment}\n\n{tweet_url}"
    url = "https://x.com/intent/post?" + urllib.parse.urlencode({"text": full_text})
    print(f"Quote tweeting: {tweet_url}")
    webbrowser.open(url)
    time.sleep(4)

    print("Posting quote tweet...")
    _run_applescript('''
    tell application "System Events"
        keystroke return using command down
    end tell
    ''')
    time.sleep(2)
    print("Quote tweet posted!")
    close_front_tab()


def visit_profile_and_like(username: str):
    """Visit a user's profile and like their latest tweet for reciprocity."""
    profile_url = f"https://x.com/{username}"
    print(f"Visiting profile: {profile_url}")
    webbrowser.open(profile_url)
    time.sleep(5)

    print("Opening latest tweet...")
    _navigate_to_first_tweet()
    time.sleep(3)

    like_tweet()
    time.sleep(1)
    close_front_tab()


def post_thread(tweets: list[str]):
    """Post a thread by posting the first tweet, then replying to it."""
    if not tweets:
        return

    # Post the first tweet
    print(f"[THREAD] Posting tweet 1/{len(tweets)}...")
    post_tweet(tweets[0])

    if len(tweets) < 2:
        return

    # Open own profile to find the tweet we just posted
    time.sleep(3)
    print("[THREAD] Opening own profile to find the tweet...")
    webbrowser.open(BOT_PROFILE_URL)
    time.sleep(5)

    # Click on the latest tweet
    _navigate_to_first_tweet()
    time.sleep(4)

    # Reply with each subsequent tweet
    for i, tweet_text in enumerate(tweets[1:], start=2):
        print(f"[THREAD] Posting tweet {i}/{len(tweets)}...")

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
        print(f"[THREAD] Tweet {i} posted!")

    close_front_tab()
    print("[THREAD] Thread complete!")


def like_own_tweet_replies():
    """Visit own profile, open latest tweet, and like replies to build loyalty."""
    print("[NOTIFY] Opening own profile...")
    webbrowser.open(BOT_PROFILE_URL)
    time.sleep(5)

    print("[NOTIFY] Opening latest tweet...")
    _navigate_to_first_tweet()
    time.sleep(4)

    # Navigate down to replies and like them
    print("[NOTIFY] Liking replies...")
    _run_applescript('''
    tell application "System Events"
        repeat 5 times
            keystroke "j"
            delay 0.5
            keystroke "l"
            delay 0.8
        end repeat
    end tell
    ''')
    time.sleep(2)
    print("[NOTIFY] Liked up to 5 replies!")
    close_front_tab()

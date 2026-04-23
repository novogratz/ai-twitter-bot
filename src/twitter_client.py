import subprocess
import time
import urllib.parse
import webbrowser


def close_front_tab():
    """Close the frontmost Safari tab to save memory."""
    close_script = '''
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
    try:
        subprocess.run(["osascript", "-e", close_script], check=True)
        print("Tab closed.")
    except Exception:
        pass


def post_tweet(text: str):
    """Open Twitter intent URL and auto-click Post using AppleScript."""
    url = "https://x.com/intent/post?" + urllib.parse.urlencode({"text": text})
    print("Opening Twitter in your browser...")
    webbrowser.open(url)

    # Wait for page to load
    time.sleep(4)

    # Use AppleScript to send Cmd+Enter which posts the tweet on Twitter
    script = '''
    tell application "System Events"
        keystroke return using command down
    end tell
    '''
    print("Auto-clicking Post...")
    subprocess.run(["osascript", "-e", script], check=True)
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
    like_script = '''
    tell application "System Events"
        keystroke "l"
    end tell
    '''
    print("Liking tweet...")
    try:
        subprocess.run(["osascript", "-e", like_script], check=True)
        time.sleep(1)
        print("Tweet liked!")
    except Exception:
        print("Failed to like tweet, continuing...")


def reply_to_tweet(tweet_url: str, reply_text: str):
    """Open a tweet, like it, click reply, type the reply, and submit."""
    print(f"Opening tweet: {tweet_url}")
    webbrowser.open(tweet_url)

    # Wait for tweet page to load
    time.sleep(6)

    # Like the tweet first (double notification for the author)
    like_tweet()

    # Click the reply box using the reply input area on the tweet page
    click_reply_script = '''
    tell application "System Events"
        keystroke "r"
    end tell
    '''
    print("Clicking reply...")
    subprocess.run(["osascript", "-e", click_reply_script], check=True)
    time.sleep(3)

    # Type the reply text using AppleScript
    # Escape special characters for AppleScript
    escaped_text = reply_text.replace("\\", "\\\\").replace('"', '\\"')
    type_script = f'''
    tell application "System Events"
        keystroke "{escaped_text}"
    end tell
    '''
    print("Typing reply...")
    subprocess.run(["osascript", "-e", type_script], check=True)
    time.sleep(2)

    # Submit with Cmd+Enter
    submit_script = '''
    tell application "System Events"
        keystroke return using command down
    end tell
    '''
    print("Submitting reply...")
    subprocess.run(["osascript", "-e", submit_script], check=True)
    time.sleep(2)
    print("Reply posted!")
    close_front_tab()


def quote_tweet(tweet_url: str, comment: str):
    """Quote tweet by posting a new tweet with the tweet URL embedded."""
    # Twitter auto-embeds URLs as quote tweets
    full_text = f"{comment}\n\n{tweet_url}"
    url = "https://x.com/intent/post?" + urllib.parse.urlencode({"text": full_text})
    print(f"Quote tweeting: {tweet_url}")
    webbrowser.open(url)

    time.sleep(4)

    script = '''
    tell application "System Events"
        keystroke return using command down
    end tell
    '''
    print("Posting quote tweet...")
    subprocess.run(["osascript", "-e", script], check=True)
    time.sleep(2)
    print("Quote tweet posted!")
    close_front_tab()


def visit_profile_and_like(username: str):
    """Visit a user's profile and like their latest tweet for reciprocity."""
    profile_url = f"https://x.com/{username}"
    print(f"Visiting profile: {profile_url}")
    webbrowser.open(profile_url)

    # Wait for profile to load
    time.sleep(5)

    # Scroll down slightly to ensure first tweet is in view, then click it
    # Use Tab to navigate to the first tweet, then Enter to open it
    navigate_script = '''
    tell application "System Events"
        -- Press Tab a few times to reach the first tweet
        keystroke tab
        delay 0.2
        keystroke tab
        delay 0.2
        keystroke tab
        delay 0.2
        keystroke return
    end tell
    '''
    print("Opening latest tweet...")
    subprocess.run(["osascript", "-e", navigate_script], check=True)
    time.sleep(3)

    # Like the tweet
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

    # Wait a bit, then open own profile to find the tweet we just posted
    time.sleep(3)
    print("[THREAD] Opening own profile to find the tweet...")
    webbrowser.open("https://x.com/kzer_ai")
    time.sleep(5)

    # Click on the latest tweet (first one on profile)
    click_first_script = '''
    tell application "System Events"
        -- Navigate to first tweet on profile
        keystroke tab
        delay 0.2
        keystroke tab
        delay 0.2
        keystroke tab
        delay 0.2
        keystroke return
    end tell
    '''
    subprocess.run(["osascript", "-e", click_first_script], check=True)
    time.sleep(4)

    # Now reply with each subsequent tweet
    for i, tweet_text in enumerate(tweets[1:], start=2):
        print(f"[THREAD] Posting tweet {i}/{len(tweets)}...")

        # Click reply
        reply_script = '''
        tell application "System Events"
            keystroke "r"
        end tell
        '''
        subprocess.run(["osascript", "-e", reply_script], check=True)
        time.sleep(2)

        # Type the reply
        escaped = tweet_text.replace("\\", "\\\\").replace('"', '\\"')
        type_script = f'''
        tell application "System Events"
            keystroke "{escaped}"
        end tell
        '''
        subprocess.run(["osascript", "-e", type_script], check=True)
        time.sleep(1)

        # Submit
        submit_script = '''
        tell application "System Events"
            keystroke return using command down
        end tell
        '''
        subprocess.run(["osascript", "-e", submit_script], check=True)
        time.sleep(3)
        print(f"[THREAD] Tweet {i} posted!")

    close_front_tab()
    print("[THREAD] Thread complete!")


def like_own_tweet_replies():
    """Visit own profile, open latest tweet, and like replies to build loyalty."""
    print("[NOTIFY] Opening own profile...")
    webbrowser.open("https://x.com/kzer_ai")
    time.sleep(5)

    # Click on the latest tweet
    click_first_script = '''
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
    print("[NOTIFY] Opening latest tweet...")
    subprocess.run(["osascript", "-e", click_first_script], check=True)
    time.sleep(4)

    # Scroll down to see replies, then like them using keyboard
    # On X, scrolling down reveals replies. We use 'j' to navigate
    # between tweets and 'l' to like each one.
    like_replies_script = '''
    tell application "System Events"
        -- Navigate down to replies and like them
        repeat 5 times
            keystroke "j"
            delay 0.5
            keystroke "l"
            delay 0.8
        end repeat
    end tell
    '''
    print("[NOTIFY] Liking replies...")
    subprocess.run(["osascript", "-e", like_replies_script], check=True)
    time.sleep(2)
    print("[NOTIFY] Liked up to 5 replies!")
    close_front_tab()

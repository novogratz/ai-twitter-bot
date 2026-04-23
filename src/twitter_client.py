import subprocess
import time
import urllib.parse
import webbrowser


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


def refresh_feed():
    """Open X home feed and refresh it so new tweets load."""
    print("Refreshing X feed...")
    webbrowser.open("https://x.com/home")
    time.sleep(3)


def reply_to_tweet(tweet_url: str, reply_text: str):
    """Open a tweet, click reply, type the reply, and submit via AppleScript."""
    print(f"Opening tweet: {tweet_url}")
    webbrowser.open(tweet_url)

    # Wait for tweet page to load
    time.sleep(5)

    # Click the reply box - on X, the reply input is in the tweet thread
    # We use AppleScript to click reply and type
    click_reply_script = '''
    tell application "System Events"
        -- Tab to the reply box area and click
        keystroke "r"
    end tell
    '''
    print("Clicking reply...")
    subprocess.run(["osascript", "-e", click_reply_script], check=True)
    time.sleep(2)

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
    time.sleep(1)

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

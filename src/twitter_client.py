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
    time.sleep(6)

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

    # Click the Reply button using JavaScript in the browser
    # This is more reliable than Cmd+Enter which can save as draft
    click_post_script = '''
    tell application "System Events"
        -- Use Tab to reach the Reply button, then Enter to click it
        keystroke tab
        delay 0.3
        keystroke return
    end tell
    '''
    print("Clicking Reply button...")
    subprocess.run(["osascript", "-e", click_post_script], check=True)
    time.sleep(3)
    print("Reply posted!")

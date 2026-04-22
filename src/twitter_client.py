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

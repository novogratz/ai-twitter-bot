"""Performance tracker: scrapes own tweets' metrics and learns what works."""
import json
import os
import subprocess
import time
import webbrowser
from datetime import datetime
from .config import BOT_PROFILE_URL, _PROJECT_ROOT
from .logger import log

PERFORMANCE_FILE = os.path.join(_PROJECT_ROOT, "performance_log.json")
LEARNINGS_FILE = os.path.join(_PROJECT_ROOT, "learnings.json")


def _load_performance() -> list:
    if os.path.exists(PERFORMANCE_FILE):
        try:
            with open(PERFORMANCE_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return []


def _save_performance(data: list):
    # Keep last 200 entries
    with open(PERFORMANCE_FILE, "w") as f:
        json.dump(data[-200:], f, indent=2)


def _load_learnings() -> dict:
    if os.path.exists(LEARNINGS_FILE):
        try:
            with open(LEARNINGS_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"top_tweets": [], "worst_tweets": [], "insights": "", "last_updated": None}


def _save_learnings(data: dict):
    with open(LEARNINGS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def scrape_own_metrics() -> list:
    """Visit own profile and scrape tweet text + metrics using JavaScript."""
    log.info("[PERF] Opening own profile to scrape metrics...")
    webbrowser.open(BOT_PROFILE_URL)
    time.sleep(6)

    # Scroll down a bit to load more tweets
    try:
        subprocess.run(["osascript", "-e", '''
        tell application "System Events"
            repeat 3 times
                key code 125
                delay 0.5
            end repeat
        end tell
        '''], check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError:
        pass
    time.sleep(2)

    # Extract tweet data via JavaScript
    js_script = '''
    tell application "Safari"
        set result to do JavaScript "
            (function() {
                var tweets = [];
                var articles = document.querySelectorAll('article[data-testid=\\"tweet\\"]');
                for (var i = 0; i < Math.min(articles.length, 15); i++) {
                    var a = articles[i];
                    var textEl = a.querySelector('[data-testid=\\"tweetText\\"]');
                    var text = textEl ? textEl.textContent.trim() : '';
                    if (!text) continue;

                    // Get metrics from aria-labels on the action buttons
                    var likeBtn = a.querySelector('[data-testid=\\"like\\"] + span, [data-testid=\\"unlike\\"] + span');
                    var likes = 0;
                    var viewSpans = a.querySelectorAll('a[href*=\\"/analytics\\"] span');
                    var views = 0;

                    // Parse likes from the like button area
                    var likeBtns = a.querySelectorAll('[data-testid=\\"like\\"], [data-testid=\\"unlike\\"]');
                    if (likeBtns.length > 0) {
                        var likeParent = likeBtns[0].closest('[role=\\"group\\"]') || likeBtns[0].parentElement;
                        var likeSpan = likeParent ? likeParent.querySelector('span[data-testid=\\"app-text-transition-container\\"]') : null;
                        if (likeSpan) likes = parseInt(likeSpan.textContent.replace(/[^0-9]/g, '')) || 0;
                    }

                    // Parse views from analytics link
                    if (viewSpans.length > 0) {
                        var viewText = viewSpans[viewSpans.length - 1].textContent;
                        views = parseInt(viewText.replace(/[^0-9.KMkm]/g, '').replace(/[Kk]/, '000').replace(/[Mm]/, '000000')) || 0;
                    }

                    // Get timestamp
                    var timeEl = a.querySelector('time');
                    var timestamp = timeEl ? timeEl.getAttribute('datetime') : '';

                    tweets.push(JSON.stringify({t: text.substring(0, 200), l: likes, v: views, ts: timestamp}));
                }
                return '[' + tweets.join(',') + ']';
            })()
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
            tweets = json.loads(raw)
            log.info(f"[PERF] Scraped {len(tweets)} tweets from profile")

            # Close tab
            subprocess.run(["osascript", "-e", '''
            tell application "Safari"
                if (count of windows) > 0 then
                    tell front window
                        if (count of tabs) > 1 then close current tab end if
                    end tell
                end if
            end tell
            '''], capture_output=True, text=True)

            return [{"text": t["t"], "likes": t["l"], "views": t["v"],
                     "timestamp": t["ts"]} for t in tweets]
    except Exception as e:
        log.info(f"[PERF] Scraping failed: {e}")

    # Close tab on failure too
    subprocess.run(["osascript", "-e", '''
    tell application "Safari"
        if (count of windows) > 0 then
            tell front window
                if (count of tabs) > 1 then close current tab end if
            end tell
        end if
    end tell
    '''], capture_output=True, text=True)

    return []


def evaluate_and_learn():
    """Scrape metrics, compare performance, generate learnings for the AI."""
    tweets = scrape_own_metrics()
    if not tweets or len(tweets) < 3:
        log.info("[PERF] Not enough tweets to evaluate.")
        return

    # Store raw performance data
    perf_data = _load_performance()
    now = datetime.now().isoformat()
    for t in tweets:
        # Avoid duplicates
        existing_texts = {p["text"] for p in perf_data}
        if t["text"] not in existing_texts:
            t["scraped_at"] = now
            perf_data.append(t)
    _save_performance(perf_data)

    # Sort by likes (best metric for engagement)
    scored = sorted(tweets, key=lambda x: x.get("likes", 0), reverse=True)

    top_5 = scored[:5]
    worst_5 = scored[-5:] if len(scored) >= 5 else []

    # Generate insights
    avg_likes = sum(t.get("likes", 0) for t in tweets) / len(tweets) if tweets else 0
    avg_views = sum(t.get("views", 0) for t in tweets) / len(tweets) if tweets else 0

    top_texts = [f"- ({t.get('likes', 0)} likes, {t.get('views', 0)} views) {t['text'][:120]}" for t in top_5]
    worst_texts = [f"- ({t.get('likes', 0)} likes, {t.get('views', 0)} views) {t['text'][:120]}" for t in worst_5]

    insights = f"""Performance snapshot ({now[:10]}):
Average: {avg_likes:.0f} likes, {avg_views:.0f} views per tweet.

TOP PERFORMERS (do MORE of this style):
{chr(10).join(top_texts)}

WORST PERFORMERS (do LESS of this style):
{chr(10).join(worst_texts)}

ADAPT: Write more like the top performers. Avoid the patterns in the worst performers.
Look at what makes the top ones work: topic? format? tone? length? humor style?"""

    learnings = {
        "top_tweets": [{"text": t["text"][:150], "likes": t.get("likes", 0),
                        "views": t.get("views", 0)} for t in top_5],
        "worst_tweets": [{"text": t["text"][:150], "likes": t.get("likes", 0),
                          "views": t.get("views", 0)} for t in worst_5],
        "insights": insights,
        "avg_likes": avg_likes,
        "avg_views": avg_views,
        "last_updated": now,
    }
    _save_learnings(learnings)
    log.info(f"[PERF] Updated learnings. Avg: {avg_likes:.0f} likes, {avg_views:.0f} views. "
             f"Top tweet: {top_5[0].get('likes', 0)} likes.")

    return learnings


def get_learnings_for_prompt() -> str:
    """Get formatted learnings to inject into the AI prompts."""
    learnings = _load_learnings()
    if not learnings.get("insights"):
        return ""
    return learnings["insights"]

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
    """Visit own profile and scrape tweet text + metrics using JavaScript.
    
    Filters out retweets/reposts (only our original content matters), uses
    aria-label matching for like counts (more reliable than DOM structure),
    and extracts views from analytics links or stats elements.
    """
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
                function parseCount(s) {
                    if (!s) return 0;
                    var m = s.match(/(\\\\d[\\\\d,\\\\\.KMkm]*)/);
                    if (!m) return 0;
                    var v = m[1].replace(/,/g, '').toUpperCase();
                    if (v.indexOf('K') !== -1) return Math.round(parseFloat(v) * 1000);
                    if (v.indexOf('M') !== -1) return Math.round(parseFloat(v) * 1000000);
                    return parseInt(v, 10) || 0;
                }
                var tweets = [];
                var articles = document.querySelectorAll('article[data-testid=\\"tweet\\"]');
                for (var i = 0; i < Math.min(articles.length, 15); i++) {
                    var a = articles[i];

                    // Skip retweets/reposts — they have socialContext and are not our content
                    var ctx = a.querySelector('[data-testid=\\"socialContext\\"]');
                    if (ctx) {
                        var ctxText = (ctx.textContent || '').trim().toLowerCase();
                        if (ctxText.indexOf('reposted') !== -1 || ctxText.indexOf('you repost') !== -1) continue;
                    }

                    var textEl = a.querySelector('[data-testid=\\"tweetText\\"]');
                    var text = textEl ? textEl.textContent.trim() : '';
                    if (!text) continue;

                    // Extract likes from aria-label on like/unlike button
                    var likes = 0;
                    var likeBtn = a.querySelector('[data-testid=\\"like\\"], [data-testid=\\"unlike\\"]');
                    if (likeBtn) {
                        var label = likeBtn.getAttribute('aria-label') || '';
                        likes = parseCount(label);
                    }
                    // Fallback: try the group element approach
                    if (likes === 0) {
                        var likeBtns = a.querySelectorAll('[data-testid=\\"like\\"], [data-testid=\\"unlike\\"]');
                        if (likeBtns.length > 0) {
                            var likeParent = likeBtns[0].closest('[role=\\"group\\"]') || likeBtns[0].parentElement;
                            var likeSpan = likeParent ? likeParent.querySelector('span[data-testid=\\"app-text-transition-container\\"]') : null;
                            if (likeSpan) likes = parseInt(likeSpan.textContent.replace(/[^0-9]/g, '')) || 0;
                        }
                    }

                    // Extract views from analytics link or stats row
                    var views = 0;
                    var analyticsLink = a.querySelector('a[href*=\\"/analytics\\"]');
                    if (analyticsLink) {
                        var spans = analyticsLink.querySelectorAll('span');
                        if (spans.length > 0) {
                            views = parseCount(spans[spans.length - 1].textContent);
                        }
                    }
                    // Fallback: look for view-like text in the stats area
                    if (views === 0) {
                        var allSpans = a.querySelectorAll('span');
                        for (var j = 0; j < allSpans.length; j++) {
                            var t = (allSpans[j].textContent || '').trim().toLowerCase();
                            if (t.indexOf('view') !== -1 || t.indexOf('vue') !== -1) {
                                views = parseCount(t);
                                if (views > 0) break;
                            }
                        }
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


def _push_perf_state():
    """Auto-push performance state files so the agents downstream can
    reproduce the bot's reads of itself. Best-effort, never raises."""
    try:
        from .git_ops import auto_push
        auto_push(
            ["performance_log.json", "learnings.json"],
            "Autonomous performance update — top/worst posts + learnings",
        )
    except Exception:
        log.info("[PERF] auto_push failed (non-fatal):")
        import traceback as _tb
        _tb.print_exc()


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

    # Fast-feedback pass: kill dead strategy-agent-added sources within 2h
    # instead of waiting 12h for the evolution agent. Best-effort — never
    # block the perf cycle.
    try:
        from .fast_feedback import scan_and_demote_dead_sources
        scan_and_demote_dead_sources()
    except Exception as e:
        log.info(f"[PERF] Fast-feedback scan failed (non-fatal): {e}")

    # Autonomous git push of performance state.
    _push_perf_state()

    return learnings


def get_learnings_for_prompt() -> str:
    """Get formatted learnings to inject into the AI prompts."""
    learnings = _load_learnings()
    if not learnings.get("insights"):
        return ""
    return learnings["insights"]


def get_pattern_stats_block() -> str:
    """Closed-loop bandit: read engagement_log column 6 (pattern_id) +
    performance_log (likes per scraped tweet text), compute average
    likes per pattern over the last ~7 days, render a winners/losers
    block injected into news/hotake/breakout prompts.

    Without this, the comedy patterns are guessed rules. With it, every
    cycle SEES which patterns landed last week and can lean into them.
    Best-effort — empty string if data is sparse.
    """
    import csv
    from collections import defaultdict
    from datetime import datetime, timedelta

    from .config import ENGAGEMENT_LOG_FILE

    if not os.path.exists(ENGAGEMENT_LOG_FILE):
        return ""

    perf = _load_performance()
    if not perf:
        return ""

    # Build text → likes map from performance_log.
    text_to_likes = {}
    for p in perf:
        text = (p.get("text") or "").strip()
        if not text:
            continue
        likes = int(p.get("likes") or 0)
        # If we've scraped the same text twice, take the higher count.
        text_to_likes[text[:120]] = max(text_to_likes.get(text[:120], 0), likes)

    # Walk engagement_log: for each post-type row with a pattern_id,
    # try to look up the like count via prefix match on text.
    cutoff = datetime.now() - timedelta(days=7)
    by_pattern = defaultdict(list)

    try:
        with open(ENGAGEMENT_LOG_FILE, "r") as f:
            reader = csv.reader(f)
            for row in reader:
                if not row or len(row) < 6:
                    continue
                try:
                    ts = datetime.fromisoformat(row[0])
                except (ValueError, IndexError):
                    continue
                if ts < cutoff:
                    continue
                row_type = row[1] if len(row) > 1 else ""
                if row_type not in ("post", "hotake", "thread"):
                    continue
                pattern = (row[5] or "").strip().upper()
                if not pattern or pattern == "OTHER":
                    continue
                text = (row[2] or "").strip()[:120]
                if not text:
                    continue
                likes = text_to_likes.get(text, 0)
                by_pattern[pattern].append(likes)
    except Exception:
        return ""

    if not by_pattern:
        return ""

    # Compute average likes per pattern, rank.
    stats = []
    for pat, likes_list in by_pattern.items():
        if len(likes_list) < 2:
            continue  # too thin to draw a conclusion
        avg = sum(likes_list) / len(likes_list)
        stats.append((pat, avg, len(likes_list)))
    if not stats:
        return ""

    stats.sort(key=lambda s: s[1], reverse=True)
    winners = stats[:3]
    losers = stats[-3:] if len(stats) > 3 else []

    lines = [
        "==================================================",
        "COMEDY PATTERN SCOREBOARD (last 7 days, closed-loop)",
        "==================================================",
        "Average likes per tweet by pattern. Lean into winners,",
        "avoid losers when possible.",
        "",
        "WINNERS:",
    ]
    for pat, avg, n in winners:
        lines.append(f"  {pat}: {avg:.1f} likes/tweet ({n} samples)")
    if losers and losers != winners:
        lines.append("")
        lines.append("LOSERS (use sparingly):")
        for pat, avg, n in losers:
            lines.append(f"  {pat}: {avg:.1f} likes/tweet ({n} samples)")
    return "\n".join(lines)

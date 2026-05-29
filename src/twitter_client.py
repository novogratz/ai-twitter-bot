"""Browser automation for X/Twitter via Safari + AppleScript (macOS only)."""
import json
import os
import re
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

# Reactive black-screen recovery: track consecutive blank pages.
# When Safari renders an empty app shell (service worker stale state), every
# scrape returns NO_ARTICLES. After N consecutive blanks, trigger a hygiene
# restart without waiting for the scheduled 2h cycle.
_blank_page_lock = threading.Lock()
_blank_page_count = 0
_BLANK_PAGE_RESTART_THRESHOLD = 5


def _record_blank_page():
    global _blank_page_count
    with _blank_page_lock:
        _blank_page_count += 1
        count = _blank_page_count
    if count >= _BLANK_PAGE_RESTART_THRESHOLD:
        _reset_blank_page_count()
        log.warning(f"[SCRAPE] {count} consecutive blank pages — triggering reactive Safari restart.")
        try:
            from . import safari_hygiene
            safari_hygiene.restart_safari(reason="black_screen_recovery")
        except Exception:
            pass


def _reset_blank_page_count():
    global _blank_page_count
    with _blank_page_lock:
        _blank_page_count = 0


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


def _scrub_metadata_leaks(text: str) -> str:
    """Last line of defense before any tweet hits Safari.

    Strips any leaked `[PATTERN ...]`, `[IMAGE: ...]`, `[SOURCE: ...]` or
    similar metadata tags that should have been pulled out by the agent's
    extract_* helpers. Bug 2026-05-06: the agent emitted multi-id
    `[PATTERN: FR_ANCHOR|UNDERSTATEMENT]` which the extract_pattern
    regex didn't match → tag leaked into the live tweet.

    Also strips codex tool-call XML (`<function=bash>...<parameter=...>`)
    that leaked into a hot take 2026-05-13.
    """
    if not text:
        return text
    # Tool-call XML — strip first because the URL extractor and other
    # downstream sanitizers will fish bogus URLs out of these blocks.
    from .llm_client import strip_tool_calls
    text = strip_tool_calls(text)

    # Whole-line metadata tags
    for tag in ("PATTERN", "IMAGE", "SOURCE", "KEYWORD", "TOPIC", "ANGLE"):
        text = re.sub(
            rf"^[ \t]*\[\s*{tag}[^\n\r]*\]\s*$\n?",
            "",
            text,
            flags=re.IGNORECASE | re.MULTILINE,
        )
    # Inline catch — strip "[PATTERN: ...]" wherever it appears.
    text = re.sub(
        r"\[\s*(?:PATTERN|IMAGE|SOURCE|KEYWORD|TOPIC|ANGLE)[^\]\n\r]*\]",
        "",
        text,
        flags=re.IGNORECASE,
    )
    # Prompt-instruction bleed (local-model output sometimes echoes the
    # rules back). qwen3.6 posted "⚠️ CRITIQUE: FR_ANCHOR" verbatim on
    # 2026-05-15. Strip whole lines starting with the warning emoji OR
    # containing common prompt-instruction keywords on their own line.
    text = re.sub(
        r"^[ \t]*[⚠❗🚨]️?[^\n\r]*(?:\n|$)",
        "",
        text,
        flags=re.MULTILINE,
    )
    text = re.sub(
        r"^[ \t]*(?:CRITIQUE|INTERDIT|RÈGLES?|RÈGLE|HARD\s+RULE|OUTPUT)\s*[:：][^\n\r]*(?:\n|$)",
        "",
        text,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    # Inline placeholder bleeds like "<UN_SEUL_ID>" or "<la hot take française>"
    text = re.sub(r"<[A-Z_]{3,}[^\n\r>]{0,80}>", "", text)
    # Stray standalone pattern IDs at end of post (the bracket is gone but
    # the bare word remains — e.g. "tweet body\n\nFR_ANCHOR").
    text = re.sub(
        r"\n+\s*(?:REPETITION|DIALOGUE|METAPHOR|RENAME|FR_ANCHOR|EN_ANCHOR|UNDERSTATEMENT|OTHER)\s*$",
        "",
        text,
    )
    # Collapse blank-line gaps the strip may have left behind.
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


class ToolCallLeakError(Exception):
    """Raised when a tweet still contains tool-call markup after scrubbing.

    Better to crash the cycle than to post '<function=bash>...' as a tweet.
    """


def post_tweet(text: str, image_path: str = None):
    """Open Twitter and auto-post. If `image_path` is given, attaches the PNG.

    Without image: uses the lightweight intent URL (text only).
    With image: uses the full /compose/post composer + clipboard paste — the
    intent URL doesn't support media uploads.
    """
    text = _scrub_metadata_leaks(text)

    # Hard reject — if tool-call markup OR a JSON stream envelope survived
    # scrubbing, refuse to post. Both of these went live in prod 2026-05-13
    # / 2026-05-14 ("<function=bash>" and `{"type":"step_start",...}`).
    from .llm_client import contains_post_unsafe_leak
    if contains_post_unsafe_leak(text):
        log.error(f"[POST] Unsafe leak detected after scrub — refusing to post. Text: {text[:200]!r}")
        raise ToolCallLeakError("tool-call / stream-envelope markup in tweet text")

    with _safari_lock:
        if image_path:
            _post_tweet_with_image(text, image_path)
            _like_own_latest_tweet()
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
        _like_own_latest_tweet()


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


def _like_own_latest_tweet():
    """Open own profile, navigate into the latest tweet, like it. Caller must hold _safari_lock."""
    webbrowser.open(BOT_PROFILE_URL)
    time.sleep(5)
    _navigate_to_first_tweet()
    time.sleep(3)
    like_tweet()
    close_front_tab()


def reply_to_own_latest(reply_text: str, must_contain: str = "") -> bool:
    """Visit own profile, open the latest tweet, post a reply.

    Used by the URL-as-self-reply pattern on Décodes (2026-05-22): main
    body ships without the article URL → 30-90s later we self-reply with
    the URL so the link card renders in the reply (doesn't deboost the
    parent). Also creates a 2-tweet thread → algo thread-depth bonus.

    `must_contain`: if non-empty, peek the visible tweet's text via JS
    before pressing 'r' and abort if the marker isn't found. This prevents
    the source-reply from attaching to a retweet/QT that ran between the
    main post and the self-reply.

    Best-effort. Returns True if the reply appeared to submit. False if
    Safari steps glitched (caller treats as non-fatal).
    """
    if not reply_text or not reply_text.strip():
        return False
    with _safari_lock:
        try:
            log.info(f"[SELF-REPLY] Opening own profile to find latest tweet")
            webbrowser.open(BOT_PROFILE_URL)
            time.sleep(5)
            _run_applescript('tell application "Safari" to activate')
            time.sleep(1)
            _navigate_to_first_tweet()
            time.sleep(4)
            _run_applescript('tell application "Safari" to activate')
            time.sleep(1)
            # Sanity check: confirm the focused tweet contains the expected
            # marker. If a retweet/QT slipped in between the main post and
            # this self-reply call, the marker won't be there and we abort.
            if must_contain:
                check_js = (
                    'var el = document.querySelector(\'[data-testid="tweetText"]\');'
                    'return el ? el.innerText : "";'
                )
                ascript = f'''
                tell application "Safari"
                    set result to do JavaScript "{check_js}" in current tab of front window
                end tell
                return result
                '''
                try:
                    r = subprocess.run(
                        ["osascript", "-e", ascript],
                        capture_output=True, text=True, timeout=8,
                    )
                    visible = (r.stdout or "").strip()
                except Exception:
                    visible = ""
                if must_contain.lower() not in visible.lower():
                    log.info(
                        f"[SELF-REPLY] Aborting: visible tweet doesn't contain "
                        f"{must_contain!r} (saw {visible[:100]!r})."
                    )
                    close_front_tab()
                    return False
            # Press 'r' to open reply composer.
            _run_applescript('tell application "System Events" to keystroke "r"')
            time.sleep(3)
            _paste_text(reply_text)
            time.sleep(2)
            _run_applescript('tell application "System Events" to keystroke return using command down')
            time.sleep(3)
            log.info(f"[SELF-REPLY] Posted: {reply_text[:80]}")
            close_front_tab()
            return True
        except Exception as e:
            log.info(f"[SELF-REPLY] failed: {e}")
            try:
                close_front_tab()
            except Exception:
                pass
            return False


LIKED_TWEETS_FILE = os.path.join(_PROJECT_ROOT, "liked_tweets.json") if "_PROJECT_ROOT" in globals() else None


def _liked_cache_path() -> str:
    """Lazy-resolve the liked_tweets.json path to avoid import-order issues."""
    from .config import _PROJECT_ROOT as _PR
    return os.path.join(_PR, "liked_tweets.json")


def _load_liked_set():
    """Return a CanonReplied set of canonical IDs we've already liked.
    Cross-bot dedup via canonical status ID prevents the 'l' shortcut
    from toggling-OFF a like we set in an earlier cycle."""
    from .reply_bot import _CanonReplied
    s = _CanonReplied()
    path = _liked_cache_path()
    if not os.path.exists(path):
        return s
    try:
        with open(path) as f:
            data = json.load(f)
        for u in (data if isinstance(data, list) else []):
            if isinstance(u, str):
                s.add(u)
    except (json.JSONDecodeError, OSError):
        pass
    return s


def _save_liked_set(s) -> None:
    """Persist liked set as ordered list, cap at 50k from the tail."""
    from .reply_bot import _canonical_tweet_id
    path = _liked_cache_path()
    existing = []
    existing_set = set()
    if os.path.exists(path):
        try:
            with open(path) as f:
                data = json.load(f)
            if isinstance(data, list):
                existing = [str(u) for u in data if isinstance(u, str)]
                existing_set = set(existing)
        except (json.JSONDecodeError, OSError):
            pass
    for u in s:
        cid = _canonical_tweet_id(u)
        if cid and cid not in existing_set:
            existing.append(cid)
            existing_set.add(cid)
    if len(existing) > 50000:
        existing = existing[-50000:]
    try:
        with open(path, "w") as f:
            json.dump(existing, f, indent=2)
    except OSError as e:
        log.info(f"[LIKE] save failed: {e}")


def _already_liked(url: str) -> bool:
    if not url:
        return False
    return url in _load_liked_set()


def _mark_liked(url: str) -> None:
    if not url:
        return
    s = _load_liked_set()
    s.add(url)
    _save_liked_set(s)


def like_tweet(tweet_url: str = ""):
    """Like the currently open tweet using the 'l' keyboard shortcut.

    The 'l' shortcut TOGGLES — pressing it on an already-liked tweet
    will UNLIKE. User incident 2026-05-18: bot retweeted+liked a tweet
    on one cycle, then replied to it later and the reply path's like
    call un-liked the original.

    Fix: if tweet_url is provided AND it's already in our liked-cache,
    skip the press. Callers should pass the URL whenever known.
    """
    if tweet_url and _already_liked(tweet_url):
        log.info(f"[LIKE] already liked {tweet_url[-50:]} — skipping (would toggle OFF).")
        return
    script = '''
    tell application "System Events"
        keystroke "l"
    end tell
    '''
    log.info("Liking tweet...")
    if _run_applescript(script):
        time.sleep(1)
        log.info("Tweet liked!")
        if tweet_url:
            _mark_liked(tweet_url)
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

        # Like the tweet (idempotent — won't toggle off if already liked
        # from a prior retweet/quote cycle). Bug 2026-05-18: bot was
        # un-liking previously-liked tweets here.
        like_tweet(tweet_url)
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
    """Publish a quote post by composing `comment` plus the source tweet URL.

    X renders a tweet URL included in a new post as a quote card. This route is
    more stable than driving the nested repost menu and keeps the same
    Safari-lock behavior as normal posts/replies.
    """
    comment = _scrub_metadata_leaks((comment or "").strip())
    if not tweet_url or not comment:
        raise ValueError("quote_tweet requires both tweet_url and comment")

    from .llm_client import contains_post_unsafe_leak
    if contains_post_unsafe_leak(comment):
        log.error(f"[QUOTE] Unsafe leak detected after scrub — refusing. Text: {comment[:200]!r}")
        raise ToolCallLeakError("tool-call / stream-envelope markup in quote text")

    with _safari_lock:
        text = f"{comment}\n{tweet_url}"
        url = "https://x.com/intent/post?" + urllib.parse.urlencode({"text": text})
        log.info(f"[QUOTE] Opening quote composer for: {tweet_url}")
        webbrowser.open(url)
        time.sleep(4)
        _run_applescript('''
        tell application "System Events"
            keystroke return using command down
        end tell
        ''')
        time.sleep(2)
        log.info(f"[QUOTE] Quote posted: {tweet_url}")
        close_front_tab()
        try:
            like_tweet(tweet_url)
        except Exception as e:
            log.info(f"[QUOTE] parent-like failed: {e}")
        try:
            _like_own_latest_tweet()
        except Exception as e:
            log.info(f"[QUOTE] self-like failed: {e}")


def unfollow_account(username: str) -> bool:
    """Visit a user's profile and click Following → confirm Unfollow.

    Best-effort. Returns True if the unfollow flow appeared to complete
    (Following button found + clicked + confirm clicked). False otherwise.
    Used by smart_unfollow_bot to keep follow-ratio healthy.
    """
    username = (username or "").strip().lstrip("@")
    if not username or len(username) > 15 or not all(
        c.isascii() and (c.isalnum() or c == "_") for c in username
    ):
        log.info(f"[UNFOLLOW] Invalid handle '{username}' — skipping.")
        return False

    with _safari_lock:
        profile_url = f"https://x.com/{username}"
        log.info(f"[UNFOLLOW] Visiting profile: {profile_url}")
        webbrowser.open(profile_url)
        time.sleep(5)

        # Step 1: click the "Following" button. Try multiple selectors since
        # X occasionally renames data-testid values.
        click_following = '''
        tell application "Safari"
            do JavaScript "
                var btn = document.querySelector('[data-testid$=\"-unfollow\"]');
                if (!btn) btn = document.querySelector('[data-testid=\"userActions\"] [role=\"button\"]');
                if (!btn) {
                    var spans = document.querySelectorAll('[role=\"button\"] span');
                    for (var i = 0; i < spans.length; i++) {
                        if (spans[i].textContent.trim() === 'Following') { btn = spans[i].closest('[role=\"button\"]'); break; }
                    }
                }
                if (btn) { btn.click(); return 'CLICKED'; }
                return 'NO_FOLLOWING_BTN';
            " in current tab of front window
        end tell
        '''
        result = _run_applescript(click_following)
        if not result or result.strip() == "NO_FOLLOWING_BTN":
            log.info(f"[UNFOLLOW] Not following @{username} (or button not found) — skipping.")
            close_front_tab()
            return False
        time.sleep(1.5)

        # Step 2: click the confirm in the modal.
        click_confirm = '''
        tell application "Safari"
            do JavaScript "
                var btn = document.querySelector('[data-testid=\"confirmationSheetConfirm\"]');
                if (btn) { btn.click(); return 'CONFIRMED'; }
                return 'NO_CONFIRM';
            " in current tab of front window
        end tell
        '''
        _run_applescript(click_confirm)
        time.sleep(1.5)
        close_front_tab()
        log.info(f"[UNFOLLOW] Unfollowed @{username}.")
        return True


def follow_account(username: str) -> bool:
    """Visit a user's profile and click the Follow button.

    Returns True only when the JS click actually fired (best-effort signal).
    Callers MUST check the return value before marking a handle as followed,
    otherwise transient AppleScript/Safari hiccups will pollute
    followed_accounts.json with false-positives we never retry.
    """
    # Sanitize: strip whitespace + leading @, reject display-name garbage.
    # X handles are [A-Za-z0-9_]{1,15}. Anything else (spaces, slashes, > 15 chars,
    # accents, punctuation) is a scraper artifact like "aisha mansion" or
    # "caborashedzaborashedles" and would just burn a profile-visit + 5s sleep.
    username = (username or "").strip().lstrip("@")
    if not username or len(username) > 15 or not all(
        c.isascii() and (c.isalnum() or c == "_") for c in username
    ):
        log.info(f"[FOLLOW] Invalid handle '{username}' — skipping.")
        return False
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
        ok = _run_applescript(follow_script)
        if ok:
            time.sleep(2)
            log.info(f"[FOLLOW] Followed @{username}!")
        else:
            log.info(f"[FOLLOW] Could not follow @{username} via JS, skipping.")
        close_front_tab()
        return ok


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
        function detectTranslatedLang(article) {
            var html = article.innerHTML;
            if (html.indexOf('Afficher l\\'original') !== -1) return 'en';
            if (html.indexOf('Show original') !== -1) return 'fr';
            return '';
        }
        function detectReplyArticle(article, tweetText) {
            var full = article.innerText || '';
            if ((tweetText || '').trim().indexOf('@') === 0) return true;
            return /Replying to|En réponse à|En reponse a|Répond à|Repond a/i.test(full);
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
            var tl = detectTranslatedLang(a);
            var isReply = detectReplyArticle(a, text);
            if (url) tweets.push(JSON.stringify({u: url, t: text.substring(0, 200), a: author || 'unknown', l: likes, r: replies, tl: tl, ir: isReply}));
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
            _record_blank_page()
            return []
        if raw.startswith('ARTICLES_'):
            log.info(f"[SCRAPE] {label}: {raw}")
            _record_blank_page()
            return []

        data = _json.loads(raw)
        tweets = [{
            "url": t["u"],
            "text": t["t"],
            "author": t["a"],
            "likes": int(t.get("l") or 0),
            "replies": int(t.get("r") or 0),
            "translated_from": t.get("tl") or "",
            "is_reply": bool(t.get("ir") or False),
        } for t in data]
        _reset_blank_page_count()
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
        # Self-like the thread head — user mandate 2026-05-18:
        # "Always auto like your own tweets or quotes... always".
        try:
            _like_own_latest_tweet()
        except Exception as e:
            log.info(f"[THREAD] self-like failed: {e}")


def retweet_post(tweet_url: str):
    """Retweet an arbitrary tweet by URL.

    Opens the tweet detail page, presses 't' (X retweet shortcut), then Enter
    to confirm the 'Repost' menu item. Uses the same Safari lock as everything
    else so it can't race with reply/post cycles.
    """
    with _safari_lock:
        log.info(f"[RETWEET] Opening tweet: {tweet_url}")
        webbrowser.open(tweet_url)
        time.sleep(7)

        _run_applescript('tell application "Safari" to activate')
        time.sleep(1)

        # Press 't' to open the retweet menu, then Enter to confirm "Repost".
        _run_applescript('''
        tell application "System Events"
            keystroke "t"
            delay 1.2
            keystroke return
        end tell
        ''')
        time.sleep(2)
        log.info(f"[RETWEET] Reposted: {tweet_url}")
        like_tweet(tweet_url)
        close_front_tab()


def pin_own_tweet(tweet_url: str) -> bool:
    """Pin one of our own tweets to the profile via the More menu.

    Best-effort. X's tweet-action menu DOM is stable but the wording of the
    'Pin' item varies (FR: 'Épingler à votre profil' / EN: 'Pin to your
    profile'). We click via JS by matching either string. Returns True if
    the pin appeared to succeed (menu item found + clicked + confirm dialog
    handled), False otherwise.

    Note: X surfaces a confirmation modal on first pin per session; we
    handle it by clicking the confirm button (data-testid="confirmationSheetConfirm").
    """
    import json as _json
    import tempfile

    js_code = """
    (function() {
        var article = document.querySelector('article[data-testid="tweet"]');
        if (!article) return 'NO_ARTICLE';
        var moreBtn = article.querySelector('[data-testid="caret"]');
        if (!moreBtn) return 'NO_MORE_BTN';
        moreBtn.click();
        return 'MORE_CLICKED';
    })()
    """
    js_pin_item = """
    (function() {
        var menuItems = document.querySelectorAll('[role="menuitem"]');
        for (var i = 0; i < menuItems.length; i++) {
            var t = (menuItems[i].textContent || '').trim().toLowerCase();
            if (t.indexOf('pin to your profile') !== -1 ||
                t.indexOf('épingler à votre profil') !== -1 ||
                t.indexOf('epingler a votre profil') !== -1) {
                menuItems[i].click();
                return 'PIN_CLICKED';
            }
            // Older variant: "Pin"
            if (t === 'pin' || t === 'épingler' || t === 'epingler') {
                menuItems[i].click();
                return 'PIN_CLICKED';
            }
        }
        return 'PIN_NOT_FOUND_' + menuItems.length;
    })()
    """
    js_confirm = """
    (function() {
        var btn = document.querySelector('[data-testid="confirmationSheetConfirm"]');
        if (btn) { btn.click(); return 'CONFIRMED'; }
        return 'NO_CONFIRM';
    })()
    """

    def _exec_js(js: str, timeout_s: int = 15) -> str:
        tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False)
        tmp.write(js)
        tmp.close()
        applescript = f'''
        tell application "Safari" to activate
        set jsCode to (read POSIX file "{tmp.name}")
        tell application "Safari"
            set result to do JavaScript jsCode in current tab of front window
        end tell
        '''
        try:
            r = subprocess.run(
                ["osascript", "-e", applescript],
                capture_output=True, text=True, timeout=timeout_s,
            )
            return (r.stdout or "").strip()
        except Exception:
            return "EXCEPTION"
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass

    with _safari_lock:
        log.info(f"[PIN] Opening tweet to pin: {tweet_url}")
        webbrowser.open(tweet_url)
        time.sleep(7)

        step1 = _exec_js(js_code)
        log.info(f"[PIN] More-menu open: {step1}")
        if step1 != "MORE_CLICKED":
            close_front_tab()
            return False
        time.sleep(1.2)

        step2 = _exec_js(js_pin_item)
        log.info(f"[PIN] Pin item click: {step2}")
        if step2 != "PIN_CLICKED":
            close_front_tab()
            return False
        time.sleep(1.5)

        step3 = _exec_js(js_confirm)
        log.info(f"[PIN] Confirm modal: {step3}")
        # Whether the confirm modal appeared or not, we leave the page.
        time.sleep(1)
        close_front_tab()
        return step3 in ("CONFIRMED", "NO_CONFIRM")


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

"""Browser automation for X/Twitter via Safari + AppleScript (macOS only)."""
import json
import os
import random
import re
import subprocess
import threading
import time
import urllib.parse
from datetime import datetime
from enum import Enum
import webbrowser
from ..core.config import _PROJECT_ROOT, BOT_PROFILE_URL, MAX_RETRIES, RETRY_DELAY_SECONDS
from ..core.json_safety import sanitize_for_json
from ..core.logger import log
from ..guards.active_hours import require_active, OutsideActiveHours

# Global lock: only one bot can use Safari at a time.
# Without this, the reply bot and engage bot type over each other. RLock is
# intentional: blank-page recovery can be triggered from inside a scrape that
# already owns the lock, and it must restart Safari before releasing control.
class _AwakeSafariLock:
    def __init__(self):
        self._lock = threading.RLock()

    def __enter__(self):
        require_active()
        self._lock.acquire()
        try:
            require_active()  # queued work may acquire the browser after bedtime
        except BaseException:
            self._lock.release()
            raise
        return self

    def __exit__(self, *exc):
        self._lock.release()


_safari_lock = _AwakeSafariLock()

# Reactive black-screen recovery: track consecutive blank pages.
# When Safari renders an empty app shell (service worker stale state), every
# scrape returns NO_ARTICLES. After N consecutive blanks, trigger a hygiene
# restart without waiting for the scheduled 2h cycle.
_blank_page_lock = threading.Lock()
_blank_recovery_lock = threading.Lock()
_blank_page_count = 0
_home_feed_blank_count = 0
_blank_page_labels: list = []  # labels of the current consecutive-blank run
_BLANK_PAGE_RESTART_THRESHOLD = 3  # lowered 5→3 (2026-06-02): recover from the
                                   # black-screen / stale-page state faster so
                                   # scrapes don't keep returning empty/old data
_HOME_FEED_BLANK_RESTART_THRESHOLD = 2  # home feed fails 2× in a row → restart


def _in_post_restart_grace() -> bool:
    """2026-07-19 storm fix (7 reactive restarts in 2.2h): scrapes queued
    behind a hygiene restart hit a cold, still-warming Safari, go blank, and
    re-trip the threshold ~15 min later — a self-perpetuating restart loop.
    Blanks within BLANK_GRACE_AFTER_RESTART_SECONDS of the last restart are
    EXPECTED and must not count. Env read at call time."""
    grace = int(os.environ.get("BLANK_GRACE_AFTER_RESTART_SECONDS", "120"))
    try:
        from . import safari_hygiene
        return (time.time() - safari_hygiene._last_run_ts()) < grace
    except Exception:
        return False


# Pages that can be LEGITIMATELY empty (no new mentions = a blank mentions
# tab). Their blanks say nothing about Safari's health — never count them.
_LEGIT_EMPTY_LABELS = {"mentions"}


def _trigger_black_screen_recovery(reason_detail: str) -> None:
    """Serialize reactive dark-screen recovery.

    Called from scrape code that often already holds _safari_lock. The RLock
    lets that owner restart Safari immediately; other threads block until the
    recovered x.com page has been warmed and verified.
    """
    if not _blank_recovery_lock.acquire(blocking=False):
        log.info("[SCRAPE] Black-screen recovery already in progress; skipping duplicate trigger.")
        return
    try:
        with _safari_lock:
            try:
                from . import safari_hygiene
                ok = safari_hygiene.restart_safari(reason="black_screen_recovery")
                if ok:
                    log.info(f"[SCRAPE] Black-screen recovery completed ({reason_detail}).")
                else:
                    log.warning(f"[SCRAPE] Black-screen recovery skipped/failed ({reason_detail}).")
            except Exception as e:
                log.warning(f"[SCRAPE] Black-screen recovery crashed ({reason_detail}): {e}")
    finally:
        _blank_recovery_lock.release()


def _record_timed_out_scrape(label: str) -> None:
    """Treat repeated Safari JS timeouts like blank X renders."""
    _record_blank_page(is_home_feed="home feed" in label, label=label)


def _record_blank_page(is_home_feed: bool = False, label: str = ""):
    global _blank_page_count, _home_feed_blank_count
    if label in _LEGIT_EMPTY_LABELS:
        return
    if _in_post_restart_grace():
        log.info("[SCRAPE] Blank page within post-restart grace — not counting toward restart threshold.")
        return
    with _blank_page_lock:
        _blank_page_count += 1
        count = _blank_page_count
        _blank_page_labels.append(label or ("home feed" if is_home_feed else "?"))
        del _blank_page_labels[:-_BLANK_PAGE_RESTART_THRESHOLD]
        distinct = len(set(_blank_page_labels))
        if is_home_feed:
            _home_feed_blank_count += 1
            hf_count = _home_feed_blank_count
        else:
            hf_count = 0
    if hf_count >= _HOME_FEED_BLANK_RESTART_THRESHOLD:
        _reset_blank_page_count()
        log.warning(f"[SCRAPE] Home feed blank {hf_count}× in a row — triggering reactive Safari restart.")
        _trigger_black_screen_recovery(f"home_feed_blank_{hf_count}")
    elif count >= _BLANK_PAGE_RESTART_THRESHOLD:
        # A wedged Safari (stale service-worker shell) blanks EVERY page, so
        # a true wedge shows ≥2 distinct labels fast. One page blanking in a
        # loop is that page being legitimately empty — not a reason to bounce
        # Safari (2026-07-19: storms counted mixed legit-empties as wedges).
        if distinct < 2:
            log.info(f"[SCRAPE] {count} consecutive blanks but all on '{_blank_page_labels[-1]}' — "
                     "single-page empty, not a Safari wedge. Holding restart.")
            return
        _reset_blank_page_count()
        log.warning(f"[SCRAPE] {count} consecutive blank pages — triggering reactive Safari restart.")
        _trigger_black_screen_recovery(f"diverse_blank_pages_{count}")


def _reset_blank_page_count():
    global _blank_page_count, _home_feed_blank_count
    with _blank_page_lock:
        _blank_page_count = 0
        _home_feed_blank_count = 0
        del _blank_page_labels[:]


def _run_applescript(script: str, retries: int = 1) -> bool:
    """Run an AppleScript command with optional retries. Returns True on success."""
    for attempt in range(retries):
        require_active()
        try:
            require_active()
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


def _paste_text(text: str) -> bool:
    """Copy text to clipboard and paste it. Handles accented characters correctly.
    Returns True when the AppleScript ran."""
    escaped = _escape_for_applescript(text)
    script = f'''
    set the clipboard to "{escaped}"
    delay 0.3
    tell application "System Events"
        keystroke "v" using command down
    end tell
    '''
    return _run_applescript(script)


_SUBMIT_KEYSTROKE = 'tell application "System Events" to keystroke return using command down'


def _paste_or_abort(text: str, tag: str) -> bool:
    """Paste into the open composer. On failure nothing was sent: close the
    tab and return False."""
    if _paste_text(text):
        return True
    log.info(f"[{tag}] Paste failed; nothing sent.")
    close_front_tab()
    return False


def _submit_or_abort(tag: str, target: str = "") -> bool:
    """Press Cmd+Return in the open composer. On failure the outcome is
    unknown: close the tab, record nothing, return False."""
    if _run_applescript(_SUBMIT_KEYSTROKE):
        return True
    log.warning(f"[{tag}] Submit keystroke failed; outcome unknown, nothing recorded"
                f"{': ' + target if target else '.'}")
    close_front_tab()
    return False


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
    from ..core.llm_client import strip_tool_calls
    text = strip_tool_calls(text)

    # Whole-line metadata tags
    for tag in ("PATTERN", "IMAGE", "SOURCE", "KEYWORD", "TOPIC", "ANGLE", "GIF"):
        text = re.sub(
            rf"^[ \t]*\[\s*{tag}[^\n\r]*\]\s*$\n?",
            "",
            text,
            flags=re.IGNORECASE | re.MULTILINE,
        )
    # Inline catch — strip "[PATTERN: ...]" wherever it appears.
    text = re.sub(
        r"\[\s*(?:PATTERN|IMAGE|SOURCE|KEYWORD|TOPIC|ANGLE|GIF)[^\]\n\r]*\]",
        "",
        text,
        flags=re.IGNORECASE,
    )
    # Generic metadata-tag catch (2026-06-14): qwen shipped "[SIGNS: yes]"
    # live at the end of a post. Strip any bracketed UPPERCASE label +
    # colon tag ("[SIGNS: yes]", "[NOTE: ...]", "[VERDICT: skip]") that the
    # keyword list above doesn't name. Requires an all-caps label (>=3
    # chars) + colon so real content like "[2026]" or "[A]" is untouched.
    text = re.sub(r"\[\s*[A-Z][A-Z _]{2,}\s*:[^\]\n\r]*\]", "", text)
    # Banned series header (operator 2026-06-06: "I don't want to see the
    # decode daily"). The prompt forbids it but weaker models (ollama
    # primary, 2026-06-11: 11 headered drafts in one night) keep emitting
    # it — and a headered draft with a valid URL would ship. Strip any
    # leading "🔎 The Decode Daily #109. AI. 2026-06-11" style header line
    # mechanically; the body opens with the hook as mandated.
    text = re.sub(
        r"^[\s🔎📰]*(?:the\s+|le\s+)?d[ée]code\s+(?:daily|weekly|monthly|quotidien|hebdo|mensuel|#?\d)[^\n]*\n+",
        "",
        text,
        flags=re.IGNORECASE,
    )
    # Bare bracketed pattern IDs — "[RENAME]", "[FR_ANCHOR|METAPHOR]" — leaked
    # live on 2026-06-05 ("CAPES DON'T SPIN COMPUTERS. WIRES DO. [RENAME]"):
    # only 4 bots call extract_pattern, and the rules above need the "PATTERN"
    # keyword. Strip every occurrence of a bracketed canonical ID here so all
    # post paths are covered.
    from ..core.pattern_tags import PATTERN_IDS
    _pat_alt = "|".join(sorted(PATTERN_IDS))
    text = re.sub(
        rf"\[\s*(?:{_pat_alt})(?:\s*[|/+,]\s*(?:{_pat_alt}))*\s*\]",
        "",
        text,
        flags=re.IGNORECASE,
    )
    # Truncated tag catch — model output cut off before closing ']', e.g. "[PATTERN: REPE"
    # at end-of-string or end-of-line with no closing bracket.
    text = re.sub(
        r"\[\s*(?:PATTERN|IMAGE|SOURCE|KEYWORD|TOPIC|ANGLE|GIF)[^\]]*$",
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
    # Hashtags banned account-wide (monetization mandate 2026-06-05 —
    # sponsor-clean timeline). Strip trailing tag runs AND inline tags.
    text = re.sub(r"(?:\s+#\w{2,50})+\s*$", "", text)
    text = re.sub(r"\s*#(\w{2,50})\b", r" \1", text)  # inline: keep the word, drop the #
    # Collapse blank-line gaps the strip may have left behind.
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def _strip_post_urls(text: str) -> str:
    """External links in standalone posts/quotes throttle reach and are
    BANNED by the monetization mandate (2026-06-05). Strip them; the
    link-in-first-reply pattern is the sanctioned alternative."""
    stripped = re.sub(r"https?://\S+", "", text or "")
    stripped = re.sub(r"[ \t]{2,}", " ", stripped)
    stripped = re.sub(r"\n{3,}", "\n\n", stripped).strip()
    if stripped != (text or "").strip():
        log.info("[POST] external URL stripped (no-links mandate).")
    return stripped


class ToolCallLeakError(Exception):
    """Raised when a tweet still contains tool-call markup after scrubbing.

    Better to crash the cycle than to post '<function=bash>...' as a tweet.
    """


class _DryRunRecorded:
    """What a write chokepoint returns when DRY_RUN wrote a dry-run ledger
    row instead of acting. Falsy because nothing shipped, so a caller that
    persists on a truthy result persists nothing (#123); `is
    DRY_RUN_RECORDED` tells it apart from a refusal."""
    __slots__ = ()

    def __bool__(self):
        return False

    def __repr__(self):
        return "DRY_RUN_RECORDED"


DRY_RUN_RECORDED = _DryRunRecorded()


def post_tweet(text: str, image_path: str = None, *, editorial: bool = False):
    """Open Twitter and auto-post. If `image_path` is given, attaches the PNG.

    Without image: uses the lightweight intent URL (text only).
    With image: uses the full /compose/post composer + clipboard paste — the
    intent URL doesn't support media uploads.
    """
    text = _scrub_metadata_leaks(text)
    if not editorial:
        text = _strip_post_urls(text)
        from ..core.humanizer import casualize
        text = casualize(text)
    # Editorial wording and its checked source link must survive unchanged.


    # Hard reject — if tool-call markup OR a JSON stream envelope survived
    # scrubbing, refuse to post. Both of these went live in prod 2026-05-13
    # / 2026-05-14 ("<function=bash>" and `{"type":"step_start",...}`).
    from ..core.llm_client import contains_post_unsafe_leak
    if contains_post_unsafe_leak(text):
        log.error(f"[POST] Unsafe leak detected after scrub — refusing to post. Text: {text[:200]!r}")
        raise ToolCallLeakError("tool-call / stream-envelope markup in tweet text")

    # Central write policy: originals daily cap + jittered spacing, then the
    # content gates (French + no near-term price target). A flagged draft is
    # skipped here as a final safety net (generators regenerate upstream).
    from ..guards import action_guard, content_guard
    from ..core import config as _cfg
    # Returns True only when the post actually shipped, DRY_RUN_RECORDED on a
    # dry run, False on any skip (policy / content / dedup).
    # ⛔ Callers MUST gate engagement logging on this result — bot.py logged log_post/log_hotake
    # unconditionally, so a dedup-blocked repeat (e.g. the same hotake) never
    # hit Twitter but still logged 5 phantom rows, polluting the per-pillar
    # ROI loop (2026-06-09; same family as the reply phantom-log bug).
    ok, why = action_guard.can_post(action_guard.POST)
    if not ok:
        log.info(f"[POST] policy skip ({why}).")
        return False
    ok, why = content_guard.validate(text, kind="original")
    if not ok:
        log.info(f"[POST] content_guard skip ({why}): {text[:120]!r}")
        return False
    if content_guard.is_duplicate(text):
        log.info(f"[POST] near-duplicate of a recent post — skipping (no duplication): {text[:120]!r}")
        return False
    if _cfg.dry_run():
        log.info(f"[POST][DRY_RUN] would post: {text[:200]!r}")
        action_guard.record(action_guard.POST, dry_run=True)
        return DRY_RUN_RECORDED

    with _safari_lock:
        # The initial check happens before waiting for Safari. Recheck under
        # its lock so concurrent posts cannot both consume the last slot.
        ok, why = action_guard.can_post(action_guard.POST)
        if not ok:
            log.info("[POST] policy skip after browser wait (%s).", why)
            return False
        if image_path:
            if not _post_tweet_with_image(text, image_path):
                return False
            action_guard.record(action_guard.POST)
            content_guard.note_posted(text)
            _record_posted(text)
            return True

        url = "https://x.com/intent/post?" + urllib.parse.urlencode({"text": text})
        log.info("Opening Twitter in your browser...")
        webbrowser.open(url)
        time.sleep(4)

        log.info("Auto-clicking Post...")
        if not _submit_or_abort("POST"):
            return False
        action_guard.record(action_guard.POST)
        log.info("Tweet submitted!")
        content_guard.note_posted(text)
        _record_posted(text)
        try:
            close_front_tab()
        except OutsideActiveHours:
            pass
    return True


def _record_posted(text: str):
    """Persist a published original/quote into tweet_history.json from the
    write chokepoint — so EVERY surface (spicy, breakout, longform, quote…)
    feeds the dedup corpus + bot memory, not just the 4 bots that called
    history.save_tweet themselves. save_tweet is idempotent, so the bots
    that already record are safe. Bug 2026-06-05: spicy posted the same
    'GPU supply / power bill' take twice because its posts never landed in
    the on-disk history the dedup reads after a restart."""
    try:
        from ..core.history import save_tweet
        save_tweet(text)
    except Exception as e:
        log.info(f"[POST] history record failed (non-fatal): {e}")


def _post_tweet_with_image(text: str, image_path: str) -> bool:
    """Compose a tweet with an attached image. Caller must already hold _safari_lock.
    Returns True only when the submit keystroke ran."""
    import os as _os
    if not _os.path.exists(image_path):
        log.info(f"[POST] Image not found at {image_path} — falling back to text-only.")
        # Fall back to text-only via the intent flow
        url = "https://x.com/intent/post?" + urllib.parse.urlencode({"text": text})
        webbrowser.open(url)
        time.sleep(4)
        if not _submit_or_abort("POST"):
            return False
        time.sleep(2)
        close_front_tab()
        return True

    log.info(f"[POST] Composing tweet with image {image_path}...")
    webbrowser.open("https://x.com/compose/post")
    time.sleep(6)  # composer needs a moment to fully render

    # Step 1: paste the text (focus is auto on the textarea on /compose/post)
    if not _paste_or_abort(text, "POST"):
        return False
    time.sleep(1)

    # Step 2: copy the image to the clipboard, then Cmd+V to attach.
    # GIFs use their own clipboard class so X uploads them ANIMATED
    # (2026-06-05 operator: promo posts ride hype GIFs).
    abs_path = _os.path.abspath(image_path)
    clip_class = "GIFf" if abs_path.lower().endswith(".gif") else "PNGf"
    copy_script = f'set the clipboard to (read POSIX file "{abs_path}" as «class {clip_class}»)'
    if not _run_applescript(copy_script):
        log.info("[POST] Could not copy image to clipboard — posting text-only.")
    else:
        time.sleep(0.5)
        _run_applescript('tell application "System Events" to keystroke "v" using command down')
        time.sleep(3)  # X needs a few seconds to upload + render the image preview

    # Step 3: submit
    if not _submit_or_abort("POST"):
        return False
    time.sleep(3)
    log.info("[POST] Tweet with image posted!")
    close_front_tab()
    return True


def refresh_feed():
    """Open X home feed and refresh it so new tweets load."""
    with _safari_lock:
        log.info("Refreshing X feed...")
        webbrowser.open("https://x.com/home")
        time.sleep(3)
        close_front_tab()


def _maybe_like_parent(tweet_url: str, env_key: str, default_prob: float) -> None:
    """Probabilistically like the tweet we just replied to / quoted.

    Operator 2026-06-15: "we got hit by spam/automation flags — cool down
    the number of likes you give." Liking the parent of EVERY reply (743/day)
    and EVERY quote was the automation signature. A human likes only some of
    what they reply to, so gate it behind a low probability (read at CALL
    time — side-effect env). Replies still ship; we just stop the
    one-like-per-reply firehose. prob<=0 disables parent-likes entirely."""
    try:
        prob = float(os.environ.get(env_key, str(default_prob)))
    except (TypeError, ValueError):
        prob = default_prob
    if prob <= 0 or random.random() > prob:
        return
    try:
        like_tweet(tweet_url)
    except Exception as e:
        log.info(f"[LIKE] parent-like skipped ({e}).")


def _liked_cache_path() -> str:
    """Lazy-resolve the liked_tweets.json path to avoid import-order issues."""
    from ..core.config import _PROJECT_ROOT as _PR
    return os.path.join(_PR, "liked_tweets.json")


def _load_liked_set():
    """Return a CanonReplied set of canonical IDs we've already liked.
    Cross-bot dedup via canonical status ID prevents the 'l' shortcut
    from toggling-OFF a like we set in an earlier cycle."""
    from ..guards import replied_store
    s = replied_store.CanonReplied()
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
    from ..guards import replied_store
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
        cid = replied_store.canonical_tweet_id(u)
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


class LikeOutcome(Enum):
    """What `like_tweet` did. Truthy only for LIKED, so a caller that tests
    the result counts only the likes that shipped."""
    LIKED = "liked"
    ALREADY_LIKED = "already_liked"
    FAILED = "failed"

    def __bool__(self):
        return self is LikeOutcome.LIKED


# The article is identified before anything is clicked: the post with status
# ID __TARGET_ID__, else the focused post, else the status page's own post.
# Only a data-testid="like" button is clicked, never "unlike", so a like can
# neither toggle off nor land on another post. Mode "read" clicks nothing;
# "list" returns the status URL of every post on the page.
_POSTS_JS = r"""
(function(mode, targetId) {
    var SEL = 'article[data-testid="tweet"]';
    function statusId(href) {
        var m = (href || '').match(/\/status\/(\d+)/);
        return m ? m[1] : '';
    }
    // The post's own timestamp link comes before a quoted post's.
    function statusLink(art) {
        var t = art.querySelector('a[href*="/status/"] time');
        var a = t && t.closest('a');
        return a ? a.href : '';
    }
    var all = document.querySelectorAll(SEL);
    var i;
    if (mode === 'list') {
        var posts = [];
        for (i = 0; i < all.length; i++) posts.push(statusLink(all[i]));
        return JSON.stringify({page: location.href, posts: posts});
    }
    var art = null, id = targetId;
    if (!id) {
        var el = document.activeElement;
        if (el && el !== document.body && el !== document.documentElement) {
            art = el.closest ? el.closest(SEL) : null;
        } else {
            id = statusId(location.pathname);
        }
    }
    for (i = 0; id && !art && i < all.length; i++) {
        if (statusId(statusLink(all[i])) === id) art = all[i];
    }
    var url = art ? statusLink(art) : '';
    if (!statusId(url)) return JSON.stringify({url: '', result: 'failed'});
    if (art.querySelector('[data-testid="unlike"]')) {
        return JSON.stringify({url: url, result: 'already_liked'});
    }
    var button = art.querySelector('[data-testid="like"]');
    if (!button) return JSON.stringify({url: url, result: 'failed'});
    if (mode !== 'press') return JSON.stringify({url: url, result: 'not_liked'});
    button.click();
    return JSON.stringify({url: url, result: 'clicked'});
})("__MODE__", "__TARGET_ID__")
"""


def _run_page_js(js: str) -> str:
    """Run `js` in Safari's front tab and return its result, "" when the
    osascript call fails."""
    import tempfile as _tf
    tmp = _tf.NamedTemporaryFile(mode="w", suffix=".js", delete=False)
    tmp.write(js)
    tmp.close()
    try:
        require_active()
        res = subprocess.run(["osascript", "-e", f'''
        set jsCode to (read POSIX file "{tmp.name}")
        tell application "Safari"
            do JavaScript jsCode in current tab of front window
        end tell
        '''], capture_output=True, text=True, timeout=10)
        return (res.stdout or "").strip()
    except OutsideActiveHours:
        raise
    except Exception:
        return ""
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


def _page_posts(mode: str, target_id: str = "") -> dict:
    """Run `_POSTS_JS` in `mode` ("list", "read" or "press") on the post
    with status ID `target_id`; {} when the page gave no answer."""
    js = _POSTS_JS.replace("__MODE__", mode).replace("__TARGET_ID__", target_id)
    try:
        data = json.loads(_run_page_js(js) or "null")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def like_tweet(tweet_url: str = "") -> "LikeOutcome | _DryRunRecorded":
    """Like one post of the open page: `tweet_url`'s when given, else the
    focused post, else the open status page's own post.

    The 'l' shortcut toggles and acts on X's own selection, so it is never
    pressed: the post is found by its status ID and only its "like" button
    is clicked. LIKED is returned once the page shows the post liked; the
    liked cache and the ledger then carry the URL read on the page. A post
    in the liked cache or shown as liked is left alone. DRY_RUN writes a
    dry-run ledger row and returns DRY_RUN_RECORDED.
    """
    if tweet_url and _already_liked(tweet_url):
        log.info(f"[LIKE] already liked {tweet_url[-50:]}; skipping.")
        return LikeOutcome.ALREADY_LIKED
    from ..guards import action_guard
    from ..core import config as _cfg
    from . import x_urls
    if _cfg.dry_run():
        log.info(f"[LIKE][DRY_RUN] would like {tweet_url[-50:] if tweet_url else '(open tweet)'}.")
        action_guard.record(action_guard.LIKE, target=tweet_url, dry_run=True)
        return DRY_RUN_RECORDED
    target = x_urls.status_id(tweet_url)
    if tweet_url and not target:
        log.info(f"[LIKE] {tweet_url} carries no status ID; nothing clicked.")
        return LikeOutcome.FAILED
    if not target:
        post = _page_posts("read")
        target = x_urls.status_id(post.get("url") or "")
        if not target:
            log.info("[LIKE] No identifiable post on the open page; nothing clicked.")
            return LikeOutcome.FAILED
        if post.get("result") == "already_liked" or _already_liked(post["url"]):
            log.info(f"[LIKE] already liked {post['url']}; skipping.")
            return LikeOutcome.ALREADY_LIKED
    pressed = _page_posts("press", target)
    url = pressed.get("url") or ""
    if pressed.get("result") == "already_liked":
        log.info(f"[LIKE] already liked {url}; skipping.")
        return LikeOutcome.ALREADY_LIKED
    if pressed.get("result") != "clicked":
        log.info(f"[LIKE] Post {target} or its like button not found on the page; nothing clicked.")
        return LikeOutcome.FAILED
    time.sleep(1)
    if _page_posts("read", target).get("result") != "already_liked":
        log.info(f"[LIKE] Clicked like on {url} but the page does not show it liked; nothing recorded.")
        return LikeOutcome.FAILED
    log.info(f"[LIKE] Liked {url}")
    _mark_liked(url)
    action_guard.record(action_guard.LIKE, target=url)
    return LikeOutcome.LIKED


def reply_to_tweet(tweet_url: str, reply_text: str, *, debate_turn: bool = False) -> bool:
    """Open a tweet, click reply, type the reply, and submit.

    Returns True only when the reply actually shipped, DRY_RUN_RECORDED on a
    dry run, False when Reply admission refuses it or a Safari step fails.
    Raises StateUnreadable when the ledger or the replied store cannot be
    read: nothing ships until the file is repaired.

    Reply admission (src/guards/reply_admission.py) owns every rule: Blocked
    account, own post, one Reply per post, Debate turn cap, spacing, and the
    final text. It runs once under the Safari lock, which also records the
    Reply, so no other thread can take the last Debate turn or the spacing
    slot between the check and the write. `debate_turn=True` marks an answer
    to someone who answered the account (CONTEXT.md).

    ⛔ CALLERS MUST NOT write the replied store before calling this — the
    claim below REFUSES anything already in it. Bug 2026-06-07: five bots
    "locked the URL in BEFORE posting" (direct_reply/_reply_to_tweets,
    early_bird, mega_watch, reply_bot, roast) → the chokepoint saw their own
    premark and silently skipped 100% of their replies since 2026-06-05
    17:46, while their unconditional log_reply() calls kept writing phantom
    rows into engagement_log (the "941 replies" day was mostly fiction;
    bot.log 'Reply posted!' said 140). The claim happens here, right before
    the Safari write; a dry run never claims, so the store only ever holds
    Replies that shipped."""
    from ..guards import action_guard, active_hours, replied_store, reply_admission
    from ..core import config as _cfg
    # Not a second admission rule: _safari_lock raises OutsideActiveHours on
    # entry, so Overnight is turned into the False refusal callers expect
    # before the lock. judge_reply still judges Waking hours under it.
    if not active_hours.may_act():
        log.info(f"[REPLY] Overnight or stop requested — skipping: {tweet_url}")
        return False
    # Every exit before the submit keystroke sent nothing: a failed step, a
    # stop or 22:00 releases the claim so a later cycle may answer.
    release_claim = False
    try:
        with _safari_lock:
            verdict = reply_admission.judge_reply(tweet_url, reply_text, debate_turn=debate_turn)
            if not verdict:
                log.info(f"[REPLY] not admitted ({verdict.refusal.value}: {verdict.reason}): "
                         f"{tweet_url} {(reply_text or '')[:120]!r}")
                return False
            if _cfg.dry_run():
                log.info(f"[REPLY][DRY_RUN] would reply to {tweet_url}: {verdict.text[:160]!r}")
                action_guard.record(action_guard.REPLY, target=tweet_url, dry_run=True)
                if debate_turn:
                    action_guard.record(action_guard.DEBATE_TURN, target=verdict.author, dry_run=True)
                return DRY_RUN_RECORDED
            # ONE reply per tweet, EVER (operator 2026-06-05). claim() checks
            # and marks under one lock; admission already read the store, this
            # is the atomic word on it.
            if not replied_store.claim(tweet_url):
                log.info(f"[REPLY] already replied to this tweet (chokepoint dedup) — skipping: {tweet_url}")
                return False
            release_claim = True
            # Make sure Safari is focused first
            _run_applescript('''
            tell application "Safari" to activate
            ''')
            time.sleep(0.5)

            log.info(f"Opening tweet: {tweet_url}")
            webbrowser.open(tweet_url)
            # Sleeps trimmed 2026-06-09 (operator: "BOT REALLY SLOW... ACCELERATE"):
            # 22s of fixed waits/reply → ~15s. Page load keeps the biggest margin.
            time.sleep(6)

            # Make sure Safari is in front
            _run_applescript('''
            tell application "Safari" to activate
            ''')
            time.sleep(0.5)

            # Like the parent only SOMETIMES (operator 2026-06-15: liking every
            # tweet we reply to was the automation flag). Idempotent like stays
            # un-toggle-safe. REPLY_LIKE_PARENT_PROB (default 0.12) ≈ like ~1 in 8.
            _maybe_like_parent(tweet_url, "REPLY_LIKE_PARENT_PROB", 0.12)
            time.sleep(1)

            log.info("Clicking reply...")
            if not _run_applescript('''
            tell application "System Events"
                keystroke "r"
            end tell
            '''):
                log.info(f"[REPLY] Reply keystroke failed; nothing sent, tweet left fresh: {tweet_url}")
                close_front_tab()
                return False
            time.sleep(3)  # Wait for reply box to open

            # Paste the reply (clipboard handles accents correctly)
            log.info("Pasting reply...")
            if not _paste_or_abort(verdict.text, "REPLY"):
                return False
            time.sleep(2)  # Wait for paste to complete

            log.info("Submitting reply...")
            require_active()  # last point where a stop still means nothing sent
            # From here X may hold the reply: a failed submit keeps the claim
            # so the tweet never gets a second one.
            release_claim = False
            if not _submit_or_abort("REPLY", target=tweet_url):
                return False
            time.sleep(2)  # Wait for submission
            log.info("Reply posted!")
            action_guard.record(action_guard.REPLY, target=tweet_url)
            if debate_turn:
                action_guard.record(action_guard.DEBATE_TURN, target=verdict.author)
            close_front_tab()
    finally:
        if release_claim:
            replied_store.release(tweet_url)
    return True


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

    # Prune policy: daily unfollow cap, 30-day anti-churn cooldown, never
    # unfollow a protected tier1/tier2 whitelist account, dry-run.
    from ..guards import action_guard
    from ..core import config as _cfg
    ok, why = action_guard.can_unfollow(username)
    if not ok:
        log.info(f"[UNFOLLOW] policy refuses @{username} ({why}).")
        return False
    if _cfg.dry_run():
        log.info(f"[UNFOLLOW][DRY_RUN] would unfollow @{username}.")
        action_guard.record(action_guard.UNFOLLOW, target=username, dry_run=True)
        return DRY_RUN_RECORDED
    action_guard.jitter_sleep(_cfg.FOLLOW_ACTION_JITTER_SECONDS)

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
        action_guard.record(action_guard.UNFOLLOW, target=username)
        action_guard.adjust_following(-1)
        log.info(f"[UNFOLLOW] Unfollowed @{username}.")
        return True


# --- Follow quality gate (operator 2026-06-12: "the accounts you follow are
# trash, very small accounts... not related to AI or investment or crypto —
# fix your algorithm"). The gate rides the profile visit follow_account
# already makes: scrape followers + bio from the loaded page, refuse before
# clicking. Whitelisted seeds are exempt; rejects are cached 30 days so a
# bad candidate never burns a second profile visit. -------------------------

_FOLLOW_REJECTS_FILE = os.path.join(_PROJECT_ROOT, "follow_quality_rejects.json")

_NICHE_BIO_RE = re.compile(
    r"\b(ai|a\.i\.|artificial intelligence|machine learning|\bml\b|llm|gpt|agent|"
    r"crypto|bitcoin|btc|eth|web3|defi|blockchain|token|"
    r"invest|investor|investing|trader|trading|markets?|stocks?|equit|finance|"
    r"financial|fintech|macro|quant|hedge|portfolio|capital|wealth|analyst|"
    r"founder|builder|startup|venture|\bvc\b|tech|software|engineer|nvidia|"
    r"bourse|économie|economy)\b",
    re.IGNORECASE,
)


def _parse_follower_count(text: str) -> int:
    """'12.3K' → 12300, '1,423' → 1423, '2.1M' → 2100000, junk → -1."""
    t = (text or "").strip().replace(",", "").replace(" ", "").replace(" ", "")
    m = re.match(r"^([\d.]+)([KkMm])?$", t)
    if not m:
        return -1
    try:
        n = float(m.group(1))
    except ValueError:
        return -1
    suffix = (m.group(2) or "").lower()
    return int(n * (1_000_000 if suffix == "m" else 1_000 if suffix == "k" else 1))


# Operator 2026-07-19: "follow US / english accounts not foreigner langage
# follows". Non-Latin scripts (CJK, Cyrillic, Arabic, Hangul, Thai, Hebrew,
# Devanagari) — accented Latin (José, Müller) intentionally NOT matched.
_NON_LATIN_SCRIPT_RE = re.compile(
    "["
    "Ѐ-ӿ"   # Cyrillic
    "֐-׿"   # Hebrew
    "؀-ۿ"   # Arabic
    "ऀ-ॿ"   # Devanagari
    "฀-๿"   # Thai
    "぀-ヿ"   # Hiragana + Katakana
    "㄰-㆏"   # Hangul compat jamo
    "一-鿿"   # CJK unified
    "가-힯"   # Hangul syllables
    "]"
)
# Common function words of major Latin-script languages that are rare in
# English bios. ≥3 hits = the bio is written in that language, not just
# quoting a name. Kept short on purpose — precision over recall.
_NON_EN_WORDS_RE = re.compile(
    r"\b(les|des|une|avec|pour|dans|vous|nous|los|las|para|desde|und|der|"
    r"nicht|für|gli|sono|anche|não|você|uma|bir|için|"
    r"değil|yang|dan|untuk)\b",
    re.IGNORECASE,
)


def _looks_non_english_profile(name: str, bio: str) -> str:
    """Return a reject reason if the profile reads non-English, else ''."""
    blob = f"{name or ''} {bio or ''}"
    if len(_NON_LATIN_SCRIPT_RE.findall(blob)) >= 3:
        return "non-English profile (non-Latin script)"
    if len(_NON_EN_WORDS_RE.findall(blob)) >= 3:
        return "non-English profile (foreign-language bio)"
    return ""


def _follow_quality_decision(followers: int, bio: str, name: str,
                             whitelisted: bool, engager: bool = False) -> tuple:
    """Pure gate logic → (ok, reason). Env read at call time.

    `engager=True` (2026-07-19 follow-your-engagers lane): the candidate
    already replied to/engaged US, which is the highest follow-back-
    probability signal there is AND proves the niche by behavior — so the
    min-followers and bio-niche gates are skipped. The English gate,
    blocklist, caps, spacing and churn cooldown still apply."""
    if whitelisted:
        return (True, "whitelisted seed (gate exempt)")
    min_followers = int(os.environ.get("FOLLOW_MIN_FOLLOWERS", "2000"))
    if not engager:
        if followers < 0:
            return (False, "followers count unreadable — won't follow blind")
        if followers < min_followers:
            return (False, f"too small ({followers} followers < {min_followers})")
    if os.environ.get("FOLLOW_REQUIRE_ENGLISH", "1") == "1":
        why = _looks_non_english_profile(name, bio)
        if why:
            return (False, why)
    if not engager and os.environ.get("FOLLOW_REQUIRE_NICHE", "1") == "1":
        blob = f"{name or ''} {bio or ''}"
        if not _NICHE_BIO_RE.search(blob):
            return (False, "off-niche bio (no AI/markets/crypto signal)")
    return (True, "")


def _quality_reject_recent(handle: str, days: int = 30) -> bool:
    try:
        with open(_FOLLOW_REJECTS_FILE) as f:
            doc = json.load(f)
        ts = doc.get((handle or "").lower(), "")
        return bool(ts) and (datetime.now() - datetime.fromisoformat(ts)).days < days
    except (OSError, json.JSONDecodeError, ValueError):
        return False


def _record_quality_reject(handle: str) -> None:
    try:
        try:
            with open(_FOLLOW_REJECTS_FILE) as f:
                doc = json.load(f)
        except (OSError, json.JSONDecodeError):
            doc = {}
        doc[(handle or "").lower()] = datetime.now().isoformat()
        with open(_FOLLOW_REJECTS_FILE, "w") as f:
            json.dump(doc, f, indent=1)
    except OSError:
        pass


def _scrape_profile_quality() -> dict:
    """Read followers count + bio + name from the CURRENTLY LOADED profile
    tab (no extra navigation). Best-effort: {} on any failure."""
    js = """
    (function() {
        var out = {followers: "", bio: "", name: ""};
        var links = document.querySelectorAll('a[href$="/verified_followers"], a[href$="/followers"]');
        for (var i = 0; i < links.length; i++) {
            var m = (links[i].textContent || "").match(/([\\d.,\\u202f ]+[KkMm]?)/);
            if (m) { out.followers = m[1].trim(); break; }
        }
        var bio = document.querySelector('[data-testid="UserDescription"]');
        if (bio) out.bio = (bio.textContent || "").slice(0, 500);
        var nm = document.querySelector('[data-testid="UserName"]');
        if (nm) out.name = (nm.textContent || "").slice(0, 120);
        return JSON.stringify(out);
    })()
    """
    import tempfile as _tf
    tmp = _tf.NamedTemporaryFile(mode="w", suffix=".js", delete=False)
    tmp.write(js)
    tmp.close()
    applescript = f'''
    tell application "Safari"
        set jsCode to (read POSIX file "{tmp.name}")
        do JavaScript jsCode in current tab of front window
    end tell
    '''
    try:
        require_active()
        res = subprocess.run(["osascript", "-e", applescript],
                             capture_output=True, text=True, timeout=15)
        if res.returncode == 0 and res.stdout.strip():
            return json.loads(res.stdout.strip())
    except (Exception, json.JSONDecodeError):
        pass
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
    return {}


def follow_account(username: str, reciprocal: bool = False,
                   engager: bool = False) -> bool:
    """Visit a user's profile and click the Follow button.

    `reciprocal=True` marks a follow-back (someone who already engages with
    us) so the whitelist-only gate is bypassed for it (see can_follow).
    `engager=True` (2026-07-19): the candidate replied to our content —
    the quality gate skips its size/niche checks (behavior proves both)
    while keeping the English gate + every cap/spacing/churn rule.

    Returns True only when the JS click actually fired (best-effort signal),
    DRY_RUN_RECORDED on a dry run. Callers MUST check the return value
    before marking a handle as followed, otherwise transient AppleScript/Safari hiccups will pollute
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
    # Follow policy: whitelist-only (no strangers / no reciprocity), ratio
    # invariant (following < ceiling * followers), daily cap, 30-day
    # anti-churn cooldown, dry-run. Enforced here so every follow bot obeys.
    from ..guards import action_guard
    from ..core import config as _cfg
    ok, why = action_guard.can_follow(username, reciprocal=reciprocal or engager)
    if not ok:
        log.info(f"[FOLLOW] policy refuses @{username} ({why}).")
        return False
    # Quality-reject cache: a candidate already judged small/off-niche
    # within 30 days never burns another profile visit.
    if _quality_reject_recent(username):
        log.info(f"[FOLLOW] @{username} in quality-reject cache — skipping.")
        return False
    if _cfg.dry_run():
        log.info(f"[FOLLOW][DRY_RUN] would follow @{username}.")
        action_guard.record(action_guard.FOLLOW, target=username, dry_run=True)
        return DRY_RUN_RECORDED
    action_guard.jitter_sleep(_cfg.FOLLOW_ACTION_JITTER_SECONDS)
    with _safari_lock:
        profile_url = f"https://x.com/{username}"
        log.info(f"[FOLLOW] Visiting profile: {profile_url}")
        webbrowser.open(profile_url)
        time.sleep(5)

        # Quality gate (operator 2026-06-12: no more trash follows) — reads
        # the page we're already on, refuses BEFORE the click.
        from ..guards.action_guard import is_whitelisted
        q = _scrape_profile_quality()
        ok, why = _follow_quality_decision(
            _parse_follower_count(q.get("followers", "")),
            q.get("bio", ""), q.get("name", ""),
            whitelisted=is_whitelisted(username),
            engager=engager,
        )
        if not ok:
            log.info(f"[FOLLOW] quality gate refuses @{username} ({why}).")
            _record_quality_reject(username)
            close_front_tab()
            return False

        # 2026-06-05 fix: the old inline-quoted JS errored on every attempt
        # ("Could not follow @X via JS" 100% of the time) — quote-escaping
        # broke under osascript, and even when it ran, only the exact text
        # 'Follow' inside placementTracking matched (X moved to
        # data-testid="<id>-follow" buttons + localized labels). Now: temp-file
        # JS (no quote hell), 3 selector strategies, and a REAL status return
        # so we only record a follow when the click actually fired.
        import tempfile as _tf
        follow_js = """
        (function() {
            var btn = document.querySelector('button[data-testid$="-follow"]');
            if (!btn) {
                var all = document.querySelectorAll('button[aria-label], [role="button"][aria-label]');
                for (var i = 0; i < all.length; i++) {
                    var al = all[i].getAttribute('aria-label') || '';
                    if (/^(Follow|Suivre) @/i.test(al)) { btn = all[i]; break; }
                }
            }
            if (!btn) {
                var btns = document.querySelectorAll('[data-testid="placementTracking"] [role="button"], main [role="button"]');
                for (var j = 0; j < btns.length; j++) {
                    var t = (btns[j].textContent || '').trim();
                    if (t === 'Follow' || t === 'Suivre') { btn = btns[j]; break; }
                }
            }
            if (!btn) {
                if (document.querySelector('button[data-testid$="-unfollow"]')) return 'ALREADY';
                return 'NO_BTN';
            }
            btn.click();
            return 'CLICKED';
        })()
        """
        tmp = _tf.NamedTemporaryFile(mode="w", suffix=".js", delete=False)
        tmp.write(follow_js)
        tmp.close()
        applescript = f'''
        tell application "Safari" to activate
        set jsCode to (read POSIX file "{tmp.name}")
        tell application "Safari"
            do JavaScript jsCode in current tab of front window
        end tell
        '''
        status = ""
        try:
            require_active()
            res = subprocess.run(["osascript", "-e", applescript],
                                 capture_output=True, text=True, timeout=15)
            status = (res.stdout or "").strip()
            if res.returncode != 0:
                log.info(f"[FOLLOW] JS error for @{username}: {res.stderr[:150]}")
        except Exception as e:
            log.info(f"[FOLLOW] osascript failed for @{username}: {e}")
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass

        ok = status == "CLICKED"
        if ok:
            time.sleep(2)
            log.info(f"[FOLLOW] Followed @{username}!")
            action_guard.record(action_guard.FOLLOW, target=username)
            action_guard.adjust_following(+1)
        elif status == "ALREADY":
            log.info(f"[FOLLOW] Already following @{username}.")
        else:
            log.info(f"[FOLLOW] Could not follow @{username} (status={status or 'JS_FAIL'}), skipping.")
        close_front_tab()
        return ok


def _like_posts_on_page(count: int, wanted, page_ok=lambda page: True) -> list[LikeOutcome]:
    """Like up to `count` posts of the open page, in page order, whose
    status URL `wanted` accepts, never our own. Every like goes through
    `like_tweet` with the post's URL; the walk stops at the first failure.
    [FAILED] when the page cannot be listed or `page_ok` refuses its URL."""
    from . import x_urls
    listing = _page_posts("list")
    page = listing.get("page") or ""
    if not isinstance(listing.get("posts"), list) or not page_ok(page):
        log.info(f"[LIKE] Could not list the expected posts on {page or 'the open page'}; nothing clicked.")
        return [LikeOutcome.FAILED]
    outcomes = []
    for url in listing["posts"]:
        if len(outcomes) >= count:
            break
        if (not isinstance(url, str) or not x_urls.status_id(url)
                or is_own_post({"url": url}) or not wanted(url)):
            continue
        outcome = like_tweet(url)
        outcomes.append(outcome)
        if outcome is LikeOutcome.FAILED:
            break
    return outcomes


def _like_summary(outcomes: list[LikeOutcome]) -> str:
    return ", ".join(f"{sum(o is kind for o in outcomes)} {kind.value}" for kind in LikeOutcome)


def visit_profile_and_like(username: str, like_count: int = 2) -> list[LikeOutcome]:
    """Visit a user's profile and like up to `like_count` of the posts it
    shows, their own only (reposts of others are skipped). Returns one
    LikeOutcome per post handled; `like_count=0` and DRY_RUN open nothing.

    Gated by `_profile_visit_allowed` (2026-06-07 home/search-only mandate):
    reciprocity likes happen when we meet people on feeds/search, not by
    visiting their profile."""
    if not _profile_visit_allowed(username):
        log.info(f"[LIKE] profile visit blocked (home/search-only mandate): @{username}")
        return []
    if like_count <= 0:
        return []
    from ..core import config as _cfg
    from . import x_urls
    if _cfg.dry_run():
        log.info(f"[LIKE][DRY_RUN] would like up to {like_count} posts of @{username}.")
        return []
    handle = username.strip().lstrip("@").lower()
    with _safari_lock:
        profile_url = f"https://x.com/{username}"
        log.info(f"Visiting profile: {profile_url}")
        webbrowser.open(profile_url)
        try:
            time.sleep(5)
            outcomes = _like_posts_on_page(like_count, lambda url: x_urls.author(url) == handle)
            log.info(f"[LIKE] @{username}: {_like_summary(outcomes)}.")
            time.sleep(1)
            return outcomes
        finally:
            close_front_tab()


def _scrape_tweets_from_page(label: str, max_tweets: int = 10):
    """Run JS on the current Safari page to extract tweets. Returns list of dicts."""
    import json as _json
    import tempfile
    import os

    # Write JS to temp file to avoid AppleScript quote escaping hell
    js_code = """
    (function() {
        function extractFromLabel(label) {
            var m = (label || '').match(/(\\d[\\d,\\.KMkm]*)/);
            if (!m) return 0;
            var s = m[1].replace(/,/g, '').toLowerCase();
            if (s.indexOf('k') !== -1) return Math.round(parseFloat(s) * 1000);
            if (s.indexOf('m') !== -1) return Math.round(parseFloat(s) * 1000000);
            return parseInt(s, 10) || 0;
        }
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
            var timeEl = a.querySelector('time[datetime]');
            var ts = timeEl ? timeEl.getAttribute('datetime') : '';
            // Views: the analytics link's aria-label carries the count
            // ("12.3K views"). Powers performance.scrape_own_metrics.
            var views = 0;
            var an = a.querySelector('a[href*="/analytics"]');
            if (an) views = extractFromLabel(an.getAttribute('aria-label') || '');
            if (url) tweets.push(JSON.stringify({u: url, t: text.substring(0, 200), a: author || 'unknown', l: likes, r: replies, v: views, tl: tl, ir: isReply, ts: ts}));
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
        require_active()
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
                _record_timed_out_scrape(label)
                return []

        raw = result.stdout.strip()
        if result.returncode != 0:
            log.info(f"[SCRAPE] JS failed for {label}: {result.stderr[:200]}")
            return []
        if not raw or raw == 'NO_ARTICLES':
            log.info(f"[SCRAPE] No articles on {label} (page not loaded?)")
            _record_blank_page(is_home_feed="home feed" in label, label=label)
            return []
        if raw.startswith('ARTICLES_'):
            log.info(f"[SCRAPE] {label}: {raw}")
            _record_blank_page(is_home_feed="home feed" in label, label=label)
            return []

        data = sanitize_for_json(_json.loads(raw))
        tweets = [{
            "url": t["u"],
            "text": t["t"],
            "author": t["a"],
            "likes": int(t.get("l") or 0),
            "replies": int(t.get("r") or 0),
            "translated_from": t.get("tl") or "",
            "is_reply": bool(t.get("ir") or False),
            # Bug 2026-06-05 (retweets 140/day → 0): the JS extracted the
            # <time datetime> but this mapping DROPPED it, so every candidate
            # had unknown age and the hard 48h freshness gate skipped 100% of
            # feed/search candidates ("No viable candidates this cycle").
            "timestamp": t.get("ts") or "",
            "views": int(t.get("v") or 0),
        } for t in data]
        _reset_blank_page_count()
        log.info(f"[SCRAPE] Found {len(tweets)} tweets on {label}")
        return tweets
    except Exception as e:
        log.info(f"[SCRAPE] Exception for {label}: {e}")
        _record_blank_page(is_home_feed="home feed" in label, label=label)
        return []
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


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


def is_own_post(tweet: dict) -> bool:
    """Authoritative ownership check for scraped tweets (2026-06-07).

    The scraper's `author` field is the DISPLAY NAME ("The AI Therapist"),
    not the @handle — five bots compared it against BOT_HANDLE and silently
    classified every own post as foreign (the boost engine never once picked
    a banger; suppression_watch measured nothing). The URL is ground truth:
    own posts and own QRTs live under /BOT_HANDLE/status/; retweets of
    others on our profile carry the ORIGINAL author's URL and are correctly
    excluded."""
    from ..core.config import BOT_HANDLE
    url = (tweet.get("url") or "").lower()
    return f"x.com/{BOT_HANDLE.lower()}/status/" in url


def _profile_visit_allowed(username: str) -> bool:
    """Operator mandate 2026-06-07 PM: NO profile visits for discovery —
    the only scrape surfaces are @TheBTCTherapist (the main account), the
    Home feed (For You + Following tab), and search terms. Our own profile
    stays visitable (boost/pin/metrics/with_replies callers need it). Env
    read at CALL time (side-effect gate — never an import-time constant)."""
    from ..core.config import BOT_HANDLE
    base = (username or "").strip().lstrip("@").split("/")[0].lower()
    if not base:
        return False
    if base == BOT_HANDLE.lower():
        return True  # own profile (incl. BOT_HANDLE/with_replies callers)
    allow = os.environ.get("PROFILE_VISIT_ALLOWLIST", "TheBTCTherapist,Graphseo")
    return base in {h.strip().lstrip("@").lower() for h in allow.split(",") if h.strip()}


def scrape_profile_tweets(username: str, max_tweets: int = 5):
    """Visit a profile and scrape their recent tweet URLs and text.

    Gated by `_profile_visit_allowed`: non-allowlisted profiles return []
    BEFORE any Safari work — discovery lives on home/following/search."""
    if not _profile_visit_allowed(username):
        log.info(f"[SCRAPE] profile visit blocked (home/search-only mandate): @{username}")
        return []
    with _safari_lock:
        profile_url = f"https://x.com/{username}"
        log.info(f"[SCRAPE] Visiting profile: {profile_url}")
        webbrowser.open(profile_url)
        time.sleep(8)
        _scroll_page()

        tweets = _scrape_tweets_from_page(f"@{username}", max_tweets)
        close_front_tab()
        return tweets


def scrape_mentions(max_tweets: int = 20):
    """Scrape the mentions notifications tab — tweets that mention/reply to
    us anywhere on X. Feeds the debate engine (operator 2026-07-19: 'more
    debates... reply to other people replies and get her on a roll'). The
    mentions tab renders standard tweet articles, so the shared page scraper
    applies; best-effort [] on any failure."""
    with _safari_lock:
        log.info("[SCRAPE] Opening mentions notifications...")
        webbrowser.open("https://x.com/notifications/mentions")
        time.sleep(8)
        for _ in range(2):
            _scroll_page()
        tweets = _scrape_tweets_from_page("mentions", max_tweets)
        close_front_tab()
        return tweets


def scrape_home_feed(max_tweets: int = 15):
    """Scrape tweets from the home feed (For You / algorithmic)."""
    with _safari_lock:
        log.info("[SCRAPE] Opening home feed...")
        webbrowser.open("https://x.com/home")
        time.sleep(8)

        # Scroll deep — reply to everything means we need to surface many tweets.
        # Each scroll reveals ~8-12 posts; cap at 15 scrolls to stay bounded.
        for _ in range(max(4, min(15, max_tweets // 7))):
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
            require_active()
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
        # Scroll proportionally to the requested depth (same as home feed).
        for _ in range(max(2, min(8, max_tweets // 12))):
            _scroll_page()

        tweets = _scrape_tweets_from_page("following feed", max_tweets)
        close_front_tab()
        return tweets


def scrape_x_search(query: str, max_tweets: int = 10, tab: str = "top"):
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
    from ..core import config as _cfg

    if _cfg.dry_run():
        log.info(f"[PIN][DRY_RUN] would pin {tweet_url}.")
        return False

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
            require_active()
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


def like_own_tweet_replies() -> list[LikeOutcome]:
    """Visit own profile, open latest tweet, and like the replies under it,
    never our own posts, to build loyalty. Returns one LikeOutcome per post
    handled; DRY_RUN opens nothing."""
    from ..core import config as _cfg
    if _cfg.dry_run():
        log.info("[NOTIFY][DRY_RUN] would like replies on our latest tweet.")
        return []
    # Cooled down 8→3 (operator 2026-06-15: too many likes tripped the
    # automation flag). Liking our own engagers is the most defensible
    # like, but fewer is calmer. Env-tunable.
    try:
        _n_like = max(0, int(os.environ.get("NOTIFY_LIKE_REPLIES_COUNT", "3")))
    except (TypeError, ValueError):
        _n_like = 3
    if _n_like == 0:
        return []
    with _safari_lock:
        log.info("[NOTIFY] Opening own profile...")
        webbrowser.open(BOT_PROFILE_URL)
        try:
            time.sleep(5)
            log.info("[NOTIFY] Opening latest tweet...")
            _navigate_to_first_tweet()
            time.sleep(4)
            log.info(f"[NOTIFY] Liking up to {_n_like} replies...")
            # Off our own status page, "not ours" would match any post.
            outcomes = _like_posts_on_page(_n_like, lambda url: True,
                                           page_ok=lambda page: is_own_post({"url": page}))
            log.info(f"[NOTIFY] Replies: {_like_summary(outcomes)}.")
            time.sleep(2)
            return outcomes
        finally:
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
            require_active()
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


def reply_to_tweet_in_thread(reply_url: str, reply_text: str, *, debate_turn: bool = False):
    """Reply to a specific reply (nested), so our reply lands UNDER theirs in the thread.

    Works because navigating to a reply's own status URL puts that reply in focus, so
    pressing 'r' replies to *that* reply. Reuses reply_to_tweet's flow.
    """
    log.info(f"[REPLYBACK] Replying in-thread to: {reply_url}")
    return reply_to_tweet(reply_url, reply_text, debate_turn=debate_turn)

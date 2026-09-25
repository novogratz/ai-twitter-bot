"""Write chokepoints for X via Safari + AppleScript (macOS only): each post,
reply, like, follow and pin has one function here that owns its rules, and
runs them through `confirmed_write`."""
import json
import os
import random
import re
import time
import urllib.parse
from datetime import datetime
from enum import Enum
from ..core.config import _PROJECT_ROOT, BOT_PROFILE_URL
from ..core.logger import log
from ..guards.active_hours import require_active
from . import confirmed_write, safari, scraper
from .confirmed_write import WriteOutcome

_SUBMIT_KEYSTROKE = 'tell application "System Events" to keystroke return using command down'


def _paste_or_abort(text: str, tag: str) -> bool:
    """Paste into the open composer. On failure nothing was sent: return
    False."""
    if safari._paste_text(text):
        return True
    log.info(f"[{tag}] Paste failed; nothing sent.")
    return False


def _submit_or_abort(tag: str, target: str = "") -> bool:
    """Press Cmd+Return in the open composer. On failure the outcome is
    unknown: return False, and the write is UNCONFIRMED."""
    if safari._run_applescript(_SUBMIT_KEYSTROKE):
        return True
    log.warning(f"[{tag}] Submit keystroke failed; outcome unknown"
                f"{': ' + target if target else '.'}")
    return False


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


class ToolCallLeakError(Exception):
    """Raised when a tweet still contains tool-call markup after scrubbing.

    Better to crash the cycle than to post '<function=bash>...' as a tweet.
    """


def post_tweet(text: str) -> WriteOutcome:
    """Publish an Original through the intent URL. Its reviewed wording and
    checked source link ship unchanged.

    Returns SHIPPED once the submit keystroke ran, REFUSED on a policy,
    content or dedup skip, FAILED when a step before the submit failed,
    UNCONFIRMED when the submit keystroke failed, DRY_RUN on a dry run.
    Only SHIPPED is truthy.
    """
    text = _scrub_metadata_leaks(text)

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
    # ⛔ Callers MUST gate engagement logging on this result — bot.py logged log_post/log_hotake
    # unconditionally, so a dedup-blocked repeat (e.g. the same hotake) never
    # hit Twitter but still logged 5 phantom rows, polluting the per-pillar
    # ROI loop (2026-06-09; same family as the reply phantom-log bug).

    def admit():
        ok, why = action_guard.can_post(action_guard.POST)
        if not ok:
            log.info(f"[POST] policy skip ({why}).")
            return WriteOutcome.REFUSED
        ok, why = content_guard.validate(text, kind="original")
        if not ok:
            log.info(f"[POST] content_guard skip ({why}): {text[:120]!r}")
            return WriteOutcome.REFUSED
        if content_guard.is_duplicate(text):
            log.info(f"[POST] near-duplicate of a recent post — skipping (no duplication): {text[:120]!r}")
            return WriteOutcome.REFUSED
        return None

    def recheck():
        # The initial check happens before waiting for Safari. Recheck under
        # its lock so concurrent posts cannot both consume the last slot.
        ok, why = action_guard.can_post(action_guard.POST)
        if not ok:
            log.info("[POST] policy skip after browser wait (%s).", why)
            return WriteOutcome.REFUSED
        return None

    def steps():
        url = "https://x.com/intent/post?" + urllib.parse.urlencode({"text": text})
        log.info("Opening Twitter in your browser...")
        safari.open_url(url)
        time.sleep(4)

        log.info("Auto-clicking Post...")
        if not _submit_or_abort("POST"):
            return WriteOutcome.UNCONFIRMED
        log.info("Tweet submitted!")
        return WriteOutcome.SHIPPED

    def after_record():
        content_guard.note_posted(text)
        _record_posted(text)

    return confirmed_write.run(
        "POST", WriteOutcome, would=lambda: f"post: {text[:200]!r}",
        rows=lambda: [(action_guard.POST, None)],
        before_lock=(admit, confirmed_write.DRY_RUN_EXIT), under_lock=(recheck,),
        steps=steps, after_record=after_record)


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
    the result counts only the likes that shipped. UNCONFIRMED: the click
    went out but the page never showed the post liked. DRY_RUN: a dry-run
    ledger row, nothing clicked."""
    LIKED = "liked"
    ALREADY_LIKED = "already_liked"
    BLOCKED = "blocked"
    FAILED = "failed"
    UNCONFIRMED = "unconfirmed"
    DRY_RUN = "dry_run"

    def __bool__(self):
        return self is LikeOutcome.LIKED


# The article is identified before anything is clicked: the post with status
# ID __TARGET_ID__, and no other. Only a data-testid="like" button is
# clicked, never "unlike", so a like can neither toggle off nor land on
# another post. Mode "read" clicks nothing; "list" returns the status URL of
# every post on the page.
_POSTS_JS = r"""
(function(mode, targetId) {
    var SEL = 'article[data-testid="tweet"]';
    function statusId(href) {
        var m = (href || '').match(/\/status\/(\d+)/);
        return m ? m[1] : '';
    }
    // A quoted post's timestamp link can come before the post's own.
    function statusLink(art) {
        var times = art.querySelectorAll('a[href*="/status/"] time');
        for (var j = 0; j < times.length; j++) {
            var a = times[j].closest('a');
            if (a && a.closest('article') === art) return a.href;
        }
        return '';
    }
    var all = document.querySelectorAll(SEL);
    var i;
    if (mode === 'list') {
        var posts = [];
        for (i = 0; i < all.length; i++) posts.push(statusLink(all[i]));
        return JSON.stringify({page: location.href, posts: posts});
    }
    var art = null;
    for (i = 0; targetId && !art && i < all.length; i++) {
        if (statusId(statusLink(all[i])) === targetId) art = all[i];
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
    return safari._run_js(js, 10, log_prefix="[LIKE]")


def _page_posts(mode: str, target_id: str = "") -> dict:
    """Run `_POSTS_JS` in `mode` ("list", "read" or "press") on the post
    with status ID `target_id`; {} when the page gave no answer."""
    js = _POSTS_JS.replace("__MODE__", mode).replace("__TARGET_ID__", target_id)
    try:
        data = json.loads(_run_page_js(js) or "null")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def like_tweet(tweet_url: str) -> LikeOutcome:
    """Like the post of the open page whose status ID `tweet_url` carries.

    The 'l' shortcut toggles and acts on X's own selection, so it is never
    pressed: the post is found by its status ID and only its "like" button
    is clicked. A post by a Blocked account (author read from the URL,
    matched as Reply admission does) returns BLOCKED; nothing is clicked or
    recorded. LIKED is returned once
    the page shows the post liked; the liked cache and the ledger then carry
    the URL read on the page. A click the page does not confirm returns
    UNCONFIRMED and records nothing. A post in the liked cache or shown as
    liked is left alone. The page is read and clicked under the Safari lock.
    DRY_RUN writes a dry-run ledger row and returns DRY_RUN.
    """
    from ..guards import action_guard, reply_admission
    from . import x_urls
    target = x_urls.status_id(tweet_url)
    liked_url = tweet_url

    def admit():
        handle = x_urls.author(tweet_url)
        if handle and reply_admission.is_blocked_account(handle):
            log.info(f"[LIKE] @{handle} is a Blocked account; {tweet_url} not liked.")
            return LikeOutcome.BLOCKED
        if _already_liked(tweet_url):
            log.info(f"[LIKE] already liked {tweet_url[-50:]}; skipping.")
            return LikeOutcome.ALREADY_LIKED
        return None

    def check_status_id():
        if not target:
            log.info(f"[LIKE] {tweet_url or '(no URL)'} carries no status ID; nothing clicked.")
            return LikeOutcome.FAILED
        return None

    def steps():
        nonlocal liked_url
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
            log.info(f"[LIKE] Clicked like on {url} but the page does not show it liked.")
            return LikeOutcome.UNCONFIRMED
        log.info(f"[LIKE] Liked {url}")
        liked_url = url
        _mark_liked(url)
        return LikeOutcome.LIKED

    # The post is on the open page: nothing to open, no tab to close.
    return confirmed_write.run(
        "LIKE", LikeOutcome, would=lambda: f"like {tweet_url[-50:]}.",
        rows=lambda: [(action_guard.LIKE, liked_url)],
        before_lock=(admit, confirmed_write.DRY_RUN_EXIT, check_status_id),
        steps=steps, close_tab=False)


def reply_to_tweet(tweet_url: str, reply_text: str, *, debate_turn: bool = False) -> WriteOutcome:
    """Open a tweet, click reply, type the reply, and submit.

    Returns SHIPPED only when the reply actually shipped, DRY_RUN on a dry
    run, REFUSED when Reply admission or the replied store refuses
    it, FAILED when a Safari step before the submit fails, UNCONFIRMED when
    the submit keystroke fails. Only SHIPPED is truthy.
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
    # Set by an admitting verdict: the exact text to send, and its author.
    admitted_text = author = ""

    def admit():
        # Not a second admission rule: _safari_lock raises OutsideActiveHours on
        # entry, so Overnight is turned into the refusal callers expect before
        # the lock. judge_reply still judges Waking hours under it.
        if not active_hours.may_act():
            log.info(f"[REPLY] Overnight or stop requested — skipping: {tweet_url}")
            return WriteOutcome.REFUSED
        return None

    def judge():
        nonlocal admitted_text, author
        verdict = reply_admission.judge_reply(tweet_url, reply_text, debate_turn=debate_turn)
        if not verdict:
            log.info(f"[REPLY] not admitted ({verdict.refusal.value}: {verdict.reason}): "
                     f"{tweet_url} {(reply_text or '')[:120]!r}")
            return WriteOutcome.REFUSED
        admitted_text, author = verdict.text, verdict.author
        return None

    def claim():
        # ONE reply per tweet, EVER (operator 2026-06-05). claim() checks
        # and marks under one lock; admission already read the store, this
        # is the atomic word on it. A dry run never gets here.
        if not replied_store.claim(tweet_url):
            log.info(f"[REPLY] already replied to this tweet (chokepoint dedup) — skipping: {tweet_url}")
            return WriteOutcome.REFUSED
        return None

    def steps():
        # Every exit before the submit keystroke sent nothing: a failed step, a
        # stop or bedtime releases the claim so a later cycle may answer.
        sent = False
        try:
            # Make sure Safari is focused first
            safari._run_applescript('''
            tell application "Safari" to activate
            ''')
            time.sleep(0.5)

            log.info(f"Opening tweet: {tweet_url}")
            safari.open_url(tweet_url)
            # Sleeps trimmed 2026-06-09 (operator: "BOT REALLY SLOW... ACCELERATE"):
            # 22s of fixed waits/reply → ~15s. Page load keeps the biggest margin.
            time.sleep(6)

            # Make sure Safari is in front
            safari._run_applescript('''
            tell application "Safari" to activate
            ''')
            time.sleep(0.5)

            # Like the parent only SOMETIMES (operator 2026-06-15: liking every
            # tweet we reply to was the automation flag). Idempotent like stays
            # un-toggle-safe. REPLY_LIKE_PARENT_PROB (default 0.12) ≈ like ~1 in 8.
            _maybe_like_parent(tweet_url, "REPLY_LIKE_PARENT_PROB", 0.12)
            time.sleep(1)

            log.info("Clicking reply...")
            if not safari._run_applescript('''
            tell application "System Events"
                keystroke "r"
            end tell
            '''):
                log.info(f"[REPLY] Reply keystroke failed; nothing sent, tweet left fresh: {tweet_url}")
                return WriteOutcome.FAILED
            time.sleep(3)  # Wait for reply box to open

            # Paste the reply (clipboard handles accents correctly)
            log.info("Pasting reply...")
            if not _paste_or_abort(admitted_text, "REPLY"):
                return WriteOutcome.FAILED
            time.sleep(2)  # Wait for paste to complete

            log.info("Submitting reply...")
            require_active()  # last point where a stop still means nothing sent
            # From here X may hold the reply: a failed submit keeps the claim
            # so the tweet never gets a second one.
            sent = True
            if not _submit_or_abort("REPLY", target=tweet_url):
                return WriteOutcome.UNCONFIRMED
            time.sleep(2)  # Wait for submission
            log.info("Reply posted!")
            return WriteOutcome.SHIPPED
        finally:
            if not sent:
                replied_store.release(tweet_url)

    def rows():
        return [(action_guard.REPLY, tweet_url)] + (
            [(action_guard.DEBATE_TURN, author)] if debate_turn else [])

    # Admission needs the lock, so a dry run stops under it; it never claims.
    return confirmed_write.run(
        "REPLY", WriteOutcome, would=lambda: f"reply to {tweet_url}: {admitted_text[:160]!r}",
        rows=rows, before_lock=(admit,), under_lock=(judge, confirmed_write.DRY_RUN_EXIT, claim),
        steps=steps)


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


def follow_account(username: str, reciprocal: bool = False,
                   engager: bool = False) -> WriteOutcome:
    """Visit a user's profile and click the Follow button.

    `reciprocal=True` marks a follow-back (someone who already engages with
    us) so the whitelist-only gate is bypassed for it (see can_follow).
    `engager=True` (2026-07-19): the candidate replied to our content —
    the quality gate skips its size/niche checks (behavior proves both)
    while keeping the English gate + every cap/spacing/churn rule.

    Returns SHIPPED only when the JS click actually fired (best-effort
    signal), DRY_RUN on a dry run, REFUSED on a policy or quality
    refusal or an account already followed, FAILED when no Follow button was
    clicked. Callers MUST check the return value
    before marking a handle as followed, otherwise transient AppleScript/Safari hiccups will pollute
    followed_accounts.json with false-positives we never retry.
    """
    # Sanitize: strip whitespace + leading @, reject display-name garbage.
    # X handles are [A-Za-z0-9_]{1,15}. Anything else (spaces, slashes, > 15 chars,
    # accents, punctuation) is a scraper artifact like "aisha mansion" or
    # "caborashedzaborashedles" and would just burn a profile-visit + 5s sleep.
    username = (username or "").strip().lstrip("@")
    from ..guards import action_guard
    from ..core import config as _cfg

    def admit():
        if not username or len(username) > 15 or not all(
            c.isascii() and (c.isalnum() or c == "_") for c in username
        ):
            log.info(f"[FOLLOW] Invalid handle '{username}' — skipping.")
            return WriteOutcome.REFUSED
        # Follow policy: whitelist-only (no strangers / no reciprocity), ratio
        # invariant (following < ceiling * followers), daily cap, 30-day
        # anti-churn cooldown, dry-run. Enforced here so every follow bot obeys.
        ok, why = action_guard.can_follow(username, reciprocal=reciprocal or engager)
        if not ok:
            log.info(f"[FOLLOW] policy refuses @{username} ({why}).")
            return WriteOutcome.REFUSED
        # Quality-reject cache: a candidate already judged small/off-niche
        # within 30 days never burns another profile visit.
        if _quality_reject_recent(username):
            log.info(f"[FOLLOW] @{username} in quality-reject cache — skipping.")
            return WriteOutcome.REFUSED
        return None

    def pause():
        action_guard.jitter_sleep(_cfg.FOLLOW_ACTION_JITTER_SECONDS)

    def steps():
        profile_url = f"https://x.com/{username}"
        log.info(f"[FOLLOW] Visiting profile: {profile_url}")
        safari.open_url(profile_url)
        time.sleep(5)

        # Quality gate (operator 2026-06-12: no more trash follows) — reads
        # the page we're already on, refuses BEFORE the click.
        from ..guards.action_guard import is_whitelisted
        q = scraper._scrape_profile_quality()
        ok, why = _follow_quality_decision(
            _parse_follower_count(q.get("followers", "")),
            q.get("bio", ""), q.get("name", ""),
            whitelisted=is_whitelisted(username),
            engager=engager,
        )
        if not ok:
            log.info(f"[FOLLOW] quality gate refuses @{username} ({why}).")
            _record_quality_reject(username)
            return WriteOutcome.REFUSED

        # 2026-06-05 fix: the old inline-quoted JS errored on every attempt
        # ("Could not follow @X via JS" 100% of the time) — quote-escaping
        # broke under osascript, and even when it ran, only the exact text
        # 'Follow' inside placementTracking matched (X moved to
        # data-testid="<id>-follow" buttons + localized labels). Now: temp-file
        # JS (no quote hell), 3 selector strategies, and a REAL status return
        # so we only record a follow when the click actually fired.
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
        status = safari._run_js(follow_js, 15, log_prefix="[FOLLOW]", activate=True)
        if status == "CLICKED":
            time.sleep(2)
            log.info(f"[FOLLOW] Followed @{username}!")
            return WriteOutcome.SHIPPED
        if status == "ALREADY":
            log.info(f"[FOLLOW] Already following @{username}.")
            return WriteOutcome.REFUSED
        log.info(f"[FOLLOW] Could not follow @{username} (status={status or 'JS_FAIL'}), skipping.")
        return WriteOutcome.FAILED

    return confirmed_write.run(
        "FOLLOW", WriteOutcome, would=lambda: f"follow @{username}.",
        rows=lambda: [(action_guard.FOLLOW, username)],
        before_lock=(admit, confirmed_write.DRY_RUN_EXIT, pause), steps=steps,
        after_record=lambda: action_guard.adjust_following(+1))


def _like_posts_on_page(count: int, wanted, page_ok=lambda page: True,
                        outcomes: list | None = None, deadline: float | None = None) -> list[LikeOutcome]:
    """Like up to `count` posts of the open page, in page order, whose
    status URL `wanted` accepts, never our own. Every like goes through
    `like_tweet` with the post's URL; the walk stops at the first FAILED or
    UNCONFIRMED, and starts no like once `time.monotonic()` reaches
    `deadline`. Outcomes are appended to `outcomes` as they come, so a
    caller keeps them when a stop raises mid-walk. [FAILED] when the page
    cannot be listed or `page_ok` refuses its URL."""
    from . import x_urls
    outcomes = [] if outcomes is None else outcomes
    listing = _page_posts("list")
    page = listing.get("page") or ""
    if not isinstance(listing.get("posts"), list) or not page_ok(page):
        log.info(f"[LIKE] Could not list the expected posts on {page or 'the open page'}; nothing clicked.")
        outcomes.append(LikeOutcome.FAILED)
        return outcomes
    handled = 0
    for url in listing["posts"]:
        if handled >= count:
            break
        if (not isinstance(url, str) or not x_urls.status_id(url)
                or scraper.is_own_post({"url": url}) or not wanted(url)):
            continue
        if deadline is not None and time.monotonic() >= deadline:
            log.info("[LIKE] Cycle time is up; no more likes on this page.")
            break
        outcome = like_tweet(url)
        outcomes.append(outcome)
        handled += 1
        if outcome in (LikeOutcome.FAILED, LikeOutcome.UNCONFIRMED):
            break
    return outcomes


def like_summary(outcomes: list[LikeOutcome]) -> str:
    # A walk opens nothing on a dry run, so it never meets DRY_RUN.
    return ", ".join(f"{sum(o is kind for o in outcomes)} {kind.value}" for kind in LikeOutcome
                     if kind is not LikeOutcome.DRY_RUN)


def like_search_posts(url: str, count: int, seconds: float,
                      outcomes: list | None = None) -> list[LikeOutcome]:
    """Open the X search `url`, scroll, and like up to `count` of the posts
    it lists, never our own, each through `like_tweet`. No like starts once
    `seconds` have passed since the Safari lock was taken, and nothing is
    clicked unless the open tab is a search page. Outcomes are appended to
    `outcomes` as they come, so a caller keeps them when a stop raises
    mid-walk; the tab is closed even then. DRY_RUN opens nothing."""
    from ..core import config as _cfg
    outcomes = [] if outcomes is None else outcomes
    if _cfg.dry_run():
        log.info(f"[LIKE][DRY_RUN] would like up to {count} posts of {url}.")
        return outcomes
    with safari._safari_lock:
        deadline = time.monotonic() + seconds
        log.info(f"[LIKE] Opening search: {url}")
        safari.open_url(url)
        try:
            time.sleep(7)
            # Scroll twice to populate ~20-30 articles.
            safari._scroll_page()
            time.sleep(1)
            safari._scroll_page()
            time.sleep(1)
            _like_posts_on_page(
                count, lambda post: True,
                page_ok=lambda page: urllib.parse.urlparse(page).path == "/search",
                outcomes=outcomes, deadline=deadline)
        finally:
            safari.close_front_tab()
    return outcomes


def visit_profile_and_like(username: str, like_count: int = 2) -> list[LikeOutcome]:
    """Visit a user's profile and like up to `like_count` of the posts it
    shows, their own only (reposts of others are skipped). Returns one
    LikeOutcome per post handled; `like_count=0` and DRY_RUN open nothing.

    Gated by `_profile_visit_allowed` (2026-06-07 home/search-only mandate):
    likes to Engagers happen when we meet them on feeds/search, not by
    visiting their profile."""
    if not scraper._profile_visit_allowed(username):
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
    with safari._safari_lock:
        profile_url = f"https://x.com/{username}"
        log.info(f"Visiting profile: {profile_url}")
        safari.open_url(profile_url)
        try:
            time.sleep(5)
            outcomes = _like_posts_on_page(like_count, lambda url: x_urls.author(url) == handle)
            log.info(f"[LIKE] @{username}: {like_summary(outcomes)}.")
            time.sleep(1)
            return outcomes
        finally:
            safari.close_front_tab()


def pin_own_tweet(tweet_url: str) -> WriteOutcome:
    """Pin one of our own tweets to the profile via the More menu.

    Best-effort. X's tweet-action menu DOM is stable but the wording of the
    'Pin' item varies (FR: 'Épingler à votre profil' / EN: 'Pin to your
    profile'). We click via JS by matching either string. Returns SHIPPED and
    writes a ledger row only when the menu item was clicked and the confirm
    dialog's button was clicked; no row otherwise: FAILED before the Pin
    click, UNCONFIRMED after it, a missing confirm dialog included. DRY_RUN
    writes a dry-run ledger row and returns DRY_RUN.

    Note: X surfaces a confirmation modal on first pin per session; we
    handle it by clicking the confirm button (data-testid="confirmationSheetConfirm").
    """
    from ..guards import action_guard

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
        return safari._run_js(js, timeout_s, log_prefix="[PIN]", activate=True)

    def steps():
        log.info(f"[PIN] Opening tweet to pin: {tweet_url}")
        safari.open_url(tweet_url)
        time.sleep(7)

        step1 = _exec_js(js_code)
        log.info(f"[PIN] More-menu open: {step1}")
        if step1 != "MORE_CLICKED":
            return WriteOutcome.FAILED
        time.sleep(1.2)

        step2 = _exec_js(js_pin_item)
        log.info(f"[PIN] Pin item click: {step2}")
        if step2 != "PIN_CLICKED":
            return WriteOutcome.FAILED
        time.sleep(1.5)

        step3 = _exec_js(js_confirm)
        log.info(f"[PIN] Confirm modal: {step3}")
        if step3 == "NO_CONFIRM":
            log.info(f"[PIN] No confirm dialog after the Pin click; not counted as a pin: {tweet_url}")
        # Whether the confirm modal appeared or not, we leave the page.
        time.sleep(1)
        return WriteOutcome.SHIPPED if step3 == "CONFIRMED" else WriteOutcome.UNCONFIRMED

    return confirmed_write.run(
        "PIN", WriteOutcome, would=lambda: f"pin {tweet_url}.",
        rows=lambda: [(action_guard.PIN, tweet_url)],
        before_lock=(confirmed_write.DRY_RUN_EXIT,), steps=steps)


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
    with safari._safari_lock:
        log.info("[NOTIFY] Opening own profile...")
        safari.open_url(BOT_PROFILE_URL)
        try:
            time.sleep(5)
            log.info("[NOTIFY] Opening latest tweet...")
            safari._navigate_to_first_tweet()
            time.sleep(4)
            log.info(f"[NOTIFY] Liking up to {_n_like} replies...")
            # Off our own status page, "not ours" would match any post.
            outcomes = _like_posts_on_page(_n_like, lambda url: True,
                                           page_ok=lambda page: scraper.is_own_post({"url": page}))
            log.info(f"[NOTIFY] Replies: {like_summary(outcomes)}.")
            time.sleep(2)
            return outcomes
        finally:
            safari.close_front_tab()


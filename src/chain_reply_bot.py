"""Chain-reply bot — respond to replies on our REPLIES (not just on our posts).

Most reply-back logic in `notify_bot.run_replyback_cycle` only handles
people who reply to OUR ORIGINAL POSTS. But the bot lives in reply
threads on other people's tweets. When someone replies to OUR REPLY in
a thread, that's a real conversation we're missing.

Strategy:
  - Every 15 min, scrape /<bot>/with_replies (the same JS we use in
    promote_bot to surface our recent replies).
  - For each of our recent replies, visit its detail page, look for
    nested replies (people responding to OUR comment).
  - For each new nested reply (URL not in chain_replied.json), generate
    a follow-up via replyback_agent. Match the parent-tweet language
    with FR priority.
  - Loop guard: track per-thread our-turn count. Cap at 3 our-turns
    per root-tweet thread. After 3, mark thread DONE and stop.
  - Cap 4 chain-replies per cycle.
"""
import json
import os
import re
import subprocess
import tempfile
import time
import traceback
import webbrowser
from datetime import datetime

from .config import _PROJECT_ROOT, BOT_HANDLE, BLOCKLIST
from .logger import log
from .twitter_client import (
    _safari_lock, close_front_tab, _scroll_page, scrape_profile_tweets,
    reply_to_tweet,
)
from .replyback_agent import generate_replyback
from .humanizer import humanize
from .engagement_log import log_reply

CHAIN_REPLIED_FILE = os.path.join(_PROJECT_ROOT, "chain_replied.json")
THREAD_TURN_FILE = os.path.join(_PROJECT_ROOT, "chain_thread_turns.json")

MAX_CHAIN_REPLIES_PER_CYCLE = int(os.environ.get("CHAIN_REPLY_CAP", "7"))
MAX_OUR_TURNS_PER_THREAD = int(os.environ.get("CHAIN_TURNS_PER_THREAD", "3"))

_OWN_HANDLE = BOT_HANDLE.lower()


def _load_replied() -> set:
    if not os.path.exists(CHAIN_REPLIED_FILE):
        return set()
    try:
        with open(CHAIN_REPLIED_FILE, "r") as f:
            return set(json.load(f) or [])
    except Exception:
        return set()


def _save_replied(s: set):
    with open(CHAIN_REPLIED_FILE, "w") as f:
        json.dump(sorted(s)[-2000:], f)


def _load_turns() -> dict:
    if not os.path.exists(THREAD_TURN_FILE):
        return {}
    try:
        with open(THREAD_TURN_FILE, "r") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _save_turns(d: dict):
    # Trim to last 500 threads tracked.
    items = list(d.items())[-500:]
    with open(THREAD_TURN_FILE, "w") as f:
        json.dump(dict(items), f, indent=2)


def _root_status_id(url: str) -> str:
    """Extract the parent thread's ROOT status id. We use the URL of OUR
    reply as the thread id — good enough for capping our-turns per thread."""
    m = re.search(r"/status/(\d+)", url or "")
    return m.group(1) if m else ""


def _scrape_replies_to(url: str, max_replies: int = 6) -> list:
    """Open a tweet (= one of OUR replies), scroll to expose nested
    responses, JS-extract them. Returns list of {user, text, url}."""
    js_code = """
    (function() {
        var articles = document.querySelectorAll('article[data-testid="tweet"]');
        // articles[0] = the focal tweet (our reply); 1+ are nested.
        var out = [];
        for (var i = 1; i < Math.min(articles.length, MAX); i++) {
            var a = articles[i];
            var textEl = a.querySelector('[data-testid="tweetText"]');
            var text = textEl ? textEl.textContent.trim() : '';
            if (!text) continue;
            var userEl = a.querySelector('[data-testid="User-Name"] a[role="link"]');
            var user = userEl ? userEl.textContent.trim().replace('@','') : '';
            var url = '';
            var links = a.querySelectorAll('a[href*="/status/"]');
            for (var l of links) {
                var h = l.getAttribute('href');
                if (h && h.match(/\\/status\\/\\d+$/)) {
                    url = 'https://x.com' + h;
                    break;
                }
            }
            out.push({user: user, text: text.substring(0, 250), url: url});
        }
        return JSON.stringify(out);
    })()
    """.replace("MAX", str(max_replies + 2))

    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False)
    tmp.write(js_code)
    tmp.close()
    applescript = f'''
    tell application "Safari" to activate
    set jsCode to (read POSIX file "{tmp.name}")
    tell application "Safari"
        set result to do JavaScript jsCode in current tab of front window
    end tell
    '''
    with _safari_lock:
        log.info(f"[CHAIN] Opening our reply: {url}")
        webbrowser.open(url)
        time.sleep(7)
        _scroll_page()
        time.sleep(1)

        try:
            r = subprocess.run(
                ["osascript", "-e", applescript],
                capture_output=True, text=True, timeout=30,
            )
            os.unlink(tmp.name)
            close_front_tab()
            if r.returncode != 0:
                return []
            raw = (r.stdout or "").strip()
            if not raw:
                return []
            try:
                return json.loads(raw)[:max_replies]
            except json.JSONDecodeError:
                return []
        except Exception:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass
            try:
                close_front_tab()
            except Exception:
                pass
            log.info("[CHAIN] Scrape exception:")
            traceback.print_exc()
            return []


def run_chain_reply_cycle():
    replied = _load_replied()
    turns = _load_turns()
    posted = 0

    log.info(f"[CHAIN] Scraping @{BOT_HANDLE}/with_replies for our recent replies...")
    try:
        own_replies = scrape_profile_tweets(f"{BOT_HANDLE}/with_replies", max_tweets=25)
    except Exception:
        log.info("[CHAIN] /with_replies scrape failed:")
        traceback.print_exc()
        return

    if not own_replies:
        log.info("[CHAIN] No replies scraped from /with_replies.")
        return

    # Filter to entries authored BY us (some entries on /with_replies are
    # the parent tweets our replies were on; we want OUR rows).
    our_reply_urls = []
    for t in own_replies:
        author = (t.get("author") or "").lower().lstrip("@")
        if author and author != _OWN_HANDLE:
            continue
        url = t.get("url") or ""
        if url:
            our_reply_urls.append(url)

    log.info(f"[CHAIN] Found {len(our_reply_urls)} of our recent replies to scan.")

    for our_url in our_reply_urls:
        if posted >= MAX_CHAIN_REPLIES_PER_CYCLE:
            break

        # Loop guard: have we already taken N turns in this thread?
        thread_id = _root_status_id(our_url)
        if not thread_id:
            continue
        prior_turns = int(turns.get(thread_id, 0))
        if prior_turns >= MAX_OUR_TURNS_PER_THREAD:
            log.info(f"[CHAIN] Thread {thread_id} at {prior_turns} turns — stopping.")
            continue

        # Look for nested replies on this URL.
        nested = _scrape_replies_to(our_url, max_replies=6)
        if not nested:
            continue

        for n in nested:
            if posted >= MAX_CHAIN_REPLIES_PER_CYCLE:
                break
            n_url = n.get("url") or ""
            if not n_url or n_url in replied:
                continue
            n_user = (n.get("user") or "").lower().lstrip("@")
            if n_user in BLOCKLIST or n_user == _OWN_HANDLE:
                continue
            n_text = (n.get("text") or "").strip()
            if not n_text:
                continue

            # Generate follow-up via replyback_agent. The agent sees the
            # reply text and writes a FR-priority response that matches
            # parent language.
            try:
                resp = generate_replyback(
                    own_tweet="(notre réponse précédente dans le thread)",
                    reply_user=n_user,
                    reply_text=n_text,
                )
            except Exception:
                log.info(f"[CHAIN] Generate failed for {n_url}:")
                traceback.print_exc()
                continue
            if not resp:
                continue
            resp = humanize(resp)
            if len(resp) < 10 or len(resp) > 270:
                continue

            # Lock URL in BEFORE posting so a crash can't double-respond.
            replied.add(n_url)
            _save_replied(replied)

            try:
                reply_to_tweet(n_url, resp)
                posted += 1
                turns[thread_id] = prior_turns + 1
                _save_turns(turns)
                try:
                    log_reply(
                        n_url, resp, action_type="reply",
                        source=f"CHAIN/{n_user}",
                    )
                except Exception:
                    pass
                log.info(f"[CHAIN] Posted chain-reply to @{n_user}: {resp[:120]!r}")
                time.sleep(8)
            except Exception:
                log.info(f"[CHAIN] reply_to_tweet failed for {n_url}:")
                traceback.print_exc()

    log.info(f"[CHAIN] Cycle done — {posted} chain-replies posted.")


def safe_run_chain_reply_cycle():
    from . import health
    try:
        run_chain_reply_cycle()
        health.record_success("chain_reply")
    except Exception:
        log.info("[CHAIN] Error during chain-reply cycle:")
        traceback.print_exc()
        health.record_failure("chain_reply")

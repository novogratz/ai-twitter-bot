"""Smart unfollow — keep the follow-ratio healthy.

With follow_blast doing ~700-1500 follow attempts/day, in 2 weeks the
bot will be following ~10k+ accounts. If only ~15% reciprocate, we
end up with a 1500-follower / 10k-follow ratio. X penalizes low
follow-ratio accounts (rate limits, lower reach, "spammer" signal).

Strategy:
  - Every 4h, scrape /CryptoAIDecode/following AND /CryptoAIDecode/followers.
  - Diff: people we follow but who DON'T follow us back.
  - Filter: never unfollow accounts on the respect_list (Mistral
    CEO, Anthropic, etc. — we keep following them out of respect
    even if they don't follow us back).
  - Filter: never unfollow accounts in TARGET_ACCOUNTS or
    EARLY_BIRD_ACCOUNTS (we want to keep engaging with them).
  - Unfollow up to UNFOLLOW_CAP_PER_CYCLE accounts (default 15).
  - Persist a "do not re-follow" set so follow_blast doesn't re-add
    them (would be infinite churn).
"""
import json
import os
import random
import subprocess
import tempfile
import time
import traceback
import urllib.parse
import webbrowser

from .config import _PROJECT_ROOT, BOT_HANDLE
from .logger import log
from .twitter_client import _safari_lock, close_front_tab, _scroll_page, unfollow_account

DO_NOT_REFOLLOW_FILE = os.path.join(_PROJECT_ROOT, "do_not_refollow.json")

UNFOLLOW_CAP_PER_CYCLE = int(os.environ.get("UNFOLLOW_CAP_PER_CYCLE", "15"))


def _scrape_handle_list(url: str, max_handles: int = 200) -> list:
    """Open url, scroll, JS-extract @handles. Same pattern as followback_bot
    but supports both /following and /followers."""
    js_code = f"""
    (function() {{
        var handles = [];
        var seen = {{}};
        var anchors = document.querySelectorAll('a[role="link"][href^="/"]');
        for (var i = 0; i < anchors.length && handles.length < {max_handles}; i++) {{
            var h = anchors[i].getAttribute('href') || '';
            var m = h.match(/^\\/([A-Za-z0-9_]+)$/);
            if (!m) continue;
            var u = m[1];
            if (['home','explore','notifications','messages','i','search',
                 'compose','settings','intent','login','signup'].indexOf(u) !== -1) continue;
            if (seen[u]) continue;
            seen[u] = 1;
            handles.push(u);
        }}
        return handles.join(',');
    }})()
    """
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
        log.info(f"[UNFOLLOW] Opening {url}")
        webbrowser.open(url)
        time.sleep(8)
        # Scroll a few times to expose more entries.
        for _ in range(4):
            _scroll_page()
            time.sleep(1)

        try:
            r = subprocess.run(
                ["osascript", "-e", applescript],
                capture_output=True, text=True, timeout=30,
            )
            os.unlink(tmp.name)
            if r.returncode != 0:
                log.info(f"[UNFOLLOW] Scrape JS failed: {r.stderr[:160]}")
                close_front_tab()
                return []
            raw = (r.stdout or "").strip()
            close_front_tab()
            if not raw:
                return []
            return [h for h in raw.split(",") if h][:max_handles]
        except Exception:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass
            log.info("[UNFOLLOW] Scrape exception:")
            traceback.print_exc()
            try:
                close_front_tab()
            except Exception:
                pass
            return []


def _load_do_not_refollow() -> set:
    if not os.path.exists(DO_NOT_REFOLLOW_FILE):
        return set()
    try:
        with open(DO_NOT_REFOLLOW_FILE, "r") as f:
            return set(json.load(f) or [])
    except Exception:
        return set()


def _save_do_not_refollow(s: set):
    with open(DO_NOT_REFOLLOW_FILE, "w") as f:
        json.dump(sorted(s)[-3000:], f, indent=2)


def _build_keep_set() -> set:
    """Accounts we MUST NOT unfollow regardless of reciprocity."""
    keep = set()
    # Respect list — Mistral, Anthropic, etc.
    try:
        from . import respect_list
        keep |= {h.lower() for h in respect_list.load()}
    except Exception:
        pass
    # Engage / direct-reply target lists — we want to keep notifying them.
    try:
        from .engage_bot import TARGET_ACCOUNTS
        keep |= {a.lower() for a in TARGET_ACCOUNTS}
    except Exception:
        pass
    try:
        from .early_bird_bot import EARLY_BIRD_ACCOUNTS
        keep |= {a.lower() for a in EARLY_BIRD_ACCOUNTS}
    except Exception:
        pass
    try:
        from .mega_watch_bot import MEGA_ACCOUNTS
        keep |= {a.lower() for a in MEGA_ACCOUNTS}
    except Exception:
        pass
    return keep


def run_unfollow_cycle():
    log.info("[UNFOLLOW] Scraping /following and /followers...")
    following = _scrape_handle_list(f"https://x.com/{BOT_HANDLE}/following", 200)
    if not following:
        log.info("[UNFOLLOW] No /following entries scraped — skipping cycle.")
        return
    followers = _scrape_handle_list(f"https://x.com/{BOT_HANDLE}/followers", 200)
    if not followers:
        log.info("[UNFOLLOW] No /followers entries scraped — skipping cycle.")
        return

    following_set = {h.lower() for h in following}
    followers_set = {h.lower() for h in followers}
    keep_set = _build_keep_set()
    do_not_refollow = _load_do_not_refollow()

    # Diff: we follow them but they don't follow us back.
    candidates = sorted(following_set - followers_set - keep_set)
    if not candidates:
        log.info("[UNFOLLOW] No non-reciprocal candidates today.")
        return

    log.info(
        f"[UNFOLLOW] {len(following_set)} following, "
        f"{len(followers_set)} followers, "
        f"{len(candidates)} non-reciprocal (after keep-list)."
    )

    # Cap. Random sample so we don't unfollow alphabetically.
    random.shuffle(candidates)
    targets = candidates[:UNFOLLOW_CAP_PER_CYCLE]
    log.info(f"[UNFOLLOW] Unfollowing {len(targets)}: {targets}")

    # Also maintain followed_accounts.json so we don't try to re-follow
    # them via reciprocity / engage paths.
    try:
        from .engage_bot import _load_followed, _save_followed
        followed = _load_followed()
    except Exception:
        followed = set()

    for h in targets:
        try:
            ok = unfollow_account(h)
            if ok:
                do_not_refollow.add(h)
                followed.discard(h)
                time.sleep(random.randint(3, 6))
        except Exception:
            log.info(f"[UNFOLLOW] @{h} failed:")
            traceback.print_exc()

    _save_do_not_refollow(do_not_refollow)
    try:
        from .engage_bot import _save_followed as _sf
        _sf(followed)
    except Exception:
        pass

    log.info(f"[UNFOLLOW] Cycle done. Total in do_not_refollow set: {len(do_not_refollow)}.")


def safe_run_unfollow_cycle():
    from . import health
    try:
        run_unfollow_cycle()
        health.record_success("unfollow")
    except Exception:
        log.info("[UNFOLLOW] Error during unfollow cycle:")
        traceback.print_exc()
        health.record_failure("unfollow")

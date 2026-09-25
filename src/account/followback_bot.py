"""Follow-back bot — scrape our followers list and follow them back.

Why: reciprocity is the single highest-leverage follower-growth tactic
on X. ~10-30% of accounts you follow follow back if you're in their
niche. The existing reciprocity loop only fires when someone REPLIES
to us — that misses 90% of new followers (lurkers + likers).

Strategy:
  - Once per ~2h, visit /TheAIShrink/followers via Safari + JS scrape.
  - Get the list of @handles currently following us.
  - Follow back any handle we haven't followed yet, capped at FOLLOW_CAP
    per cycle (don't burn the daily follow budget all at once).
  - Skip the accounts in followed_accounts.json, which follow_account keeps
    for a follow that shipped or an account found already followed.
  - The scrape reads the page's primary column only, so suggested accounts
    ("Who to follow") never pass for followers, and records what it read
    with follow_policy.record_followers: the policy admits a Follow-back on
    that record, never on this job's word.

Safety: handle whitelist heuristic — skip obvious bots (handle made of
random alphanumerics with no vowels, length=15) and BLOCKLIST entries.
"""
import json
import os
import random
import re
import time
import traceback

from ..core.config import _PROJECT_ROOT, BOT_HANDLE, BLOCKLIST
from ..core.logger import log
from ..core.state_store import StateUnreadable
from ..guards import follow_policy
from ..x import safari
from ..x.safari import _safari_lock, close_front_tab, _scroll_page
from ..x.twitter_client import follow_account


FOLLOW_BACK_CAP_PER_CYCLE = int(os.environ.get("FOLLOWBACK_CAP", "8"))


def _looks_like_real_handle(handle: str) -> bool:
    """Cheap bot-handle filter, after the policy's handle check, so an
    invalid handle never takes a pick of the cycle."""
    if not follow_policy.valid_handle(handle):
        return False
    h = handle.lower()
    if h in BLOCKLIST:
        return False
    # Pure-alphanumeric with no vowels = likely a bot (e.g., xkprz9821).
    if not re.search(r"[aeiouAEIOU]", handle):
        return False
    # Mostly digits = throwaway.
    digits = sum(1 for c in handle if c.isdigit())
    if digits >= len(handle) * 0.6:
        return False
    return True


def _scrape_followers_list(max_handles: int = 30) -> list[str]:
    """Scrape the @handles of the open followers page's primary column, and
    record them as followers."""
    js_code = """
    (function() {
        var handles = [];
        var seen = {};
        var column = document.querySelector('[data-testid="primaryColumn"]');
        if (!column) return '';
        var anchors = column.querySelectorAll('a[role="link"][href^="/"]');
        for (var i = 0; i < anchors.length && handles.length < MAX; i++) {
            var h = anchors[i].getAttribute('href') || '';
            var m = h.match(/^\\/([A-Za-z0-9_]+)$/);
            if (!m) continue;
            var u = m[1];
            // Skip non-profile paths
            if (['home','explore','notifications','messages','i','search',
                 'compose','settings','intent','login','signup'].indexOf(u) !== -1) continue;
            if (seen[u]) continue;
            seen[u] = 1;
            handles.push(u);
        }
        return handles.join(',');
    })()
    """.replace("MAX", str(max_handles * 2))

    raw = safari._run_js(js_code, 30, log_prefix="[FOLLOWBACK]", activate=True)
    if not raw:
        return []
    handles = [h for h in raw.split(",") if h and h.lower() != BOT_HANDLE.lower()]
    handles = handles[:max_handles]
    follow_policy.record_followers(handles)
    return handles


def run_followback_cycle():
    """Visit /TheAIShrink/followers and follow back fresh ones."""
    followed = follow_policy.followed()

    with _safari_lock:
        url = f"https://x.com/{BOT_HANDLE}/followers"
        log.info(f"[FOLLOWBACK] Opening {url}")
        safari.open_url(url)
        time.sleep(8)
        # Scroll twice to load 30-50 followers.
        _scroll_page()
        time.sleep(2)
        _scroll_page()
        time.sleep(2)

        candidates = _scrape_followers_list(max_handles=50)
        close_front_tab()

    if not candidates:
        log.info("[FOLLOWBACK] No candidates scraped.")
        return

    log.info(f"[FOLLOWBACK] Scraped {len(candidates)} follower handles. Filtering.")

    fresh = []
    for h in candidates:
        if h.lower() == BOT_HANDLE.lower():
            continue
        if h in followed:
            continue
        if not _looks_like_real_handle(h):
            log.info(f"[FOLLOWBACK] Skipping suspicious handle @{h}")
            continue
        fresh.append(h)

    if not fresh:
        log.info("[FOLLOWBACK] No fresh follow-back candidates after filtering.")
        return

    # Cap per cycle so we don't burn the daily follow budget.
    random.shuffle(fresh)
    pick = fresh[:FOLLOW_BACK_CAP_PER_CYCLE]
    log.info(f"[FOLLOWBACK] Following back {len(pick)} accounts: {pick}")

    shipped = 0
    for h in pick:
        try:
            result = follow_account(h)
            if result.is_budget_refusal:
                log.info(f"[FOLLOWBACK] Follow budget: {result.value}; ending cycle.")
                break
            shipped += bool(result)
            time.sleep(random.randint(3, 6))
        except StateUnreadable:
            raise  # a guarded file stops the job, not one pick at a time
        except Exception:
            log.info(f"[FOLLOWBACK] Follow @{h} failed:")
            traceback.print_exc()

    log.info(f"[FOLLOWBACK] Cycle done: {shipped} followed back.")


def safe_run_followback_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    from ..core import health
    try:
        run_followback_cycle()
        health.record_success("followback")
    except Exception:
        log.info("[FOLLOWBACK] Error during follow-back cycle:")
        traceback.print_exc()
        health.record_failure("followback")

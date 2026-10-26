"""Read-only, exact-status Reply receipts and counters. Never infer a zero."""
import json
import time
from datetime import timedelta

from ..core import account
from ..guards import active_hours
from . import safari, x_urls

# Use the article's timestamp link, not a quoted post or analytics URL. All
# counters must belong to that same article and status. Missing labels stay null.
_VISIBLE = r"""(() => {
  if (!['x.com', 'www.x.com', 'twitter.com', 'www.twitter.com'].includes(location.hostname)) return '[]';
  function count(el) {
    if (!el) return null;
    const label = el.getAttribute('aria-label') || el.textContent || '';
    const m = label.match(/(?:^|\s)(\d[\d,]*(?:\.\d+)?)\s*([kKmM]?)(?:\s|$|\.)/);
    if (!m) return null;
    const n = Number(m[1].replace(/,/g, ''));
    return Math.round(n * ({k:1000,m:1000000}[m[2].toLowerCase()] || 1));
  }
  return JSON.stringify(Array.from(document.querySelectorAll('article[data-testid="tweet"]')).flatMap(a => {
    const time = a.querySelector('time[datetime]');
    const link = time && time.closest('a[href*="/status/"]');
    const match = link && (link.getAttribute('href') || '').match(/^\/([A-Za-z0-9_]{1,15})\/status\/(\d+)$/);
    const text = a.querySelector('[data-testid="tweetText"]');
    const user = a.querySelector('[data-testid="User-Name"] a[href]');
    if (!match || !text || !user || user.getAttribute('href').toLowerCase() !== '/' + match[1].toLowerCase()) return [];
    const own = el => el && el.closest('article[data-testid="tweet"]') === a;
    const like = a.querySelector('[data-testid="like"], [data-testid="unlike"]');
    const views = a.querySelector('a[href$="/status/' + match[2] + '/analytics"]');
    return [{url:'https://x.com/' + match[1] + '/status/' + match[2], text:text.textContent.trim(),
             likes:count(own(like) ? like : null), views:count(own(views) ? views : null)}];
  }));
})()"""


def read_visible():
    active_hours.require_active()
    raw = safari._run_js(_VISIBLE, 8, log_prefix="[REPLY-METRICS]", activate=False)
    try:
        rows = json.loads(raw)
        return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
    except (ValueError, TypeError):
        return []


def capture(text: str, *, since, parent: str) -> str:
    """Match one recent own status with exactly the submitted text, or unknown."""
    now = active_hours.now_local()
    matches = set()
    expected = " ".join(text.split())
    for row in read_visible():
        url = x_urls.canonical_status_url(row.get("url", ""))
        at = x_urls.posted_at(url)
        if (url and x_urls.author(url) in account.own_handles() and at
                and since - timedelta(seconds=5) <= at <= now
                and x_urls.status_id(url) != x_urls.status_id(parent)
                and " ".join(str(row.get("text", "")).split()) == expected):
            matches.add(url)
    return next(iter(matches)) if len(matches) == 1 else ""


def observe(url: str) -> dict | None:
    url = x_urls.canonical_status_url(url)
    if not url or x_urls.author(url) not in account.own_handles():
        return None
    with safari._safari_lock:
        active_hours.require_active()
        opened = safari.open_url(url)
        if not opened:
            return None
        try:
            time.sleep(4)
            matches = [row for row in read_visible()
                       if x_urls.canonical_status_url(row.get("url", "")) == url]
            if len(matches) == 1:
                return {**matches[0], "url": url}
            return None
        finally:
            safari.close_front_tab()

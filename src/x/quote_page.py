"""Native quote composer and exact own receipt, bound to the selected source."""
import json
import time

from ..core import account
from ..guards.active_hours import require_active
from . import repost_page, safari, x_urls

COMPOSER = r"""((SOURCE, TEXT, HANDLE, MODE) => {
  const fail = () => JSON.stringify({ready:false});
  if (!['x.com','www.x.com'].includes(location.hostname)) return fail();
  if ((document.querySelector('[data-testid="AppTabBar_Profile_Link"]')?.getAttribute('href') || '').toLowerCase() !== '/'+HANDLE.toLowerCase()) return fail();
  const all = [...document.querySelectorAll('[role="dialog"]')].filter(e=>e.getClientRects().length);
  const dialogs = all.filter(d=>!all.some(other=>other!==d && d.contains(other)));
  if (dialogs.length !== 1) return fail();
  const area = dialogs[0];
  const fields = [...area.querySelectorAll('[data-testid^="tweetTextarea_"][contenteditable="true"]')].filter(e=>e.getClientRects().length);
  if (fields.length !== 1) return fail();
  const target = new URL(SOURCE).pathname.toLowerCase();
  const cards = [...area.querySelectorAll('a[href*="/status/"]')].filter(e=>{
    const u = new URL(e.href, location.origin);
    return !fields[0].contains(e) && u.protocol === 'https:' && !u.username && !u.password
      && ['x.com','www.x.com','twitter.com','www.twitter.com'].includes(u.hostname)
      && u.pathname.toLowerCase() === target;
  });
  if (!cards.length) return fail();
  const norm = s => (s || '').replace(/\s+/g,' ').trim();
  if (MODE === 'focus') {
    if (norm(fields[0].innerText)) return fail();
    fields[0].focus();
    return JSON.stringify({ready:true});
  }
  if (norm(fields[0].innerText) !== norm(TEXT)) return fail();
  const buttons = [...area.querySelectorAll('[data-testid="tweetButton"]')].filter(e=>e.getClientRects().length);
  if (buttons.length !== 1 || buttons[0].disabled || buttons[0].getAttribute('aria-disabled') === 'true') return fail();
  if (MODE === 'submit') buttons[0].click();
  return JSON.stringify({ready:true});
})"""


def composer(url, text, mode="read"):
    if mode not in {"read", "focus", "submit"}:
        raise ValueError(mode)
    require_active()
    js = COMPOSER + "(" + ",".join(json.dumps(v) for v in (url, text, account.current().handle, mode)) + ")"
    try:
        return json.loads(safari._run_js(js, 8, log_prefix="[QUOTE]"))
    except (ValueError, TypeError):
        return {}  # distinguish lost response from a proven no-click refusal


def prepare(url, text):
    if repost_page.read(url, "open_quote").get("state") != "menu_opened":
        return False
    time.sleep(1)
    if repost_page.read(url, "quote").get("state") != "quote_opened":
        return False
    for _ in range(8):
        time.sleep(1)
        if composer(url, text, "focus").get("ready") is True:
            return safari._paste_text(text) and composer(url, text).get("ready") is True
    return False


RECEIPTS = r"""(() => {
  if (!['x.com','www.x.com'].includes(location.hostname)) return '[]';
  return JSON.stringify([...document.querySelectorAll('article[data-testid="tweet"]')].slice(0,60).flatMap(a=>{
    const own = e => e?.closest('article[data-testid="tweet"]') === a && !e.closest('[data-testid="quoteTweet"],div[role="link"]');
    const stamp = [...a.querySelectorAll('time')].find(own);
    const link = stamp?.closest('a[href*="/status/"]');
    const body = [...a.querySelectorAll('[data-testid="tweetText"]')].find(own);
    const user = [...a.querySelectorAll('[data-testid="User-Name"] a[href]')].find(own);
    if (!link || !body || !user) return [];
    const m = new URL(link.href).pathname.match(/^\/([A-Za-z0-9_]{1,15})\/status\/(\d+)$/);
    if (!m || user.getAttribute('href')?.toLowerCase() !== '/'+m[1].toLowerCase()) return [];
    const sources = [...a.querySelectorAll('a[href*="/status/"]')].filter(e=>
      e.closest('article[data-testid="tweet"]') === a && e.closest('[data-testid="quoteTweet"],div[role="link"]'));
    return [{url:link.href, text:body.innerText, sources:sources.map(e=>e.href)}];
  }));
})()"""


def receipt(url, text, since):
    for attempt in range(12):
        require_active()
        if attempt == 4:
            safari._run_js("location.href=" + json.dumps("https://x.com/" + account.current().handle) + "; 'quote-receipt';", 5)
        try:
            rows = json.loads(safari._run_js(RECEIPTS, 8, log_prefix="[QUOTE]"))
        except (TypeError, ValueError):
            rows = []
        matches = set()
        for row in rows if isinstance(rows, list) else []:
            own = x_urls.canonical_status_url(row.get("url", ""))
            stamp = x_urls.posted_at(own)
            if (own and stamp and x_urls.author(own) == account.current().handle.lower()
                    and since - 5 <= stamp.timestamp() <= time.time() + 5
                    and " ".join(row.get("text", "").split()) == " ".join(text.split())
                    and url in {x_urls.canonical_status_url(u) for u in row.get("sources", [])}):
                matches.add(own)
        if len(matches) == 1:
            return next(iter(matches))
        time.sleep(1)
    return ""

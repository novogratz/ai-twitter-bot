"""Exact text composer and receipt evidence, inside the shared Safari lock."""
from datetime import datetime, timezone
import json
import time
from urllib.parse import urlencode

from ..core import account
from ..guards.active_hours import require_active
from . import safari, x_urls


def _read(js):
    raw = safari._run_js(js, 8, log_prefix="[NEWS-SAFARI]")
    return json.loads(raw)


def composer(text, *, click=False):
    # Repeat identity, unique composer, exact text and button checks at click.
    js = r"""((TEXT,HANDLE,CLICK) => {
      const norm = x => (x || '').replace(/\s+/g,' ').trim();
      if (!['x.com','www.x.com'].includes(location.hostname)) return 'false';
      const owner = document.querySelector('[data-testid="AppTabBar_Profile_Link"]')?.getAttribute('href');
      if ((owner || '').toLowerCase() !== '/' + HANDLE.toLowerCase()) return 'false';
      const fields = [...document.querySelectorAll('[data-testid^="tweetTextarea_"][contenteditable="true"]')].filter(e=>e.getClientRects().length);
      if (fields.length !== 1 || norm(fields[0].innerText) !== norm(TEXT)) return 'false';
      const area = fields[0].closest('[role="dialog"]') || document.querySelector('main');
      const buttons = [...(area?.querySelectorAll('[data-testid="tweetButton"],[data-testid="tweetButtonInline"]') || [])].filter(b=>b.getClientRects().length);
      if (buttons.length !== 1 || buttons[0].disabled || buttons[0].getAttribute('aria-disabled') === 'true') return 'false';
      if (CLICK) buttons[0].click();
      return 'true';
    })(""" + ",".join((json.dumps(text), json.dumps(account.current().handle), "true" if click else "false")) + ")"
    require_active()
    return _read(js) is True


def prepare(text):
    require_active()
    if not safari.open_url("https://x.com/intent/post?" + urlencode({"text": text})):
        return False
    for _ in range(8):
        time.sleep(1)
        if composer(text):
            return True
    return False


def receipt(text, source_url, since):
    # Expand only observed anchor destinations, never a shortened URL guess.
    js = r"""((SOURCE) => {
      if (!['x.com','www.x.com'].includes(location.hostname)) return '[]';
      return JSON.stringify([...document.querySelectorAll('article[data-testid="tweet"]')].flatMap(a=>{
        const own = e => e?.closest('article[data-testid="tweet"]') === a && !e.closest('[data-testid="quoteTweet"],div[role="link"]');
        const t = [...a.querySelectorAll('time[datetime]')].find(own);
        const link = t?.closest('a[href*="/status/"]');
        const body = [...a.querySelectorAll('[data-testid="tweetText"]')].find(own);
        const user = [...a.querySelectorAll('[data-testid="User-Name"] a[href]')].find(own);
        const m = (link?.getAttribute('href') || '').match(/^\/([A-Za-z0-9_]{1,15})\/status\/(\d+)$/);
        if(!body || !m || user?.getAttribute('href')?.toLowerCase() !== '/'+m[1].toLowerCase()) return [];
        const copy = body.cloneNode(true);
        for (const el of copy.querySelectorAll('a[href]')) {
          const dest = el.getAttribute('data-expanded-url') || el.getAttribute('title') || el.getAttribute('href');
          if(dest === SOURCE) el.textContent = SOURCE;
        }
        return [{url:'https://x.com/'+m[1]+'/status/'+m[2],text:copy.textContent}];
      }));
    })(""" + json.dumps(source_url) + ")"
    expected = " ".join(text.split())
    for attempt in range(12):
        require_active()
        if attempt == 4:
            safari._run_js("location.href=" + json.dumps("https://x.com/" + account.current().handle) + "; 'news-receipt';", 5)
        matches = set()
        for row in _read(js):
            url = x_urls.canonical_status_url(row.get("url", ""))
            stamp = x_urls.posted_at(url)
            if (url and x_urls.author(url) == account.current().handle.lower() and stamp
                    and since - 5 <= stamp.timestamp() <= time.time() + 5
                    and " ".join(row.get("text", "").split()) == expected):
                matches.add(url)
        if len(matches) == 1:
            return next(iter(matches))
        time.sleep(1)
    return ""

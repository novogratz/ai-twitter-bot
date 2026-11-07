"""Exact text composer and receipt evidence, inside the shared Safari lock."""
from datetime import datetime, timezone
import json
import re
import time
from urllib.parse import urlencode

from ..core import account
from ..core.logger import log
from ..guards.active_hours import require_active
from . import safari, x_urls


def _read(js):
    raw = safari._run_js(js, 8, log_prefix="[NEWS-SAFARI]")
    return json.loads(raw)


def _composer_state(text, *, click=False):
    # Repeat identity, unique composer, exact text and button checks at click.
    js = r"""((TEXT,HANDLE,CLICK) => {
      const norm = x => (x || '').replace(/\s+/g,' ').trim();
      const result = (ready, reason) => JSON.stringify({ready, reason});
      if (!['x.com','www.x.com'].includes(location.hostname)) return result(false, 'wrong_host');
      const owner = document.querySelector('[data-testid="AppTabBar_Profile_Link"]')?.getAttribute('href');
      if ((owner || '').toLowerCase() !== '/' + HANDLE.toLowerCase()) return result(false, 'wrong_owner');
      // The home-page composer can remain visible behind the intent dialog.
      // Scope both the text and Post button to the single active dialog.
      const allDialogs = [...document.querySelectorAll('[role="dialog"]')].filter(e=>e.getClientRects().length);
      // X nests its aria-modal dialog inside a second role=dialog wrapper.
      // Count innermost dialogs, retaining refusal for separate modal layers.
      const dialogs = allDialogs.filter(d=>!allDialogs.some(other=>other!==d && d.contains(other)));
      if (dialogs.length > 1) return result(false, 'ambiguous_dialog');
      const area = dialogs[0] || document.querySelector('main');
      const fields = [...(area?.querySelectorAll('[data-testid^="tweetTextarea_"][contenteditable="true"]') || [])].filter(e=>e.getClientRects().length);
      if (fields.length !== 1) return result(false, 'ambiguous_composer');
      if (norm(fields[0].innerText) !== norm(TEXT)) return result(false, 'text_mismatch');
      const buttons = [...(area?.querySelectorAll('[data-testid="tweetButton"],[data-testid="tweetButtonInline"]') || [])].filter(b=>b.getClientRects().length);
      if (buttons.length !== 1 || buttons[0].disabled || buttons[0].getAttribute('aria-disabled') === 'true') return result(false, 'button_unavailable');
      if (CLICK) buttons[0].click();
      return result(true, CLICK ? 'clicked' : 'ready');
    })(""" + ",".join((json.dumps(text), json.dumps(account.current().handle), "true" if click else "false")) + ")"
    require_active()
    return _read(js)


def composer(text, *, click=False):
    return _composer_state(text, click=click).get("ready") is True


def prepare(text):
    require_active()
    if not safari.open_url("https://x.com/intent/post?" + urlencode({"text": text})):
        log.info("[NEWS] Composer preparation failed: open_url")
        return False
    state = {}
    for _ in range(8):
        time.sleep(1)
        state = _composer_state(text)
        if state.get("ready") is True:
            return True
    log.info("[NEWS] Composer preparation failed: %s", state.get("reason", "unreadable"))
    return False


def _shortlink_matches(link, source_url, store, cfg):
    """Observe only t.co's HTTPS redirect, without following it or forwarding auth."""
    from ..video import security
    try:
        part = security.validate_url(link, {"t.co"})
        if part.query or not re.fullmatch(r"/[A-Za-z0-9]{1,64}", part.path) or store is None or cfg is None:
            return False
        store.charge("requests", 1, cfg.requests_per_day, time.time())
        connection = security._PinnedHTTPS("t.co", timeout=3)
        try:
            connection.request("HEAD", part.path)
            response = connection.getresponse()
            return response.status in (301, 302, 303, 307, 308) and response.getheader("Location") == source_url
        finally:
            connection.close()
    except (OSError, ValueError, RuntimeError):
        return False


def receipt(text, source_url, since, *, store=None, cfg=None):
    # Expand only observed anchor destinations, never a shortened URL guess.
    js = r"""((SOURCE) => {
      if (!['x.com','www.x.com'].includes(location.hostname)) return '[]';
      return JSON.stringify([...document.querySelectorAll('article[data-testid="tweet"]')].slice(0,60).flatMap(a=>{
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
        const links = [...a.querySelectorAll('a[href]')].filter(e=>
          e.closest('article[data-testid="tweet"]') === a && !e.closest('[data-testid="quoteTweet"]'))
          .map(e=>e.getAttribute('data-expanded-url') || e.getAttribute('title') || e.getAttribute('href'))
          .filter(u=>u?.startsWith('https://')).slice(0,8);
        return [{url:'https://x.com/'+m[1]+'/status/'+m[2],text:copy.textContent,links}];
      }));
    })(""" + json.dumps(source_url) + ")"
    expected = " ".join(text.split())
    # X can remove the trailing URL from tweetText and display a link card.
    body = " ".join(text.removesuffix(source_url).split()) if text.endswith(source_url) else None
    resolved = {}
    for attempt in range(12):
        require_active()
        if attempt == 4:
            safari._run_js("location.href=" + json.dumps("https://x.com/" + account.current().handle) + "; 'news-receipt';", 5)
        matches = set()
        for row in _read(js):
            url = x_urls.canonical_status_url(row.get("url", ""))
            stamp = x_urls.posted_at(url)
            if not (url and x_urls.author(url) == account.current().handle.lower() and stamp
                    and since - 5 <= stamp.timestamp() <= time.time() + 5):
                continue
            observed = " ".join(row.get("text", "").split())
            if observed == expected:
                matches.add(url)
            elif body is not None and observed == body:
                for link in row.get("links", [])[:8]:
                    if link == source_url:
                        matches.add(url)
                        break
                    if link not in resolved and len(resolved) < 3:
                        resolved[link] = _shortlink_matches(link, source_url, store, cfg)
                    if resolved.get(link):
                        matches.add(url)
                        break
        if len(matches) == 1:
            return next(iter(matches))
        time.sleep(1)
    return ""

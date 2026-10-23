"""Identify a standalone original and use only its explicit repost controls."""
import json

from ..core import account
from . import safari, x_urls


SCRIPT = r"""(() => {
  const id = __ID__, author = __AUTHOR__, self = __SELF__, mode = __MODE__;
  if (!['x.com', 'www.x.com', 'twitter.com', 'www.twitter.com'].includes(location.hostname)) return '{}';
  const page = location.pathname.match(/^\/([A-Za-z0-9_]{1,15})\/status\/(\d+)\/?$/);
  if (!page || page[2] !== id || page[1].toLowerCase() !== author || self.includes(author)) return '{}';
  const articles = [...document.querySelectorAll('article')];
  const own = (article, selector) => [...article.querySelectorAll(selector)]
    .filter(el => el.closest('article') === article
      && !el.closest('[data-testid="quoteTweet"], div[role="link"]'));
  const status = link => link?.pathname.match(/^\/([A-Za-z0-9_]{1,15})\/status\/(\d+)\/?$/);
  const permalink = article => own(article, 'a[href]').find(l => status(l) && l.querySelector('time'));
  const targets = articles.filter(a => status(permalink(a))?.[2] === id);
  if (targets.length !== 1 || articles[0] !== targets[0]) return '{}';
  const article = targets[0], link = permalink(article);
  if (status(link)[1].toLowerCase() !== author) return '{}';
  const text = own(article, '[data-testid="tweetText"]')[0]?.innerText || '';
  if (!text.trim() || text.trim().startsWith('@') || /Replying to|En réponse à/i.test(article.innerText)) return '{}';
  const result = {url: link.href, text, state: 'unavailable'};
  const existing = own(article, '[data-testid="unretweet"]');
  if (existing.length === 1) {
    result.state = 'reposted';
    return JSON.stringify(result);
  }
  const buttons = own(article, '[data-testid="retweet"]');
  if (buttons.length !== 1 || buttons[0].disabled || buttons[0].getAttribute('aria-disabled') === 'true')
    return JSON.stringify(result);
  result.state = 'ready';
  if (mode === 'open') {
    if (document.querySelector('[data-testid="retweetConfirm"], [data-testid="unretweetConfirm"]')) return '{}';
    buttons[0].click();
    result.state = 'menu_opened';
  } else if (mode === 'confirm') {
    const choices = [...document.querySelectorAll('[data-testid="retweetConfirm"]')]
      .filter(el => el.getClientRects().length && el.getAttribute('aria-disabled') !== 'true');
    if (choices.length !== 1 || document.querySelector('[data-testid="unretweetConfirm"]')) return '{}';
    choices[0].click();
    result.state = 'submitted';
  }
  return JSON.stringify(result);
})()"""


def read(url: str, mode: str = "read") -> dict:
    if mode not in {"read", "open", "confirm"}:
        raise ValueError(mode)
    url = x_urls.canonical_status_url(url)
    if not url:
        return {}
    script = SCRIPT.replace("__ID__", json.dumps(x_urls.status_id(url)))
    script = script.replace("__AUTHOR__", json.dumps(x_urls.author(url)))
    script = script.replace("__SELF__", json.dumps(sorted(account.own_handles())))
    script = script.replace("__MODE__", json.dumps(mode))
    try:
        data = json.loads(safari._run_js(script, 10, log_prefix="[PRIORITY]") or "null")
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) and x_urls.canonical_status_url(data.get("url")) == url else {}

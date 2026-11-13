"""Identify a standalone original and use only its explicit repost controls."""
import json

from ..core import account
from . import safari, x_urls


SCRIPT = r"""(() => {
  const id = __ID__, author = __AUTHOR__, self = __SELF__, rawMode = __MODE__;
  const mode = rawMode.replace(/^meme_/, '');
  const selfMode = mode.startsWith('self_');
  if (!['x.com', 'www.x.com', 'twitter.com', 'www.twitter.com'].includes(location.hostname)) return '{}';
  const page = location.pathname.match(/^\/([A-Za-z0-9_]{1,15})\/status\/(\d+)\/?$/);
  if (!page || page[2] !== id || page[1].toLowerCase() !== author || (selfMode ? !self.includes(author) : self.includes(author))) return '{}';
  if (selfMode || mode.includes('quote') || rawMode.startsWith('meme_')) {
    const owner = document.querySelector('[data-testid="AppTabBar_Profile_Link"]')?.getAttribute('href');
    if (!self.includes((owner || '').replace(/^\//,'').toLowerCase())) return '{}';
  }
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
  const textEl = own(article, '[data-testid="tweetText"]')[0];
  const text = textEl?.innerText || '';
  if (!text.trim() || text.trim().startsWith('@') || /Replying to|En réponse à/i.test(article.innerText)) return '{}';
  const result = {url: link.href, text, language:textEl?.getAttribute('lang') || '', state: 'unavailable'};
  const videos = own(article, 'video');
  result.has_video = videos.length === 1;
  result.media_id = result.has_video ? (videos[0].poster || '').match(/\/(?:ext_tw_video_thumb|amplify_video_thumb)\/(\d+)\//)?.[1] || '' : '';
  const viewEls = own(article, 'a[href$="/status/'+id+'/analytics"]');
  const label = viewEls.length === 1 ? (viewEls[0].getAttribute('aria-label') || viewEls[0].textContent || '') : '';
  const number = label.trim().match(/^((?:\d{1,3}(?:[, \u00a0\u202f]\d{3})+|\d+)(?:\.\d+)?)\s*([kKmMbB]?)(?:\s+(?:views?|vues?)(?:[.\s].*)?)?$/i);
  const value = number ? Number(number[1].replace(/[, \u00a0\u202f]/g,'')) : null;
  result.views = number && (number[2] || Number.isInteger(value)) ? Math.round(value * ({k:1000,m:1000000,b:1000000000}[number[2].toLowerCase()] || 1)) : null;
  if (!Number.isSafeInteger(result.views) || result.views < 0) result.views = null;
  const likes = own(article, '[data-testid="like"], [data-testid="unlike"]');
  const likeLabel = likes.length === 1 ? (likes[0].getAttribute('aria-label') || '') : '';
  const likeNumber = likeLabel.trim().match(/^((?:\d{1,3}(?:[, \u00a0\u202f]\d{3})+|\d+)(?:\.\d+)?)\s*([kKmMbB]?)\s+(?:likes?|mentions? j’aime)(?:[.\s].*)?$/i);
  const likeValue = likeNumber ? Number(likeNumber[1].replace(/[, \u00a0\u202f]/g,'')) : null;
  result.likes = likeNumber && (likeNumber[2] || Number.isInteger(likeValue)) ? Math.round(likeValue * ({k:1000,m:1000000,b:1000000000}[likeNumber[2].toLowerCase()] || 1)) : null;
  if (!Number.isSafeInteger(result.likes) || result.likes < 0) result.likes = null;
  const existing = own(article, '[data-testid="unretweet"]');
  if (existing.length === 1) {
    result.state = 'reposted';
    if (!['open_quote', 'quote', 'self_undo_open', 'self_undo_confirm'].includes(mode)) return JSON.stringify(result);
  }
  const buttons = existing.length === 1 ? existing : own(article, '[data-testid="retweet"]');
  if (buttons.length !== 1 || buttons[0].disabled || buttons[0].getAttribute('aria-disabled') === 'true')
    return JSON.stringify(result);
  if (existing.length !== 1) result.state = 'ready';
  if (mode === 'self_undo_open' && existing.length !== 1) return JSON.stringify(result);
  if (mode === 'open' || mode === 'open_quote' || mode === 'self_open' || mode === 'self_undo_open') {
    if (document.querySelector('[data-testid="retweetConfirm"], [data-testid="unretweetConfirm"]')) return '{}';
    buttons[0].click();
    result.state = 'menu_opened';
  } else if (mode === 'confirm' || mode === 'self_confirm') {
    const choices = [...document.querySelectorAll('[data-testid="retweetConfirm"]')]
      .filter(el => el.getClientRects().length && el.getAttribute('aria-disabled') !== 'true');
    if (choices.length !== 1 || document.querySelector('[data-testid="unretweetConfirm"]')) return '{}';
    choices[0].click();
    result.state = 'submitted';
  } else if (mode === 'self_undo_confirm') {
    const choices = [...document.querySelectorAll('[data-testid="unretweetConfirm"]')]
      .filter(el => el.getClientRects().length && el.getAttribute('aria-disabled') !== 'true');
    if (existing.length !== 1 || choices.length !== 1 || document.querySelector('[data-testid="retweetConfirm"]')) return '{}';
    choices[0].click();
    result.state = 'undo_submitted';
  } else if (mode === 'quote') {
    const choices = [...document.querySelectorAll('[role="menuitem"]')].filter(el =>
      el.getClientRects().length && /^(Quote|Citer)$/i.test(el.innerText.trim())
      && el.getAttribute('aria-disabled') !== 'true');
    if (choices.length !== 1) return '{}';
    choices[0].click();
    result.state = 'quote_opened';
  }
  return JSON.stringify(result);
})()"""


def read(url: str, mode: str = "read") -> dict:
    if mode not in {"read", "open", "confirm", "open_quote", "quote",
                    "meme_read", "meme_open", "meme_confirm",
                    "self_read", "self_open", "self_confirm", "self_undo_open", "self_undo_confirm"}:
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

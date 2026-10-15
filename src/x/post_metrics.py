"""The same article-local counters for discovery and final Reply verification."""

POST_METRICS_JS = r"""
function postMetric(article, testids) {
  const selector = testids.map(id => '[data-testid="' + id + '"]').join(', ');
  const buttons = [...article.querySelectorAll(selector)].filter(el =>
    el.closest('article') === article
    && !el.closest('[data-testid="quoteTweet"], div[role="link"]'));
  if (buttons.length !== 1) return null;
  function count(raw) {
    const match = (raw || '').trim().match(/^(\d[\d,.\u00a0\u202f ]*)([KMB])?(?=\s|$)/i);
    if (!match) return null;
    let value = match[1].trim(), multiplier = 1;
    if (match[2]) {
      if (!/^\d+(?:[.,]\d+)?$/.test(value)) return null;
      value = value.replace(',', '.');
      multiplier = {k: 1000, m: 1000000, b: 1000000000}[match[2].toLowerCase()];
    } else {
      if (!/^(?:\d+|\d{1,3}(?:,\d{3})+|\d{1,3}(?:[ \u00a0\u202f]\d{3})+)$/.test(value)) return null;
      value = value.replace(/[, \u00a0\u202f]/g, '');
    }
    const result = Math.floor(Number(value) * multiplier);
    return Number.isSafeInteger(result) && result >= 0 ? result : null;
  }
  const button = buttons[0];
  return count(button.getAttribute('aria-label')) ?? count(button.innerText || button.textContent);
}
"""

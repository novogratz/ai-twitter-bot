"""Fetch the og:image preview from a news article URL.

Used by the news post path so a tweet ships with the actual article's
preview picture (same image people see when a link is shared) — no
text-on-slide duplication. The og:image lives in the article HTML's
`<meta property="og:image" ...>` tag and is what every social platform
uses for link previews.

If the fetch fails for any reason (timeout, parse, no og:image, redirect
loop), we return None and the caller falls back to text-only — never
crash the post path.
"""
import os
import re
import tempfile
import urllib.request
import urllib.parse
from typing import Optional

from .logger import log


_HEADERS = {
    # Some publishers serve a different (or no) og:image to obvious bots —
    # mimic a real browser to dodge that.
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/17.0 Safari/605.1.15"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

_OG_IMAGE_RE = re.compile(
    r"""<meta[^>]+property\s*=\s*["']og:image(?::secure_url)?["'][^>]+content\s*=\s*["']([^"']+)["']""",
    re.IGNORECASE,
)
# Also handle the reverse attribute order (content first, property second).
_OG_IMAGE_RE_REVERSE = re.compile(
    r"""<meta[^>]+content\s*=\s*["']([^"']+)["'][^>]+property\s*=\s*["']og:image(?::secure_url)?["']""",
    re.IGNORECASE,
)
# Twitter card image as fallback — many publishers set this even when og:image is missing.
_TWITTER_IMAGE_RE = re.compile(
    r"""<meta[^>]+name\s*=\s*["']twitter:image(?::src)?["'][^>]+content\s*=\s*["']([^"']+)["']""",
    re.IGNORECASE,
)


def _http_get(url: str, timeout: int = 8) -> Optional[bytes]:
    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except Exception as e:
        log.info(f"[ARTICLE_IMG] GET failed for {url[:80]}: {e}")
        return None


def _extract_image_url(html: str, base_url: str) -> Optional[str]:
    """Find the og:image (or twitter:image) URL in the article HTML and
    resolve it against base_url so relative paths become absolute."""
    for pattern in (_OG_IMAGE_RE, _OG_IMAGE_RE_REVERSE, _TWITTER_IMAGE_RE):
        m = pattern.search(html)
        if m:
            return urllib.parse.urljoin(base_url, m.group(1).strip())
    return None


def fetch_article_image(url: str) -> Optional[str]:
    """Download the og:image of `url` and return a temp PNG/JPG path.
    Returns None on any failure — caller is expected to fall back."""
    if not url or not url.startswith(("http://", "https://")):
        return None

    raw = _http_get(url)
    if not raw:
        return None
    try:
        html = raw.decode("utf-8", errors="ignore")
    except Exception:
        return None

    img_url = _extract_image_url(html, url)
    if not img_url:
        log.info(f"[ARTICLE_IMG] No og:image / twitter:image on {url[:80]}")
        return None

    img_bytes = _http_get(img_url)
    if not img_bytes or len(img_bytes) < 1024:
        # Anything under 1KB is almost certainly a tracking pixel or 404 page.
        return None

    # Pick a reasonable extension. Twitter accepts JPG/PNG/WEBP/GIF.
    parsed = urllib.parse.urlparse(img_url)
    ext = os.path.splitext(parsed.path)[1].lower() or ".jpg"
    if ext not in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        ext = ".jpg"

    fd, path = tempfile.mkstemp(prefix="kzer_article_", suffix=ext)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(img_bytes)
    except Exception as e:
        log.info(f"[ARTICLE_IMG] Write failed: {e}")
        return None
    log.info(f"[ARTICLE_IMG] Saved {len(img_bytes)} bytes from {img_url[:80]} → {path}")
    return path

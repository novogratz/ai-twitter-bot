"""Generate quote-card PNGs for hot takes and memes.

Renders the tweet text on a clean dark background with @kzer_ai branding —
the result reads like a Notes-app screenshot, which historically performs
2-3x better than text-only posts on X.
"""
import os
import random
import tempfile
from typing import Optional

try:
    from PIL import Image, ImageDraw, ImageFont
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False


# Card design — 1200x675 = X's recommended 16:9 (looks great in feed).
CARD_W = 1200
CARD_H = 675
PADDING = 80
BRAND_HANDLE = "@kzer_ai"

# Color palettes — picked at random per card so the feed doesn't look repetitive.
PALETTES = [
    # (bg, text, accent)
    ("#0F1419", "#F7F9F9", "#1D9BF0"),  # X dark + classic blue
    ("#000000", "#FFFFFF", "#FFD700"),  # pure black + gold
    ("#1A1A2E", "#EAEAEA", "#E94560"),  # midnight + crimson
    ("#0D1117", "#C9D1D9", "#58A6FF"),  # GitHub dark
    ("#1B1B1F", "#FFFFFF", "#7FB069"),  # near-black + green
    ("#181818", "#F5F5F5", "#FF6B35"),  # smoke + orange
]


def _find_font(size: int) -> Optional["ImageFont.FreeTypeFont"]:
    """Find a system font that supports French accents + emojis. Falls back to default."""
    candidates = [
        # macOS — clean modern sans
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/HelveticaNeue.ttc",
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/SFNSRounded.ttf",
        "/System/Library/Fonts/SFNS.ttf",
        # Linux fallbacks
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except (OSError, IOError):
                continue
    return ImageFont.load_default()


def _wrap_text(text: str, font, max_width: int, draw) -> list:
    """Greedy word-wrap — keeps each line under max_width pixels."""
    words = text.split()
    lines, current = [], ""
    for w in words:
        candidate = (current + " " + w).strip()
        bbox = draw.textbbox((0, 0), candidate, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = w
    if current:
        lines.append(current)
    return lines


def _pick_font_size(text: str) -> int:
    """Bigger text for shorter tweets (more meme-y), smaller for long ones."""
    n = len(text)
    if n < 60:
        return 72
    if n < 120:
        return 60
    if n < 200:
        return 50
    return 42


def make_quote_card(text: str, output_path: Optional[str] = None, source: Optional[str] = None) -> Optional[str]:
    """Render `text` as a quote-card PNG. Returns the file path, or None if PIL missing.

    `source` (optional) is a news-source domain like "bloomberg.com". When
    provided, a small "VIA <DOMAIN>" badge is rendered bottom-left so the card
    visually telegraphs "this is real news commentary" instead of opinion.
    Off-platform links in the IMAGE don't trigger X's link-deboost — they're
    pixels, not URLs.
    """
    if not _PIL_AVAILABLE:
        return None

    bg, fg, accent = random.choice(PALETTES)
    img = Image.new("RGB", (CARD_W, CARD_H), bg)
    draw = ImageDraw.Draw(img)

    # Accent bar on the left edge — subtle visual hook.
    draw.rectangle((0, 0, 12, CARD_H), fill=accent)

    # Body text
    font_size = _pick_font_size(text)
    font = _find_font(font_size)
    max_width = CARD_W - 2 * PADDING
    lines = _wrap_text(text, font, max_width, draw)

    # Vertical centering — measure total block height
    line_h = font_size + 14
    block_h = len(lines) * line_h
    y0 = (CARD_H - block_h) // 2 - 30  # nudge up to leave room for handle
    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        line_w = bbox[2] - bbox[0]
        x = (CARD_W - line_w) // 2
        draw.text((x, y0 + i * line_h), line, fill=fg, font=font)

    # Handle in bottom-right
    handle_font = _find_font(28)
    handle_bbox = draw.textbbox((0, 0), BRAND_HANDLE, font=handle_font)
    handle_w = handle_bbox[2] - handle_bbox[0]
    draw.text(
        (CARD_W - handle_w - PADDING, CARD_H - 60),
        BRAND_HANDLE,
        fill=accent,
        font=handle_font,
    )

    # Optional news-source badge in bottom-left. Visually anchors the card
    # as news commentary (vs opinion), which is what the user asked for:
    # "make it more visual / link to the news".
    if source:
        src_label = f"📰 VIA {source.upper()}"
        src_font = _find_font(24)
        draw.text(
            (PADDING, CARD_H - 60),
            src_label,
            fill=fg,
            font=src_font,
        )

    # Persist
    if output_path is None:
        fd, output_path = tempfile.mkstemp(prefix="kzer_card_", suffix=".png")
        os.close(fd)
    img.save(output_path, "PNG", optimize=True)
    return output_path

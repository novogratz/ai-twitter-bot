"""Auto-curating joke bank — learns from the bot's own winners.

The static gold-standard exemplars in news/hotake prompts go stale.
This bot writes joke_bank.md by pulling the top-performing recent
posts (sorted by likes/views ratio with a small floor) and writing
them out as fresh exemplars.

Every news + hotake generation calls `render_joke_bank_block()` which
samples 5 random entries from the bank and injects them into the
prompt. So the bot's prompt EVOLVES with what hit yesterday.

Runs every hour via APScheduler. Idempotent — writes the same file
each time so a missed cycle doesn't matter.
"""
import json
import os
import random
import traceback
from datetime import datetime, timedelta
from typing import Optional

from .config import _PROJECT_ROOT
from .logger import log

PERFORMANCE_LOG_FILE = os.path.join(_PROJECT_ROOT, "performance_log.json")
JOKE_BANK_FILE = os.path.join(_PROJECT_ROOT, "joke_bank.md")
TOP_N = 30
MIN_LIKES_FLOOR = 4
WINDOW_DAYS = 14


def _load_performance() -> list:
    if not os.path.exists(PERFORMANCE_LOG_FILE):
        return []
    try:
        with open(PERFORMANCE_LOG_FILE) as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _clean_tweet_text(t: str) -> str:
    """Strip URLs and PATTERN/SOURCE leftovers so the exemplar is just the
    body the model produced."""
    import re
    t = re.sub(r"https?://\S+", "", t)
    t = re.sub(r"\[\s*(?:PATTERN|SOURCE|IMAGE|KEYWORD|TOPIC|ANGLE)[^\]]*\]", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _likes_per_view(p: dict) -> float:
    likes = int(p.get("likes") or 0)
    views = int(p.get("views") or 0)
    if views < 50:
        return 0.0
    return likes / views


def _entry_score(p: dict) -> float:
    """Compose a score that rewards both absolute likes and like/view rate."""
    likes = int(p.get("likes") or 0)
    if likes < MIN_LIKES_FLOOR:
        return 0.0
    return likes + 100.0 * _likes_per_view(p)


def _recent_entries() -> list:
    now = datetime.now()
    cutoff = now - timedelta(days=WINDOW_DAYS)
    out = []
    for p in _load_performance():
        sa = p.get("scraped_at")
        try:
            ts = datetime.fromisoformat(sa) if sa else None
        except (ValueError, TypeError):
            ts = None
        if ts and ts < cutoff:
            continue
        text = _clean_tweet_text(p.get("text") or "")
        if not text or len(text) < 30:
            continue
        score = _entry_score(p)
        if score <= 0:
            continue
        out.append({
            "text": text,
            "likes": int(p.get("likes") or 0),
            "views": int(p.get("views") or 0),
            "score": score,
        })
    out.sort(key=lambda r: r["score"], reverse=True)
    # Dedup by leading 40 chars so near-paraphrases don't dominate.
    seen = set()
    deduped = []
    for r in out:
        key = r["text"][:40].lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
        if len(deduped) >= TOP_N:
            break
    return deduped


def _write_bank(entries: list) -> None:
    header = (
        "# Joke bank — auto-curated from @cryptoiadecode's own winners.\n"
        f"# Generated {datetime.now().isoformat(timespec='minutes')}. "
        f"Top {len(entries)} of last {WINDOW_DAYS}d (≥{MIN_LIKES_FLOOR} likes).\n"
        "# Prompts pull 5 random entries from this file each cycle so the\n"
        "# voice EVOLVES with what hits, instead of recycling 7 hardcoded\n"
        "# exemplars forever.\n\n"
    )
    lines = [header]
    for r in entries:
        lines.append(f"- ({r['likes']} likes / {r['views']} views) \"{r['text']}\"\n")
    try:
        with open(JOKE_BANK_FILE, "w") as f:
            f.writelines(lines)
    except OSError as e:
        log.info(f"[JOKE_BANK] write failed: {e}")


def _read_bank_entries() -> list[str]:
    """Return raw exemplar lines from joke_bank.md (no header)."""
    if not os.path.exists(JOKE_BANK_FILE):
        return []
    out = []
    try:
        with open(JOKE_BANK_FILE) as f:
            for line in f:
                line = line.strip()
                if line.startswith("- "):
                    out.append(line[2:])
    except OSError:
        return []
    return out


def render_joke_bank_block(sample_size: int = 5) -> str:
    """Return a prompt-injectable block of N random exemplars from the
    auto-curated joke bank. Returns empty string if the bank is empty
    (callers fall back to their static exemplars in that case).
    """
    entries = _read_bank_entries()
    if not entries:
        return ""
    picks = random.sample(entries, min(sample_size, len(entries)))
    head = (
        "🥇 EXEMPLARS — tirés de TES posts qui ont le mieux marché "
        "récemment. Étudie le style, l'angle, la chute. Vise CETTE énergie.\n"
    )
    return head + "\n".join(picks)


def run_joke_bank_cycle() -> None:
    entries = _recent_entries()
    if not entries:
        log.info("[JOKE_BANK] no qualifying entries — skipping write.")
        return
    _write_bank(entries)
    log.info(
        f"[JOKE_BANK] wrote {len(entries)} exemplars to joke_bank.md "
        f"(top liked: {entries[0]['likes']}, range "
        f"{entries[-1]['likes']}-{entries[0]['likes']})."
    )


def safe_run_joke_bank_cycle() -> None:
    try:
        run_joke_bank_cycle()
    except Exception:
        log.info("[JOKE_BANK] outer error:")
        traceback.print_exc()

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


def _own_handle() -> str:
    try:
        from .config import BOT_HANDLE
        return (BOT_HANDLE or "").lower().lstrip("@")
    except Exception:
        return ""


def _looks_like_own_post(p: dict, own: str) -> bool:
    """Detect entries authored by us. Filters out the bot's OWN past
    posts so they don't become exemplars — without this, hallucinated
    entities (e.g. 'DeFi United', invented in April) get pulled back
    into the prompt and the model treats them as real and recycles them.
    Self-reinforcing hallucination = lethal."""
    if not own:
        return False
    author = (p.get("author") or "").lower().lstrip("@")
    if author == own:
        return True
    url = (p.get("url") or "").lower()
    if f"/{own}/status/" in url or f"x.com/{own}" in url:
        return True
    return False


def _recent_entries() -> list:
    now = datetime.now()
    cutoff = now - timedelta(days=WINDOW_DAYS)
    own = _own_handle()
    out = []
    for p in _load_performance():
        # 2026-05-18: filter out our OWN posts. Otherwise the bot reads its
        # own April hallucinations ("DeFi United") and treats them as
        # successful exemplars to recycle.
        if _looks_like_own_post(p, own):
            continue
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
        "# Joke bank — auto-curated from top-engagement tweets the bot WATCHED\n"
        "# (i.e. real tweets by other accounts in our niche, NOT our own posts).\n"
        f"# Generated {datetime.now().isoformat(timespec='minutes')}. "
        f"Top {len(entries)} of last {WINDOW_DAYS}d (≥{MIN_LIKES_FLOOR} likes).\n"
        "# Filtered to exclude our own posts so we don't recycle our own\n"
        "# hallucinations as exemplars (bug 2026-05-18: 'DeFi United' was\n"
        "# invented in April, then re-injected via this bank for weeks).\n\n"
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

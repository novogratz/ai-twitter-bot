"""Self-winners bank — same idea as joke_bank.py but pulls OUR OWN
top-engagement Décodes / posts that hit a real engagement floor.

The joke_bank studies OTHER accounts' top tweets. This one studies our
own wins so the model learns what SHIPS on this specific account, with
our specific voice, at our current follower count.

Filter:
- Only posts authored by us (URL contains /BOT_HANDLE/status/).
- Likes >= 10 (real engagement floor — avoids feedback-loop on noise).
- Last 30 days only.
- Score = likes + 50*(likes/views) to weight both volume and rate.

The output `self_winners.md` gets pulled into news + hotake prompts
alongside the joke_bank block. Inject 3 random examples per call.
"""
import json
import os
import random
import traceback
from datetime import datetime, timedelta
from typing import Optional

from .config import _PROJECT_ROOT, BOT_HANDLE
from .logger import log

PERFORMANCE_LOG_FILE = os.path.join(_PROJECT_ROOT, "performance_log.json")
SELF_WINNERS_FILE = os.path.join(_PROJECT_ROOT, "self_winners.md")
TOP_N = 20
MIN_LIKES_FLOOR = 10
WINDOW_DAYS = 30


def _own_handle() -> str:
    return (BOT_HANDLE or "").lower().lstrip("@")


def _is_own(p: dict, own: str) -> bool:
    if not own:
        return False
    if (p.get("author") or "").lower().lstrip("@") == own:
        return True
    url = (p.get("url") or "").lower()
    return f"/{own}/status/" in url or f"x.com/{own}" in url


def _clean(text: str) -> str:
    import re
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\[\s*(?:PATTERN|SOURCE|IMAGE|KEYWORD|TOPIC|ANGLE)[^\]]*\]", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _load_perf() -> list:
    if not os.path.exists(PERFORMANCE_LOG_FILE):
        return []
    try:
        with open(PERFORMANCE_LOG_FILE) as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _score(p: dict) -> float:
    likes = int(p.get("likes") or 0)
    views = int(p.get("views") or 0)
    if likes < MIN_LIKES_FLOOR:
        return 0.0
    rate = (likes / views) if views >= 200 else 0.0
    return likes + 50.0 * rate


def _recent_winners() -> list:
    own = _own_handle()
    cutoff = datetime.now() - timedelta(days=WINDOW_DAYS)
    out = []
    for p in _load_perf():
        if not _is_own(p, own):
            continue
        sa = p.get("scraped_at")
        try:
            ts = datetime.fromisoformat(sa) if sa else None
        except (ValueError, TypeError):
            ts = None
        if ts and ts < cutoff:
            continue
        text = _clean(p.get("text") or "")
        if not text or len(text) < 30:
            continue
        s = _score(p)
        if s <= 0:
            continue
        out.append({
            "text": text,
            "likes": int(p.get("likes") or 0),
            "views": int(p.get("views") or 0),
            "score": s,
        })
    out.sort(key=lambda r: r["score"], reverse=True)
    seen, dedup = set(), []
    for r in out:
        key = r["text"][:60].lower()
        if key in seen:
            continue
        seen.add(key)
        dedup.append(r)
        if len(dedup) >= TOP_N:
            break
    return dedup


def _write(entries: list) -> None:
    header = (
        "# Self-winners — YOUR OWN top-engagement Décodes/posts (last "
        f"{WINDOW_DAYS}d, ≥{MIN_LIKES_FLOOR} likes).\n"
        f"# Generated {datetime.now().isoformat(timespec='minutes')}. "
        f"Top {len(entries)} entries.\n"
        "# These are PROVEN winners for THIS account at its current size.\n"
        "# Prompts pull 3 random entries each cycle so the voice keeps\n"
        "# converging on what's actually landing.\n\n"
    )
    lines = [header]
    for r in entries:
        lines.append(f"- ({r['likes']} likes / {r['views']} views) \"{r['text']}\"\n")
    try:
        with open(SELF_WINNERS_FILE, "w") as f:
            f.writelines(lines)
    except OSError as e:
        log.info(f"[SELF_WINNERS] write failed: {e}")


def _read_entries() -> list[str]:
    if not os.path.exists(SELF_WINNERS_FILE):
        return []
    out = []
    try:
        with open(SELF_WINNERS_FILE) as f:
            for line in f:
                line = line.strip()
                if line.startswith("- "):
                    out.append(line[2:])
    except OSError:
        return []
    return out


def render_self_winners_block(sample_size: int = 3) -> str:
    entries = _read_entries()
    if not entries:
        return ""
    picks = random.sample(entries, min(sample_size, len(entries)))
    head = (
        "🏆 TES PROPRES POSTS QUI ONT HIT — Étudie le pattern (sujet, "
        "format, chute) puis DÉPASSE-LE. Tu vises CETTE énergie, en mieux.\n"
    )
    return head + "\n".join(picks)


def run_self_winners_cycle() -> None:
    entries = _recent_winners()
    if not entries:
        log.info("[SELF_WINNERS] no qualifying own-posts — skipping write.")
        return
    _write(entries)
    log.info(
        f"[SELF_WINNERS] wrote {len(entries)} own winners "
        f"(top: {entries[0]['likes']} likes, range "
        f"{entries[-1]['likes']}-{entries[0]['likes']})."
    )


def safe_run_self_winners_cycle() -> None:
    try:
        run_self_winners_cycle()
    except Exception:
        log.info("[SELF_WINNERS] outer error:")
        traceback.print_exc()

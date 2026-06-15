"""Reply-winners bank — the operator's insight (2026-06-15): "replies get
a crazy amount of likes, posts not really — could the bot inspire itself
from replies?"

YES. Replies are the proven winners for THIS account's voice. They win
because they REACT to something specific, they're conversational and human,
and they don't try to be clever — they say the sharp true thing in plain
words. Posts fail when they float free, abstract, trying too hard.

This module scrapes our own /with_replies tab (the one place X shows our
replies WITH like counts — they otherwise live invisibly on others'
threads), keeps the highest-liked ones, and writes `reply_winners.md`. The
post/quote generators inject a few as the GOLD-STANDARD VOICE to imitate:
"write your post to land exactly like these replies."

Parallel to self_winners.py (own POSTS that hit), but reply_winners is the
lever that matters now: self_winners has been empty (posts get ~0 likes)
while replies rack up likes daily.
"""
import os
import random
import re
import traceback
from datetime import datetime

from .config import _PROJECT_ROOT, BOT_HANDLE
from .logger import log

REPLY_WINNERS_FILE = os.path.join(_PROJECT_ROOT, "reply_winners.md")
TOP_N = int(os.environ.get("REPLY_WINNERS_TOP_N", "25"))
# Floor 2: replies pull real likes, so even 2 is a meaningful signal and
# filters the 0/1-like noise. Env-tunable as the account grows.
MIN_LIKES_FLOOR = int(os.environ.get("REPLY_WINNERS_MIN_LIKES", "2"))
_MAX_SCRAPE = int(os.environ.get("REPLY_WINNERS_SCRAPE_N", "40"))

_FR_MARKERS = (" le ", " la ", " les ", " des ", " une ", " est ", " dans ",
               " pour ", " avec ", " sur ", " que ", " qui ", " pas ")


def _looks_french(text: str) -> bool:
    t = " " + (text or "").lower() + " "
    return sum(1 for m in _FR_MARKERS if m in t) >= 3


def _own(url: str) -> bool:
    h = (BOT_HANDLE or "").lower().lstrip("@")
    return bool(h) and f"/{h}/status/" in (url or "").lower()


def _clean(text: str) -> str:
    text = re.sub(r"https?://\S+", "", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _mine_winners() -> list:
    """Scrape our /with_replies tab, keep our own replies above the like
    floor, English only, sorted by likes desc, deduped."""
    from .twitter_client import scrape_own_replies
    try:
        tweets = scrape_own_replies(max_tweets=_MAX_SCRAPE) or []
    except Exception as e:
        log.info(f"[REPLY_WINNERS] scrape failed: {e}")
        return []

    out = []
    for t in tweets:
        if not t.get("is_reply"):
            continue
        if not _own(t.get("url") or ""):
            continue
        likes = int(t.get("likes") or 0)
        if likes < MIN_LIKES_FLOOR:
            continue
        text = _clean(t.get("text") or "")
        if not text or len(text) < 20:
            continue
        if _looks_french(text):  # therapist voice is EN now
            continue
        out.append({"text": text, "likes": likes})

    out.sort(key=lambda r: r["likes"], reverse=True)
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
        f"# Reply-winners — YOUR OWN replies that earned the most likes "
        f"(≥{MIN_LIKES_FLOOR}).\n"
        f"# Generated {datetime.now().isoformat(timespec='minutes')}. "
        f"Top {len(entries)} entries.\n"
        "# Replies are THE proven voice for this account. Posts/quotes pull\n"
        "# a few each cycle and imitate the energy: reactive, specific,\n"
        "# human, plain words, the sharp true thing — no cleverness.\n\n"
    )
    lines = [header]
    for r in entries:
        lines.append(f"- ({r['likes']} likes) \"{r['text']}\"\n")
    try:
        with open(REPLY_WINNERS_FILE, "w") as f:
            f.writelines(lines)
    except OSError as e:
        log.info(f"[REPLY_WINNERS] write failed: {e}")


def _read_entries() -> list:
    if not os.path.exists(REPLY_WINNERS_FILE):
        return []
    out = []
    try:
        with open(REPLY_WINNERS_FILE) as f:
            for line in f:
                line = line.strip()
                if line.startswith("- "):
                    out.append(line[2:])
    except OSError:
        return []
    return out


def render_reply_winners_block(sample_size: int = 3) -> str:
    """Inject into post/quote prompts: the proven reply voice to imitate.
    Empty string when the bank is empty (no injection rather than stale)."""
    entries = _read_entries()
    if not entries:
        return ""
    picks = random.sample(entries, min(sample_size, len(entries)))
    head = (
        "🎯 YOUR REPLIES GET WAY MORE LIKES THAN YOUR POSTS. Here are your\n"
        "best ones (with like counts). They win because they REACT to one\n"
        "specific thing, in plain human words, with the sharp true take —\n"
        "no cleverness, no abstraction. Write THIS post/quote to land\n"
        "exactly like these. Same reactive, specific, human energy:\n"
    )
    return head + "\n".join(picks)


def run_reply_winners_cycle() -> None:
    entries = _mine_winners()
    if not entries:
        _write([])  # clear, never keep a stale bank (self_winners lesson)
        log.info("[REPLY_WINNERS] no qualifying replies scraped — bank cleared.")
        return
    _write(entries)
    log.info(
        f"[REPLY_WINNERS] wrote {len(entries)} reply winners "
        f"(top {entries[0]['likes']} likes, range "
        f"{entries[-1]['likes']}-{entries[0]['likes']})."
    )


def safe_run_reply_winners_cycle() -> None:
    try:
        run_reply_winners_cycle()
    except Exception:
        log.info("[REPLY_WINNERS] outer error:")
        traceback.print_exc()

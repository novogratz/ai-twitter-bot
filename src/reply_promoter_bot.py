"""Reply-winner promoter — proven content graduates to the profile.

Operator 2026-07-28 ("do everything you think we should do"): our replies
earn real likes inside OTHER people's threads (the 100-like / 13.3K-view
reply is the account's biggest measured win), but that content lives and
dies in someone else's comments. This bot takes the highest-liked reply
from the reply_winners bank (already scraped + like-ranked every 3h) and
rewrites it as a STANDALONE post — the audience-tested insight gets a
second life in front of the profile audience.

Max 1/day; each winner promoted at most once ever (state file). Ships
through the post_tweet chokepoint (caps, spacing, dedup, content guard).
"""
import json
import os
import re
import traceback
from datetime import date

from .config import _PROJECT_ROOT, HOTAKE_MODEL, PROFILE_LLM_PROVIDER
from .logger import log
from .llm_client import run_llm, unwrap_text
from .humanizer import humanize

STATE_FILE = os.path.join(_PROJECT_ROOT, "reply_promoter_state.json")
WINNERS_FILE = os.path.join(_PROJECT_ROOT, "reply_winners.md")

# Bank line format (reply_winners._write): - (N likes) "text"
_ENTRY_RE = re.compile(r'^- \((\d+) likes\) "(.+)"\s*$')


def _load_state() -> dict:
    try:
        with open(STATE_FILE) as f:
            st = json.load(f)
        if isinstance(st, dict):
            return st
    except (OSError, json.JSONDecodeError):
        pass
    return {"date": "", "promoted": []}


def _save_state(st: dict) -> None:
    st["promoted"] = st.get("promoted", [])[-300:]
    with open(STATE_FILE, "w") as f:
        json.dump(st, f, indent=1)


def _bank_entries() -> list:
    """[(likes, text)] from the winners bank, best first."""
    out = []
    try:
        with open(WINNERS_FILE) as f:
            for line in f:
                m = _ENTRY_RE.match(line.strip())
                if m:
                    out.append((int(m.group(1)), m.group(2)))
    except OSError:
        return []
    out.sort(key=lambda e: e[0], reverse=True)
    return out


PROMOTE_PROMPT = """You are @TheAIShrink — THE AI THERAPIST. A woman, 35-40, practicing
therapist and mom, the sharpest AI mind on the timeline (warm, wry, magnetic, zero bro-speak).

You wrote this REPLY in someone else's thread and it earned {likes} likes — the audience
already voted for this insight:

"{reply_text}"

Rewrite it as a STANDALONE post for your own profile. The insight stays; the packaging changes:
- It must stand alone with ZERO context from the original thread. If the reply leans on the
  parent tweet ("this", "you're right that...", an unnamed "he/they"), name the subject or
  generalize it.
- Keep the exact energy that won: plain words, specific, human, one sharp true thing.
- Her voice. ONE idea, <=240 chars, no hashtags, no links, no em dashes.
- Do NOT copy the reply verbatim — repackage it (the reply is public; a copy-paste looks lazy).
- If the reply is too thread-bound to stand alone → output exactly SKIP.

Output ONLY the post text, or exactly SKIP."""


def run_reply_promoter_cycle():
    if os.environ.get("ENABLE_REPLY_PROMOTER", "1") != "1":
        log.info("[PROMOTER] Disabled. Skipping.")
        return
    min_likes = int(os.environ.get("REPLY_PROMOTE_MIN_LIKES", "4"))

    st = _load_state()
    today = date.today().isoformat()
    if st.get("date") == today:
        log.info("[PROMOTER] Already promoted today. Skipping.")
        return

    promoted = set(st.get("promoted", []))
    candidates = [(l, t) for l, t in _bank_entries()
                  if l >= min_likes and t not in promoted]
    if not candidates:
        log.info(f"[PROMOTER] No unpromoted winner >= {min_likes} likes in the bank. Skipping.")
        return

    likes, reply_text = candidates[0]
    result = run_llm(PROMOTE_PROMPT.format(likes=likes, reply_text=reply_text[:400]),
                     HOTAKE_MODEL, label="REPLY_PROMOTE",
                     force_provider=PROFILE_LLM_PROVIDER)
    if result.returncode != 0:
        return
    post = unwrap_text(result.stdout).strip()
    if not post or post.upper().startswith("SKIP"):
        # Thread-bound winner — burn it so tomorrow tries the next one.
        st.setdefault("promoted", []).append(reply_text)
        _save_state(st)
        log.info("[PROMOTER] Model skipped (thread-bound reply) — winner burned, next one tomorrow.")
        return
    post = humanize(post)

    from .twitter_client import post_tweet
    from .engagement_log import log_post
    if post_tweet(post):
        st["date"] = today
        st.setdefault("promoted", []).append(reply_text)
        _save_state(st)
        log_post(post, source=f"PROMOTED_REPLY/{likes}likes")
        log.info(f"[PROMOTER] Promoted a {likes}-like reply to the profile.")
    else:
        log.info("[PROMOTER] Chokepoint refused — winner preserved for next cycle.")


def safe_run_reply_promoter_cycle():
    from . import health
    try:
        run_reply_promoter_cycle()
        health.record_success("reply_promoter")
    except Exception:
        log.info("[PROMOTER] Error during cycle:")
        traceback.print_exc()
        health.record_failure("reply_promoter")

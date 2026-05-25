"""Viral follow-up bot — when our own post hits VIRAL_THRESHOLD+, post a follow-up.

Why: when X's algo decides a tweet is working, the first ~hour after takeoff
is the highest-leverage window we have. Adding a follow-up reply on the same
thread (a) extends the audience time-on-thread, (b) creates a 2-for-1 surface
where the second tweet also lands in the For You feed of liked-the-original
users, (c) gives us a chance to drop another joke + push the punchline.

Strategy:
  - Every 30 min: scrape /CryptoAIDecode for our recent posts.
  - For each post with likes >= VIRAL_THRESHOLD that we haven't followed up on:
    - Generate a short follow-up via LLM that extends the original joke
      (one-liner punchline, NOT another news take).
    - Reply to the post in-thread.
    - Persist URL in viral_followed_up.json so we never double-follow-up.
  - Cap 3 follow-ups per cycle (keep cadence honest).
"""
import json
import os
import time
import traceback
from datetime import datetime
from typing import Optional

from .config import _PROJECT_ROOT, BOT_HANDLE, REPLY_MODEL
from .llm_client import run_llm, unwrap_text
from .logger import log
from .twitter_client import scrape_profile_tweets, reply_to_tweet_in_thread
from .humanizer import humanize
from .engagement_log import log_reply

VIRAL_FOLLOWED_FILE = os.path.join(_PROJECT_ROOT, "viral_followed_up.json")
VIRAL_THRESHOLD = int(os.environ.get("VIRAL_THRESHOLD", "4"))
VIRAL_FOLLOWUP_CAP_PER_CYCLE = int(os.environ.get("VIRAL_FOLLOWUP_CAP", "5"))


FOLLOWUP_PROMPT = """You are @CryptoAIDecode. Your tweet is landing hard — extend the joke.

Your original tweet:
"{post_text}"

({likes} likes, {replies} replies)

Your job: write ONE short follow-up sentence, posted as a reply to your own tweet, that EXTENDS the joke or lands ONE MORE LAYER.

LANGUAGE: match the language of the original tweet. English -> English follow-up. French -> French follow-up. No mixing.

🎯 LAUGH TEST — if it doesn't make YOU laugh, rewrite until it does.
The audience is riding high on the original joke. Don't kill the vibe with
a flat follow-up. DEADPAN. SHARP. ONE MORE PUNCHLINE.
User directive: be funnier in replies. The follow-up should feel like the
second joke in a bit, not a caption. Add surprise, not explanation.

PREFERRED SHAPES (pick one):
  - Callback ("Edit: I forgot to mention the worst part...")
  - Mini-dialogue ("- But how?" / "- Nobody knows. That's the point.")
  - Renaming ("Stargate: the world's most expensive GPU fireplace.")
  - Anti-climax ("Huge launch. Revolutionary. The slide deck was beautiful.")
  - Understatement ("Minor detail: the math doesn't work.")
  - Absurd comparison ("This is like bringing a knife to a GPU fight.")

RULES:
- Max 200 characters. Short lands harder.
- No emojis. No hashtags. No em dashes (—).
- No "Update:", "Follow-up:", "More seriously". You extend the bit, not pivot.
- Use ONE exact detail from the original tweet. Generic follow-ups bomb.
- Last 3-8 words should be the punchline. No soft landing.
- If you don't have a real second punchline -> output exactly: SKIP

Output ONLY the follow-up text, or SKIP."""


def _load_followed_up() -> set:
    if os.path.exists(VIRAL_FOLLOWED_FILE):
        try:
            with open(VIRAL_FOLLOWED_FILE, "r") as f:
                return set(json.load(f))
        except (json.JSONDecodeError, IOError):
            pass
    return set()


def _save_followed_up(s: set):
    with open(VIRAL_FOLLOWED_FILE, "w") as f:
        json.dump(list(s)[-500:], f)


def _generate_followup(post_text: str, likes: int, replies: int) -> Optional[str]:
    from . import personality_store
    extras = [personality_store.hard_rules_block()]
    prompt = FOLLOWUP_PROMPT.format(
        post_text=post_text, likes=likes, replies=replies,
    ) + "\n\n" + "\n\n".join(extras)
    result = run_llm(prompt, REPLY_MODEL, label="VIRAL_FOLLOWUP")
    if result.returncode != 0:
        log.info(f"[VIRAL] LLM failed: {result.stderr[:160]}")
        return None
    text = unwrap_text(result.stdout).strip()
    if not text or text.upper() == "SKIP":
        return None
    if "skip" in text.lower():
        return None
    text = humanize(text)
    if len(text) < 10 or len(text) > 270:
        return None
    return text


def run_viral_followup_cycle():
    """Find own posts that took off and post one follow-up reply each."""
    followed_up = _load_followed_up()

    log.info(f"[VIRAL] Scraping @{BOT_HANDLE} for posts > {VIRAL_THRESHOLD} likes...")
    try:
        tweets = scrape_profile_tweets(BOT_HANDLE, max_tweets=25)
    except Exception:
        log.info("[VIRAL] Scrape failed:")
        traceback.print_exc()
        return

    candidates = []
    bot_lc = BOT_HANDLE.lower()
    for t in tweets:
        author = (t.get("author") or "").lower().lstrip("@")
        if author and author != bot_lc:
            continue
        url = t.get("url") or ""
        if not url or url in followed_up:
            continue
        likes = int(t.get("likes") or 0)
        if likes < VIRAL_THRESHOLD:
            continue
        text = (t.get("text") or "").strip()
        if not text:
            continue
        candidates.append({
            "url": url,
            "text": text,
            "likes": likes,
            "replies": int(t.get("replies") or 0),
        })

    if not candidates:
        log.info(f"[VIRAL] No own post >= {VIRAL_THRESHOLD} likes pending follow-up.")
        return

    # Sort by likes desc and keep top N — focus on the strongest signal.
    candidates.sort(key=lambda c: (c["likes"], c["replies"]), reverse=True)
    pick = candidates[:VIRAL_FOLLOWUP_CAP_PER_CYCLE]

    log.info(f"[VIRAL] {len(pick)} viral post(s) to follow up on.")
    for c in pick:
        log.info(f"[VIRAL]   - {c['likes']} likes: {c['text'][:120]!r}")

        followup = _generate_followup(c["text"], c["likes"], c["replies"])
        if not followup:
            log.info("[VIRAL]   Agent returned SKIP / invalid. Marking done so we don't loop.")
            followed_up.add(c["url"])
            _save_followed_up(followed_up)
            continue

        log.info(f"[VIRAL]   Follow-up: {followup}")

        # Lock URL in BEFORE posting so a crash can't double-followup.
        followed_up.add(c["url"])
        _save_followed_up(followed_up)

        try:
            reply_to_tweet_in_thread(c["url"], followup)
            log.info("[VIRAL]   Posted in-thread.")
            try:
                log_reply(
                    c["url"],
                    f"[VIRAL_FOLLOWUP] {followup}",
                    action_type="reply",
                    source=f"VIRAL/{BOT_HANDLE}",
                )
            except Exception:
                pass
            time.sleep(5)
        except Exception:
            log.info("[VIRAL]   Reply failed:")
            traceback.print_exc()


def safe_run_viral_followup_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    from . import health
    try:
        run_viral_followup_cycle()
        health.record_success("viral_followup")
    except Exception:
        log.info("[VIRAL] Error during viral follow-up cycle:")
        traceback.print_exc()
        health.record_failure("viral_followup")

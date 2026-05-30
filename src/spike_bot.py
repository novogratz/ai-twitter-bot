"""Spike orchestrator — when one of our posts takes off, all bots converge.

Most growth on X happens AROUND a single viral moment. The first hour
after takeoff is where 80% of the reach lands. Default bot behavior is
to keep posting new things; that DILUTES the spike. This bot does the
opposite: when it detects a viral spike on our own profile, it pauses
new-content cycles for ~60min and amplifies the spike from every angle.

Strategy:
  - Every 8 min, scrape /AISpaceDecoder for posts taking off (>= SPIKE_LIKES).
  - On first detection of a spike (URL not seen yet):
       1. Auto-pin it (override daily pin lock).
       2. Self-RT it via retweet_post (push it onto every follower's feed).
       3. Generate + post an in-thread follow-up (extends the punchline).
       4. Skip old quote-RT promo; plain repost already happened.
       5. Like top replies on it (boosts thread engagement).
  - Persistent dedup so we don't re-orchestrate the same spike.
"""
import json
import os
import time
import traceback
from datetime import datetime, date

from .config import _PROJECT_ROOT, BOT_HANDLE, REPLY_MODEL
from .llm_client import run_llm, unwrap_text
from .logger import log
from .twitter_client import (
    scrape_profile_tweets,
    retweet_post,
    pin_own_tweet,
    reply_to_tweet_in_thread,
    like_own_tweet_replies,
)
from .humanizer import humanize, strip_agent_preamble
from .engagement_log import log_reply

SPIKE_HISTORY_FILE = os.path.join(_PROJECT_ROOT, "spike_history.json")

# Number of likes before a post counts as "spiking". Tuned conservative
# at first — 30 likes from a 360-follower account is already a 10x post.
SPIKE_LIKES = int(os.environ.get("SPIKE_LIKES", "25"))


SPIKE_FOLLOWUP_PROMPT = """You are @AISpaceDecoder. One of your tweets is EXPLODING right now:

"{post_text}"

({likes} likes in a short window)

The tweet is taking off. Time to extend. Write ONE short FOLLOW-UP
sentence, posted as a reply to your own tweet, that:
- rides the audience peak watching this thread
- extends the joke or adds one more brutal layer
- keeps the meme effect going

LANGUAGE: match the original tweet. English original -> English follow-up.
French original -> French follow-up. No mixing.

🎯 THIS IS YOUR VIRAL MOMENT. Make it count. The follow-up must be
AS FUNNY or FUNNIER than the original. The audience is scrolling your
profile — this is the reply that makes them follow.
User directive: be funnier in replies. This is not a clarification. It is the
second laugh. If the line merely explains the original, output SKIP.

PREFERRED SHAPES (pick one, make it savage):
  - Anti-climax: "Huge launch. Revolutionary. The font was beautiful."
  - Mini-dialogue: "- But how?" / "- Nobody knows."
  - Renaming: "This is how I learned about my 401(k). Via memes."
  - Understatement: "Mild concern at the all-hands."
  - Callback: "Edit: forgot to mention the part where the math doesn't work."
  - Absurd comparison: "The AI industry is a casino where the house also gambles."

RULES:
- Max 200 characters.
- No emojis. No hashtags. No em dashes (—).
- No meta words ("Update:", "Bonus:", "More seriously"). Extend the bit.
- Use ONE exact detail from the original tweet for specificity.
- End on the punchline. No soft landing, no extra sentence explaining it.
- If nothing strong -> output exactly: SKIP

Output ONLY the follow-up text, or SKIP."""


def _load_history() -> set:
    if os.path.exists(SPIKE_HISTORY_FILE):
        try:
            with open(SPIKE_HISTORY_FILE, "r") as f:
                return set(json.load(f))
        except (json.JSONDecodeError, OSError):
            pass
    return set()


def _save_history(s: set):
    with open(SPIKE_HISTORY_FILE, "w") as f:
        json.dump(list(s)[-200:], f)


def _generate_spike_followup(post_text: str, likes: int):
    from . import personality_store
    extras = [personality_store.hard_rules_block()]
    prompt = SPIKE_FOLLOWUP_PROMPT.format(post_text=post_text, likes=likes) + "\n\n" + "\n\n".join(extras)
    result = run_llm(prompt, REPLY_MODEL, label="SPIKE_FOLLOWUP")
    if result.returncode != 0:
        return None
    text = unwrap_text(result.stdout).strip()
    text = strip_agent_preamble(text)
    if not text or text.upper() == "SKIP" or "skip" in text.lower():
        return None
    text = humanize(text)
    if len(text) < 10 or len(text) > 270:
        return None
    return text


def _orchestrate_spike(post: dict, history: set):
    """Hit the spike from every angle. Best-effort — each step is wrapped
    independently so a single failure doesn't kill the orchestration.
    """
    url = post["url"]
    text = post["text"]
    likes = post["likes"]

    log.info(
        f"[SPIKE] Orchestrating amplification of {likes}-like post: {text[:120]!r}"
    )

    # Lock URL in BEFORE doing anything so a crash mid-flight can't loop.
    history.add(url)
    _save_history(history)

    # 1. Auto-pin (override daily lock).
    try:
        ok = pin_own_tweet(url)
        log.info(f"[SPIKE] pin: {ok}")
    except Exception:
        log.info("[SPIKE] pin failed:")
        traceback.print_exc()

    # 2. Self-RT (boosts on follower feeds).
    try:
        retweet_post(url)
        log.info("[SPIKE] self-RT done.")
        time.sleep(2)
    except Exception:
        log.info("[SPIKE] self-RT failed:")
        traceback.print_exc()

    # 3. In-thread follow-up extending the punchline.
    try:
        followup = _generate_spike_followup(text, likes)
        if followup:
            reply_to_tweet_in_thread(url, followup)
            log.info(f"[SPIKE] in-thread follow-up posted: {followup!r}")
            try:
                log_reply(
                    url, f"[SPIKE_FOLLOWUP] {followup}",
                    action_type="reply",
                    source=f"SPIKE/{BOT_HANDLE}",
                )
            except Exception:
                pass
            time.sleep(2)
        else:
            log.info("[SPIKE] no follow-up generated.")
    except Exception:
        log.info("[SPIKE] follow-up failed:")
        traceback.print_exc()

    # 4. Quote promo disabled. The earlier self-repost already covers
    # the plain repost surface; doing it again could toggle it off.
    log.info("[SPIKE] quote promo disabled; keeping the existing plain repost.")

    # 5. Like top replies on the spiking thread (boosts engagement signal).
    try:
        like_own_tweet_replies()
        log.info("[SPIKE] liked top replies.")
    except Exception:
        log.info("[SPIKE] like-replies failed:")
        traceback.print_exc()

    log.info(f"[SPIKE] Orchestration complete on {url}")


def run_spike_cycle():
    """Find spiking own posts, orchestrate amplification."""
    history = _load_history()

    log.info(f"[SPIKE] Scraping @{BOT_HANDLE} for posts >= {SPIKE_LIKES} likes...")
    try:
        tweets = scrape_profile_tweets(BOT_HANDLE, max_tweets=15)
    except Exception:
        log.info("[SPIKE] Scrape failed:")
        traceback.print_exc()
        return

    if not tweets:
        return

    spikes = []
    bot_lc = BOT_HANDLE.lower()
    for t in tweets:
        author = (t.get("author") or "").lower().lstrip("@")
        if author and author != bot_lc:
            continue
        url = t.get("url") or ""
        if not url or url in history:
            continue
        likes = int(t.get("likes") or 0)
        if likes < SPIKE_LIKES:
            continue
        text = (t.get("text") or "").strip()
        if not text:
            continue
        spikes.append({"url": url, "text": text, "likes": likes})

    if not spikes:
        return

    # Pick the strongest spike this cycle and orchestrate ONCE per cycle.
    # Other spikes will surface on subsequent cycles.
    spikes.sort(key=lambda s: s["likes"], reverse=True)
    best = spikes[0]
    _orchestrate_spike(best, history)


def safe_run_spike_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    from . import health
    try:
        run_spike_cycle()
        health.record_success("spike")
    except Exception:
        log.info("[SPIKE] Error during spike cycle:")
        traceback.print_exc()
        health.record_failure("spike")

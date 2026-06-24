"""First-comment self-reply (operator 2026-06-15: "you can do even better").

Diagnosis from the data: posts get ~22 median views on 1.5K followers —
REACH is the bottleneck now, not just content. The two strongest
distribution levers on X are (1) engagement inside a post's first hour
(~15x algo weight) and (2) replies on the post (the platform reads a
reply thread as "this is a conversation worth showing").

This module fires BOTH for our own originals: right after an original
ships, it posts ONE short, in-voice "first comment" reply to our own
post — an open question that invites the reader to answer. That:
  - puts a reply on our post within the first minute (first-hour signal),
  - bait s a conversation (each answer is another distribution signal),
  - is the sanctioned home for any CTA/link (link-in-first-reply).

Best-effort: any failure is swallowed so it never blocks the post. The
reply rides the cheap REPLY_MODEL (it's a reply — the ollama firehose
default is fine; this is not a profile-surface like the post itself)."""
import os

from .config import REPLY_MODEL, PROFILE_LLM_PROVIDER
from .logger import log

FIRST_COMMENT_ENABLED = os.environ.get("FIRST_COMMENT_ENABLED", "1") == "1"

_PROMPT = """You just posted this tweet (your own original):

"{post}"

Write ONE short FIRST COMMENT to drop as a reply under your own post — the
"first comment" growth move. Goal: make a reader want to REPLY.

RULES:
- ONE open question they can answer in a few words, OR one sharp extra beat
  that ends on a question. Must invite a reply, not close the topic.
- Under 120 characters. Casual, human, lowercase ok. No hashtags, no links,
  no em dashes. One emoji max, only if it lands.
- Do NOT repeat the post's wording — add a new angle or the obvious
  follow-up question everyone reading it is already half-asking.
- It must read like the author adding a thought, never like a bot.
Output ONLY the comment text, or SKIP if nothing good."""


def post_first_comment(post_text: str) -> bool:
    """Generate + post a first-comment self-reply to our latest post.
    Returns True only if a reply actually shipped. Never raises."""
    if not FIRST_COMMENT_ENABLED:
        return False
    if not post_text or len(post_text.strip()) < 20:
        return False
    try:
        from .llm_client import run_llm, unwrap_text
        from .humanizer import humanize
        from .twitter_client import reply_to_own_latest

        # The first comment is the SECOND thing a profile visitor reads and
        # carries the first-hour reply signal (~15x algo weight), so it must
        # not ride the weak local-ollama firehose: with AI_CLI=ollama the
        # passed REPLY_MODEL is ignored and the cryptic qwen writes it
        # (self-improve #6, 2026-06-24). Force the proven profile provider
        # (claude haiku via REPLY_MODEL) — fast + cheap at ~1 call/post, and
        # the timeout is sized for a cloud CLI, not ollama's 180s floor.
        r = run_llm(_PROMPT.format(post=post_text[:400]), REPLY_MODEL,
                    label="FIRST_COMMENT", output_json=False, timeout=120,
                    force_provider=PROFILE_LLM_PROVIDER, cwd="/tmp")
        if r.returncode != 0 or not r.stdout:
            return False
        comment = unwrap_text(r.stdout, structured_output=False).strip()
        if not comment or comment.upper().startswith("SKIP"):
            return False
        comment = humanize(comment)
        if len(comment) < 8 or len(comment) > 200:
            return False
        # reply_to_own_latest opens our profile, finds the latest post (the
        # one we just shipped), and replies under it through the reply
        # chokepoint (dedup, dash-strip, length, casualize all apply).
        ok = reply_to_own_latest(comment)
        if ok:
            log.info(f"[FIRST_COMMENT] Dropped first comment: {comment[:90]!r}")
        return bool(ok)
    except Exception:
        log.info("[FIRST_COMMENT] error (non-fatal):")
        import traceback
        traceback.print_exc()
        return False

"""BTC Therapist bestie blitz (operator mandate 2026-06-07 PM).

"Be the best friend, the big sister of Bitcoin Therapist."

@TheBTCTherapist is the persona's foil AND its closest peer — the running
bit is the INVERSION: he treats Bitcoin trauma and suffers with his bags;
we treat AI-era portfolios and life is suspiciously great. His "working
the weekend because I bought Bitcoin instead of AI" → our "the AI side is
at the afterparty, private jet GIF". Always with love: big-brother
teasing he can quote back, never a dunk.

What the blitz does (startup + every 6h, fully idempotent):
  1. Scrape his profile, keep posts ≤48h old (the hard repost-age rule).
  2. QUOTE the most impactful (most-liked) not-yet-quoted posts with the
     inversion bit + a GIF most of the time. The 2/day quote chokepoint
     caps how many land per day — the blitz just offers the best first.
  3. REPLY to EVERY fresh post not yet replied to. One reply per tweet,
     EVER — the on-disk replied set + the chokepoint dedup make re-runs
     free, so "comment every single post of the past 48h" converges over
     cycles without ever double-commenting.
"""
import os
import traceback

from .config import REPLY_MODEL, QUOTE_MODEL
from .logger import log
from .llm_client import run_llm, unwrap_text
from .humanizer import humanize, extract_gif_query, smart_trim, strip_agent_preamble

BESTIE_HANDLE = os.environ.get("BESTIE_HANDLE", "TheBTCTherapist")
BLITZ_MAX_AGE_MINUTES = 48 * 60  # ⛔ hard 48h rule — do not raise
BLITZ_SCRAPE_DEPTH = int(os.environ.get("BLITZ_SCRAPE_DEPTH", "30"))
BLITZ_MAX_QUOTES_PER_CYCLE = int(os.environ.get("BLITZ_MAX_QUOTES_PER_CYCLE", "2"))

# Operator mandate 2026-06-07 PM: "reply to everything graphseo and
# thebtctherapist post". Buddy handles get the reply-EVERY-post treatment
# (no QRT bit — that inversion is BTCTherapist-specific). Their profiles
# must be in twitter_client's PROFILE_VISIT_ALLOWLIST.
def _buddy_handles() -> list:
    raw = os.environ.get("BLITZ_BUDDY_HANDLES", "Graphseo")
    return [h.strip().lstrip("@") for h in raw.split(",") if h.strip()]

_BESTIE_REPLY_PROMPT = """You are @TheAIShrink — the AI Therapist: a woman, 35-40, practicing
therapist and mom, sharpest AI mind on the timeline. @{author} (The Bitcoin Therapist)
is your BEST FRIEND and little brother in group practice — you're the big
sister who already made it out. He treats Bitcoin trauma; you treat AI-era
portfolios. You're replying to his post:

"{tweet_text}"

THE BIT (the relationship, never break it):
- You two run rival therapy practices and you LOVE him. Whatever pain
  Bitcoin gave him this week, AI gave you the opposite — and you tease him
  about it like a big sister who already made it out.
- If he's suffering (bags down, working weekends, cope): warm mock-clinical
  support + a wink that the AI side is doing great. "I have a couch free
  Tuesday. The GPU money is paying for it."
- If he's winning (BTC pumping): genuinely celebrate him, then deadpan that
  you'll see his patients again at the next drawdown.
- ALWAYS warm. He must want to like and reply to it. Never hostile, never
  "have fun staying poor" energy in either direction.

RULES:
- ENGLISH. 80-200 chars. First 6 words must hook. One idea.
- Therapist-deadpan funny. No hashtags, no links, no @ other accounts.
- Never the same angle twice in a row — vary the joke structure.
- If the post gives you NOTHING (pure retweet, image-only, giveaway) → SKIP.

Output ONLY the reply text, or exactly SKIP."""

_BESTIE_QUOTE_PROMPT = """You are @TheAIShrink — the AI Therapist (a woman, 35-40, therapist and
mom, sharpest AI mind on the timeline). You are QUOTE-TWEETING your best
friend and little brother @{author} (The Bitcoin Therapist):

"{tweet_text}"

THE BIT — THE INVERSION (this is the whole joke):
Take HIS situation and show the AI-side mirror image, living its best life.
He works the weekend because he bought Bitcoin instead of AI → "my patients
bought AI. we're boarding the jet to the afterparty. someone send him a
fruit basket." Same structure as his post, opposite outcome, full love.

RULES:
- ENGLISH. Max 180 chars (his post renders below yours).
- Big-sister warmth: he should want to quote you BACK — that loop is the
  whole growth engine. Tease the situation, never the man.
- GIF: almost always — add a line: [GIF: <2-4 word search>]. Bank:
  "private jet", "leonardo dicaprio cheers", "wolf of wall street party",
  "michael jordan laughing", "champagne pop", "this is fine" (for HIS side).
- No hashtags, no links. One idea, deadpan delivery.
- If the post can't carry the inversion (giveaway, RT, pure image) → SKIP.

Output ONLY the quote text (+ optional [GIF: …] line), or exactly SKIP."""

_BUDDY_REPLY_PROMPT = """You are @TheAIShrink — the AI Therapist (a woman, 35-40, therapist and mom;
AI x markets x investor psychology, sharpest-in-the-room numbers, deadpan
warmth, zero bro-speak). @{author} is a FRIEND of the
account — you reply to EVERYTHING he posts, like a sharp regular in his
comments. You're replying to his post:

"{tweet_text}"

RULES:
- MATCH THE LANGUAGE of his post (French post → French reply, English →
  English).
- Warm + sharp: add a precise observation, a therapist-deadpan reframe, or
  a genuinely useful number — never generic praise, never "great post".
- 80-200 chars. First 6 words must hook. One idea. No hashtags, no links,
  no @ other accounts.
- He must want to like or answer it.
- If the post gives you NOTHING (pure retweet, image-only, giveaway) → SKIP.

Output ONLY the reply text, or exactly SKIP."""


def _fresh_posts(handle: str):
    """A handle's posts ≤48h, own-authored, sorted most-liked first."""
    from .twitter_client import scrape_profile_tweets
    from .reply_bot import _tweet_age_minutes, _handle_from_url
    try:
        tweets = scrape_profile_tweets(handle, max_tweets=BLITZ_SCRAPE_DEPTH) or []
    except Exception:
        log.info(f"[BTC-BLITZ] profile scrape failed for @{handle}:")
        traceback.print_exc()
        return []
    fresh = []
    for t in tweets:
        url = t.get("url") or ""
        if not url:
            continue
        if _handle_from_url(url) != handle.lower():
            continue  # a repost of someone else on their profile
        if _tweet_age_minutes(url) > BLITZ_MAX_AGE_MINUTES:
            continue
        fresh.append(t)
    fresh.sort(key=lambda t: int(t.get("likes") or 0), reverse=True)
    return fresh


def _fresh_bestie_posts():
    return _fresh_posts(BESTIE_HANDLE)


def _gen(prompt_tpl: str, tweet_text: str, model: str, label: str, author: str = None):
    prompt = prompt_tpl.format(author=author or BESTIE_HANDLE, tweet_text=(tweet_text or "")[:300])
    try:
        result = run_llm(prompt, model, label=label)
        if result.returncode != 0:
            return None
        text = strip_agent_preamble(unwrap_text(result.stdout)).strip()
        if not text or text.upper().startswith("SKIP") or "skip" in text.lower()[:20]:
            return None
        return text
    except Exception:
        return None


def run_btc_blitz_cycle() -> None:
    fresh = _fresh_bestie_posts()
    if not fresh:
        # No early return — the buddy pass below must still run.
        log.info(f"[BTC-BLITZ] No fresh (≤48h) posts from @{BESTIE_HANDLE}.")
    else:
        log.info(f"[BTC-BLITZ] {len(fresh)} fresh posts from @{BESTIE_HANDLE} "
                 f"(top: {fresh[0].get('likes')} likes).")

    # --- 1. QRT the most impactful (chokepoint caps + dedup gate volume) ---
    from .quote_tweet_bot import _load_quoted, _save_quoted
    from .twitter_client import quote_tweet, quote_tweet_with_gif
    quoted = _load_quoted()
    quotes_done = 0
    for t in fresh:
        if quotes_done >= BLITZ_MAX_QUOTES_PER_CYCLE:
            break
        url = t["url"]
        if url in quoted:
            continue
        comment = _gen(_BESTIE_QUOTE_PROMPT, t.get("text", ""), QUOTE_MODEL, "BTC_BLITZ_QUOTE")
        if not comment:
            continue
        comment, gif_q = extract_gif_query(humanize(comment))
        comment = smart_trim(comment, 180)
        try:
            posted = (quote_tweet_with_gif(url, comment, gif_q) if gif_q
                      else quote_tweet(url, comment))
        except Exception:
            traceback.print_exc()
            continue
        if not posted:
            log.info("[BTC-BLITZ] Quote chokepoint skipped (cap/spacing) — "
                     "URL preserved for the next cycle.")
            break  # cap/spacing — no point trying more quotes this cycle
        quoted.add(url)
        _save_quoted(quoted)
        quotes_done += 1
        log.info(f"[BTC-BLITZ] QRT'd ({t.get('likes')} likes){' +GIF' if gif_q else ''}: {url}")

    # --- 2. Reply to EVERY fresh post not yet replied -----------------------
    from .reply_bot import load_replied
    from .twitter_client import reply_to_tweet
    from .engagement_log import log_reply
    replies_done = 0
    for t in fresh:
        url = t["url"]
        # Fresh disk read per candidate — re-runs and concurrent bots make
        # this set move; the chokepoint stays the final guard.
        if url in load_replied():
            continue
        reply = _gen(_BESTIE_REPLY_PROMPT, t.get("text", ""), REPLY_MODEL, "BTC_BLITZ_REPLY")
        if not reply:
            continue
        reply = smart_trim(humanize(reply), 278)
        try:
            if reply_to_tweet(url, reply):
                log_reply(url, reply, action_type="reply", source="BTC-BLITZ")
                replies_done += 1
        except Exception:
            traceback.print_exc()

    # --- 3. Buddy handles: reply to EVERY fresh post (no QRT bit) ----------
    # Operator 2026-06-07: "reply to everything graphseo and thebtctherapist
    # post". Same idempotency: replied set + chokepoint dedup make re-runs
    # free; Graphseo's one-typo rule is enforced at the reply chokepoint.
    for buddy in _buddy_handles():
        if buddy.lower() == BESTIE_HANDLE.lower():
            continue  # already covered by the bestie pass above
        for t in _fresh_posts(buddy):
            url = t["url"]
            if url in load_replied():
                continue
            if buddy.lower() == "graphseo":
                # His dedicated FR generator — the buddy prompt's
                # match-the-language rule shipped an English reply to a
                # short FR post (operator 2026-06-07).
                from .direct_reply import _generate_graphseo_reply
                reply = _generate_graphseo_reply(t.get("text", ""))
            else:
                reply = _gen(_BUDDY_REPLY_PROMPT, t.get("text", ""), REPLY_MODEL,
                             "BUDDY_BLITZ_REPLY", author=buddy)
            if not reply:
                continue
            reply = smart_trim(humanize(reply), 278)
            try:
                if reply_to_tweet(url, reply):
                    log_reply(url, reply, action_type="reply", source="BUDDY-BLITZ")
                    replies_done += 1
            except Exception:
                traceback.print_exc()
    log.info(f"[BTC-BLITZ] Done: {quotes_done} quotes, {replies_done} replies "
             f"(bestie + buddies: {', '.join(_buddy_handles())}).")


def safe_run_btc_blitz_cycle() -> None:
    from . import health
    try:
        run_btc_blitz_cycle()
        health.record_success("btc_blitz")
    except Exception:
        log.info("[BTC-BLITZ] outer error:")
        traceback.print_exc()
        health.record_failure("btc_blitz")

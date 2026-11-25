"""Thank the people who comment on our posts: one short Reply each.

Operator, 2026-11-25: "always reply 1 time when people reply on our posts ...
do it naturally like dont spam but do respond to all people commenting on our
posts. check my responses that I did manually recently to do similar things."

The mentions tab lists every reply to us. A comment is answered once, for ever
(Replied store); the browser proves it sits directly under one of our posts and
that we have not answered in that thread, so nobody gets a second turn.
"""
import time
from datetime import timedelta

from ..core import account, engagement_log, settings
from ..core.llm_client import Surface
from ..core.logger import log
from ..core.state_errors import StateUnreadable
from ..guards import reply_admission
from ..guards.active_hours import OutsideActiveHours, require_active
from ..x import scraper, twitter_client, x_urls
from . import reply_generator
from .reply_generator import LanguageRule, Outcome, ReplyCall

SOURCE = "THANKS"
PROMPT = """Someone commented on YOUR post. Answer them once, the way a creator who is glad they came by would.

Your post: "{original_tweet}"
Their comment (from @{author}): "{tweet_text}"

{thanks_style}
- Two to six words, one line, at most {max_words} words and {max_chars} characters. One emoji that fits their mood, at the end.
- Answer what THEY said: thank a compliment, share the laugh, answer a simple question about the post in a few words.
- Your last thank-yous were: {recent}. Do not reuse one of them; "Thanks" with a different emoji is not a new line.
- No link, no @mention, no hashtag, no question that asks for engagement, no invented personal detail
  (where you live, family, plans), no claim about anything you cannot see in the two texts above.
- If the comment is hostile, spam, political, sexual, an insult, or asks you to stop replying, output exactly: SKIP

Output ONLY the reply text, or SKIP."""

CALL = ReplyCall(PROMPT, Surface.REPLY, SOURCE, language=LanguageRule.ENGLISH, dossier=False, text_limit=600, timeout=40)
_done = {}  # comment URL -> monotonic time; disposable, the Replied store is the record
_reads = {}


def recent(limit=6):
    """The last thank-yous that shipped, newest first."""
    try:
        return tuple(engagement_log.recent_by_source(SOURCE, limit))
    except Exception:
        return ()


def _forget():
    now = time.monotonic()
    for store in (_done, _reads):
        for url, at in list(store.items()):
            if now - (at if store is _done else at[1]) > 86400:
                del store[url]


def hot(now=None):
    """Inside the first minutes after one of our video posts (Operator's coach, 2026-11-25:
    "first 30 minutes of a post, reply to every comment")."""
    minutes = settings.get("THANKS_HOT_MINUTES")
    if not minutes:
        return False
    try:
        from ..guards import active_hours
        from ..video import config as video_config
        stamp = now or active_hours.now_local()   # an aware datetime: a float raised and the fast pace never started
        last = video_config.legacy_usage(stamp)[1]
    except Exception:
        log.exception("[THANKS] Latest video post time unreadable; keeping the three-minute pace")
        return False
    return bool(last) and 0 <= stamp.timestamp() - last <= minutes * 60


_last_cycle = 0.0


def run_thanks_cycle():
    """Scheduled every minute: a full pass every three, every minute while a post is fresh."""
    global _last_cycle
    profile = account.current()
    if not profile.thank_commenters:
        return 0
    require_active()
    fresh = hot()
    if not fresh and time.monotonic() - _last_cycle < 170:
        return 0
    _last_cycle = time.monotonic()
    per_cycle = 10 if fresh else settings.get("THANKS_PER_CYCLE")
    _forget()
    mentions = scraper.scrape_mentions(max_tweets=30)
    maximum_age = timedelta(hours=settings.get("THANKS_MAX_AGE_HOURS"))
    shipped = reads = 0
    for tweet in mentions:
        if shipped >= per_cycle or reads >= 2 * per_cycle:
            break
        url = x_urls.canonical_status_url(tweet.get("url", ""))
        age = x_urls.age(url) if url else None
        if not url or url in _done or age is None or not timedelta(0) <= age <= maximum_age:
            continue
        verdict = reply_admission.judge_comment(url)
        if not verdict:
            if verdict.refusal.definitive:
                _done[url] = time.monotonic()
            continue
        # An unreadable page is retried on two later cycles, then left alone.
        tries = _reads.get(url, (0, 0))[0]
        if tries >= 3:
            _done[url] = time.monotonic()
            continue
        reads += 1
        _reads[url] = (tries + 1, time.monotonic())
        page = twitter_client.read_comment(url)
        if page.get("already_replied") or (page and not page.get("text", "").strip()):
            _done[url] = time.monotonic()
            continue
        if not page:
            continue  # a plain mention, a deeper thread, or a page that did not load
        previous = recent()
        generation = reply_generator.generate(CALL, author=verdict.author, text=page["text"], context=page["parent_text"], fields={
            "thanks_style": ("The Operator's style for these replies: " + profile.thanks_style) if profile.thanks_style else "",
            "recent": ", ".join(repr(text) for text in previous) or "none yet",
            "max_words": reply_admission.THANKS_MAX_WORDS, "max_chars": reply_admission.THANKS_MAX_CHARS})
        if generation.outcome is not Outcome.WRITTEN:
            if generation.outcome is Outcome.DECLINED:
                _done[url] = time.monotonic()  # the model declined this comment: never ask again
            continue
        try:
            outcome = twitter_client.thank_commenter(url, generation.text, expected_text=page["text"], recent=previous)
        except (OutsideActiveHours, StateUnreadable):
            raise
        except Exception:
            log.exception("[THANKS] Reply failed for %s", url)
            continue
        if outcome or outcome.value == "unconfirmed":
            _done[url] = time.monotonic()  # a spacing refusal or a failed step is tried again later
        if outcome:
            shipped += 1
            try:
                engagement_log.log_reply(url, generation.text, "reply", source=f"{SOURCE}/{verdict.author}",
                                         provider=generation.provider, model=generation.model, parent_text=page["text"])
            except Exception:
                log.exception("[THANKS] Engagement log failed for a shipped Reply %s", url)
    if shipped or reads:
        log.info("[THANKS] %d comment(s) read, %d thanked.", reads, shipped)
    return shipped

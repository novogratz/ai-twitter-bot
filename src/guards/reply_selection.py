"""Curated Reply evidence and short-text rules, checked again at final admission.

Evidence is disposable, never a publication claim. Restart requires a fresh read;
the permanent Reply journal and histories remain the authority on prior sends.
"""
from datetime import datetime, timedelta
import re
import time

from ..core import account, engagement_log, settings
from ..x import x_urls
from . import active_hours, content_guard, review_store

_profiles = {}
_sources = {}
HEART = re.compile("[❤♥♡💕💖💗💓💞💘💝💟🧡💛💚💙💜🤎🖤🤍🩷🩵🩶🫶]")
# Operator 2026-11-21: a thumbs up is a valid supportive reaction alongside
# hearts. One at most, never for watched authors, never a quota.
REACTION = re.compile("[👍]")


def enabled():
    return settings.get("REPLY_CURATED_MODE")


def broad():
    return enabled() and settings.get("REPLY_BROAD_DISCOVERY")


def minimum_likes():
    return max(5 if broad() else 20 if enabled() else 0, settings.get("REPLY_MIN_LIKES"))


def freshness_refusal(url):
    """The For You mode's ordinary-source deadline, independent of queue age."""
    if not broad() or not settings.get("REPLY_FOR_YOU_FIRST") or account.watched_url(url):
        return ""
    maximum = max(0, min(60, settings.get("DIRECT_REPLY_MAX_AGE_MINUTES")))
    canonical = x_urls.canonical_status_url(url)
    age = x_urls.age(canonical, active_hours.now_local()) if canonical else None
    if age is None or not timedelta(0) <= age <= timedelta(minutes=maximum):
        return f"ordinary source older than {maximum} minutes or unknown/future timestamp"
    return ""


_CREATIVE = re.compile(r"\b(?:slopcore|brainrot|art(?:ist|work)?|animation|animated|film|cinematic|music video|surreal|character|portrait)\b", re.I)
_SHARED_RESOURCE = re.compile(
    r"\b(?:roadmap|learning path|step[ -]?\d+|resources?|guides?|tutorials?|"
    r"checklists?|repositories|repository|repo|open[ -]source|datasets?|papers?)\b", re.I)
_PLAYFUL_COMPARISON = re.compile(
    r"(?P<subject>[a-z][a-z0-9]+(?:[ ._-][a-z0-9]+){0,3})\s*>\s*"
    r"(?:everyone|everything|the rest)\s*(?::[-]?[d)]|;[-]?\))", re.I)


def source_lane(url, text, source=""):
    from . import reply_intent
    if reply_intent.requests_advice(text):
        return "technical"
    if reply_intent._ROADMAP.search(text):
        return "share"
    if account.watched_url(url):
        return "share"
    if "CREATOR" in source or _CREATIVE.search(text):
        return "artist"
    return "share"


def profile(author, *, refresh=False):
    now = time.time()
    row = _profiles.get(author, {})
    if not 0 <= now - row.get("observed_at", 0) <= 21600:
        row = {}
    if not row and refresh:
        from ..x.profile_evidence import read
        for key, entry in list(_profiles.items()):
            if not 0 <= now - entry.get("observed_at", 0) <= 21600:
                del _profiles[key]
        if len(_profiles) >= 400:
            del _profiles[min(_profiles, key=lambda key: _profiles[key].get("observed_at", 0))]
        row = read(author)
        if row.get("handle") == author:
            _profiles[author] = row
    return row


def audience_refusal(author):
    followers = profile(author).get("followers")
    if type(followers) is not int:
        return "author follower count unavailable or expired"
    if followers < settings.get("REPLY_MIN_FOLLOWERS"):
        return "author below follower floor"
    return ""


def basic_refusal(url, text, *, source_language=""):
    from . import reply_intent
    if not x_urls.canonical_status_url(url) or x_urls.author(url) in account.own_handles():
        return "invalid or own source"
    if why := freshness_refusal(url):
        return why
    age = x_urls.age(url, active_hours.now_local())
    if age is None or not timedelta(0) <= age <= timedelta(hours=24):
        return "source older than 24 hours or unknown/future timestamp"
    outer = reply_intent.outer_text(text).replace("’", "'")
    if reply_intent.NO_BOTS.search(outer) or review_store.opted_out(x_urls.author(url)):
        return "author requested no bots or no contact"
    if reply_intent.BAIT.search(outer) or reply_intent._PROMOTION.search(outer):
        return "promotion or engagement bait"
    if account.current().engagement_niche_only and account.current().relevance.off_topic.search(outer):
        return "source matches the Account's excluded topics"
    # A trailing artist/tool credit is not a request directed at that account.
    direct = re.match(r"^(?:(?:hey|hi|hello|please)[,! ]+)?@", outer, re.I)
    if (direct or "?" in outer) and reply_intent._addressed_elsewhere(outer):
        return "addressed to another recipient"
    language = source_language or ((evidence(url, text).get("evidence") or {}).get("language", "") if broad() else "")
    ok, reason = content_guard.validate(outer, kind="source", source_language=language)
    return "" if ok else "source content refused: " + reason


def remember(url, text, lane, evidence=None):
    # Never extend a reviewed source's lifetime on rediscovery.
    now = time.time()
    for key, row in list(_sources.items()):
        if now - row["at"] > 1800:
            del _sources[key]
    if len(_sources) >= 400 and url not in _sources:
        del _sources[min(_sources, key=lambda k: _sources[k]["at"])]
    prior = _sources.get(url, {})
    if broad():
        lane = source_lane(url, text, "CREATOR" if lane == "artist" else "")
    _sources[url] = dict(text=text, lane=lane, evidence=evidence, at=prior.get("at", now))


def evidence(url, text):
    row = _sources.get(url, {})
    return row if row.get("text") == text and 0 <= time.time() - row.get("at", 0) <= 1800 else {}


def source_refusal(url, text):
    selected = {}
    if broad() and account.watched_url(url):
        from . import watch_curation
        selected = watch_curation.selected(url)
    language = selected.get("language", "") if selected.get("text") == text else ""
    if why := basic_refusal(url, text, source_language=language):
        return why
    if broad():
        if account.watched_url(url):
            if not selected or selected["text"] != text:
                return "watched source lacks a current exact selective topic review"
            return "" if account.watched_topic_allowed(text, url=url) else "watched source outside configured topics"
        return "" if account.matches_niche(text) else "Reply requires AI/SI topic evidence in this post"
    if why := audience_refusal(x_urls.author(url)):
        return why
    row = evidence(url, text)
    if not row:
        return "source lacks current curated selection evidence"
    if row["lane"] == "artist":
        from ..video.artist_review import valid
        media = row.get("evidence") or {}
        if account.watched_url(url) or not valid(media, url, text, media.get("media_id")):
            return "artist video lacks an exact approved visual review"
    elif row["lane"] != "technical" or not account.matches_niche(text):
        return "technical Reply requires AI/SI topic evidence in this post"
    return ""


def topic_allowed(url, text):
    return not source_refusal(url, text)


def page_refusal(url, text, page):
    if why := source_refusal(url, text):
        return why
    row = evidence(url, text)
    if broad():
        if account.watched_url(url):
            from . import watch_curation
            # 2026-11-25: the opened page's `text` also carries a quoted post's text, the review
            # holds the outer text only; every watched quote post was refused here. Compare outer with outer.
            if not watch_curation.reviewed({**page, "text": text}):
                return "selected watched source or media changed or its review expired"
        if not row:
            return "full source was not read before drafting"
        media_id = (row.get("evidence") or {}).get("media_id")
        if media_id and page.get("media_id") != media_id:
            return "source video changed or disappeared"
        return ""
    if row["lane"] == "artist" and (page.get("has_video") is not True
            or page.get("media_id") != row["evidence"]["media_id"]):
        return "reviewed video changed or disappeared"
    return ""


def recent_sends():
    from . import reply_budget
    return sorted(reply_budget.entries().values(), key=lambda row: datetime.fromisoformat(row["submitted_at"]), reverse=True)


def heart_allowed():
    # Unknown historical journal texts defer to the confirmed writing memory.
    # Operator 2026-11-21: warmer voice — two heartless sends between hearts.
    gap = 2
    recent = recent_sends()[:gap]
    return (not any(row.get("heart") for row in recent)
            and not any(HEART.search(text) for text in engagement_log.recent_replies(gap)))


def preferred_lane():
    lanes = [row.get("lane") for row in recent_sends()[:6]]
    # Search/queue preference only. No filler or forced alternating replies.
    return "technical" if lanes.count("artist") >= 4 else "artist"


def short_reply_limits(author=""):
    """The active account's concise ordinary/watched text bounds."""
    watched = broad() and author.lower().lstrip("@") in account.current().auto_engage_handles
    return min(90 if watched else 140, settings.get("REPLY_SHORT_MAX_CHARS")), 12 if watched else 24


def text_refusal(author, text, *, url=""):
    normalized = re.findall(r"\w+", text.casefold())
    if normalized and any(row.get("status") == "pending" and
            re.findall(r"\w+", row.get("text", "").casefold()) == normalized for row in recent_sends()[:100]):
        return "same wording as a recent unresolved Reply submission"
    if broad():
        characters, words = short_reply_limits(author)
        if not text.strip() or len(text) > characters or len(text.split()) > words or "\n" in text:
            return f"Reply must stay within {words} words and {characters} characters on one line"
        # Count an unfinished second sentence too; a terminal smiley or heart
        # is not another sentence. Decimal model versions remain one token.
        sentence_text = re.sub(r"(?<!\S)[:;]-?[)(dDpP](?=\s|$)", "", text)
        if sum(bool(re.search(r"\w", part)) for part in re.split(r"[.!?]+(?:\s+|$)", sentence_text)) > 1:
            return "Reply must be a few words or one short sentence"
    else:
        if len(text) > min(140, settings.get("REPLY_SHORT_MAX_CHARS")) or len(text.split()) > 24 or "\n" in text:
            return "Reply must be one short line, at most 24 words and 140 characters"
        if len(re.findall(r"[.!?](?:\s|$)", text)) > 1:
            return "Reply must be a few words or one sentence"
    hearts = HEART.findall(text)
    if url:
        lane = _sources.get(url, {}).get("lane")
        if broad() and lane == "share":
            if re.match(r"^(?:you (?:should|need|must)|try|check|make sure|remember|consider|use|test|learn|fit|avoid|start|add|actually|instead)\b", text, re.I):
                return "unsolicited advice or correction on a shared post"
        if not broad() and lane == "artist" and (len(text) > 90 or len(text.split()) > 12):
            return "artist reaction must stay within 12 words and 90 characters"
        if hearts and lane not in ("artist", "share"):
            return "hearts belong to artist reactions and warm share replies"
    if hearts and (author in account.current().auto_engage_handles or len(hearts) > 1 or not heart_allowed()):
        return "heart reserved for occasional warm reactions; recent sends already used one"
    thumbs = REACTION.findall(text)
    if thumbs and (author in account.current().auto_engage_handles or len(thumbs) > 1):
        return "one thumbs up at most, never for watched authors"
    return ""


def simple_reaction(url, text):
    """Source-bound language/length exceptions, never a drafting phrase bank."""
    if not broad() or not url:
        return False
    row = _sources.get(url, {})
    if not evidence(url, row.get("text", "")):
        return False
    if source_refusal(url, row["text"]):
        return False
    plain = REACTION.sub("", HEART.sub("", text)).replace("\ufe0f", "").strip()
    words = re.sub(r"[!.]", "", plain).casefold().strip()
    if account.watched_url(url):
        # Source-bound English exception, never a phrase rotation or technical fallback.
        return not HEART.search(text) and not REACTION.search(text) and words in {
            "facts", "agree", "agreed", "i agree", "exactly", "nice", "neat", "promising", "impressive", "handy", "useful", "cool",
            "nice upgrade", "useful upgrade", "nice addition",
        }
    from . import reply_intent
    outer = reply_intent.outer_text(row["text"])
    # A brief agreement can stand alone on a freshly read eligible statement.
    # This only scopes the language/minimum-length exception: drafting still
    # has to support the agreement, and all source/history gates still apply.
    if row.get("lane") == "share" and not HEART.search(text) and words in {
        "facts", "agree", "agreed", "i agree", "exactly", "fair enough", "so true",
    }:
        return True
    # Compact playful comparisons lack English function words. Bind the
    # subject to this original rather than globally treating brand names as
    # English. A rhetorical question may still carry a technical lane hint.
    comparison = _PLAYFUL_COMPARISON.fullmatch(text.strip()) if len(text) <= 60 else None
    if comparison:
        subject = comparison["subject"].strip()
        personal = {"me", "my", "mine", "you", "your", "yours", "we", "us", "our", "ours",
                    "it", "this", "that", "these", "those", "everyone", "everything", "all"}
        return (not set(subject.lower().split()) & personal
                and bool(re.search(r"(?<!\w)" + re.escape(subject) + r"(?!\w)", outer, re.I)))
    if row.get("lane") == "artist":
        # Operator 2026-11-21: "Love it!!" and a few warm reactions can be the
        # whole reply on an artistic slopcore post. Admission scope only, never
        # a drafting rotation; repetition checks still apply.
        return (not plain and len(HEART.findall(text)) + len(REACTION.findall(text)) == 1) or words in {
            "love it", "love this idea", "love the idea", "lovely idea", "fun idea",
            "love this concept", "love the concept", "lovely concept",
            "so good", "so cute", "love it so much", "love everything about this",
        }
    if row.get("lane") == "share" and _SHARED_RESOURCE.search(outer):
        return not HEART.search(text) and words in {
            "thanks for sharing", "thank you for sharing", "useful, thanks", "helpful, thanks",
            "cool, thanks for sharing", "thanks for putting this together",
        }
    return False


def draft_fields(url, text):
    import json
    row = evidence(url, text)
    media = row.get("evidence") or {}
    return {"lane": row.get("lane", source_lane(url, text)),
            "media_evidence": json.dumps(media.get("verdict", {}).get("observations", []), ensure_ascii=False),
            "heart_instruction": ("One heart (❤️, 💙, 🩷…) or one 👍 is optional when you feel it; never mandatory."
                if row.get("lane", source_lane(url, text)) in ("artist", "share") and heart_allowed()
                else "A single 👍 can fit; no heart in this reply.")}


def write_allowed(action, url):
    """The only extra X writes: exact configured watched authors' likes/reposts."""
    return (action in {"like", "retweet", "watch_repost"} and account.watched_url(url)
            and not review_store.opted_out(x_urls.author(url)))

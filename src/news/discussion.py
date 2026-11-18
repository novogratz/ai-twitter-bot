"""Occasional subjective questions, using the existing durable text publisher."""
from datetime import datetime, timezone
from difflib import SequenceMatcher
import json
import re
import time

from jsonschema import ValidationError, validate

from ..core import reply_wording, settings
from ..core.logger import log
from ..guards import content_guard, respect_list
from ..video.security import Deferred
from . import editor
from .adapters import Codex
from .config import load
from .store import Store, identity

REVIEW_FLAGS = ("question_only", "no_unsupported_claims", "natural", "english", "on_topic",
                "no_engagement_bait", "distinct_from_recent", "options_supported")
REVIEW = editor.obj({**{name: editor.BOOL for name in REVIEW_FLAGS}, "reason": editor.TEXT})


def draft_schema(cfg):
    return editor.obj({"topic": {"type": "string", "enum": cfg.discussion_topics},
                       "question": {"type": "string", "minLength": 20, "maxLength": 200},
                       "options": {"type": "array", "maxItems": 8 if cfg.discussion_models else 0,
                                   "items": {"type": "string",
                                   **({"enum": cfg.discussion_models} if cfg.discussion_models else {})}}})


def tweet(draft, cfg):
    """No fabricated model versions, URLs, numerical claims or mechanical truncation."""
    from twitter_text import parse_tweet, extract_urls_with_indices
    validate(draft, draft_schema(cfg))
    if len(set(draft["options"])) != len(draft["options"]):
        raise ValueError("discussion model choices must be unique")
    question = reply_wording.apply(draft["question"].strip(), kind="original")
    if (question.count("?") != 1 or not question.endswith("?")
            or any(c in question for c in "\r\n#—") or re.search(r"\d|https?://|@[\w]", question)):
        raise ValueError("discussion must be one subjective question without version or factual numbers")
    text = question
    if draft["options"]:
        text += "\n\n" + "\n".join("• " + name for name in draft["options"])
    weighted = parse_tweet(text)
    if not weighted.valid or weighted.weightedLength > 280 or extract_urls_with_indices(text):
        raise ValueError("discussion does not fit a complete source-free question")
    if not content_guard.validate(text, kind="original")[0] or respect_list.scrub_text_or_skip(text)[1]:
        raise ValueError("discussion content refused")
    return text, weighted.weightedLength


def cadence_refusal(store, cfg, now, *, exclude=""):
    rows = store.rows("""SELECT o.id,o.state,o.acknowledged,o.due FROM outbox o
        JOIN stories s ON s.id=o.story WHERE json_extract(s.document,'$.post_kind')='discussion'
        AND o.id!=? AND (o.state IN ('published','submitting','publish_unknown','delivered')
        OR (o.state='pending' AND o.expires>?))""", (exclude, now))
    for row in rows:
        if row["state"] in ("pending", "submitting", "publish_unknown"):
            return "another discussion is pending or uncertain"
        if now - (row["acknowledged"] or row["due"]) < cfg.discussion_interval_hours * 3600:
            return "discussion publication spacing"
    return ""


def repeated(store, text, *, exclude=""):
    normalized = " ".join(re.findall(r"\w+", text.split("\n\n", 1)[0].casefold()))
    # Exact copies stay blocked permanently; recent paraphrases also refuse.
    rows = store.rows("""SELECT id,document FROM stories
        WHERE json_extract(document,'$.post_kind')='discussion' AND id!=?
        ORDER BY updated DESC""", (exclude,))
    for index, row in enumerate(rows):
        previous = " ".join(re.findall(r"\w+", json.loads(row["document"]).get("text", "").split("\n\n", 1)[0].casefold()))
        if normalized == previous or (index < 50 and SequenceMatcher(None, normalized, previous).ratio() >= .8):
            return True
    return False


def admit(store, cfg, story, ident, text, now):
    if not settings.get("DISCUSSION_POSTS_ENABLED"):
        raise Deferred("discussion publishing disabled")
    expected, _ = tweet(story["draft"], cfg)
    if expected != text or identity(text) != story.get("reviewed_text_hash"):
        raise ValueError("reviewed discussion bytes changed")
    if not all(story.get("final_review", {}).get(name) is True for name in REVIEW_FLAGS):
        raise ValueError("discussion lacks independent approval")
    if not 0 <= now - story.get("verified_at", 0) <= 86400:
        raise ValueError("discussion review expired")
    if reason := cadence_refusal(store, cfg, now, exclude=ident):
        raise Deferred(reason)
    if repeated(store, text, exclude=ident):
        raise ValueError("discussion repeats a prior question")


def prepare(cfg=None, *, store=None, model=None, now=None):
    """Prepare only; the existing delivery tick owns all browser/publication work."""
    if not settings.get("NEWS_ENABLED") or not settings.get("DISCUSSION_POSTS_ENABLED"):
        return None
    cfg, store, now = cfg or load(), store or Store(), time.time() if now is None else now
    if not cfg.discussion_topics:
        return None
    try:
        with store.lock():
            # News and already approved work go first. An uncertain send never creates a replacement.
            if store.meta("startup_news", {}).get("state") == "pending":
                return None
            if store.rows("SELECT id FROM outbox WHERE state IN ('submitting','publish_unknown') OR (state='pending' AND expires>?) LIMIT 1", (now,)):
                return None
            if cadence_refusal(store, cfg, now) or now - store.meta("discussion_last_attempt", 0) < 3600:
                return None
            store.set_meta("discussion_last_attempt", now)
            from . import history
            history.context(store, cfg, now)
            recent = [json.loads(r["document"]).get("text", "") for r in store.rows(
                "SELECT document FROM stories WHERE json_extract(document,'$.post_kind')='discussion' ORDER BY updated DESC LIMIT 30")]
            model = model or Codex(store, cfg, now)
            draft = model.call("DISCUSSION_DRAFT", {"topics": cfg.discussion_topics,
                "model_families": cfg.discussion_models, "recent_questions": recent}, draft_schema(cfg))
            text, length = tweet(draft, cfg)
            if repeated(store, text) or content_guard.is_duplicate(text):
                return None
            review = model.call("DISCUSSION_REVIEW", {"tweet": text, "draft": draft,
                "model_families": cfg.discussion_models, "recent_questions": recent}, REVIEW)
            validate(review, REVIEW)
            if not all(review[k] for k in REVIEW_FLAGS):
                return None
            story = {"post_kind": "discussion", "event_key": "discussion:" + draft["topic"],
                "development": identity(editor.normalize(text)), "url": "", "title": draft["question"],
                "summary": text, "text": text, "draft": draft, "final_review": review,
                "reviewed_text_hash": identity(text), "verified_at": now}
            ident = store.remember(story, "verified", now)
            payload = {"id": ident, "role": "main", "kind": "discussion", "tweet": text,
                "weighted_characters": length, "display": text,
                "created_at": datetime.fromtimestamp(now, timezone.utc).isoformat()}
            store.enqueue(ident, "discussion:" + ident, payload, now)
            return payload
    except BlockingIOError:
        return None
    except (ValueError, ValidationError) as exc:
        log.info("[DISCUSSION] Draft refused: %s", str(exc)[:200])
        return None

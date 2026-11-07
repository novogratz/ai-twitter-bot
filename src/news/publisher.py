"""Hash-bound news publication, coexisting with the video reservation journal."""
from datetime import datetime, timedelta
import json
from pathlib import Path
import sqlite3
import time

from ..core import config, settings
from ..guards import action_guard
from ..video import config as video_config
from ..video.schedule import clocks
from ..video.security import Deferred
from ..video.store import DATABASE as VIDEO_DATABASE
from . import editor
from .adapters import Delivery
from .store import DATABASE, dumps, identity


def video_refusal(cfg, now):
    if not settings.get("VIDEO_ENABLED"):
        return ""
    gap = max(1200, cfg.video_gap_minutes * 60)
    vc = video_config.load()
    local = datetime.fromtimestamp(now, editor.TZ)
    for day in (-1, 0, 1):
        for clock in clocks(vc):
            hour, minute = map(int, clock.split(":"))
            due = (local + timedelta(days=day)).replace(hour=hour, minute=minute, second=0, microsecond=0).timestamp()
            if abs(now - due) < gap:
                return "protected video window"
    path = Path(str(VIDEO_DATABASE))
    if path.exists():
        with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
            if db.execute("SELECT 1 FROM reservations WHERE state IN ('reserved','uploading','submitting','publish_unknown')").fetchone():
                return "video publication reserved or uncertain"
            last = db.execute("SELECT MAX(confirmed) FROM reservations WHERE state='confirmed'").fetchone()[0]
            if last and now - last < gap:
                return "spacing after confirmed video"
    return ""


def video_hold(now, gap=1800):
    """Reciprocal check at the video's own final chokepoint; no DB creation."""
    path = Path(str(DATABASE))
    if not path.exists():
        return ""
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=2) as db:
        if db.execute("SELECT 1 FROM outbox WHERE state IN ('submitting','publish_unknown')").fetchone():
            return "news send unresolved"
        row = db.execute("SELECT MAX(acknowledged) FROM outbox WHERE state='published'").fetchone()
        if row[0] and now - row[0] < max(1200, gap):
            return "spacing after confirmed news"
    return ""


def admit(store, cfg, ident, now):
    if not settings.get("NEWS_ENABLED") or not settings.get("NEWS_AUTO_PUBLISH"):
        raise Deferred("automatic news publication disabled")
    from ..video.startup import waiting_reason
    if waiting_reason():
        raise Deferred("startup video still holds interactions")
    rows = store.rows("SELECT * FROM outbox WHERE id=?", (ident,))
    if not rows or rows[0]["state"] != "pending" or rows[0]["expires"] <= now:
        raise ValueError("news delivery is not pending and current")
    row = rows[0]
    payload = json.loads(row["payload"])
    if payload["role"] != "main":
        raise ValueError("only the main pick is authorized for automatic publication")
    story = json.loads(store.rows("SELECT document FROM stories WHERE id=?", (row["story"],))[0]["document"])
    if not all(story.get("final_review", {}).get(k) is True for k in editor.REVIEW_FLAGS):
        raise ValueError("missing independent final approval")
    if not 0 <= now - story.get("verified_at", 0) <= 86400:
        raise ValueError("news verification expired")
    if editor.tweet(story)[0] != payload["tweet"]:
        raise ValueError("reviewed news bytes changed")
    if identity(payload["tweet"]) != story.get("reviewed_text_hash"):
        raise ValueError("final review does not bind this text")
    if identity([{k: d.get(k) for k in ("url", "text", "dates")} for d in story.get("evidence", [])]) != story.get("evidence_hash"):
        raise ValueError("reviewed evidence changed")
    if editor.gate(story, story["evidence"], [], story["window_start"], now, cfg)[0] != "verified":
        raise ValueError("news evidence no longer passes verification")
    if store.rows("SELECT id FROM outbox WHERE state IN ('submitting','publish_unknown')"):
        raise Deferred("previous news send unresolved")
    local = datetime.fromtimestamp(now, editor.TZ)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    used = store.rows("SELECT COUNT(*) AS n FROM outbox WHERE state='published' AND acknowledged>=?", (midnight,))[0]["n"]
    if used >= config.posts_ceiling():
        raise Deferred("news daily ceiling reached")
    last = store.rows("SELECT MAX(acknowledged) AS at FROM outbox WHERE state='published'")[0]["at"]
    if last and now - last < settings.get("NEWS_MIN_SECONDS_BETWEEN_POSTS"):
        raise Deferred("news publication spacing")
    why = video_refusal(cfg, now)
    if why:
        raise Deferred(why)
    ok, why = action_guard.can_post(action_guard.POST, news=True)
    if not ok:
        raise Deferred(why)
    from ..editorial.slot_journal import FileJournal
    why = action_guard.profile_submission_refusal(FileJournal(), local)
    if why:
        raise Deferred(why)
    return payload


class SafariDelivery:
    def __init__(self, store, cfg):
        self.store, self.cfg = store, cfg
        self.drafts = Delivery(cfg)

    def send(self, ident, payload):
        if payload["role"] != "main":
            return self.drafts.send(ident, payload)
        from ..x.twitter_client import post_news
        from ..x.confirmed_write import WriteOutcome
        result = post_news(self.store, self.cfg, ident)
        row = self.store.rows("SELECT state,receipt FROM outbox WHERE id=?", (ident,))[0]
        if result is WriteOutcome.SHIPPED and row["state"] == "published":
            return json.loads(row["receipt"])
        if row["state"] in ("submitting", "publish_unknown"):
            raise RuntimeError("news send uncertain; automatic retry prohibited")
        raise Deferred("news write deferred: " + result.value)


def begin_submit(store, cfg, ident):
    now = time.time()
    admit(store, cfg, ident, now)
    with store.connect() as db:
        changed = db.execute("UPDATE outbox SET state='submitting',acknowledged=? WHERE id=? AND state='pending'", (now, ident)).rowcount
        if changed != 1:
            raise ValueError("news submission claim lost")
    return now


def confirmed(store, ident, url, now, *, reconcile=False):
    receipt = {"id": ident, "accepted": True, "post_url": url, "confirmed_at": now}
    with store.connect() as db:
        states = ("submitting", "publish_unknown") if reconcile else ("submitting", "submitting")
        changed = db.execute("UPDATE outbox SET state='published',receipt=?,acknowledged=?,error=NULL WHERE id=? AND state IN (?,?)",
                             (dumps(receipt), now, ident, *states)).rowcount
        if not changed:
            return None
        db.execute("UPDATE stories SET state='published' WHERE id=?", (ident,))
        from .startup import confirmed as confirm_startup
        confirm_startup(db, ident, url, now)
    return receipt

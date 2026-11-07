"""Durable startup intent; the existing outbox/publisher alone sends news."""
import json

from ..core import settings
from ..core.logger import log
from .store import dumps

KEY = "startup_news"


def request(store, request_id, now):
    if not settings.get("NEWS_ENABLED") or not settings.get("NEWS_AUTO_PUBLISH") or settings.get("DRY_RUN"):
        return None
    if not request_id or len(request_id) > 200:
        raise ValueError("stable startup news request ID required")
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT value FROM meta WHERE key=?", (KEY,)).fetchone()
        previous = json.loads(row[0]) if row else None
        if previous and (previous["state"] == "pending" or previous["request_id"] == request_id):
            return previous
        intent = {"request_id": request_id, "requested_at": now, "state": "pending"}
        db.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (KEY, dumps(intent)))
        return intent


def confirmed(db, ident, url, now):
    """Called in the same transaction as a verified own-X publication receipt."""
    row = db.execute("SELECT value FROM meta WHERE key=?", (KEY,)).fetchone()
    intent = json.loads(row[0]) if row else None
    if not intent or intent.get("state") != "pending" or now < intent["requested_at"]:
        return
    receipt = intent | {"state": "posted", "outbox_id": ident, "post_url": url, "confirmed_at": now}
    db.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (KEY, dumps(receipt)))
    db.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (KEY + ":" + intent["request_id"], dumps(receipt)))
    log.info("[STARTUP] News confirmed: %s", url)

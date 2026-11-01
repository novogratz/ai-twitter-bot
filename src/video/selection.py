"""Explicit one-clip choices, separate from automatic popularity/freshness ranking."""
import json
import math
from pathlib import Path

from .security import sha256
from .store import ASSETS, SAVED_ASSETS, dumps

KEY = "operator_video_selection"


def selected(doc, now):
    choice = doc.get("operator_selection", {})
    if not isinstance(choice, dict):
        return False
    start, expiry = choice.get("selected_at"), choice.get("expires_at")
    return bool(choice.get("scope") == "one_video" and choice.get("request_id")
        and doc.get("original_sha256") and choice.get("sha256") == doc["original_sha256"]
        and choice.get("source_id") == doc.get("source_id")
        and choice.get("canonical_url") == doc.get("canonical_url")
        and all(type(t) in (int, float) and math.isfinite(t) for t in (start, expiry))
        and start <= now < expiry <= start + 86400)


def choose(store, ident, request_id, now, *, dry_run=False):
    if not isinstance(request_id, str) or not request_id.strip() or len(request_id) > 200:
        raise ValueError("a stable explicit selection request ID is required")
    row = store.candidate(ident)
    if row["state"] in ("posted", "reserved", "duplicate"):
        raise ValueError("cannot select a posted, reserved or duplicate clip")
    doc = row["document"]
    original = Path(doc.get("original_path", "")).resolve(strict=True)
    roots = [(Path(str(root)) / ident).resolve() for root in (ASSETS, SAVED_ASSETS)]
    if (not original.is_file() or not any(original.is_relative_to(root) for root in roots)
            or sha256(original) != doc.get("original_sha256")):
        raise ValueError("selection requires the unchanged saved original")
    previous = doc.get("operator_selection", {})
    if previous.get("request_id") == request_id:
        if not selected(doc, now):
            raise ValueError("selection expired or original changed; use a new explicit request ID")
        return previous  # repeated commands never extend consent or enqueue twice
    choice = {"request_id": request_id, "scope": "one_video", "candidate": ident,
              "sha256": doc["original_sha256"], "source_id": doc["source_id"],
              "canonical_url": doc["canonical_url"], "selected_at": now, "expires_at": now + 86400}
    if dry_run:
        return choice | {"dry_run": True}
    with store.transaction() as db:
        if db.execute("SELECT 1 FROM reservations WHERE state IN ('reserved','uploading','submitting','publish_unknown')").fetchone():
            raise ValueError("finish or reconcile the active publication before changing selection")
        current = db.execute("SELECT state,document FROM candidates WHERE id=?", (ident,)).fetchone()
        current_doc = json.loads(current["document"])
        if (current["state"] in ("posted", "reserved", "duplicate")
                or current_doc.get("original_sha256") != choice["sha256"]
                or current_doc.get("original_path") != doc.get("original_path")):
            raise ValueError("candidate changed during selection")
        active = db.execute("SELECT value FROM meta WHERE key=?", (KEY,)).fetchone()
        old = json.loads(active[0]) if active else None
        if old and old["candidate"] != ident:
            other = db.execute("SELECT document,state FROM candidates WHERE id=?", (old["candidate"],)).fetchone()
            if other and other["state"] == "reserved":
                raise ValueError("the previous choice is already reserved")
            if other:
                other_doc = json.loads(other["document"])
                other_doc.pop("operator_selection", None)
                db.execute("UPDATE candidates SET document=? WHERE id=?", (dumps(other_doc), old["candidate"]))
        current_doc["operator_selection"] = choice
        db.execute("UPDATE candidates SET document=?,state='held',reason='explicit selection; verification pending',updated=? WHERE id=?",
                   (dumps(current_doc), now, ident))
        store.put_meta(db, KEY, choice)
        db.execute("INSERT INTO jobs(kind,item,due) VALUES('inspect_source',?,?) ON CONFLICT(kind,item) DO UPDATE SET "
                   "due=excluded.due,state=CASE WHEN jobs.state='running' THEN jobs.state ELSE 'pending' END,attempts=0", (ident, now))
        db.execute("INSERT INTO events(at,kind,item,detail) VALUES(?,?,?,?)",
                   (now, "operator_selection", ident, "Explicit clip choice bypasses automatic age/score selection only; all publication gates remain."))
    return choice

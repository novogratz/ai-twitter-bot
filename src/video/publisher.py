"""One durable slot owner. Ambiguous sends stay held until positive reconciliation."""
from datetime import datetime, timedelta, timezone
import json
import time
import uuid

from . import config, inventory, ranking, schedule
from .media import matches_history
from .security import sha256
from .store import dumps

ACTIVE = ("reserved", "uploading", "submitting", "publish_unknown")


def replace_deleted(store, post_id, request_id, now, cfg, *, operator_reports_deleted=False):
    """One explicit replacement, preserving the deleted receipt and its slot/day.

    An operator report is recorded as such, never as browser proof of deletion.
    Workers never call this function. The original claim/history are retained.
    """
    if not operator_reports_deleted or not request_id or not config.live() or not schedule.eligible(now):
        raise ValueError("explicit live replacement request and deletion report required")
    stamp = now.timestamp()
    with store.transaction() as db:
        prior = db.execute("SELECT value FROM meta WHERE key=?", ("replacement_of:" + post_id,)).fetchone()
        if prior:
            ident = json.loads(prior[0])["reservation"]
            return dict(db.execute("SELECT * FROM reservations WHERE id=?", (ident,)).fetchone())
        old = db.execute("SELECT * FROM reservations WHERE post_id=? AND state='confirmed'", (post_id,)).fetchone()
        if not old or db.execute("SELECT 1 FROM reservations WHERE state IN ('reserved','uploading','submitting','publish_unknown')").fetchone():
            raise ValueError("confirmed original required; finish any active publication first")
        candidate = db.execute("SELECT * FROM candidates WHERE id=?", (old["candidate"],)).fetchone()
        doc = json.loads(candidate["document"])
        recorded = db.execute("SELECT payload FROM history WHERE post_id=?", (post_id,)).fetchone()
        prior_doc = json.loads(recorded[0]) if recorded else {}
        if (prior_doc.get("output_sha256") != doc.get("output_sha256")
                or prior_doc.get("original_sha256") != doc.get("original_sha256")):
            raise ValueError("replacement must use the originally published reviewed asset")
        reason = ranking.gate(doc, cfg, stamp, final=True)
        if reason:
            raise ValueError(reason)
        if sha256(doc["output_path"]) != doc["output_sha256"]:
            raise ValueError("reviewed output changed")
        last = db.execute("SELECT MAX(confirmed) FROM reservations WHERE state='confirmed' AND id<>?", (old["id"],)).fetchone()[0]
        if last is not None and stamp - last < cfg.min_spacing_seconds:
            raise ValueError("spacing from another successful post")
        ident, token = uuid.uuid4().hex, uuid.uuid4().hex
        caption = ranking.caption(doc, cfg, stamp)
        midnight = datetime.combine(schedule.local(now).date() + timedelta(days=1), datetime.min.time(), schedule.ZONE).timestamp()
        db.execute("UPDATE reservations SET slot=NULL,startup=NULL WHERE id=?", (old["id"],))
        db.execute("INSERT INTO reservations(id,slot,startup,candidate,state,created,updated,deadline,token,lease,caption,transport) "
                   "VALUES(?,?,?,?,'reserved',?,?,?,?,?,?,?)", (ident, old["slot"], old["startup"], old["candidate"],
                   stamp, stamp, min(stamp + 600, midnight - 1), token,
                   stamp + cfg.lease_seconds, caption, old["transport"]))
        db.execute("UPDATE content_claims SET reservation=? WHERE candidate=?", (ident, old["candidate"]))
        db.execute("UPDATE candidates SET state='reserved' WHERE id=?", (old["candidate"],))
        db.execute("UPDATE slots SET state='reserved',reservation=? WHERE reservation=?", (ident, old["id"]))
        db.execute("UPDATE startup SET state='reserved',reservation=? WHERE reservation=?", (ident, old["id"]))
        db.execute("UPDATE startup_days SET reservation=? WHERE reservation=?", (ident, old["id"]))
        evidence = {"request_id": request_id, "reservation": ident, "replaces_reservation": old["id"],
                    "deleted_post_id": post_id, "operator_reports_deleted": True, "requested_at": stamp}
        store.put_meta(db, "replacement_of:" + post_id, evidence)
        store.put_meta(db, "replacement:" + ident, evidence)
        historical = db.execute("SELECT payload FROM history WHERE post_id=?", (post_id,)).fetchone()
        if historical:
            payload = json.loads(historical[0]) | {"deletion_status": "operator_reported_deleted", "replacement": evidence}
            db.execute("UPDATE history SET payload=? WHERE post_id=?", (dumps(payload), post_id))
        db.execute("INSERT INTO events(at,kind,item,detail) VALUES(?,'operator_requested_replacement',?,?)",
                   (stamp, old["candidate"], dumps(evidence)))
        return dict(db.execute("SELECT * FROM reservations WHERE id=?", (ident,)).fetchone())


def request_startup(store, request_id, now, cfg, *, explicit_live=False):
    if not explicit_live or not config.live():
        return None
    day = schedule.local(now).date().isoformat()
    with store.transaction() as db:
        old = db.execute("SELECT * FROM startup WHERE id=? OR requested_day=? OR state IN ('pending','reserved')",
                         (request_id, day)).fetchone()
        if old:
            return dict(old)
        db.execute("INSERT INTO startup(id,requested_day,requested) VALUES(?,?,?)", (request_id, day, now.timestamp()))
        from .preparation import recover_supply
        recover_supply(db, cfg, now.timestamp())
        for platform in config.PLATFORMS:
            db.execute("INSERT INTO jobs(kind,item,due) VALUES('discovery',?,?) ON CONFLICT(kind,item) "
                       "DO UPDATE SET due=excluded.due,state=CASE WHEN jobs.state='running' THEN jobs.state ELSE 'pending' END,attempts=0",
                       (platform, now.timestamp()))
        return {"id": request_id, "requested_day": day, "state": "pending"}


def tick_calendar(store, now, cfg):
    stamp = now.timestamp()
    with store.transaction() as db:
        scheduled = schedule.slots(schedule.local(now).date(), cfg)
        for key, at in scheduled:
            db.execute("INSERT OR IGNORE INTO slots(id,due) VALUES(?,?)", (key, at.timestamp()))
        expected = {key for key, _ in scheduled}
        for row in db.execute("SELECT id FROM slots WHERE state='pending'").fetchall():
            if row["id"].startswith(str(schedule.local(now).date()) + "/") and row["id"] not in expected:
                db.execute("UPDATE slots SET state='skipped',reason='schedule reconciled' WHERE id=?", (row["id"],))
        db.execute("UPDATE slots SET state='skipped',reason=CASE WHEN reason='' THEN 'grace expired; no catch-up' "
                   "ELSE reason || '; grace expired; no catch-up' END WHERE state='pending' AND due+?<?",
                   (cfg.grace_seconds, stamp))
        for request in db.execute("SELECT * FROM startup WHERE state='pending'").fetchall():
            requested = datetime.fromtimestamp(request["requested"], timezone.utc)
            if schedule.eligible_seconds(requested, now) >= cfg.startup_seconds:
                db.execute("UPDATE startup SET state='skipped',reason='eligible-time expiry' WHERE id=?", (request["id"],))


def reserve(store, now, cfg, *, operator_direct=False):
    """No network under the transaction; refreshed ready assets compete atomically."""
    tick_calendar(store, now, cfg)
    if not config.live() or not schedule.eligible(now):
        return None
    if store.meta("paused", True) or store.meta("shutdown", False):
        return None
    from .reconcile import history_ready
    if not history_ready(store, cfg) and not operator_direct:
        return None
    if not store.meta("account_verified", False):
        return None
    if store.meta("publish_retry_after", 0) > now.timestamp():
        return None
    stamp, day = now.timestamp(), schedule.local(now).date().isoformat()
    with store.transaction() as db:
        if db.execute("SELECT 1 FROM reservations WHERE state IN ('reserved','uploading','submitting','publish_unknown')").fetchone():
            return None
        slot = db.execute("SELECT * FROM slots WHERE state='pending' AND due<=? AND due+?>=? ORDER BY due LIMIT 1",
                          (stamp, cfg.grace_seconds, stamp)).fetchone()
        # Changing the slot configuration midday cannot create a second daily grid.
        consumed = db.execute("SELECT COUNT(*) FROM slots WHERE id LIKE ? AND state IN ('posted','reserved')", (day + "/%",)).fetchone()[0]
        if slot and consumed >= cfg.scheduled_daily_cap:
            db.execute("UPDATE slots SET state='skipped',reason='scheduled daily cap already committed' WHERE id=?", (slot["id"],))
            slot = None
        startup = db.execute("SELECT * FROM startup WHERE state='pending' ORDER BY requested LIMIT 1").fetchone()
        if slot and slot["attempts"] >= cfg.max_attempts:
            db.execute("UPDATE slots SET state='skipped',reason='bounded publishing retries exhausted' WHERE id=?", (slot["id"],))
            slot = None
        if startup and startup["attempts"] >= cfg.max_attempts:
            db.execute("UPDATE startup SET state='skipped',reason='bounded publishing retries exhausted' WHERE id=?", (startup["id"],))
            startup = None
        if startup and db.execute("SELECT 1 FROM startup_days WHERE day=?", (day,)).fetchone():
            db.execute("UPDATE startup SET state='skipped',reason='startup calendar-day cap' WHERE id=?", (startup["id"],))
            startup = None
        if not slot and startup:
            upcoming = schedule.next_slot(now, cfg)
            if upcoming and 0 <= upcoming[1].timestamp() - stamp <= cfg.min_spacing_seconds:
                return None  # due scheduled post satisfies both, never publish early
        if not slot and not startup:
            return None
        last = db.execute("SELECT MAX(confirmed) FROM reservations WHERE state='confirmed'").fetchone()[0]
        ready_at = (last + cfg.min_spacing_seconds) if last is not None else stamp
        if slot and ready_at > slot["due"] + cfg.grace_seconds:
            db.execute("UPDATE slots SET state='skipped',reason='actual spacing exceeds grace' WHERE id=?", (slot["id"],))
            slot = None
        if ready_at > stamp or (not slot and not startup):
            return None
        from .selection import KEY
        selection_row = db.execute("SELECT value FROM meta WHERE key=?", (KEY,)).fetchone()
        choice = json.loads(selection_row[0]) if selection_row else None
        # A direct operator request may publish one explicitly selected, reviewed
        # clip while older account media is still being backfilled. Never grant
        # this exception to normal scheduled/worker calls or another candidate.
        if operator_direct and (not choice or choice["expires_at"] <= stamp):
            return None
        if choice and choice["expires_at"] > stamp:
            rows = db.execute("SELECT * FROM candidates WHERE id=? AND state='ready' "
                              "AND id NOT IN (SELECT candidate FROM content_claims)", (choice["candidate"],)).fetchall()
            # An explicit first choice must not silently fall through to a different clip.
            if not rows:
                return None
        else:
            choice = None
            rows = db.execute("SELECT * FROM candidates WHERE state='ready' AND id NOT IN (SELECT candidate FROM content_claims) "
                              "ORDER BY score DESC,discovered LIMIT 80").fetchall()
        valid = []
        claimed = db.execute("SELECT c.document,c.fingerprint FROM candidates c JOIN content_claims p ON c.id=p.candidate").fetchall()
        history = [json.loads(row["payload"]) for row in db.execute("SELECT payload FROM history")]
        for candidate in rows:
            doc = json.loads(candidate["document"])
            reason = ranking.gate(doc, cfg, stamp, final=True)
            if choice and (choice["sha256"] != doc.get("original_sha256") or not ranking.selected(doc, stamp)):
                reason = "explicitly selected original changed or selection expired"
            if any(matches_history(doc, prior) for prior in history):
                reason = "video already in permanent posting history"
            for prior in claimed:
                previous = json.loads(prior["document"])
                if inventory.same_content((candidate, doc), (prior, previous)):
                    reason = "content already permanently reserved/published"
                    break
            if reason:
                db.execute("UPDATE candidates SET state='held',reason=? WHERE id=?", (reason, candidate["id"]))
            else:
                valid.append((candidate, doc))
        if not valid:
            if slot:
                db.execute("UPDATE slots SET reason='no eligible ready video' WHERE id=?", (slot["id"],))
            return None  # keep the slot open until grace; report final skip
        valid = inventory.distinct(valid)
        if cfg.protect_primary_windows and slot and not startup:
            primary = schedule.primary_slot(slot["id"], cfg)
            covered = db.execute("SELECT 1 FROM slots WHERE id=? AND state='posted'", (primary,)).fetchone()
            if primary != slot["id"] and covered:
                valid = inventory.surplus(valid, now, cfg)
                if not valid:
                    db.execute("UPDATE slots SET reason='inventory held for upcoming primary windows' WHERE id=?", (slot["id"],))
                    return None  # a replenished buffer can still use this slot within grace
        fresh = [(r, d) for r, d in valid if stamp - d["published_at"] <= cfg.preferred_age_hours * 3600]
        if fresh:
            valid = fresh
        elif not choice:
            # 2026-11-04: progressively older fallback, never choose a two-year
            # archive clip ahead of an eligible recent-week/month candidate.
            for days in (7, 30, 90, 365, 730):
                newer = [(r, d) for r, d in valid if stamp - d["published_at"] <= days * 86400]
                if newer:
                    valid = newer
                    break
        recent = [json.loads(r[0]) for r in db.execute("SELECT c.document FROM candidates c JOIN reservations r "
                  "ON r.candidate=c.id WHERE r.state='confirmed' ORDER BY r.confirmed DESC LIMIT 4")]
        top_score = valid[0][0]["score"] or 0
        comparable = valid if choice else [(r, d) for r, d in valid if (r["score"] or 0) >= top_score - 3]
        def repetition(pair):
            _, doc = pair
            return sum(2 * (d["creator"] == doc["creator"]) + (d["inspection"]["cast"] == doc["inspection"]["cast"])
                       + bool(d["inspection"].get("song") and d["inspection"].get("song") == doc["inspection"].get("song")) for d in recent)
        row, doc = min(comparable, key=repetition)
        ident, token = uuid.uuid4().hex, uuid.uuid4().hex
        remaining = cfg.startup_seconds - schedule.eligible_seconds(datetime.fromtimestamp(startup["requested"], timezone.utc), now) if startup else 0
        deadline = slot["due"] + cfg.grace_seconds if slot else stamp + remaining
        if startup:
            deadline = min(deadline, stamp + remaining)
        midnight = datetime.combine(schedule.local(now).date() + timedelta(days=1), datetime.min.time(), schedule.ZONE).timestamp()
        deadline = min(deadline, midnight - 1)
        caption = ranking.caption(doc, cfg, stamp)
        db.execute("INSERT INTO reservations(id,slot,startup,candidate,state,created,updated,deadline,token,lease,caption,transport) "
                   "VALUES(?,?,?,?,'reserved',?,?,?,?,?,?,?)", (ident, slot["id"] if slot else None,
                   startup["id"] if startup else None, row["id"], stamp, stamp, deadline, token, stamp + cfg.lease_seconds, caption, cfg.publishing_transport))
        db.execute("INSERT INTO content_claims VALUES(?,?)", (row["id"], ident))
        db.execute("UPDATE candidates SET state='reserved' WHERE id=?", (row["id"],))
        if operator_direct:
            db.execute("INSERT INTO events(at,kind,item,detail) VALUES(?,?,?,?)", (stamp,
                "operator_direct_publication", row["id"],
                "Explicit selected-video send; current imported history and source-identifier novelty checked. Older archive backfill remains incomplete."))
        if slot:
            db.execute("UPDATE slots SET state='reserved',reservation=?,attempts=attempts+1,reason='' WHERE id=?", (ident, slot["id"]))
        if startup:
            db.execute("UPDATE startup SET state='reserved',reservation=?,attempts=attempts+1 WHERE id=?", (ident, startup["id"]))
            db.execute("INSERT INTO startup_days VALUES(?,?,?)", (day, startup["id"], ident))
        return dict(db.execute("SELECT * FROM reservations WHERE id=?", (ident,)).fetchone())


def guard(store, ident, token, now, cfg, *, submitting=False):
    if not config.live() or not schedule.eligible(datetime.fromtimestamp(now, timezone.utc)):
        raise ValueError("video publishing disabled or overnight")
    if store.meta("paused", True) or store.meta("shutdown", False):
        raise ValueError("video publishing paused")
    from ..guards.active_hours import break_until, stop_requested
    if stop_requested() or break_until(datetime.fromtimestamp(now, timezone.utc)) is not None:
        raise ValueError("interaction break/shutdown")
    rows = store.rows("SELECT * FROM reservations WHERE id=? AND token=?", (ident, token))
    if not rows or rows[0]["state"] not in ("reserved", "uploading") or rows[0]["lease"] < now:
        raise ValueError("lost publishing lease")
    row = rows[0]
    if row["transport"] != cfg.publishing_transport:
        raise ValueError("reservation transport changed; recover it before switching")
    if now > row["deadline"]:
        raise ValueError("publication deadline passed")
    doc = store.candidate(row["candidate"])["document"]
    reason = ranking.gate(doc, cfg, now, final=True)
    if reason:
        raise ValueError(reason)
    if submitting:
        if now + 20 >= row["deadline"]:
            raise ValueError("insufficient request time before grace/cooldown deadline")
        if row["transport"] == "api":
            if not row["media_id"] or not row["media_expires"] or now + 30 >= row["media_expires"]:
                raise ValueError("upload expired or not ready")
        else:
            evidence = json.loads(row["browser_evidence"])
            if (not evidence.get("ready") or evidence.get("sha256") != doc["output_sha256"]
                    or not 0 <= now - evidence.get("checked_at", 0) <= 30):
                raise ValueError("Safari attachment readiness missing or stale")
        if sha256(doc["output_path"]) != doc["output_sha256"]:
            raise ValueError("asset changed after quality inspection")
    return row


def authorize_submit(store, ident, token, now, cfg):
    row = guard(store, ident, token, now, cfg, submitting=True)
    from ..guards import content_guard, respect_list
    ok, reason = content_guard.validate(row["caption"], kind="original")
    if not ok or respect_list.scrub_text_or_skip(row["caption"])[1]:
        raise ValueError("final caption content check refused")
    with store.transaction() as db:
        # Re-read switches and the success clock inside the final transaction.
        flags = {r[0]: json.loads(r[1]) for r in db.execute("SELECT key,value FROM meta WHERE key IN ('paused','shutdown')")}
        if flags.get("paused", True) or flags.get("shutdown", False):
            raise ValueError("video publishing paused")
        replacement = db.execute("SELECT value FROM meta WHERE key=?", ("replacement:" + ident,)).fetchone()
        excluded = json.loads(replacement[0])["replaces_reservation"] if replacement else ""
        last = db.execute("SELECT MAX(confirmed) FROM reservations WHERE state='confirmed' AND id<>?", (excluded,)).fetchone()[0]
        if last is not None and now - last < cfg.min_spacing_seconds:
            raise ValueError("actual success spacing")
        changed = db.execute("UPDATE reservations SET state='submitting',submitted=?,updated=?,attempts=attempts+1 "
                             "WHERE id=? AND token=? AND state IN ('reserved','uploading') AND lease>=? AND deadline>=?",
                             (now, now, ident, token, now, now)).rowcount
        if changed != 1:
            raise ValueError("reservation no longer owned")
    return row


def confirm(store, ident, token, now, post_id):
    with store.transaction() as db:
        row = db.execute("SELECT * FROM reservations WHERE id=? AND token=? AND state IN ('submitting','publish_unknown')",
                         (ident, token)).fetchone()
        if not row:
            raise ValueError("cannot confirm unknown reservation")
        url = "https://x.com/i/status/" + post_id
        db.execute("UPDATE reservations SET state='confirmed',confirmed=?,updated=?,post_id=?,post_url=?,reason='' WHERE id=?",
                   (now, now, post_id, url, ident))
        db.execute("UPDATE candidates SET state='posted' WHERE id=?", (row["candidate"],))
        db.execute("UPDATE slots SET state='posted' WHERE reservation=?", (ident,))
        db.execute("UPDATE startup SET state='posted' WHERE reservation=?", (ident,))
        from .selection import KEY
        selection_row = db.execute("SELECT value FROM meta WHERE key=?", (KEY,)).fetchone()
        if selection_row and json.loads(selection_row[0])["candidate"] == row["candidate"]:
            db.execute("DELETE FROM meta WHERE key=?", (KEY,))
        if row["startup"]:
            # A response spanning midnight conservatively occupies the receipt day.
            day = schedule.local(datetime.fromtimestamp(now, timezone.utc)).date().isoformat()
            db.execute("UPDATE startup_days SET day=? WHERE reservation=?", (day, ident))
        doc = json.loads(db.execute("SELECT document FROM candidates WHERE id=?", (row["candidate"],)).fetchone()[0])
        doc["caption"] = row["caption"]
        db.execute("UPDATE candidates SET document=? WHERE id=?", (dumps(doc), row["candidate"]))
        identity = {key: doc.get(key) for key in ("platform", "source_id", "creator", "original_sha256",
                    "output_sha256", "original_fingerprint", "output_fingerprint")}
        db.execute("INSERT OR IGNORE INTO history VALUES(?,?,?)", (post_id, now, dumps({"url": url, "candidate": row["candidate"],
                   **identity, "fingerprint": doc.get("output_fingerprint"),
                   "source_url": doc["canonical_url"], "caption": row["caption"],
                   "operator_selection": doc.get("operator_selection")})))


def unknown(store, ident, token, now, reason):
    with store.transaction() as db:
        db.execute("UPDATE reservations SET state='publish_unknown',reason=?,updated=? WHERE id=? AND token=? AND state='submitting'",
                   (reason, now, ident, token))


def fail_before_submit(store, ident, token, now, reason, *, rejected=False):
    with store.transaction() as db:
        row = db.execute("SELECT * FROM reservations WHERE id=? AND token=?", (ident, token)).fetchone()
        if not row or (row["state"] not in ("reserved", "uploading") and not (rejected and row["state"] == "submitting")):
            return False
        db.execute("UPDATE slots SET state='pending',reservation=NULL,reason=? WHERE reservation=?", (reason, ident))
        db.execute("UPDATE startup SET state='pending',reservation=NULL,reason=? WHERE reservation=?", (reason, ident))
        db.execute("DELETE FROM startup_days WHERE reservation=?", (ident,))
        db.execute("DELETE FROM content_claims WHERE reservation=?", (ident,))
        db.execute("UPDATE candidates SET state='ready' WHERE id=? AND state='reserved'", (row["candidate"],))
        db.execute("INSERT INTO events(at,kind,item,detail) VALUES(?,'pre_submit_failure',?,?)",
                   (now, ident, dumps({"slot": row["slot"], "startup": row["startup"], "reason": reason})))
        db.execute("UPDATE reservations SET state='failed',slot=NULL,startup=NULL,updated=?,reason=? WHERE id=?", (now, reason, ident))
        store.put_meta(db, "publish_retry_after", now + 60)
        return True


def recover(store, now):
    for row in store.rows("SELECT * FROM reservations WHERE state IN ('reserved','uploading','submitting') AND lease<?", (now,)):
        if row["state"] == "submitting":
            unknown(store, row["id"], row["token"], now, "worker died after durable submit intent")
        else:
            fail_before_submit(store, row["id"], row["token"], now, "abandoned before submit")


def publish_tick(store, cfg, *, now=None, client=None):
    now = now or schedule.utc_now()
    recover(store, now.timestamp())
    tick_calendar(store, now, cfg)
    if not config.live():
        return "dry-run"
    # Pure local refresh before selection; no download/model/search on this worker.
    if store.meta("next_score_refresh", 0) <= now.timestamp():
        for item in store.rows("SELECT id FROM candidates WHERE state IN ('ready','held') LIMIT 80"):
            candidate = store.candidate(item["id"])
            if not candidate["document"].get("qc"):
                continue
            doc = ranking.refresh(store, candidate, now.timestamp(), cfg)
            why = ranking.gate(doc, cfg, now.timestamp(), final=True)
            store.save_candidate(candidate["id"], doc, now.timestamp(), state="held" if why else "ready", reason=why,
                                 score=doc["ranking"]["total"], fingerprint=json.loads(candidate["fingerprint"]) if candidate["fingerprint"] else None)
        store.set_meta("next_score_refresh", now.timestamp() + 300)
    row = reserve(store, now, cfg)
    if not row:
        return "waiting"
    try:
        if client is None:
            if cfg.publishing_transport == "safari":
                from ..x.safari_video import SafariVideoClient
                client = SafariVideoClient(store, cfg)
            else:
                from ..x.video_client import XClient
                client = XClient(store, cfg)
        if cfg.publishing_transport == "safari":
            client.publish_reserved(row["id"], row["token"])
            return "attempted"
        client.preflight(publishing=True, force=False)
        def check():
            guard(store, row["id"], row["token"], time.time(), cfg)
        def checkpoint(media_id, media_key, expires):
            with store.transaction() as db:
                if db.execute("UPDATE reservations SET state='uploading',media_id=?,media_key=?,media_expires=?,updated=? "
                              "WHERE id=? AND token=? AND state IN ('reserved','uploading')", (media_id, media_key, expires,
                              time.time(), row["id"], row["token"])).rowcount != 1:
                    raise ValueError("upload lease lost")
        doc = store.candidate(row["candidate"])["document"]
        check()
        client.upload(doc["output_path"], checkpoint, check)
        client.publish_reserved(row["id"], row["token"])
    except Exception:
        # This cannot release a submitting/unknown claim, even if confirmation persistence failed.
        fail_before_submit(store, row["id"], row["token"], time.time(), "pre-submit upload/admission failure")
    return "attempted"

"""Prepare before a due window; persist work and warn before supply becomes late."""
from datetime import datetime, timedelta, timezone
import json

from ..core.logger import log
from . import schedule
from .store import dumps


def maintain_reserve(store, cfg, now):
    """Keep real eligible inventory and expiring X checks moving between slots."""
    if not cfg.adaptive_discovery:
        return
    with store.transaction() as db:
        last = db.execute("SELECT value FROM meta WHERE key='reserve-maintained-at'").fetchone()
        if last and now - json.loads(last[0]) < 300:
            return
        store.put_meta(db, "reserve-maintained-at", now)
    from . import inventory, memory, ranking
    from .handoff import build
    from .reconcile import preparation_reason
    memory.import_seed(store, cfg, now)
    for item in store.rows("SELECT id FROM candidates WHERE state IN ('ready','held') "
                           "AND json_extract(document,'$.qc') IS NOT NULL "
                           "AND id NOT IN (SELECT candidate FROM content_claims) "
                           "AND id NOT IN (SELECT item FROM jobs WHERE state='running') ORDER BY updated LIMIT 80"):
        row = store.candidate(item["id"])
        doc = ranking.refresh(store, row, now, cfg)
        why = memory.refusal(store, doc) or ranking.gate(doc, cfg, now, final=True)
        check = doc.get("novelty", {})
        refresh = (check.get("state") in ("checked_no_match", "verified_low_reach_match", "unknown_or_stale")
                   and now - check.get("checked_at", 0) >= cfg.x_reach_max_age_seconds - 1800)
        if refresh and not memory.refusal(store, doc) and not preparation_reason(doc, cfg, now):
            with store.transaction() as db:
                db.execute("INSERT INTO jobs(kind,item,due) VALUES('novelty',?,?) ON CONFLICT(kind,item) "
                           "DO UPDATE SET state='pending',due=excluded.due WHERE jobs.state='done'", (row["id"], now))
        doc["handoff"] = build(store, row, doc, cfg, now)
        why = why or doc["handoff"]["hold_reason"]
        store.save_candidate(row["id"], doc, now, state="held" if why else "ready", reason=why,
                             score=doc["ranking"]["total"], fingerprint=json.loads(row["fingerprint"]) if row["fingerprint"] else None)
    coverage = inventory.report(store, cfg, datetime.fromtimestamp(now, timezone.utc))
    ready = coverage["eligible_distinct"]
    store.set_meta("reserve-health", {"checked_at": now, "eligible_distinct": ready,
                   "minimum": cfg.ready_reserve_min, "target": cfg.buffer_target,
                   "shortfall": max(0, cfg.ready_reserve_min - ready)})
    if ready < cfg.ready_reserve_min:
        # Bring source polls forward; admission still enforces caches, circuits,
        # hourly calls and daily budgets. Never reset failed media retry counts.
        for platform, options in cfg.platforms.items():
            if not options.get("enabled", True) or store.meta("platform_disabled:" + platform, False):
                continue
            with store.transaction() as db:
                db.execute("INSERT INTO jobs(kind,item,due) VALUES('discovery',?,?) ON CONFLICT(kind,item) "
                           "DO UPDATE SET due=MIN(due,excluded.due),state='pending' "
                           "WHERE jobs.state IN ('done','pending')", (platform, now))
        store.event(now, "reserve_shortfall", "video", f"{ready}/{cfg.ready_reserve_min} eligible; discovery continues without lowering quality")


def recover_supply(db, cfg, now):
    """New preparation/startup can retry held work, preserving all posting claims."""
    # A widened fallback window can recover formerly age-expired leads. Derived
    # files may be gone: the normal media path must download and inspect again.
    db.execute("UPDATE candidates SET state='held',reason='age policy changed; reinspection required' "
               "WHERE state='expired' AND reason='freshness expired' AND published>=? AND published<=? "
               "AND id NOT IN (SELECT candidate FROM content_claims)",
               (now - cfg.max_age_hours * 3600, now))
    db.execute("UPDATE jobs SET state='pending',due=?,attempts=0 "
               "WHERE kind IN ('media','novelty','inspect_source','inspect_output') AND state='dead' "
               "AND item IN (SELECT id FROM candidates WHERE state='held') "
               "AND item NOT IN (SELECT candidate FROM content_claims)", (now,))
    if cfg.auto_edit:
        # A material editing/cast change permits ONE new preparation of saved,
        # unclaimed sources. Completed refusals under this policy stay completed.
        from .editing import policy_revision
        revision = policy_revision(cfg)
        for row in db.execute("SELECT id,document FROM candidates WHERE state='held' "
                              "AND published>=? AND published<=? AND id NOT IN (SELECT candidate FROM content_claims)",
                              (now - cfg.max_age_hours * 3600, now)).fetchall():
            doc = json.loads(row["document"])
            if doc.get("editing_policy_revision") == revision:
                continue
            if db.execute("SELECT 1 FROM jobs WHERE item=? AND state='running'", (row["id"],)).fetchone():
                continue
            doc["editing_policy_revision"] = revision
            db.execute("UPDATE candidates SET document=? WHERE id=?", (dumps(doc), row["id"]))
            # A new plan is a new job kind of work, not permission to reset a
            # previously exhausted transient-error allowance.
            db.execute("INSERT INTO jobs(kind,item,due) VALUES('media',?,?) ON CONFLICT(kind,item) DO UPDATE SET "
                       "state='pending',due=excluded.due WHERE jobs.state='done'", (row["id"], now))


def prepare_upcoming(store, cfg, now):
    stamp = datetime.fromtimestamp(now, timezone.utc)
    for day in (schedule.local(stamp).date(), schedule.local(stamp).date() + timedelta(days=1)):
        for ident, due in schedule.slots(day, cfg):
            remaining = due.timestamp() - now
            if not 0 <= remaining <= cfg.preparation_lead_seconds:
                continue
            key = "preparation:" + ident
            with store.transaction() as db:
                if not db.execute("SELECT 1 FROM meta WHERE key=?", (key,)).fetchone():
                    store.put_meta(db, key, {"started": now, "due": due.timestamp()})
                    for platform in cfg.platforms:
                        db.execute("INSERT INTO jobs(kind,item,due) VALUES('discovery',?,?) ON CONFLICT(kind,item) "
                                   "DO UPDATE SET due=MIN(due,excluded.due),state=CASE WHEN jobs.state='running' "
                                   "THEN jobs.state ELSE 'pending' END,attempts=CASE WHEN jobs.state='running' THEN jobs.attempts ELSE 0 END",
                                   (platform, now))
                    # Only a fresh preparation window retries bounded failed media work.
                    # The inspector/rights/novelty checks still decide eligibility.
                    recover_supply(db, cfg, now)
                    db.execute("INSERT INTO events(at,kind,item,detail) VALUES(?,?,?,?)",
                               (now, "preparation_started", ident, "Discovery/media queued before the due window"))
            checkpoint = "30m" if remaining > 900 else "15m" if remaining > 300 else "5m"
            warning_key = key + ":" + checkpoint
            with store.transaction() as db:
                ready = db.execute("SELECT COUNT(*) FROM candidates WHERE state='ready'").fetchone()[0]
                if ready or db.execute("SELECT 1 FROM meta WHERE key=?", (warning_key,)).fetchone():
                    continue
                store.put_meta(db, warning_key, now)
                db.execute("INSERT INTO events(at,kind,item,detail) VALUES(?,?,?,?)",
                           (now, "supply_warning", ident, dumps({"ready": ready, "seconds_remaining": round(remaining)})))
            log.warning("[VIDEO] %s due in %s minutes: no ready video; preparation is active.", ident, round(remaining / 60))

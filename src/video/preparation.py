"""Prepare before a due window; persist work and warn before supply becomes late."""
from datetime import datetime, timedelta, timezone

from ..core.logger import log
from . import schedule
from .store import dumps


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

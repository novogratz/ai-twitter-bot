"""Process-safe WAL journal. Publication uncertainty and provenance never expire."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import uuid

from ..core import state_store

DATABASE = state_store.StatePath("video_pipeline.sqlite3")
ASSETS = state_store.StatePath("video_assets")
SAVED_ASSETS = state_store.StatePath("video_saved_assets")
SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS candidates(
 id TEXT PRIMARY KEY, platform TEXT NOT NULL, source_id TEXT NOT NULL, canonical_url TEXT NOT NULL UNIQUE,
 creator TEXT NOT NULL, published REAL, discovered REAL NOT NULL, updated REAL NOT NULL,
 state TEXT NOT NULL DEFAULT 'discovered', reason TEXT NOT NULL DEFAULT '', document TEXT NOT NULL,
 fingerprint TEXT, score REAL, UNIQUE(platform,source_id));
CREATE TABLE IF NOT EXISTS observations(candidate TEXT, observed REAL, payload TEXT NOT NULL,
 PRIMARY KEY(candidate,observed));
CREATE TABLE IF NOT EXISTS jobs(
 id INTEGER PRIMARY KEY, kind TEXT NOT NULL, item TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
 due REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, owner TEXT, lease REAL, token TEXT,
 error TEXT NOT NULL DEFAULT '', UNIQUE(kind,item));
CREATE TABLE IF NOT EXISTS workers(role TEXT PRIMARY KEY, owner TEXT, heartbeat REAL, detail TEXT);
CREATE TABLE IF NOT EXISTS startup(
 id TEXT PRIMARY KEY, requested_day TEXT NOT NULL UNIQUE, requested REAL NOT NULL,
 state TEXT NOT NULL DEFAULT 'pending', reservation TEXT, reason TEXT NOT NULL DEFAULT '', attempts INTEGER NOT NULL DEFAULT 0);
CREATE UNIQUE INDEX IF NOT EXISTS one_pending_startup ON startup((1)) WHERE state IN ('pending','reserved');
CREATE TABLE IF NOT EXISTS startup_days(day TEXT PRIMARY KEY, request TEXT UNIQUE, reservation TEXT UNIQUE);
CREATE TABLE IF NOT EXISTS slots(
 id TEXT PRIMARY KEY, due REAL NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
 reservation TEXT, reason TEXT NOT NULL DEFAULT '', attempts INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS reservations(
 id TEXT PRIMARY KEY, slot TEXT UNIQUE, startup TEXT UNIQUE, candidate TEXT NOT NULL,
 state TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL, deadline REAL NOT NULL,
 token TEXT NOT NULL, lease REAL NOT NULL, caption TEXT NOT NULL, media_id TEXT, media_key TEXT,
 media_expires REAL, submitted REAL, network_started REAL, confirmed REAL, post_id TEXT UNIQUE, post_url TEXT,
 reason TEXT NOT NULL DEFAULT '', attempts INTEGER NOT NULL DEFAULT 0,
 transport TEXT NOT NULL DEFAULT 'api', browser_evidence TEXT NOT NULL DEFAULT '{}');
CREATE UNIQUE INDEX IF NOT EXISTS one_publisher ON reservations((1))
 WHERE state IN ('reserved','uploading','submitting','publish_unknown');
CREATE TABLE IF NOT EXISTS content_claims(candidate TEXT PRIMARY KEY, reservation TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS history(post_id TEXT PRIMARY KEY, published REAL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS costs(day TEXT, provider TEXT, kind TEXT, amount REAL NOT NULL,
 PRIMARY KEY(day,provider,kind));
CREATE TABLE IF NOT EXISTS circuits(provider TEXT PRIMARY KEY, failures INTEGER NOT NULL, until REAL NOT NULL);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, at REAL, kind TEXT, item TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS reply_samples(id INTEGER PRIMARY KEY, at REAL, phase TEXT, seconds REAL, backlog INTEGER);
CREATE TABLE IF NOT EXISTS model_calls(id TEXT PRIMARY KEY, provider TEXT, started REAL, lease REAL, finished REAL);
CREATE TABLE IF NOT EXISTS outcomes(post_id TEXT, window INTEGER, observed REAL, payload TEXT,
 PRIMARY KEY(post_id,window));
"""


def dumps(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


class Store:
    def __init__(self, path=None, *, timeout=2):
        self.path = Path(path or str(DATABASE))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        db = self.connect()
        try:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, 2):
                raise ValueError("unsupported video database version; do not reset posting history")
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(SCHEMA)
            # Additive migration: existing upload IDs, claims and unknown sends
            # stay intact. Historical reservations remain on their API transport.
            db.execute("BEGIN IMMEDIATE")
            try:
                columns = {r[1] for r in db.execute("PRAGMA table_info(reservations)")}
                if "transport" not in columns:
                    db.execute("ALTER TABLE reservations ADD COLUMN transport TEXT NOT NULL DEFAULT 'api'")
                if "browser_evidence" not in columns:
                    db.execute("ALTER TABLE reservations ADD COLUMN browser_evidence TEXT NOT NULL DEFAULT '{}'")
                db.execute("PRAGMA user_version=2")
                db.commit()
            except BaseException:
                db.rollback()
                raise
        finally:
            db.close()

    def connect(self):
        db = sqlite3.connect(self.path, timeout=self.timeout, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA synchronous=FULL")
        db.execute("PRAGMA foreign_keys=ON")
        return db

    @contextmanager
    def transaction(self):
        db = self.connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def rows(self, sql, args=()):
        db = self.connect()
        try:
            return [dict(r) for r in db.execute(sql, args)]
        finally:
            db.close()

    def meta(self, key, default=None):
        rows = self.rows("SELECT value FROM meta WHERE key=?", (key,))
        return json.loads(rows[0]["value"]) if rows else default

    def set_meta(self, key, value):
        with self.transaction() as db:
            self.put_meta(db, key, value)

    @staticmethod
    def put_meta(db, key, value):
        db.execute("INSERT INTO meta VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                   (key, dumps(value)))

    def event(self, now, kind, item, detail):
        with self.transaction() as db:
            db.execute("INSERT INTO events(at,kind,item,detail) VALUES(?,?,?,?)", (now, kind, item, detail))

    def enqueue(self, kind, item, now):
        with self.transaction() as db:
            db.execute("INSERT OR IGNORE INTO jobs(kind,item,due) VALUES(?,?,?)", (kind, item, now))

    def claim(self, kind, owner, now, cfg):
        with self.transaction() as db:
            db.execute("UPDATE jobs SET state='dead',error='retry limit' WHERE kind=? AND attempts>=? "
                       "AND (state='pending' OR (state='running' AND lease<?))", (kind, cfg.max_attempts, now))
            row = db.execute("SELECT * FROM jobs WHERE kind=? AND attempts<? AND "
                             "((state='pending' AND due<=?) OR (state='running' AND lease<?)) "
                             "ORDER BY due,id LIMIT 1", (kind, cfg.max_attempts, now, now)).fetchone()
            if not row:
                return None
            token = uuid.uuid4().hex
            db.execute("UPDATE jobs SET state='running',owner=?,lease=?,token=?,attempts=attempts+1 WHERE id=?",
                       (owner, now + cfg.lease_seconds, token, row["id"]))
            return dict(row) | {"token": token, "attempts": row["attempts"] + 1}

    def finish(self, job, now, *, error="", repeat=None):
        with self.transaction() as db:
            state = "pending" if error or repeat is not None else "done"
            due = now + (min(3600, 30 * 2 ** job["attempts"]) if error else (repeat or 0))
            return db.execute("UPDATE jobs SET state=?,due=?,lease=NULL,error=?,attempts=? "
                              "WHERE id=? AND token=? AND state='running' AND lease>=?",
                              (state, due, error, job["attempts"] if error else 0, job["id"], job["token"], now)).rowcount == 1

    def heartbeat(self, role, owner, now, detail="idle"):
        with self.transaction() as db:
            db.execute("INSERT INTO workers VALUES(?,?,?,?) ON CONFLICT(role) DO UPDATE SET "
                       "owner=excluded.owner,heartbeat=excluded.heartbeat,detail=excluded.detail",
                       (role, owner, now, detail))

    def candidate(self, ident):
        rows = self.rows("SELECT * FROM candidates WHERE id=?", (ident,))
        if not rows:
            raise KeyError(ident)
        row = rows[0]
        row["document"] = json.loads(row["document"])
        return row

    def save_candidate(self, ident, document, now, *, state, reason="", score=None, fingerprint=None, job=None):
        with self.transaction() as db:
            if job and not db.execute("SELECT 1 FROM jobs WHERE id=? AND token=? AND state='running' AND lease>=?",
                                      (job["id"], job["token"], now)).fetchone():
                raise RuntimeError("media lease lost; stale worker cannot commit")
            db.execute("UPDATE candidates SET document=?,updated=?,state=?,reason=?,score=?,fingerprint=? "
                       "WHERE id=? AND state NOT IN ('reserved','posted','rejected')",
                       (dumps(document), now, state, reason, score, dumps(fingerprint) if fingerprint else None, ident))

    def budget(self, provider, kind, amount, limit, now):
        from .schedule import local
        day = local(datetime.fromtimestamp(now, timezone.utc)).date().isoformat()
        with self.transaction() as db:
            spent = db.execute("SELECT COALESCE(SUM(amount),0) FROM costs WHERE day=? AND kind=?", (day, kind)).fetchone()[0]
            if spent + amount > limit:
                return False
            db.execute("INSERT INTO costs VALUES(?,?,?,?) ON CONFLICT(day,provider,kind) DO UPDATE "
                       "SET amount=amount+excluded.amount", (day, provider, kind, amount))
            return True

    def refund_budget(self, provider, kind, amount, now):
        """Release an unused byte reservation; observed consumption stays recorded."""
        from .schedule import local
        day = local(datetime.fromtimestamp(now, timezone.utc)).date().isoformat()
        if amount <= 0:
            return
        with self.transaction() as db:
            db.execute("UPDATE costs SET amount=MAX(0,amount-?) WHERE day=? AND provider=? AND kind=?",
                       (amount, day, provider, kind))

    def circuit_ready(self, provider, now):
        rows = self.rows("SELECT until FROM circuits WHERE provider=?", (provider,))
        return not rows or rows[0]["until"] <= now

    def circuit(self, provider, now, *, failed, retry_after=0):
        with self.transaction() as db:
            row = db.execute("SELECT failures FROM circuits WHERE provider=?", (provider,)).fetchone()
            failures = ((row[0] if row else 0) + 1) if failed else 0
            delay = max(retry_after, min(3600, 30 * 2 ** min(failures, 7))) if failed else 0
            db.execute("INSERT INTO circuits VALUES(?,?,?) ON CONFLICT(provider) DO UPDATE "
                       "SET failures=excluded.failures,until=excluded.until", (provider, failures, now + delay))

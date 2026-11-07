"""Permanent event history, evidence, operational coverage and delivery outbox."""
from contextlib import contextmanager
from datetime import datetime
import fcntl
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from zoneinfo import ZoneInfo

from ..core.state_store import StatePath

DATABASE = StatePath("news.sqlite3")
INBOX = StatePath("news_inbox")
LOCK = StatePath("news.lock")


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def identity(value):
    return hashlib.sha256(dumps(value).encode()).hexdigest()[:32]


class Store:
    def __init__(self, path=None):
        self.path = Path(path or str(DATABASE))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            if db.execute("PRAGMA user_version").fetchone()[0] not in (0, 1):
                raise ValueError("unsupported news database version; preserve history")
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, started REAL, finished REAL,
                    window_start REAL, status TEXT, errors TEXT);
                CREATE TABLE IF NOT EXISTS leads(url TEXT PRIMARY KEY, title TEXT, discovered REAL,
                    checked REAL DEFAULT 0, document TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS stories(id TEXT PRIMARY KEY, event_key TEXT, development TEXT,
                    url TEXT, title TEXT, state TEXT, document TEXT NOT NULL, updated REAL,
                    UNIQUE(event_key, development));
                CREATE INDEX IF NOT EXISTS stories_url ON stories(url);
                CREATE VIRTUAL TABLE IF NOT EXISTS memory USING fts5(id UNINDEXED, text);
                CREATE TABLE IF NOT EXISTS outbox(id TEXT PRIMARY KEY, story TEXT UNIQUE, run TEXT,
                    payload TEXT NOT NULL, state TEXT DEFAULT 'pending', attempts INTEGER DEFAULT 0,
                    due REAL, expires REAL, receipt TEXT, acknowledged REAL, error TEXT);
                CREATE TABLE IF NOT EXISTS cache(url TEXT PRIMARY KEY, expires REAL, document TEXT);
                CREATE TABLE IF NOT EXISTS circuits(url TEXT PRIMARY KEY, until REAL);
                CREATE TABLE IF NOT EXISTS costs(day TEXT, kind TEXT, amount INTEGER,
                    PRIMARY KEY(day, kind));
                CREATE TABLE IF NOT EXISTS coverage(name TEXT PRIMARY KEY, status TEXT, detail TEXT, at REAL);
                PRAGMA user_version=1;
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @contextmanager
    def lock(self):
        # Whole-run OS lock also fences manual runs and a second scheduler.
        with self.path.with_suffix(".lock").open("a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def rows(self, sql, args=()):
        with self.connect() as db:
            return [dict(r) for r in db.execute(sql, args)]

    def execute(self, sql, args=()):
        with self.connect() as db:
            db.execute(sql, args)

    def meta(self, key, default=None):
        rows = self.rows("SELECT value FROM meta WHERE key=?", (key,))
        return json.loads(rows[0]["value"]) if rows else default

    def set_meta(self, key, value):
        self.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (key, dumps(value)))

    def charge(self, kind, amount, limit, now):
        day = datetime.fromtimestamp(now, ZoneInfo("America/Toronto")).date().isoformat()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT amount FROM costs WHERE day=? AND kind=?", (day, kind)).fetchone()
            used = row[0] if row else 0
            if used + amount > limit:
                raise RuntimeError(f"news {kind} daily budget exhausted")
            db.execute("INSERT OR REPLACE INTO costs VALUES (?,?,?)", (day, kind, used + amount))

    def coverage(self, name, status, detail, now):
        self.execute("INSERT OR REPLACE INTO coverage VALUES (?,?,?,?)", (name, status, detail, now))

    def lead(self, doc, now):
        self.execute("""INSERT INTO leads(url,title,discovered,document) VALUES (?,?,?,?)
            ON CONFLICT(url) DO UPDATE SET title=excluded.title,document=excluded.document""",
            (doc["url"], doc["title"], now, dumps(doc)))

    def remember(self, doc, state, now):
        key = identity([doc["event_key"], doc["development"]])
        with self.connect() as db:
            # Delivery/acknowledgement history must never be downgraded by rediscovery.
            old = db.execute("SELECT state FROM stories WHERE id=?", (key,)).fetchone()
            if old and old[0] in ("queued", "delivered", "acknowledged", "published", "publish_unknown"):
                return key
            db.execute("INSERT OR REPLACE INTO stories VALUES (?,?,?,?,?,?,?,?)",
                       (key, doc["event_key"], doc["development"], doc["url"], doc["title"], state, dumps(doc), now))
            db.execute("DELETE FROM memory WHERE id=?", (key,))
            db.execute("INSERT INTO memory VALUES (?,?)", (key, " ".join(str(doc.get(k, "")) for k in
                       ("event_key", "title", "summary", "text", "development"))))
        return key

    def related(self, text, url=""):
        words = list(dict.fromkeys(re.findall(r"[\w]{3,}", text.lower())))[:32]
        rows = self.rows("SELECT * FROM stories WHERE url=?", (url,)) if url else []
        if words:
            query = " OR ".join('"' + word + '"' for word in words)
            rows += self.rows("""SELECT s.* FROM memory JOIN stories s ON s.id=memory.id
                WHERE memory MATCH ? ORDER BY rank LIMIT 40""", (query,))
        return list({r["id"]: {**json.loads(r["document"]), "id": r["id"], "state": r["state"]}
                     for r in rows}.values())

    def enqueue(self, story_id, run, payload, now):
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO outbox(id,story,run,payload,due,expires) VALUES (?,?,?,?,?,?)",
                       (story_id, story_id, run, dumps(payload), now, now + 86400))
            db.execute("UPDATE stories SET state='queued' WHERE id=?", (story_id,))

    def acknowledge(self, delivery_id, now):
        with self.connect() as db:
            row = db.execute("SELECT story,state FROM outbox WHERE id=?", (delivery_id,)).fetchone()
            if not row or row["state"] != "delivered":
                raise ValueError("only an actually delivered draft can be acknowledged")
            db.execute("UPDATE outbox SET acknowledged=COALESCE(acknowledged,?) WHERE id=?", (now, delivery_id))
            db.execute("UPDATE stories SET state='acknowledged' WHERE id=?", (row["story"],))

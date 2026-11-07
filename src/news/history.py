"""Read existing local history/queues without changing their publication claims."""
from datetime import datetime, timedelta
import json
from pathlib import Path
import re
import sqlite3

from ..core import history, settings
from ..core.state_store import StatePath
from ..editorial.slot_journal import STATE
from ..video import config as video_config
from ..video.schedule import clocks
from ..video.store import DATABASE as VIDEO_DATABASE
from .adapters import canonical, timestamp
from .editor import TZ
from .store import identity

WATCH_HISTORY = StatePath("news_watch_history.json")
POST_QUEUE = StatePath("posting_queue.json")
REVIEW_HISTORY = StatePath("editorial_review.jsonl")


def records(value):
    if isinstance(value, dict):
        if any(isinstance(value.get(k), str) and value[k] for k in ("text", "tweet", "title", "summary", "caption", "url", "source_url", "event_key")):
            yield value
        for child in value.values():
            if isinstance(child, (list, dict)):
                yield from records(child)
    elif isinstance(value, list):
        for child in value:
            yield from records(child)


def import_file(store, path, now, *, queue=False):
    path = Path(path)
    name = str(path)
    if not path.exists():
        store.coverage(name, "missing", "not checked: file absent", now)
        return []
    try:
        if path.stat().st_size > 30_000_000:
            raise ValueError("history exceeds bounded import; split into JSONL files")
        text = path.read_text()
        data = [json.loads(line) for line in text.splitlines() if line.strip()] if path.suffix == ".jsonl" else json.loads(text)
        if not isinstance(data, (dict, list)):
            raise ValueError("unsupported history shape")
        occupied, count = [], 0
        for row in records(data):
            content = (row.get("text") or row.get("tweet") or row.get("caption") or row.get("summary")
                       or row.get("title") or row.get("source_url") or row.get("url") or row.get("event_key"))
            if not isinstance(content, str):
                continue
            source = row.get("source") if isinstance(row.get("source"), dict) else {}
            url = row.get("source_url") or source.get("url") or row.get("url") or ""
            if not url:
                match = re.search(r"https://[^\s]+", content)
                url = match[0] if match else ""
            try:
                url = canonical(url) if url else ""
            except ValueError:
                url = ""
            doc = {"event_key": row.get("event_key") or "import:" + identity([name, content, url]),
                   "development": row.get("development") or "recorded", "url": url,
                   "title": str(row.get("title") or content[:300]), "text": content[:6000],
                   "summary": str(row.get("summary", ""))[:2000], "origin": name,
                   "historical_date": row.get("timestamp") or row.get("ts") or ""}
            state = str(row.get("state") or row.get("status") or ("queued" if queue else "historical"))
            store.remember(doc, state, now)
            count += 1
            if queue:
                for key in ("scheduled_at", "post_at", "due"):
                    value = row.get(key)
                    stamp = timestamp(value) if isinstance(value, str) else value if type(value) in (int, float) else None
                    if stamp and stamp >= now and state not in ("cancelled", "published", "rejected"):
                        occupied.append(stamp)
        store.coverage(name, "imported", f"{count} accessible records indexed; historical completeness unknown", now)
        return occupied
    except (ValueError, OSError, RecursionError) as exc:
        store.coverage(name, "error", type(exc).__name__, now)
        raise ValueError("available news/post history could not be read") from exc


def context(store, cfg, now):
    occupied = []
    for path in (history.HISTORY.path, STATE.path, str(REVIEW_HISTORY), str(WATCH_HISTORY), *cfg.history_files):
        import_file(store, path, now)
    for path in (str(POST_QUEUE), *cfg.queue_files):
        occupied += import_file(store, path, now, queue=True)
    if settings.get("VIDEO_ENABLED"):
        vc = video_config.load()
        local = datetime.fromtimestamp(now, TZ)
        for day in range(3):
            for clock in clocks(vc):
                hour, minute = map(int, clock.split(":"))
                due = (local + timedelta(days=day)).replace(hour=hour, minute=minute, second=0, microsecond=0).timestamp()
                if due >= now:
                    occupied.append(due)
        path = Path(str(VIDEO_DATABASE))
        if path.exists():
            try:
                with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=2) as db:
                    occupied += [r[0] for r in db.execute("SELECT due FROM slots WHERE due>=? AND state IN ('pending','reserved')", (now,))]
                    occupied += [r[0] for r in db.execute("SELECT created FROM reservations WHERE state IN ('reserved','uploading','submitting','publish_unknown')")]
                store.coverage("video_queue", "read", "scheduled windows and available reservations checked", now)
            except sqlite3.Error:
                store.coverage("video_queue", "error", "could not read existing video queue", now)
                raise ValueError("video queue unavailable") from None
        else:
            store.coverage("video_queue", "missing", "configured windows protected; actual queue absent", now)
    return occupied

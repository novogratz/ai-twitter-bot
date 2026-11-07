"""Permanent owner delivery/rejection memory; never sourced from scraped claims."""
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from .store import dumps


def normalized(value):
    return " ".join(re.findall(r"\w+", str(value).casefold()))


def import_seed(store, cfg, now):
    if not cfg.discovery_memory_file:
        return
    path = Path(cfg.discovery_memory_file)
    if path.stat().st_size > 2_000_000:
        raise ValueError("personal video seed exceeds bounded size")
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if store.meta("personal_memory_seed_hash") == digest:
        return
    seed = json.loads(raw)
    if seed.get("version") != 1 or not isinstance(seed.get("records"), list) or len(seed["records"]) > 5000:
        raise ValueError("invalid personal video memory")
    with store.transaction() as db:
        for record in seed["records"]:
            if (not isinstance(record, dict) or not re.fullmatch(r"[\w.-]{1,128}", record.get("id", ""))
                    or record.get("state") not in ("posted", "delivered", "rejected", "shown")
                    or not isinstance(record.get("urls"), list) or not record.get("evidence")):
                raise ValueError("personal video memory needs explicit owner decision/evidence")
            for url in record["urls"]:
                from .connectors import HOSTS, canonical
                platform = next((p for p, hosts in HOSTS.items() if urlsplit(url).hostname in hosts), None)
                if not platform or canonical(platform, url) != url:
                    raise ValueError("personal video memory needs canonical public video URLs")
            db.execute("INSERT OR IGNORE INTO personal_memory VALUES(?,?,?,?)",
                       (record["id"], record["state"], dumps(record), now))
        store.put_meta(db, "personal_memory_seed_hash", digest)
        store.put_meta(db, "personal_memory_coverage", {"scope": seed.get("coverage", "partial operator seed"),
                                                     "records": len(seed["records"]), "checked_at": now})


def refusal(store, doc):
    from .media import matches_history
    for row in store.rows("SELECT state,document FROM personal_memory"):
        prior = json.loads(row["document"])
        exact = doc.get("canonical_url") and doc["canonical_url"] in prior.get("urls", [])
        title = prior.get("match_title") is True and normalized(doc.get("title")) == normalized(prior.get("title"))
        if exact or title or matches_history(doc, prior):
            return "owner already " + row["state"] + " this footage"
    return ""


def remember(store, row, state, now):
    """Explicit operator feedback/delivery; preparing a clip is not delivery."""
    if state not in ("delivered", "rejected", "shown"):
        raise ValueError("unsupported owner video decision")
    doc = row["document"]
    record = {key: doc[key] for key in ("platform", "source_id", "title", "original_sha256", "output_sha256",
                                       "original_fingerprint", "output_fingerprint") if key in doc}
    record.update(id="candidate-" + row["id"], urls=[doc["canonical_url"]], state=state,
                  source_url=doc["canonical_url"], evidence="explicit operator CLI decision")
    with store.transaction() as db:
        db.execute("INSERT OR IGNORE INTO personal_memory VALUES(?,?,?,?)",
                   (record["id"], state, dumps(record), now))


def context(store, limit=40):
    rows = store.rows("SELECT state,document FROM personal_memory ORDER BY recorded DESC LIMIT ?", (limit,))
    return [{"state": row["state"], "urls": (doc := json.loads(row["document"])).get("urls", []),
             "title": doc.get("title", "")[:500]} for row in rows]

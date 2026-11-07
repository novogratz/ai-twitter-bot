"""Discover → evidence → verify → deduplicate → rank → review → outbox."""
from datetime import datetime, timezone
import json
from pathlib import Path
import time
import uuid
from urllib.parse import urlsplit

from jsonschema import validate

from ..core.logger import log
from ..core import settings
from ..video.security import Deferred
from . import editor, history
from .adapters import Codex, Delivery, HTTP, canonical
from .config import load
from .store import DATABASE, Store, dumps, identity


def deliver(store, cfg, adapter, now, limit=2):
    delivered = []
    store.execute("UPDATE outbox SET state='expired',error='draft expired before delivery' WHERE state='pending' AND expires<=?", (now,))
    rows = store.rows("""SELECT * FROM outbox WHERE state='pending' AND due<=?
        ORDER BY due, CASE json_extract(payload,'$.role') WHEN 'main' THEN 0 ELSE 1 END, id LIMIT ?""", (now, limit))
    for row in rows:
        payload = json.loads(row["payload"])
        store.execute("UPDATE outbox SET attempts=attempts+1 WHERE id=?", (row["id"],))
        try:
            receipt = adapter.send(row["id"], payload)
            if receipt.get("accepted") is not True or receipt.get("id") != row["id"]:
                raise ValueError("unconfirmed destination receipt")
            with store.connect() as db:
                state = "published" if receipt.get("post_url") else "delivered"
                db.execute("UPDATE outbox SET state=?,receipt=?,error=NULL WHERE id=?", (state, dumps(receipt), row["id"]))
                db.execute("UPDATE stories SET state=? WHERE id=?", (state, row["story"]))
            delivered.append(payload)
        except Exception as exc:
            current = store.rows("SELECT state FROM outbox WHERE id=?", (row["id"],))[0]["state"]
            if current in ("published", "submitting", "publish_unknown"):
                continue
            if isinstance(exc, Deferred):
                store.execute("UPDATE outbox SET attempts=MAX(0,attempts-1),due=?,error=? WHERE id=?",
                              (now + 60, str(exc), row["id"]))
                continue
            # A destination may already have accepted it: preserve ID and exact bytes.
            state = "held" if row["attempts"] + 1 >= cfg.delivery_attempts else "pending"
            store.execute("UPDATE outbox SET state=?,due=?,error=? WHERE id=?",
                (state, now + max(60 * 2 ** min(row["attempts"], 8), getattr(exc, "retry_after", 0)), type(exc).__name__, row["id"]))
    return delivered


def retry_pending(cfg=None, *, store=None, delivery=None, now=None):
    """Retry the durable outbox without discovery, model calls or new picks."""
    now = time.time() if now is None else now
    if store is None:
        if not Path(str(DATABASE)).exists():
            return []
        store = Store()
    try:
        with store.lock():
            if not store.rows("SELECT id FROM outbox WHERE state='pending' AND due<=? LIMIT 1", (now,)):
                return []
            cfg = cfg or load()
            if delivery is None:
                if settings.get("NEWS_AUTO_PUBLISH"):
                    from .publisher import SafariDelivery
                    delivery = SafariDelivery(store, cfg)
                else:
                    delivery = Delivery(cfg)
            return deliver(store, cfg, delivery, now)
    except BlockingIOError:
        # A manual preparation or hourly scan owns the same outbox. Its next
        # delivery pass, or the next minute tick, will see the retained claim.
        return []


def _compact_history(rows):
    return [{k: r.get(k, "") for k in ("id", "event_key", "development", "url", "title", "summary", "text", "state")}
            for r in rows]


def _supporting_links(document, cfg):
    """Prefer actual papers, artifacts and corroboration over site navigation."""
    ranked, seen = [], {document["url"].rstrip("/")}
    generic = {"/news", "/blog", "/research", "/index", "/about", "/pricing", "/docs"}
    for link in document.get("links", []):
        url = link["url"]
        path = urlsplit(url).path.rstrip("/")
        title = " ".join(link.get("title", "").lower().split())
        info = cfg.source_info(url)
        if (url.rstrip("/") in seen or not path or path in generic
                or info["role"] not in ("primary", "evidence")
                or title in ("home", "news", "blog", "research", "about", "pricing", "sign in", "log in")):
            continue
        seen.add(url.rstrip("/"))
        evidence = any(term in title + " " + path.lower() for term in
                       ("paper", "report", "system-card", "system card", "model card", "download", "weights",
                        "checkpoint", "repository", "github", "fix", "advisori", "benchmark", "proof", ".pdf"))
        score = 2 * evidence + (info["owner"] != document.get("owner"))
        ranked.append((score, url))
    return [url for _, url in sorted(ranked, key=lambda item: item[0], reverse=True)[:2]]


def run(cfg=None, *, store=None, http=None, model=None, delivery=None, now=None, import_history=True):
    cfg, store, now = cfg or load(), store or Store(), time.time() if now is None else now
    if delivery is None and settings.get("NEWS_AUTO_PUBLISH"):
        from .publisher import SafariDelivery
        delivery = SafariDelivery(store, cfg)
    with store.lock():
        return _run(cfg, store, http or HTTP(store, cfg, now), model or Codex(store, cfg, now),
                    delivery or Delivery(cfg), now, import_history)


def _run(cfg, store, http, model, delivery, now, import_history):
    run_id = uuid.uuid4().hex
    previous = store.meta("last_complete", store.meta("first_window", now - 86400))
    start = min(now - 86400, previous)
    store.set_meta("first_window", store.meta("first_window", start))
    store.execute("INSERT INTO runs VALUES (?,?,NULL,?,'running','[]')", (run_id, now, start))
    errors, results = [], []
    try:
        occupied = history.context(store, cfg, now) if import_history else []
        if import_history:
            extended = history.startup_window(store, start, now)
            if extended < start:
                start = extended
                store.set_meta("first_window", start)
                store.execute("UPDATE runs SET window_start=? WHERE id=?", (start, run_id))
        # Retry delivery without suppressing hourly discovery. A retrying run
        # creates no additional picks, so it cannot send two main stories.
        pending = store.rows("SELECT id FROM outbox WHERE state='pending'")
        allow_new = not pending and not store.rows("SELECT id FROM outbox WHERE state IN ('submitting','publish_unknown')")
        if pending:
            results = deliver(store, cfg, delivery, now)
        for source in cfg.sources:
            try:
                leads = http.discover(source)
                for lead in leads:
                    store.lead(lead, now)
                store.coverage(source["url"], "read", f"{len(leads)} bounded leads; not full archive coverage", now)
            except Exception as exc:
                errors.append(source["name"] + ": " + type(exc).__name__)
                store.coverage(source["url"], "error", type(exc).__name__, now)
        if cfg.search_adapter == "codex":
            try:
                found = model.call("DISCOVER", {"window_start": datetime.fromtimestamp(start, timezone.utc).isoformat(),
                    "now": datetime.fromtimestamp(now, timezone.utc).isoformat(), "queries": cfg.search_queries,
                    "sources": cfg.sources, "allowed_evidence_hosts": sorted(cfg.hosts)}, editor.LEADS, search=True)
                validate(found, editor.LEADS)
                for lead in found["leads"]:
                    lead["url"] = canonical(lead["url"])
                    if urlsplit(lead["url"]).hostname in cfg.hosts:
                        store.lead(lead, now)
            except Exception as exc:
                errors.append("search: " + type(exc).__name__)
        candidates = store.rows("SELECT * FROM leads ORDER BY checked,discovered DESC LIMIT 120")
        if not candidates:
            picks = []
        else:
            triage = model.call("TRIAGE", {"now": now, "window_start": start, "limit": cfg.candidates_per_run,
                "leads": [json.loads(r["document"]) for r in candidates]}, editor.TRIAGE)
            validate(triage, editor.TRIAGE)
            # URLs returned by a model must come from the supplied discovery pool.
            by_url = {r["url"]: json.loads(r["document"]) for r in candidates}
            picks = [by_url[u] for u in dict.fromkeys(triage["urls"]) if u in by_url][:cfg.candidates_per_run]
        verified = []
        for lead in picks:
            try:
                docs = [http.document(lead["url"])]
                evidence_urls = list(dict.fromkeys(lead.get("evidence_urls", [])))[:3]
                # Actual outgoing evidence links can establish original provenance even without search.
                evidence_urls += _supporting_links(docs[0], http.cfg) if hasattr(http, "cfg") else []
                for url in dict.fromkeys(evidence_urls):
                    try:
                        docs.append(http.document(url))
                    except Exception as exc:
                        errors.append("evidence: " + type(exc).__name__)
                evidence_hash = identity([{k: d.get(k) for k in ("url", "text", "dates")} for d in docs])
                if store.meta("evidence:" + lead["url"]) == evidence_hash:
                    store.execute("UPDATE leads SET checked=? WHERE url=?", (now, lead["url"]))
                    continue
                related = store.related(lead["title"] + " " + docs[0]["text"][:1500], docs[0]["url"])
                story = model.call("VERIFY_AND_WRITE", {"now": now, "window_start": start, "lead": lead,
                    "evidence": docs, "history": _compact_history(related)}, editor.STORY)
                validate(story, editor.STORY)
                # A changed title must not hide an existing exact event/development identity.
                related += [{**json.loads(r["document"]), "id": r["id"], "state": r["state"]}
                            for r in store.rows("SELECT * FROM stories WHERE event_key=?", (story["event_key"],))]
                state, reason = editor.gate(story, docs, related, start, now, cfg)
                story["evidence"] = docs
                story["evidence_hash"] = evidence_hash
                story["decision_reason"] = reason
                story["verified_at"] = now
                story["window_start"] = start
                if not story["event_key"].strip() or not story["development"].strip():
                    story["event_key"] = "unresolved:" + identity(lead["url"])
                    story["development"] = evidence_hash
                # A duplicate observation cannot overwrite the original event or its evidence.
                if state != "duplicate":
                    key = store.remember(story, state, now)
                else:
                    key = identity([story["event_key"], story["development"]])
                if state == "verified":
                    verified.append((story, key, related))
                if state in ("rejected", "stale", "duplicate"):
                    store.set_meta("evidence:" + lead["url"], evidence_hash)
                store.execute("UPDATE leads SET checked=? WHERE url=?", (now, lead["url"]))
            except Exception as exc:
                errors.append("candidate: " + type(exc).__name__)
                store.execute("UPDATE leads SET checked=? WHERE url=?", (now, lead["url"]))
        verified.sort(key=lambda v: sum(v[0]["scores"].values()), reverse=True)
        selected_events = set()
        for story, key, related in verified:
            if not allow_new or len(selected_events) >= 2:
                break
            if story["event_key"] in selected_events or (selected_events and sum(story["scores"].values()) < cfg.backup_score_min):
                continue
            try:
                text, length = editor.tweet(story)
                reviewed = model.call("FINAL_REVIEW", {"tweet": text, "story": story,
                    "history": _compact_history(related), "now": now, "window_start": start}, editor.REVIEW)
                validate(reviewed, editor.REVIEW)
                if not all(reviewed[k] for k in editor.REVIEW_FLAGS):
                    story["final_review"] = reviewed
                    store.remember(story, "held", now)
                    continue
                recommendation = editor.recommendation(story, now, occupied, cfg.video_gap_minutes)
                payload = {"id": key, "role": "backup" if selected_events else "main", "tweet": text,
                    "weighted_characters": length, "recommendation": recommendation,
                    "display": text + "\n\n" + recommendation, "created_at": datetime.fromtimestamp(now, timezone.utc).isoformat()}
                story["final_review"] = reviewed
                story["reviewed_text_hash"] = identity(text)
                store.remember(story, "verified", now)
                store.enqueue(key, run_id, payload, now)
                store.set_meta("evidence:" + story["url"], story["evidence_hash"])
                selected_events.add(story["event_key"])
            except Exception as exc:
                story["final_error"] = str(exc)[:240]
                store.remember(story, "held", now)
                errors.append("final review: " + type(exc).__name__)
        if selected_events:
            results += deliver(store, cfg, delivery, now, limit=2 - len(results))
        if not errors:
            store.set_meta("last_complete", now)
        store.execute("UPDATE runs SET finished=?,status=?,errors=? WHERE id=?",
                      (now, "partial" if errors else "complete", dumps(errors), run_id))
        if errors:
            log.warning("[NEWS] Partial coverage: %s", "; ".join(errors))
        return results
    except Exception as exc:
        store.execute("UPDATE runs SET finished=?,status='error',errors=? WHERE id=?",
                      (now, dumps([*errors, type(exc).__name__]), run_id))
        raise

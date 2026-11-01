"""Read-only X history, novelty and ambiguous-publication reconciliation."""
from datetime import datetime
import json
from pathlib import Path
import tempfile

from . import ranking
from .media import duplicate, fingerprint, probe
from .publisher import confirm
from .security import AccessError, request
from .store import ASSETS, dumps


def media_fingerprint(media, store, cfg, now, *, offload=True, client=None):
    variants = [v for v in media.get("variants", []) if v.get("content_type") == "video/mp4" and v.get("url")]
    if not variants:
        if client is not None and getattr(client, "transport", "") == "safari" and media.get("post_url"):
            return client.fingerprint(media)
        raise AccessError("native video bytes are not accessible through the selected X transport")
    if cfg.publishing_transport == "safari" and offload:
        import hashlib
        key = hashlib.sha256(dumps({"key": media.get("media_key"), "variants": variants}).encode()).hexdigest()
        cached = store.meta("x_fingerprint:" + key)
        if cached:
            return cached
        store.set_meta("x_media:" + key, media)
        store.enqueue("x_media", key, now)
        raise AccessError("video fingerprint queued for the independent media worker")
    source = min(variants, key=lambda v: abs(v.get("bit_rate", 0) - 1_000_000))
    if not store.budget("x_media", "download_bytes", cfg.max_download_bytes, cfg.download_budget_bytes, now):
        raise AccessError("history/novelty media download budget exhausted")
    Path(str(ASSETS)).mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="x-check-", dir=str(ASSETS)) as folder:
        path = Path(folder) / "source.mp4"
        try:
            with path.open("wb") as stream:
                request(source["url"], hosts={"video.twimg.com"}, sink=stream,
                        mime={"video/mp4"}, max_bytes=cfg.max_download_bytes, timeout=cfg.task_timeout_seconds)
        finally:
            consumed = path.stat().st_size if path.exists() else 0
            store.refund_budget("x_media", "download_bytes", max(0, cfg.max_download_bytes - consumed), now)
        return fingerprint(path, probe(path, cfg), cfg)


def import_history(store, client, cfg, now):
    """Resume page scans; no completeness claim until accessible media is fingerprinted."""
    client.preflight()
    store.set_meta("account_verified", True)
    if store.meta("history_import_complete", False):
        return
    cursor = store.meta("history_cursor")
    pending = store.meta("history_pending_page")
    if pending and pending.get("cursor") == cursor:
        page = pending["page"]
    else:
        page = client.timeline(cursor)
        # A virtualized timeline can change while fingerprints are collected.
        # Persist the observed page before processing; never replace unfinished
        # entries with a different viewport after a restart or a deferred sample.
        store.set_meta("history_pending_page", {"cursor": cursor, "page": page})
    media = {m["media_key"]: m for m in page.get("includes", {}).get("media", [])}
    processed_videos = 0
    for post in page.get("data", []):
        if store.rows("SELECT 1 FROM history WHERE post_id=?", (post["id"],)):
            continue
        doc = {"text": post.get("text"), "url": "https://x.com/i/status/" + post["id"],
               "transport": getattr(client, "transport", "api")}
        keys = post.get("attachments", {}).get("media_keys", [])
        for key in keys:
            if key not in media:
                raise AccessError("history contains inaccessible media; export or restore access before live selection")
            if media[key]["type"] == "video":
                doc["fingerprint"] = media_fingerprint(media[key], store, cfg, now, client=client)
                doc["media_key"] = key
                processed_videos += 1
        created = datetime.fromisoformat(post["created_at"].replace("Z", "+00:00")).timestamp()
        with store.transaction() as db:
            db.execute("INSERT OR IGNORE INTO history VALUES(?,?,?)", (post["id"], created, dumps(doc)))
        if processed_videos >= 3:
            return  # keep this page cursor; persisted post IDs make the next bounded pass resume safely
    next_token = page.get("meta", {}).get("next_token")
    with store.transaction() as db:
        store.put_meta(db, "history_cursor", next_token)
        store.put_meta(db, "history_pending_page", None)
        if not next_token:
            store.put_meta(db, "history_import_complete", True)
            store.put_meta(db, "history_coverage", {"checked_at": now, "scope": getattr(client, "scope", "all API-accessible timeline pages; older inaccessible posts are not proven absent")})


def novelty(store, row, client, cfg, now, *, operator_direct=False):
    doc = row["document"]
    if operator_direct and not ranking.selected(doc, now):
        raise ValueError("direct source-identifier check requires an active operator selection")
    if not row.get("fingerprint"):
        return "unchecked"
    source_fp = json.loads(row["fingerprint"])
    # Source identifiers and confirmed cast/song describe the actual clip. Search
    # results cannot provide instructions or authorize publication.
    identifiers = ['url:"' + doc["canonical_url"].replace('"', '') + '"', '"' + doc["source_id"] + '"']
    cast = [cfg.targets[k][0] for k in doc.get("inspection", {}).get("cast", []) if k in cfg.targets]
    query = "(" + " OR ".join(identifiers) + ") -is:retweet"
    queries = [query]
    if cast and not operator_direct:
        queries.append('"' + cast[0].replace('"', '') + '" (dance OR singing OR parody) has:videos -is:retweet')
    checked, found, truncated = [], False, False
    for query in queries:
        cursor = None
        for _ in range(3):
            page = client.search(query, cursor)
            checked.append({"query": query, "at": now, "results": len(page.get("data", []))})
            for post in page.get("data", []):
                urls = [u.get("expanded_url", "") for u in post.get("entities", {}).get("urls", [])]
                if doc["canonical_url"] in urls:
                    found = True
            for media in page.get("includes", {}).get("media", []):
                if media.get("type") == "video":
                    if duplicate(source_fp, media_fingerprint(media, store, cfg, now, client=client)):
                        found = True
            cursor = page.get("meta", {}).get("next_token")
            if found or not cursor:
                break
        truncated |= bool(cursor and not found)
        if found:
            break
    # The checked scope is the bounded set actually searched and inspected.
    # A popular-character search can have endless results; reaching its page
    # budget does not mean no search occurred, nor establish global absence.
    # Unreadable pages/media still raise before any checked verdict is saved.
    state = "found_existing" if found else "checked_no_match"
    doc["novelty"] = {"state": state, "checked_at": now, "evidence": checked,
                      "scope": getattr(client, "scope", "recent X API search; no match does not establish global absence"),
                      "source_identifiers_only": operator_direct, "truncated": truncated}
    doc = ranking.refresh(store, row | {"document": doc}, now, cfg)
    reason = ranking.gate(doc, cfg, now, final=True)
    store.save_candidate(row["id"], doc, now, state="held" if reason else "ready", reason=reason,
                         score=doc["ranking"]["total"], fingerprint=source_fp)
    return state


def reconcile_unknown(store, client, now):
    rows = store.rows("SELECT * FROM reservations WHERE state='publish_unknown'")
    if not rows:
        return
    # Read all accessible pages until earlier than the submit intent. Positive
    # media-key + caption match is evidence; an empty search never releases a claim.
    for row in rows:
        cursor = None
        for _ in range(32):
            page = client.timeline(cursor)
            for post in page.get("data", []):
                keys = post.get("attachments", {}).get("media_keys", [])
                if row.get("transport", "api") == "safari":
                    # A browser media key is a post identifier, not an uploaded
                    # content key. Require actual video matching after a crash.
                    if " ".join(post.get("text", "").split()) != " ".join(row["caption"].split()):
                        continue
                    created = datetime.fromisoformat(post["created_at"].replace("Z", "+00:00")).timestamp()
                    if not row["submitted"] - 5 <= created <= row["submitted"] + 120:
                        continue
                    candidate = store.candidate(row["candidate"])
                    expected = candidate["document"].get("output_fingerprint")
                    if not expected:
                        continue
                    for media in page.get("includes", {}).get("media", []):
                        if media.get("media_key") in keys and media.get("type") == "video":
                            from .config import load
                            if duplicate(expected, media_fingerprint(media, store, load(), now, client=client)):
                                confirm(store, row["id"], row["token"], now, str(post["id"]))
                                return
                elif row["media_key"] and row["media_key"] in keys and post.get("text") == row["caption"]:
                    confirm(store, row["id"], row["token"], now, str(post["id"]))
                    return
            cursor = page.get("meta", {}).get("next_token")
            if not cursor:
                break
        store.event(now, "publish_unknown", row["id"], "no positive match; slot/content remain held, no retry")


def collect_outcomes(store, client, now):
    for row in store.rows("SELECT post_id,confirmed FROM reservations WHERE state='confirmed' ORDER BY confirmed DESC LIMIT 30"):
        age = (now - row["confirmed"]) / 3600
        for window in (1, 24, 48):
            if not window <= age < window + (2 if window == 1 else 12):
                continue
            if store.rows("SELECT 1 FROM outcomes WHERE post_id=? AND window=?", (row["post_id"], window)):
                continue
            metrics = client.metrics(row["post_id"])
            playback = []
            for media in metrics.get("includes", {}).get("media", []):
                actual = {k: v for k, v in media.get("non_public_metrics", {}).items()
                          if k.startswith("playback_") and type(v) is int}
                if actual:
                    playback.append({"media_key": media.get("media_key"), "observed_counters": actual})
            payload = {"observed_age_hours": age, "observed": metrics, "retention": playback or None, "estimated": False}
            with store.transaction() as db:
                db.execute("INSERT OR IGNORE INTO outcomes VALUES(?,?,?,?)", (row["post_id"], window, now, dumps(payload)))

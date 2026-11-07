"""Read-only X history, novelty and ambiguous-publication reconciliation."""
from datetime import datetime
import hashlib
import json
import math
import re
from pathlib import Path
import tempfile
import time

from . import ranking
from .config import source_duration_limit
from .media import duplicate, fingerprint, probe
from .publisher import confirm
from .security import AccessError, Deferred, request, sha256
from .store import ASSETS, dumps


def history_ready(store, cfg):
    """A bounded initial import is distinct from a completed historical archive."""
    if store.meta("history_import_complete", False):
        return True
    cursor = store.meta("history_cursor", {}) or {}
    return bool(cfg.initial_history_pages and isinstance(cursor, dict)
                and type(cursor.get("offset")) is int and cursor["offset"] >= cfg.initial_history_pages
                and store.rows("SELECT 1 FROM history LIMIT 1"))


def native_fingerprint_result(store, post_id, now):
    """A queued complete-byte read needs no additional Safari transaction."""
    reference = store.meta("browser_native_media:" + post_id, {}) or {}
    key = reference.get("key")
    if not key:
        return None
    cached = store.meta("x_fingerprint:" + key)
    if cached:
        return cached
    item = store.meta("x_media:" + key, {}) or {}
    plan = item.get("native_source", {}).get("source_download", {})
    if (0 <= now - plan.get("captured_at", 0) < 3600 and now < plan.get("expires_at", 0)
            and store.rows("SELECT 1 FROM jobs WHERE kind='x_media' AND item=? AND state IN ('pending','running')", (key,))):
        raise Deferred("normal-page video bytes queued for the independent media worker", retry_after=30)
    return None


def queue_native_fingerprint(store, item, observed, duration, cfg, now):
    from .native_source import x_media_plan
    if (type(duration) not in (int, float) or not math.isfinite(duration)
            or not .5 <= duration <= source_duration_limit(cfg)):
        return None
    document = x_media_plan(observed, item["post_url"], now)
    if document is None:
        return None
    evidence = document["source_evidence"]
    key = hashlib.sha256(dumps({"transport": "normal_page_player_v1", "post_url": document["canonical_url"],
                               "media_id": evidence["media_id"]}).encode()).hexdigest()
    cached = store.meta("x_fingerprint:" + key)
    if cached:
        return cached
    # A failed download keeps its bounded retry history. It cannot be restarted
    # indefinitely by another Safari read of the same unchanged media identity.
    if store.rows("SELECT 1 FROM jobs WHERE kind='x_media' AND item=? AND state='dead'", (key,)):
        return None
    payload = {"media_key": item.get("media_key", "browser:" + document["source_id"]),
               "post_url": document["canonical_url"], "native_source": document, "duration": duration}
    with store.transaction() as db:
        store.put_meta(db, "x_media:" + key, payload)
        store.put_meta(db, "browser_native_media:" + document["source_id"], {"key": key, **evidence})
        db.execute("INSERT OR IGNORE INTO jobs(kind,item,due) VALUES('x_media',?,?)", (key, now))
    raise Deferred("normal-page video bytes queued for the independent media worker", retry_after=30)


def media_fingerprint(media, store, cfg, now, *, offload=True, client=None):
    native = media.get("native_source")
    if native is not None:
        if offload:
            raise AccessError("native media decoding belongs to the independent media worker")
        from .native_source import download, x_media_plan
        from . import media as media_tools
        evidence = native.get("source_evidence", {})
        plan = native.get("source_download", {})
        # Recheck saved identity at the independent worker boundary; source text
        # and a plausible CDN URL alone cannot bind media to the inspected post.
        observed = {"post_id": evidence.get("post_id"), "post_url": evidence.get("post_url"),
                    "media_id": evidence.get("media_id"), "media": evidence.get("media_urls"),
                    "user_agent": plan.get("user_agent")}
        verified = x_media_plan(observed, media.get("post_url", ""), plan.get("captured_at", 0))
        if (verified is None or verified != native or type(media.get("duration")) not in (int, float)
                or not .5 <= media["duration"] <= source_duration_limit(cfg)):
            raise AccessError("native video resource identity is unverified")
        if not 0 <= now - plan["captured_at"] < 3600 or now >= plan["expires_at"]:
            raise Deferred("native video resources need a fresh normal-page observation", retry_after=30)
        Path(str(ASSETS)).mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="x-native-check-", dir=str(ASSETS)) as folder:
            path = Path(folder) / "source.mp4"
            previous_deadline = media_tools._job_deadline
            deadline = time.monotonic() + cfg.media_job_seconds
            media_tools._job_deadline = min(previous_deadline, deadline) if previous_deadline is not None else deadline
            try:
                info = None
                def validate(path):
                    nonlocal info
                    try:
                        info = probe(path, cfg, source=True) if cfg.auto_edit else probe(path, cfg)
                    except (StopIteration, KeyError, TypeError) as exc:
                        raise AccessError("native resource does not contain complete video and audio") from exc
                    if abs(info["duration"] - media["duration"]) > .25:
                        raise AccessError("native video bytes differ from observed player duration")
                download(native, path, cfg, store, now, validate=validate)
                if info is None:
                    validate(path)
                result = fingerprint(path, info, cfg)
                count = min(30, max(4, math.ceil(info["duration"])))
                digest = sha256(path)
                if result.get("sha256") != digest or len(result.get("visual", [])) != count:
                    raise AccessError("native video byte fingerprint is incomplete")
                result["source_evidence"] = evidence | {"sha256": digest, "duration": info["duration"],
                                                         "decoded_samples": count, "checked_at": now}
                return result
            finally:
                media_tools._job_deadline = previous_deadline
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
        raise Deferred("video fingerprint queued for the independent media worker")
    source = min(variants, key=lambda v: abs(v.get("bit_rate", 0) - 1_000_000))
    Path(str(ASSETS)).mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="x-check-", dir=str(ASSETS)) as folder:
        allowance = int(store.reserve_up_to("x_media", "download_bytes", cfg.max_download_bytes,
                                           cfg.download_budget_bytes, now))
        if not allowance:
            raise Deferred("history/novelty media download budget exhausted")
        path = Path(folder) / "source.mp4"
        try:
            with path.open("wb") as stream:
                request(source["url"], hosts={"video.twimg.com"}, sink=stream,
                        mime={"video/mp4"}, max_bytes=allowance, timeout=cfg.task_timeout_seconds)
        except AccessError as exc:
            if allowance < cfg.max_download_bytes and str(exc) == "response exceeds byte budget":
                raise Deferred("history/novelty media download budget insufficient") from exc
            raise
        finally:
            consumed = path.stat().st_size if path.exists() else 0
            store.refund_budget("x_media", "download_bytes", max(0, allowance - consumed), now)
        info = probe(path, cfg, source=True) if cfg.auto_edit else probe(path, cfg)
        return fingerprint(path, info, cfg)


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


def _known_x_source(doc, now):
    """The verified original may appear in searches without being another copy."""
    from .connectors import canonical
    if doc.get("platform") == "x" and not ranking.source_gate(doc, now):
        try:
            source_url = canonical("x", doc["canonical_url"])
            if source_url.rsplit("/", 1)[-1] == str(doc["source_id"]):
                return str(doc["source_id"])
        except ValueError:
            pass
    return None


def preparation_reason(doc, cfg, now):
    """Spend novelty reads on clips whose actual preparation could qualify."""
    if doc.get("qc") and (reason := ranking.output_gate(doc, cfg)):
        return reason
    if cfg.bangers_only:
        from .bangers import score
        reviewed = score(doc, now)
        return "" if reviewed["total"] is not None and (ranking.selected(doc, now) or reviewed["total"] >= cfg.banger_min_score) else "current excerpt is below banger threshold"
    parts = doc.get("ranking", {}).get("components", {})
    if not ranking.selected(doc, now) and parts:
        # This upper bound is only a cost-admission calculation. It never
        # changes observed scores, unknown popularity or novelty evidence.
        possible = parts | {"novelty": 10}
        values = [value for value in possible.values() if value is not None]
        if all(type(value) in (int, float) and math.isfinite(value) for value in values):
            if (sum(values) < cfg.score_threshold
                    and not ranking.unknown_momentum_eligible({"ranking": {"components": possible}}, cfg)):
                return "current reviewed scores cannot reach publication threshold"
    return ""


def novelty(store, row, client, cfg, now, *, operator_direct=False):
    doc = row["document"]
    if cfg.bangers_only and not operator_direct and row.get("fingerprint"):
        from .exposure import check
        return check(store, row, client, cfg, now)
    if operator_direct and not ranking.selected(doc, now):
        raise ValueError("direct source-identifier check requires an active operator selection")
    if not row.get("fingerprint"):
        return "unchecked"
    if reason := preparation_reason(doc, cfg, now):
        raise Deferred("novelty waits for eligible preparation: " + reason, retry_after=300)
    source_fp = json.loads(row["fingerprint"])
    # Source identifiers and confirmed cast/song describe the actual clip. Search
    # results cannot provide instructions or authorize publication.
    identifiers = ['url:"' + doc["canonical_url"].replace('"', '') + '"', '"' + doc["source_id"] + '"']
    cast = [cfg.targets[k][0] for k in doc.get("inspection", {}).get("cast", []) if k in cfg.targets]
    query = "(" + " OR ".join(identifiers) + ") -is:retweet"
    queries = [query]
    if cast and not operator_direct:
        # An entire celebrity's dance history is not a clip-specific novelty
        # query. Prefer the source's quoted song/title plus the attributed cast.
        quoted = re.search(r'"([^"\n]{2,80})"|“([^”\n]{2,80})”|《([^》\n]{2,80})》|「([^」\n]{2,80})」|『([^』\n]{2,80})』',
                           str(doc.get("title", "")))
        phrase = " ".join(next((part for part in quoted.groups() if part), "").replace('"', ' ').split()) if quoted else ""
        subject = " ".join('"' + name.replace('"', '') + '"' for name in cast[:2])
        detail = '"' + phrase + '"' if phrase else "(dance OR singing OR parody)"
        queries.append(subject + " " + detail + " has:videos -is:retweet")
    progress_key = "novelty_progress:" + row["id"]
    progress = store.meta(progress_key, {}) or {}
    source_id = _known_x_source(doc, now)
    if (progress.get("sha256") != doc.get("original_sha256") or progress.get("queries") != queries
            or progress.get("revision") != 2 or progress.get("known_source_id") != source_id):
        progress = {"revision": 2, "known_source_id": source_id,
                    "sha256": doc.get("original_sha256"), "queries": queries, "query_index": 0,
                    "page_index": 0, "cursor": None, "pending_page": None, "media_index": 0,
                    "checked": [], "truncated": False}
    checked, found, inspected = progress["checked"], False, 0
    while progress["query_index"] < len(queries):
        query = queries[progress["query_index"]]
        cursor = progress["cursor"]
        while progress["page_index"] < 3:
            page = progress["pending_page"]
            if page is None:
                page = client.search(query, progress["cursor"])
                progress["pending_page"] = page
                progress["observed_at"] = now
                store.set_meta(progress_key, progress)
            posts = page.get("data", [])
            # An authorized X original is necessarily already on X. Exclude
            # only its exact, source-bound status; other copies still count.
            from .connectors import canonical
            source_posts = [post for post in posts if str(post.get("id")) == source_id]
            other_posts = [post for post in posts if str(post.get("id")) != source_id]
            source_keys = {key for post in source_posts for key in post.get("attachments", {}).get("media_keys", [])}
            other_keys = {key for post in other_posts for key in post.get("attachments", {}).get("media_keys", [])}
            excluded_keys = source_keys - other_keys
            for post in other_posts:
                urls = [u.get("expanded_url", "") for u in post.get("entities", {}).get("urls", [])]
                for url in urls:
                    try:
                        if canonical(doc["platform"], url) == doc["canonical_url"]:
                            found = True
                    except ValueError:
                        continue
            videos = [m for m in page.get("includes", {}).get("media", [])
                      if m.get("type") == "video" and m.get("media_key") not in excluded_keys]
            while not found and progress["media_index"] < len(videos):
                if inspected:
                    raise Deferred("novelty video inspection continues from its saved page", retry_after=10)
                media = videos[progress["media_index"]]
                if duplicate(source_fp, media_fingerprint(media, store, cfg, now, client=client)):
                    found = True
                progress["media_index"] += 1
                inspected += 1
                store.set_meta(progress_key, progress)
            checked.append({"query": query, "at": progress["observed_at"], "results": len(posts),
                            "known_source_posts": len(source_posts)})
            cursor = page.get("meta", {}).get("next_token")
            progress.update(cursor=cursor, pending_page=None, media_index=0, page_index=progress["page_index"] + 1)
            store.set_meta(progress_key, progress)
            if found or not cursor:
                break
        progress["truncated"] |= bool(cursor and not found)
        if found:
            break
        progress.update(query_index=progress["query_index"] + 1, page_index=0, cursor=None)
        store.set_meta(progress_key, progress)
    # The checked scope is the bounded set actually searched and inspected.
    # A popular-character search can have endless results; reaching its page
    # budget does not mean no search occurred, nor establish global absence.
    # Unreadable pages/media still raise before any checked verdict is saved.
    state = "found_existing" if found else "checked_no_match"
    doc["novelty"] = {"state": state, "checked_at": now, "evidence": checked,
                      "scope": getattr(client, "scope", "recent X API search; no match does not establish global absence"),
                      "source_identifiers_only": operator_direct, "truncated": progress["truncated"]}
    doc = ranking.refresh(store, row | {"document": doc}, now, cfg)
    reason = ranking.gate(doc, cfg, now, final=True)
    store.save_candidate(row["id"], doc, now, state="held" if reason else "ready", reason=reason,
                         score=doc["ranking"]["total"], fingerprint=source_fp)
    store.set_meta(progress_key, None)
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

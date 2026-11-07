"""Bounded, resumable matching-copy reads; the largest observed reach wins."""
import json
import re

from ..core import account
from ..x import x_urls
from . import ranking
from .media import duplicate
from .security import Deferred
from .store import dumps


def queries(doc, cfg):
    result = ['(url:"' + doc["canonical_url"].replace('"', '') + '" OR "' + doc["source_id"] + '") has:videos -is:retweet']
    title = " ".join(re.sub(r'[^\w\s]', ' ', str(doc.get("title", ""))).split())[:100]
    cast = [cfg.targets[k][0] for k in doc.get("inspection", {}).get("cast", []) if k in cfg.targets]
    if title and (len(title.split()) >= 2 or len(re.findall(r'[\u4e00-\u9fff]', title)) >= 6):
        result.append('"' + title + '" has:videos -is:retweet')
    # Creator/song variants broaden exact-title coverage without inventing an X
    # handle or issuing an entire celebrity's generic video-history search.
    songs = re.findall(r'["“「《]([^"”」》]{4,70})["”」》]', str(doc.get("title", "")))
    if cast and songs:
        result.append('"' + cast[0] + '" "' + songs[0] + '" has:videos -is:retweet')
    elif cast and doc.get("creator"):
        creator = re.sub(r'[^\w\s]', ' ', str(doc["creator"]))[:80].strip()
        if creator:
            result.append('"' + creator + '" "' + cast[0] + '" has:videos -is:retweet')
    return result


def _copy(post, media, now):
    ident = str(post.get("id", ""))
    url = post.get("url") or media.get("post_url", "")
    if x_urls.status_id(url) != ident:
        url = ""
    observed = post.get("view_observation", {})
    valid = observed.get("post_id") == ident and observed.get("url") == url and url
    views = observed.get("views") if valid else None
    return {"post_id": ident, "url": url, "views": views if type(views) is int and views >= 0 else None,
            "observed_at": observed.get("at", now) if valid else now,
            "basis": "matching temporal video; exact outer-status view counter" if valid else "matching video; views unknown"}


def check(store, row, client, cfg, now):
    from .reconcile import media_fingerprint, preparation_reason
    doc = row["document"]
    if why := preparation_reason(doc, cfg, now):
        raise Deferred("X exposure waits for a qualifying prepared excerpt: " + why, retry_after=300)
    source = json.loads(row["fingerprint"])
    searches = queries(doc, cfg)
    cluster = doc.get("content_cluster", row["id"])
    key = "exposure-progress:" + row["id"]
    progress = store.meta(key, {}) or {}
    if (progress.get("sha256") != doc.get("original_sha256") or progress.get("queries") != searches
            or now - progress.get("started", 0) > cfg.x_reach_max_age_seconds):
        progress = {"sha256": doc["original_sha256"], "queries": searches, "started": now,
                    "query": 0, "page": 0, "cursor": None, "pending": None, "media": 0,
                    "copies": [], "checked": [], "truncated": False}
    # Source metrics are part of the maximum too; selecting a different copy
    # never deletes a previously located large matching copy in this cluster.
    if doc.get("platform") == "x" and not ranking.source_gate(doc, now, cfg):
        metrics = doc["source_metrics"]
        original = {"post_id": str(doc["source_id"]), "url": doc["canonical_url"], "views": metrics["views"],
                    "observed_at": metrics["observed_at"], "basis": "verified exact source player"}
        _remember(store, cluster, original)
    inspected = 0
    while progress["query"] < len(searches):
        if progress["pending"] is None:
            progress["pending"] = client.search(searches[progress["query"]], progress["cursor"])
            progress["page_observed"] = now
            store.set_meta(key, progress)
        page = progress["pending"]
        videos = [m for m in page.get("includes", {}).get("media", []) if m.get("type") == "video"]
        while progress["media"] < len(videos):
            if inspected:
                raise Deferred("X exposure continues from saved matching-copy evidence", retry_after=10)
            media = videos[progress["media"]]
            result = media_fingerprint(media, store, cfg, now, client=client)
            matched = duplicate(source, result) or bool(doc.get("output_fingerprint") and duplicate(doc["output_fingerprint"], result))
            if matched:
                posts = [p for p in page.get("data", []) if media["media_key"] in p.get("attachments", {}).get("media_keys", [])]
                for post in posts:
                    copy = _copy(post, media, progress["page_observed"])
                    progress["copies"].append(copy)
                    _remember(store, cluster, copy)
            progress["media"] += 1
            inspected += 1
            store.set_meta(key, progress)
        progress["checked"].append({"query": searches[progress["query"]], "at": progress["page_observed"],
                                    "video_count": len(videos), "post_count": len(page.get("data", []))})
        cursor = page.get("meta", {}).get("next_token")
        progress.update(page=progress["page"] + 1, cursor=cursor, pending=None, media=0)
        if not cursor or progress["page"] >= 3:
            progress["truncated"] |= bool(cursor)
            progress.update(query=progress["query"] + 1, page=0, cursor=None)
        store.set_meta(key, progress)
    copies = [json.loads(r["document"]) for r in store.rows("SELECT document FROM exposure_memory WHERE cluster=?", (cluster,))]
    known = [c["views"] for c in copies if type(c.get("views")) is int]
    own = any(x_urls.author(c.get("url", "")) in account.own_handles() for c in copies)
    stale = any(type(c.get("views")) is not int or not 0 <= now - c.get("observed_at", 0) <= cfg.x_reach_max_age_seconds for c in copies)
    highest = max(known, default=None)
    state = ("found_existing" if own else "known_high_reach_match" if highest is not None and highest > cfg.x_max_views else
             "unknown_or_stale" if stale or progress["truncated"] else "verified_low_reach_match" if copies else "checked_no_match")
    doc["novelty"] = {"state": state, "public_result": "checked_no_match_public" if state == "checked_no_match" else state,
        "checked_at": now, "matching_copies": copies, "highest_observed_views": highest,
        "personal_duplicate": own, "evidence": progress["checked"], "truncated": progress["truncated"],
        "scope": getattr(client, "scope", "bounded public X search; no global-exclusivity claim")}
    doc = ranking.refresh(store, row | {"document": doc}, now, cfg)
    why = ranking.gate(doc, cfg, now, final=True)
    from .handoff import build
    doc["handoff"] = build(store, row, doc, cfg, now)
    why = why or doc["handoff"]["hold_reason"]
    store.save_candidate(row["id"], doc, now, state="held" if why else "ready", reason=why,
                         score=doc["ranking"]["total"], fingerprint=source)
    store.set_meta(key, None)
    return state


def _remember(store, cluster, copy):
    with store.transaction() as db:
        old = db.execute("SELECT document FROM exposure_memory WHERE cluster=? AND post_id=?", (cluster, copy["post_id"])).fetchone()
        previous = json.loads(old[0]) if old else {}
        # Retain the highest actual observation AND its original observation time.
        # A later unknown/smaller counter cannot refresh or hide that observation.
        if type(previous.get("views")) is int and (type(copy.get("views")) is not int or previous["views"] > copy["views"]):
            copy = previous
        db.execute("INSERT INTO exposure_memory VALUES(?,?,?,?,?) ON CONFLICT(cluster,post_id) DO UPDATE SET "
                   "views=excluded.views,observed=excluded.observed,document=excluded.document",
                   (cluster, copy["post_id"], copy["views"], copy["observed_at"], dumps(copy)))

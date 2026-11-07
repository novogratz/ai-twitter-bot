"""Read a permitted source player's actual media URLs; download in another worker."""
import json
import math
from pathlib import Path
import re
import tempfile
import time
from urllib.parse import parse_qs, urlsplit

from . import ranking
from .config import source_duration_limit
from .security import AccessError, Deferred, request


def _source_failed(doc, now):
    """Spend the reserve on new leads before repeatedly opening blocked pages."""
    attempts = min(8, int(doc.get("source_capture_failures", 0)) + 1)
    doc["source_capture_failures"] = attempts
    doc["source_capture_retry_at"] = now + min(86400, 1200 * 3 ** (attempts - 1))


def _source_succeeded(doc):
    doc.pop("source_capture_retry_at", None)
    doc.pop("source_capture_failures", None)


def media_host(url):
    parts = urlsplit(url)
    host = parts.hostname or ""
    if (parts.scheme != "https" or parts.username or parts.password or parts.port not in (None, 443)
            or not (host.endswith(".bilivideo.com") or host == "upos-hz-mirrorakam.akamaized.net")):
        raise AccessError("source player supplied an unapproved media URL")
    return host


def plan(payload, source_id, now):
    """Only bounded, unencrypted streams actually exposed by the normal player."""
    if payload.get("id") != source_id or payload.get("encrypted"):
        raise AccessError("source identity/encryption check failed")
    published = payload.get("published")
    if type(published) not in (int, float) or not math.isfinite(published) or not 0 < published <= now:
        raise AccessError("source publication timestamp unavailable")
    selected = {}
    expires = now + 3600
    for kind, codec in (("video", "avc1"), ("audio", "mp4a")):
        streams = [v for v in payload.get(kind, []) if not v.get("drm") and str(v.get("codecs", "")).startswith(codec)
                   and (kind != "video" or 32 <= v.get("height", 0) <= 1080)]
        if not streams:
            raise AccessError("normal player lacks supported unencrypted video/audio")
        stream = max(streams, key=lambda v: (v.get("height", 0), v.get("bandwidth", 0)))
        urls = list(dict.fromkeys([stream.get("url", ""), *stream.get("backups", [])]))
        for url in urls:
            media_host(url)
            deadline = parse_qs(urlsplit(url).query).get("deadline", [])
            if deadline:
                if not deadline[0].isdigit() or int(deadline[0]) <= now + 120:
                    raise AccessError("normal player supplied expired media; reload source page")
                expires = min(expires, int(deadline[0]))
        # Prefer the player-provided CDN that delivered complete bytes in the
        # 2026-11-01 real download; retain bounded fallback to its other URLs.
        urls.sort(key=lambda u: not media_host(u).endswith(".bilivideo.com"))
        selected[kind] = urls[:3]
    ua = payload.get("user_agent", "")
    if not isinstance(ua, str) or not ua or len(ua) > 1000 or "\n" in ua or "\r" in ua:
        raise AccessError("invalid browser user agent")
    return {"version": 1, "platform": "bilibili", "source_id": source_id,
            "captured_at": now, "expires_at": expires, "user_agent": ua, **selected}


def _capture_bilibili(store, cfg, now):
    """One short Safari transaction, owned by the publisher; never renders/posts."""
    options = cfg.platforms.get("bilibili", {})
    if (not options.get("enabled", True) or not options.get("safari_player")
            or store.meta("platform_disabled:bilibili", False)
            or store.meta("next_source_capture:bilibili", 0) > now):
        return None
    store.set_meta("next_source_capture:bilibili", now + 60)
    candidates = store.rows("SELECT id FROM candidates WHERE platform='bilibili' "
                            "AND state IN ('discovered','held','ready') "
                            "AND length(source_id)=12 AND source_id GLOB 'BV*' "
                            "AND source_id NOT GLOB '*[^A-Za-z0-9]*' "
                            "ORDER BY COALESCE(json_extract(document,'$.source_capture_attempt'),0),published DESC,discovered DESC LIMIT 80")
    chosen = None
    for item in candidates:
        row = store.candidate(item["id"])
        doc = row["document"]
        if doc.get("source_capture_retry_at", 0) > now:
            continue
        if not isinstance(doc.get("source_id"), str) or not re.fullmatch(r"BV[A-Za-z0-9]{10}", doc["source_id"]):
            continue
        if (doc.get("source_duration_evidence", {}).get("source_id") == doc.get("source_id")
                and doc.get("source_duration", 0) > source_duration_limit(cfg)):
            continue
        downloaded = bool(doc.get("original_sha256") and Path(doc.get("original_path", "")).is_file())
        if (not downloaded and ranking.permission(doc, cfg, now) and not doc.get("local_file") and not doc.get("media_url")
                and now - doc.get("source_capture_attempt", 0) >= 1200
                and not store.rows("SELECT 1 FROM jobs WHERE item=? AND state='running'", (row["id"],))):
            chosen = row
            break
    if not chosen:
        return None
    row, doc = chosen, chosen["document"]
    source_id = doc["source_id"]
    doc["source_capture_attempt"] = now
    try:
        if not store.budget("bilibili", "requests", 1, cfg.request_budget - cfg.publishing_request_reserve, now):
            raise AccessError("source request budget exhausted")
        from ..x import safari
        from ..x.safari_video import browser_session
        url = "https://www.bilibili.com/en/video/" + source_id + "/"
        js = r'''JSON.stringify((()=>{const d=window.__INITIAL_STATE__?.videoData;
          const p=window.__playinfo__?.data;if(!d||!p)return {};
          const stream=s=>({url:s.baseUrl||s.base_url,backups:s.backupUrl||s.backup_url||[],
            height:s.height,bandwidth:s.bandwidth,codecs:s.codecs,drm:!!(s.drm||s.drm_info)});
          return {id:d.bvid,title:d.title,creator:d.owner?.name,published:d.pubdate,duration:d.duration,
            related:[...document.querySelectorAll('a[href*="/video/BV"]')].filter(a=>a.getClientRects().length)
              .slice(0,80).map(a=>({url:a.href,title:a.getAttribute('title')||a.innerText||a.querySelector('img')?.alt||''})),
            metrics:{views:d.stat?.view,likes:d.stat?.like,shares:d.stat?.share},
            encrypted:!!(p.is_drm||p.drm_tech_type),user_agent:navigator.userAgent,
            video:(p.dash?.video||[]).map(stream),audio:(p.dash?.audio||[]).map(stream)};})())'''
        with browser_session():
            if not safari.open_url(url):
                raise AccessError("source page did not open")
            try:
                payload = {}
                for _ in range(12):
                    raw = safari._run_js(js, timeout_s=5, target_url=url)
                    if raw and len(raw) <= 200000:
                        payload = json.loads(raw)
                    if payload.get("id"):
                        break
                    time.sleep(.5)
            finally:
                safari.close_front_tab()
        from .connectors import ingest
        leads = related_candidates(payload.get("related", []), cfg, row["id"], now)
        if leads:
            ingest(store, "bilibili", leads, now, cfg)
        duration = payload.get("duration")
        if (payload.get("id") == source_id and type(duration) in (int, float)
                and math.isfinite(duration) and duration > source_duration_limit(cfg)):
            doc["source_duration"] = duration
            doc["source_duration_evidence"] = {"source_id": source_id, "observed_at": now}
            doc["preparation_hold"] = {"stage": "source_duration", "reason": "source exceeds configured duration", "at": now}
            store.save_candidate(row["id"], doc, time.time(), state="held", reason="source exceeds configured duration")
            return "source duration held"
        downloaded = bool(doc.get("original_sha256") and Path(doc.get("original_path", "")).is_file())
        if not downloaded:
            doc["source_download"] = plan(payload, source_id, now)
        elif (payload.get("id") != source_id or type(payload.get("published")) not in (int, float)
              or not 0 < payload["published"] <= now):
            raise AccessError("source metadata identity/timestamp unverified")
        doc.update(published_at=payload["published"], creator=str(payload.get("creator") or doc["creator"]),
                   title=str(payload.get("title", ""))[:2000], access_status="normal Safari player media available",
                   publication_evidence="Timestamp from the authenticated normal video page; not discovery time")
        _source_succeeded(doc)
        store.save_candidate(row["id"], doc, time.time(), state=row["state"] if downloaded else "discovered",
                             reason=row["reason"] if downloaded else "source media captured; verification queued",
                             score=row["score"], fingerprint=json.loads(row["fingerprint"]) if row["fingerprint"] else None)
        metrics = {k: v if type(v) is int and v >= 0 else None for k, v in payload.get("metrics", {}).items()}
        with store.transaction() as db:
            db.execute("UPDATE candidates SET published=?,creator=? WHERE id=?", (doc["published_at"], doc["creator"], row["id"]))
            db.execute("INSERT OR IGNORE INTO observations(candidate,observed,payload) VALUES(?,?,?)", (row["id"], now, json.dumps(metrics)))
            if not downloaded:
                db.execute("INSERT INTO jobs(kind,item,due) VALUES('media',?,?) ON CONFLICT(kind,item) DO UPDATE SET "
                           "state='pending',due=excluded.due,attempts=0", (row["id"], now))
        store.set_meta("source_player:bilibili", {"status": "operational", "checked_at": now, "candidate": row["id"],
                       "scope": "normal Safari player on this observed page; other clips can be restricted"})
        return "source media captured"
    except Exception as exc:
        from ..guards.active_hours import OutsideActiveHours
        from .security import Deferred
        if isinstance(exc, (OutsideActiveHours, Deferred)):
            raise
        from .config import safe_label
        _source_failed(doc, now)
        detail = safe_label(str(exc)) if isinstance(exc, AccessError) else type(exc).__name__
        store.save_candidate(row["id"], doc, time.time(), state=row["state"],
                             reason="source player unavailable: " + detail, score=row["score"],
                             fingerprint=json.loads(row["fingerprint"]) if row["fingerprint"] else None)
        store.set_meta("source_player:bilibili", {"status": "limited", "checked_at": now,
                       "reason": type(exc).__name__ + ": normal player media unavailable; no login/CAPTCHA bypass"})
        return "source player unavailable"


def capture_next(store, cfg, now):
    """Rotate bounded normal-page reads across enabled sources; no media work here."""
    if store.meta("next_source_capture", 0) > now:
        return None
    from . import native_source
    platforms = [key for key, options in cfg.platforms.items()
                 if options.get("enabled", True) and options.get("safari_player")
                 and not store.meta("platform_disabled:" + key, False)]
    if not platforms:
        return None
    offset = store.meta("source_capture_offset", 0) % len(platforms)
    for platform in platforms[offset:] + platforms[:offset]:
        if platform == "bilibili":
            result = _capture_bilibili(store, cfg, now)
            if result:
                store.set_meta("next_source_capture", now + 60)
                store.set_meta("source_capture_offset", platforms.index(platform) + 1)
                return result
            continue
        if platform not in native_source.CDNS:
            continue
        chosen = None
        for item in store.rows("SELECT id FROM candidates WHERE platform=? AND state IN ('discovered','held','ready') "
                               "ORDER BY CASE WHEN state='ready' THEN 0 ELSE 1 END,"
                               "COALESCE(json_extract(document,'$.source_capture_attempt'),0),published DESC,discovered DESC LIMIT 80", (platform,)):
            row = store.candidate(item["id"])
            doc = row["document"]
            if doc.get("source_capture_retry_at", 0) > now:
                continue
            refresh_x = platform == "x" and now - doc.get("source_metrics", {}).get("observed_at", 0) >= 1800
            have_original = doc.get("original_sha256") and Path(doc.get("original_path", "")).is_file()
            needs_source = not (have_original or doc.get("media_url") or doc.get("local_file"))
            if (ranking.permission(doc, cfg, now) and (refresh_x or needs_source)
                    and now - doc.get("source_capture_attempt", 0) >= 1200
                    and not store.rows("SELECT 1 FROM jobs WHERE item=? AND state='running'", (row["id"],))):
                chosen = row
                break
        if not chosen:
            continue
        row, doc = chosen, chosen["document"]
        store.set_meta("next_source_capture", now + 60)
        store.set_meta("source_capture_offset", platforms.index(platform) + 1)
        doc["source_capture_attempt"] = now
        downloaded = bool(doc.get("original_sha256") and Path(doc.get("original_path", "")).is_file())
        try:
            if not store.budget(platform, "requests", 1, cfg.request_budget - cfg.publishing_request_reserve, now):
                raise Deferred("source request budget exhausted")
            native_source.capture(row, cfg, now)
            _source_succeeded(doc)
            reason = ranking.source_gate(doc, now, cfg)
            if reason:
                raise AccessError(reason)
            store.save_candidate(row["id"], doc, time.time(), state=row["state"] if downloaded else "discovered",
                                 reason=row["reason"] if downloaded else "source media captured; verification queued",
                                 score=row["score"], fingerprint=json.loads(row["fingerprint"]) if row["fingerprint"] else None)
            with store.transaction() as db:
                db.execute("UPDATE candidates SET published=?,creator=? WHERE id=?", (doc["published_at"], doc["creator"], row["id"]))
                observed = doc.get("source_metrics", {})
                if type(observed.get("views")) is int:
                    db.execute("INSERT OR IGNORE INTO observations VALUES(?,?,?)", (row["id"], now, json.dumps({"views": observed["views"]})))
                if not downloaded:
                    db.execute("INSERT INTO jobs(kind,item,due) VALUES('media',?,?) ON CONFLICT(kind,item) DO UPDATE SET "
                               "state='pending',due=excluded.due,attempts=0", (row["id"], now))
            store.set_meta("source_player:" + platform, {"status": "operational", "checked_at": now,
                           "candidate": row["id"], "scope": "observed normal page only"})
            return "source media captured"
        except Exception as exc:
            from ..guards.active_hours import OutsideActiveHours
            from .config import safe_label
            if isinstance(exc, (OutsideActiveHours, Deferred)):
                raise
            reason = safe_label(str(exc)) if isinstance(exc, AccessError) else type(exc).__name__
            _source_failed(doc, now)
            store.save_candidate(row["id"], doc, time.time(), state="held", reason="source player unavailable: " + reason,
                                 score=row["score"], fingerprint=json.loads(row["fingerprint"]) if row["fingerprint"] else None)
            store.set_meta("source_player:" + platform, {"status": "limited", "checked_at": now, "reason": reason})
            return "source player unavailable"
    return None


def related_candidates(links, cfg, source_candidate, now):
    """Visible recommendations supply leads only, never rights or inspection."""
    from .connectors import canonical
    result, seen = [], set()
    if not isinstance(links, list):
        return result
    for link in links[:80]:
        if not isinstance(link, dict):
            continue
        title = str(link.get("title", ""))[:500]
        if not any(alias.casefold() in title.casefold() for aliases in cfg.targets.values() for alias in aliases):
            continue
        if not re.search(r"dance|sing|music|parody|boy.?band|trouble.?maker|跳舞|唱歌|鬼畜|舞蹈|男团|演唱", title, re.I):
            continue
        try:
            raw = urlsplit(str(link.get("url", "")))
            path = raw.path.removeprefix("/en")
            url = canonical("bilibili", raw._replace(path=path, query="", fragment="").geturl())
        except ValueError:
            continue
        if url in seen:
            continue
        if not re.fullmatch(r"BV[A-Za-z0-9]{10}", url.rsplit("/", 1)[-1]):
            continue
        seen.add(url)
        result.append({"source_id": url.rsplit("/", 1)[-1], "canonical_url": url,
                       "creator": "", "title": title, "published_at": None,
                       "access_status": "visible normal-page recommendation",
                       "discovery_evidence": {"url": url, "observed_at": now, "source_candidate": source_candidate,
                                              "method": "visible Safari recommendation link"}})
    # A recommendation shelf can put ten real rally/event dances before the
    # first generated parody. Rank all bounded leads before limiting ingestion;
    # this hint never supplies inspection, cast attribution or permission.
    synthetic = r"(?<![a-z0-9])(?:ai|aigc)(?![a-z0-9])|\b(?:deepfake|synthetic)\b|生成|换脸|合成"
    result.sort(key=lambda item: not bool(re.search(synthetic, item["title"], re.I)))
    return result[:10]


def download_player(doc, destination, cfg, store, now):
    """Download original DASH tracks outside Safari, then remux without altering them."""
    if doc.get("platform") != "bilibili":
        from .native_source import download
        return download(doc, destination, cfg, store, now)
    from . import media
    source = doc["source_download"]
    if (source.get("platform") != "bilibili" or source.get("source_id") != doc["source_id"]
            or now >= source.get("expires_at", 0) or now - source.get("captured_at", 0) > 3600):
        raise AccessError("source player media reference expired or mismatched")
    with tempfile.TemporaryDirectory(prefix="source-", dir=destination.parent) as folder:
        paths = []
        total = 0
        for kind in ("video", "audio"):
            path = Path(folder) / (kind + ".m4s")
            succeeded = False
            for url in source[kind]:
                if total >= cfg.max_download_bytes:
                    raise AccessError("source exceeds aggregate per-file download cap")
                allowance = int(store.reserve_up_to("bilibili", "download_bytes", cfg.max_download_bytes - total,
                                                    cfg.download_budget_bytes, now))
                if not allowance:
                    raise Deferred("daily download budget exhausted")
                started = False
                try:
                    timeout = cfg.task_timeout_seconds
                    if media._job_deadline is not None:
                        timeout = min(timeout, media._job_deadline - time.monotonic())
                    if timeout <= 0:
                        raise TimeoutError("complete source-download job deadline")
                    with path.open("wb") as stream:
                        started = True
                        request(url, hosts={media_host(url)}, headers={"User-Agent": source["user_agent"],
                            "Referer": "https://www.bilibili.com/"}, sink=stream,
                            max_bytes=allowance, timeout=timeout,
                            mime={"video/mp4", "audio/mp4", "application/octet-stream"})
                    succeeded = True
                except AccessError as exc:
                    if allowance < cfg.max_download_bytes - total and str(exc) == "response exceeds byte budget":
                        raise Deferred("daily download budget insufficient") from exc
                except (TimeoutError, OSError):
                    pass
                finally:
                    used = path.stat().st_size if started and path.exists() else 0
                    store.refund_budget("bilibili", "download_bytes", max(0, allowance - used), now)
                if succeeded:
                    break
            if not succeeded:
                raise AccessError("all player-provided source URLs failed; refresh normal page")
            total += path.stat().st_size
            paths.append(path)
        media.ffmpeg(["-protocol_whitelist", "file,pipe", "-i", str(paths[0]), "-i", str(paths[1]),
                "-map", "0:v:0", "-map", "1:a:0", "-c", "copy", "-movflags", "+faststart",
                "-f", "mp4", str(destination)], cfg)
        if destination.stat().st_size > cfg.max_download_bytes:
            raise AccessError("muxed original exceeds download cap")
        destination.chmod(0o444)

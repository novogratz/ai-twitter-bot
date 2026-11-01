"""Read a permitted source player's actual media URLs; download in another worker."""
import json
import math
from pathlib import Path
import re
import tempfile
import time
from urllib.parse import parse_qs, urlsplit

from . import ranking
from .security import AccessError, request


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


def capture_next(store, cfg, now):
    """One short Safari transaction, owned by the publisher; never renders/posts."""
    options = cfg.platforms.get("bilibili", {})
    if (not options.get("enabled", True) or not options.get("safari_player")
            or store.meta("platform_disabled:bilibili", False)
            or store.meta("next_source_capture", 0) > now):
        return None
    store.set_meta("next_source_capture", now + 60)
    candidates = store.rows("SELECT id FROM candidates WHERE platform='bilibili' "
                            "AND state IN ('discovered','held','ready') ORDER BY published DESC,discovered DESC LIMIT 40")
    chosen = None
    for item in candidates:
        row = store.candidate(item["id"])
        doc = row["document"]
        if (ranking.permission(doc, cfg, now) and not doc.get("local_file") and not doc.get("media_url")
                and now - doc.get("source_capture_attempt", 0) >= 1200
                and not store.rows("SELECT 1 FROM jobs WHERE item=? AND state='running'", (row["id"],))):
            chosen = row
            break
    if not chosen:
        return None
    row, doc = chosen, chosen["document"]
    source_id = doc["source_id"]
    if not re.fullmatch(r"BV[A-Za-z0-9]{10}", source_id):
        return None
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
          return {id:d.bvid,title:d.title,creator:d.owner?.name,published:d.pubdate,
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
        doc["source_download"] = plan(payload, source_id, now)
        doc.update(published_at=payload["published"], creator=str(payload.get("creator") or doc["creator"]),
                   title=str(payload.get("title", ""))[:2000], access_status="normal Safari player media available",
                   publication_evidence="Timestamp from the authenticated normal video page; not discovery time")
        downloaded = bool(doc.get("original_sha256"))
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
        store.save_candidate(row["id"], doc, time.time(), state=row["state"],
                             reason="source player unavailable: " + type(exc).__name__, score=row["score"],
                             fingerprint=json.loads(row["fingerprint"]) if row["fingerprint"] else None)
        store.set_meta("source_player:bilibili", {"status": "limited", "checked_at": now,
                       "reason": type(exc).__name__ + ": normal player media unavailable; no login/CAPTCHA bypass"})
        return "source player unavailable"


def download_player(doc, destination, cfg, store, now):
    """Download original DASH tracks outside Safari, then remux without altering them."""
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
                if not store.budget("bilibili", "download_bytes", cfg.max_download_bytes, cfg.download_budget_bytes, now):
                    raise AccessError("daily download budget exhausted")
                try:
                    timeout = cfg.task_timeout_seconds
                    if media._job_deadline is not None:
                        timeout = min(timeout, media._job_deadline - time.monotonic())
                    if timeout <= 0:
                        raise TimeoutError("complete source-download job deadline")
                    with path.open("wb") as stream:
                        request(url, hosts={media_host(url)}, headers={"User-Agent": source["user_agent"],
                            "Referer": "https://www.bilibili.com/"}, sink=stream,
                            max_bytes=cfg.max_download_bytes - total, timeout=timeout,
                            mime={"video/mp4", "audio/mp4", "application/octet-stream"})
                    succeeded = True
                except (AccessError, TimeoutError, OSError):
                    pass
                finally:
                    used = path.stat().st_size if path.exists() else 0
                    store.refund_budget("bilibili", "download_bytes", max(0, cfg.max_download_bytes - used), now)
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

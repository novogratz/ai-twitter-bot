"""Permitted creator-feed adapters; no unofficial login, scraping or Research API."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit, urlunsplit

from .security import AccessError, Deferred, json_request
from .store import dumps

HOSTS = {"instagram": {"www.instagram.com", "instagram.com"},
         "tiktok": {"www.tiktok.com", "tiktok.com"},
         "bilibili": {"www.bilibili.com", "bilibili.com"},
         "rednote": {"www.xiaohongshu.com", "xiaohongshu.com"},
         "x": {"x.com", "www.x.com", "twitter.com", "www.twitter.com"}}
REASONS = {
    "instagram": "Needs a permitted creator feed/provider and licensed original; no Meta access configured.",
    "tiktok": "Needs opted-in creator feed/provider and licensed original; Research Tools are ineligible for commercial use.",
    "bilibili": "Needs authorized creator feed/provider; official Open Platform requires application and user authorization.",
    "rednote": "Needs permitted creator feed/provider; reviewed commerce docs do not establish a public video-search API.",
    "x": "Needs public discovery or an authorized feed; source views and original media must be verified.",
}


def canonical(platform, url):
    part = urlsplit(url)
    if part.scheme != "https" or part.hostname not in HOSTS[platform] or part.username or part.password or part.port:
        raise ValueError("invalid platform source URL")
    patterns = {"instagram": r"/(?:reel|reels|p)/[A-Za-z0-9_-]+/?",
                "tiktok": r"/@[\w.-]+/video/\d+/?",
                "bilibili": r"/video/(?:BV[\w]+|av\d+)/?",
                "rednote": r"/(?:explore|discovery/item)/[A-Za-z0-9]+/?",
                "x": r"/[A-Za-z0-9_]{1,15}/status/[0-9]+/?"}
    if not re.fullmatch(patterns[platform], part.path):
        raise ValueError("source URL must identify a video, not a search/profile")
    host = "x.com" if platform == "x" else "www." + part.hostname.removeprefix("www.")
    return urlunsplit(("https", host, part.path.rstrip("/"), "", ""))


def timestamp(value):
    if value is None:
        return None
    if isinstance(value, (float, int)):
        return datetime.fromtimestamp(value, timezone.utc).timestamp()
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("source timestamp has no timezone")
    return parsed.timestamp()


def queries(cfg):
    terms = ("跳舞", "唱歌", "鬼畜", "舞蹈", "parody", "dance", "singing", "music")
    return [f"{name} {term}" for names in cfg.targets.values() for name in names for term in terms]


class CreatorFeed:
    """A documented local contract, NOT a claimed platform search endpoint.

    An operator-supplied provider executable implements licensed keyword/creator/
    related discovery, or an authorized creator supplies a JSON feed. No provider
    is installed, subscribed to or represented as operational automatically.
    """
    platform = ""

    def __init__(self, cfg):
        self.cfg = cfg
        self.options = cfg.platforms.get(self.platform, {})

    def capability(self):
        if not self.options.get("enabled", True):
            return {"status": "blocked", "reason": "disabled by operator"}
        if self.options.get("public_search") and not (self.options.get("feed") or self.options.get("provider_command")):
            import shutil
            if not shutil.which("codex") or not self.cfg.targets:
                return {"status": "blocked", "reason": "public discovery needs Codex CLI login and configured targets"}
            return {"status": "limited", "reason": "Codex public web discovery only; media access, publication time and permission remain unverified."}
        if not self.options.get("permission_reference"):
            return {"status": "blocked", "reason": REASONS[self.platform]}
        if self.options.get("feed") or self.options.get("provider_command"):
            return {"status": "limited", "reason": "Authorized feed configured; live access and completeness not yet verified."}
        return {"status": "blocked", "reason": REASONS[self.platform]}

    def discover(self, cursor, cfg, store=None, *, fresh=False):
        if self.capability()["status"] == "blocked":
            raise AccessError(self.capability()["reason"])
        if self.options.get("public_search") and not (self.options.get("feed") or self.options.get("provider_command")):
            from .public_discovery import search
            if store is None:
                raise AccessError("public discovery requires the shared budget/queue store")
            return search(store, cfg, self.platform, self.options, cursor, fresh=fresh)
        command = self.options.get("provider_command", [])
        if command:
            if not Path(command[0]).is_absolute():
                raise ValueError("provider executable must be an absolute operator-configured path")
            payload = {"version": 1, "platform": self.platform, "cursor": cursor,
                       "queries": queries(cfg), "creators": self.options.get("creators", []),
                       "related_creators": True, "limit": 40}
            # Metadata is JSON data on stdin. Never interpolate it into a shell/prompt.
            from .media import bounded_command
            data = json.loads(bounded_command(command, payload, cfg.task_timeout_seconds))
        else:
            source = self.options["feed"]
            if source.startswith("https://"):
                host = urlsplit(source).hostname
                if host not in cfg.media_hosts:
                    raise AccessError("creator feed host needs explicit allowlisting")
                data = json_request(source, hosts=cfg.media_hosts, timeout=cfg.task_timeout_seconds)
            else:
                path = Path(source)
                if not path.is_absolute() or path.stat().st_size > 2_000_000:
                    raise AccessError("feed must be an absolute local JSON path under 2 MB")
                data = json.loads(path.read_text())
        if data.get("version") != 1 or not isinstance(data.get("items"), list) or len(data["items"]) > 200:
            raise ValueError("unsupported creator-feed contract")
        return data


class Instagram(CreatorFeed):
    platform = "instagram"


class TikTok(CreatorFeed):
    platform = "tiktok"


class Bilibili(CreatorFeed):
    platform = "bilibili"


class RedNote(CreatorFeed):
    platform = "rednote"


class X(CreatorFeed):
    platform = "x"


ADAPTERS = {c.platform: c for c in (Instagram, TikTok, Bilibili, RedNote, X)}


def ingest(store, platform, items, now, cfg):
    accepted = 0
    for item in items[:200]:
        try:
            # Deliberate field allowlist: source-supplied scores, rights assertions,
            # instructions, evidence, novelty and output paths have no authority.
            url = canonical(platform, item["canonical_url"])
            source_id = str(item["source_id"])
            if not re.fullmatch(r"[\w.-]{1,128}", source_id):
                raise ValueError("invalid source ID")
            published = timestamp(item.get("published_at"))
            if published and (published > now + 300 or now - published > cfg.max_age_hours * 3600):
                continue
            doc = {key: item[key] for key in ("title", "media_url", "local_file", "permission_id", "publication_evidence", "discovery_evidence") if key in item}
            doc.update({"platform": platform, "source_id": source_id, "canonical_url": url,
                        "creator": str(item["creator"])[:128], "published_at": published,
                        "access_status": item.get("access_status", "discovered"), "novelty": {"state": "unchecked"}})
            if not published or not doc.get("publication_evidence"):
                doc["published_at"] = None  # discovery is never proof of upload time
            ident = hashlib.sha256(f"{platform}:{source_id}".encode()).hexdigest()[:32]
            with store.transaction() as db:
                count = db.execute("SELECT COUNT(*) FROM candidates WHERE state IN ('discovered','held','ready')").fetchone()[0]
                if count >= cfg.queue_limit:
                    break
                old = db.execute("SELECT id FROM candidates WHERE (platform=? AND source_id=?) OR canonical_url=?",
                                 (platform, source_id, url)).fetchone()
                if not old:
                    db.execute("INSERT INTO candidates(id,platform,source_id,canonical_url,creator,published,discovered,updated,document) "
                               "VALUES(?,?,?,?,?,?,?,?,?)", (ident, platform, source_id, url, doc["creator"], doc["published_at"], now, now, dumps(doc)))
                    if doc.get("media_url") or doc.get("local_file"):
                        db.execute("INSERT OR IGNORE INTO jobs(kind,item,due) VALUES('media',?,?)", (ident, now))
                    else:
                        db.execute("UPDATE candidates SET state='held',reason='public discovery only; authorized original and upload timestamp required' WHERE id=?", (ident,))
                    accepted += 1
                else:
                    ident = old["id"]
                    previous = db.execute("SELECT state,document FROM candidates WHERE id=?", (ident,)).fetchone()
                    prior = json.loads(previous["document"])
                    # A creator feed can later supply an authorized original for
                    # a search-only candidate. Never overwrite an inspected asset.
                    if (previous["state"] in ("held", "discovered") and not prior.get("original_sha256")
                            and (doc.get("media_url") or doc.get("local_file"))):
                        prior.update(doc)
                        db.execute("UPDATE candidates SET document=?,published=?,updated=?,state='discovered',reason='' WHERE id=?",
                                   (dumps(prior), doc.get("published_at"), now, ident))
                        db.execute("INSERT INTO jobs(kind,item,due) VALUES('media',?,?) ON CONFLICT(kind,item) DO UPDATE SET state='pending',due=excluded.due,attempts=0",
                                   (ident, now))
                metrics = item.get("metrics", {})
                observed = timestamp(item.get("metrics_observed_at"))
                if observed and observed <= now + 60 and now - observed <= cfg.max_age_hours * 3600:
                    clean = {k: metrics.get(k) if type(metrics.get(k)) is int and metrics[k] >= 0 else None
                             for k in ("views", "likes", "shares", "comments")}
                    db.execute("INSERT OR IGNORE INTO observations VALUES(?,?,?)", (ident, observed, dumps(clean)))
                    if platform == "x" and item.get("metrics_evidence") == url and observed <= now:
                        current = json.loads(db.execute("SELECT document FROM candidates WHERE id=?", (ident,)).fetchone()[0])
                        current["source_metrics"] = {"views": clean["views"], "observed_at": observed, "source_url": url}
                        db.execute("UPDATE candidates SET document=? WHERE id=?", (dumps(current), ident))
        except (KeyError, ValueError, TypeError, OverflowError):
            store.event(now, "source_rejected", platform, "invalid metadata record")
    return accepted


def discover(store, platform, now, cfg, *, fresh=False):
    adapter = ADAPTERS[platform](cfg)
    if store.meta("platform_disabled:" + platform, False):
        store.set_meta("source:" + platform, {"status": "blocked", "reason": "disabled by operator"})
        return "blocked"
    if not store.circuit_ready(platform, now):
        return "circuit open"
    if adapter.capability()["status"] == "blocked":
        store.set_meta("source:" + platform, adapter.capability())
        return "blocked"
    if not store.budget(platform, "requests", 1, cfg.request_budget - cfg.publishing_request_reserve, now):
        return "request budget exhausted"
    try:
        result = adapter.discover(store.meta("cursor:" + platform), cfg, store, fresh=fresh)
        count = ingest(store, platform, result["items"], now, cfg)
        store.set_meta("cursor:" + platform, result.get("cursor"))
        # Related creators are suggestions, not automatically authorized sources.
        store.set_meta("related:" + platform, result.get("related_creators", [])[:40])
        store.set_meta("source:" + platform, {"status": result.get("platform_status", "limited"), "checked_at": now,
                       "searched_at": result.get("searched_at"), "cached": result.get("cached", False),
                       "reason": (result.get("access_note") or "Public search checked; candidates require authorized original, verified upload time and actual inspection."
                                  if result.get("public_search") or result.get("cached") else
                                  "Feed read succeeded; coverage limited to configured authorized source."), "accepted": count})
        store.circuit(platform, now, failed=False)
        return "ok"
    except Deferred as exc:
        store.set_meta("source:" + platform, {"status": "limited", "checked_at": now, "reason": str(exc)})
        raise
    except Exception as exc:
        store.circuit(platform, now, failed=True, retry_after=getattr(exc, "retry_after", 0))
        store.set_meta("source:" + platform, {"status": "blocked", "checked_at": now,
                       "reason": f"{type(exc).__name__}: provider unavailable; inspect private provider logs"})
        raise

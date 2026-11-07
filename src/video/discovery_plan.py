"""Persistent, bounded discovery rotation and reserve-aware provider allocation."""
from datetime import datetime, timezone
import json
from pathlib import Path

from . import memory
from .security import Deferred

MODES = ("fresh", "fresh", "archive", "fresh", "new_creators", "fresh", "archive", "fresh", "archive", "fresh")


def operator_text(path):
    if not path:
        return ""
    source = Path(path)
    if source.stat().st_size > 100_000:
        raise ValueError("discovery instruction/query file exceeds bounded size")
    return source.read_text()


def admission(store, cfg, platform, now, *, fresh=False):
    if not cfg.adaptive_discovery:
        return None
    hour = datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%dT%H")
    key = "discovery-hour:" + hour
    if not fresh:
        choices = []
        for name, options in cfg.platforms.items():
            if (not options.get("enabled", True) or not options.get("public_search")
                    or store.meta("platform_disabled:" + name, False) or not store.circuit_ready(name, now)):
                continue
            cached = store.meta("public_discovery:" + name, {}) or {}
            if cached.get("next", 0) > now:
                continue
            weight = options.get("weight", 1)
            if type(weight) not in (int, float) or not 0 < weight <= 100:
                raise ValueError("discovery platform weight must be 0..100")
            stats = store.meta("discovery-allocation:" + name, {}) or {}
            count = stats.get("calls", 0) if stats.get("day") == hour[:10] else 0
            choices.append(((count + 1) / weight, cached.get("checked_at", 0), name))
        if choices and min(choices)[2] != platform:
            raise Deferred("another available discovery source has the next bounded turn", retry_after=60)
    if not store.budget("codex-discovery", key, 1, cfg.discovery_calls_per_hour, now):
        raise Deferred("hourly discovery budget reserved; media inspection keeps its capacity", retry_after=300)
    return key


def plan(store, cfg, platform, options, cursor, now):
    cursor = dict(cursor or {})
    turn = int(cursor.get("turn", 0))
    mode = MODES[turn % len(MODES)]
    from .schedule import local
    today = local(datetime.fromtimestamp(now, timezone.utc)).date().isoformat()
    deep = bool(mode == "archive" and store.meta("discovery-deep-day") != today)
    lane = ("concept", "creator", "source_chain")[turn % 3]
    source = None
    if lane == "source_chain":
        choices = store.rows("SELECT id,document FROM candidates WHERE state='held' "
                             "AND json_extract(document,'$.original_sha256') IS NOT NULL ORDER BY updated LIMIT 80")
        seen = cursor.get("source_chain_seen", [])
        for row in choices:
            doc = json.loads(row["document"])
            if row["id"] in seen or memory.refusal(store, doc):
                continue
            source = {key: doc.get(key) for key in ("canonical_url", "creator", "title", "probe")}
            source["candidate"] = row["id"]
            seen = (seen + [row["id"]])[-80:]
            cursor["source_chain_seen"] = seen
            break
        if source is None:
            lane = "concept"
    creators = list(options.get("creators", []))
    creator = creators[(turn // 3) % len(creators)] if creators and lane == "creator" else None
    if lane == "creator" and not creator:
        lane = "concept"
    profiles = dict(cursor.get("profiles", {}))
    creator_progress = profiles.get(creator, {}) if creator else {}
    bank = [line.strip() for line in operator_text(cfg.query_bank_file).splitlines() if line.strip() and not line.startswith("#")]
    vocabulary = [bank[(turn * 3 + i) % len(bank)] for i in range(3)] if bank else []
    seen = store.rows("SELECT canonical_url FROM candidates ORDER BY discovered DESC LIMIT 100")
    result = {"lane": lane, "mode": mode, "deep": deep, "max_leads": 120 if deep else 30,
              "max_searches": 6 if deep else 3, "vocabulary": vocabulary,
              "creator": creator, "creator_progress": creator_progress,
              "creator_identity_note": "operator seed name; verify profile URL, never manufacture it",
              "source_chain": source, "personal_history": memory.context(store),
              "already_queued_urls": [row["canonical_url"] for row in seen],
              "history_scope": {"archive_complete": store.meta("history_import_complete", False),
                                "seed": store.meta("personal_memory_coverage", {})}}
    if creator:
        profiles[creator] = {"last_search_at": now, "mode": mode, "passes": creator_progress.get("passes", 0) + 1,
                             "scope": "bounded search, not an exhaustive profile crawl"}
    cursor.update(turn=turn + 1, profiles=profiles, plan_day=today)
    return result, cursor


def completed(store, platform, plan, now):
    day = datetime.fromtimestamp(now, timezone.utc).date().isoformat()
    old = store.meta("discovery-allocation:" + platform, {}) or {}
    store.set_meta("discovery-allocation:" + platform, {"day": day,
        "calls": old.get("calls", 0) + 1 if old.get("day") == day else 1, "last": now})
    if plan.get("deep"):
        from .schedule import local
        store.set_meta("discovery-deep-day", local(datetime.fromtimestamp(now, timezone.utc)).date().isoformat())

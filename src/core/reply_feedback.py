"""Confirmed Reply receipts and sampled outcomes, never a publication guard.

Every captured own URL joins the append-only engagement CSV. A deterministic
one-in-five sample gets bounded 1h/24h observations; missing counters stay
unknown. Losing this disposable report cannot authorize a second Reply.
"""
import csv
import hashlib
import json
import re
import threading
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from . import config, settings
from .logger import log
from .state_store import DISPOSABLE, StateFile, StatePath
from ..guards import active_hours
from ..x import x_urls

FEEDBACK = StateFile("reply_feedback.json", {}, DISPOSABLE)
REPORT = StateFile("reply_performance.json", {}, DISPOSABLE)
REPORT_TEXT = StatePath("reply_performance.md")
_receipts: dict[str, str] = {}
_lock = threading.Lock()
SAMPLE_EVERY = 5
WINDOWS = {"1h": (1, 3), "24h": (24, 36)}


def topic(text: str) -> str:
    """Coarse topical cohorts, descriptive only; not a relevance filter."""
    for name, pattern in (("video", r"\b(video|animation|filmmaking|motion)\b"),
                          ("images", r"\b(images?|diffusion|rendering)\b"),
                          ("agents_coding", r"\b(agents?|coding|code|workflow)\b"),
                          ("compute", r"\b(gpus?|chips?|inference|training|latency)\b"),
                          ("models", r"\b(models?|llms?|benchmark|reasoning)\b")):
        if re.search(pattern, text, re.I):
            return name
    return "other"


def stamp(value):
    try:
        at = datetime.fromisoformat(value)
        return at.replace(tzinfo=ZoneInfo(config.BOT_TIMEZONE)) if at.tzinfo is None else at
    except (ValueError, TypeError):
        return None


def sampled(parent: str) -> bool:
    key = x_urls.status_id(parent)
    return bool(key) and int(hashlib.sha256(key.encode()).hexdigest(), 16) % SAMPLE_EVERY == 0


def publication_url(parent: str) -> str:
    with _lock:
        return _receipts.get(x_urls.status_id(parent), "")


def record_confirmed(parent: str, text: str, own_url: str = "", now=None):
    """Called only after SHIPPED and its ledger row, while still on the page."""
    from . import account
    now = now or active_hours.now_local()
    sid = x_urls.status_id(parent)
    own_url = x_urls.canonical_status_url(own_url)
    if (x_urls.author(own_url) not in account.own_handles()
            or x_urls.status_id(own_url) == sid):
        own_url = ""
    with _lock:
        _receipts[sid] = own_url
        while len(_receipts) > 100:
            _receipts.pop(next(iter(_receipts)))
    if not sampled(parent):
        return
    age = x_urls.age(parent, now)
    words = len(text.split())
    row = dict(parent=parent, url=own_url, text=text, sent_at=now.isoformat(),
               parent_age_minutes=round(age.total_seconds() / 60, 1) if age is not None else None,
               length="brief" if words <= 8 else "one_line" if words <= 22 else "longer",
               hour=now.astimezone(ZoneInfo(config.BOT_TIMEZONE)).hour,
               source="", provider="", model="", topic="other", observations={})

    def save(rows):
        cutoff = now - timedelta(days=3)
        kept = {k: v for k, v in rows.items() if isinstance(v, dict)
                and (at := stamp(v.get("sent_at"))) and at >= cutoff}
        kept.setdefault(sid, row)
        return kept
    FEEDBACK.update(save)


def annotate(parent: str, **metadata):
    if not sampled(parent):
        return
    def save(rows):
        row = rows.get(x_urls.status_id(parent))
        if isinstance(row, dict):
            row.update({k: metadata[k] for k in ("source", "provider", "model", "topic") if k in metadata})
        return rows
    FEEDBACK.update(save)


def due(rows: dict, now) -> list:
    """Due samples, earliest deadlines first. A failed read backs off 20 min."""
    pending = []
    for sid, row in rows.items():
        if not isinstance(row, dict) or not row.get("url"):
            continue
        at = stamp(row.get("sent_at"))
        if not at:
            continue
        attempted = stamp(row.get("last_attempt"))
        if attempted and now - attempted < timedelta(minutes=20):
            continue
        hours = (now - at).total_seconds() / 3600
        for window, (start, end) in WINDOWS.items():
            if window not in row.get("observations", {}) and start <= hours <= end:
                pending.append((at + timedelta(hours=end), sid, window, row))
    return sorted(pending, key=lambda p: (p[0], p[1]))


def _counter(value):
    return value if type(value) is int and value >= 0 else None


def _save_observation(sid, window, observed, now):
    def save(rows):
        row = rows.get(sid)
        if not isinstance(row, dict):
            return rows
        row["last_attempt"] = now.isoformat()
        # A missing or different status is not an observation of this Reply.
        if (not observed or x_urls.canonical_status_url(observed.get("url", "")) != row["url"]):
            return rows
        likes, views = _counter(observed.get("likes")), _counter(observed.get("views"))
        if likes is None and views is None:
            return rows
        row.setdefault("observations", {}).setdefault(window, dict(
            observed_at=now.isoformat(), age_hours=round((now - stamp(row["sent_at"])).total_seconds() / 3600, 2),
            likes=likes, views=views,
            likes_per_1000_views=round(likes * 1000 / views, 2) if likes is not None and views else None))
        return rows
    FEEDBACK.update(save)


def _history(now):
    """Positional CSV read: legacy headers have fewer columns than newer rows."""
    rows = []
    try:
        with open(config.ENGAGEMENT_LOG_FILE, newline="") as handle:
            for raw in csv.reader(handle):
                if len(raw) < 4 or raw[1] != "reply":
                    continue
                at = stamp(raw[0])
                if at and now - timedelta(days=7) <= at <= now:
                    rows.append(dict(at=at, source=raw[4] if len(raw) > 4 else "",
                                     url=raw[9] if len(raw) > 9 else ""))
    except FileNotFoundError:
        pass
    return rows


def _active_seconds(now):
    wake = now.replace(hour=active_hours.WAKE.hour, minute=active_hours.WAKE.minute, second=0, microsecond=0)
    end = active_hours.bedtime(wake)
    elapsed_end = min(max(now, wake), end)
    total, elapsed = (end - wake).total_seconds(), (elapsed_end - wake).total_seconds()
    for hour in range(24):
        window = active_hours.break_window(wake.replace(hour=hour))
        if window:
            start, stop = window
            total -= max(0, (min(stop, end) - max(start, wake)).total_seconds())
            elapsed -= max(0, (min(stop, elapsed_end) - max(start, wake)).total_seconds())
    return total, elapsed


def summarize(rows, history, followers, now=None):
    now = now or active_hours.now_local()
    today = [r for r in history if r["at"].astimezone(now.tzinfo).date() == now.date()]
    total, elapsed = _active_seconds(now)
    low, high = sorted((settings.get("REPLY_DAILY_TARGET_MIN"), settings.get("REPLY_DAILY_TARGET_MAX")))
    samples = [r for r in rows.values() if isinstance(r, dict)]
    cohorts = {}
    for row in samples:
        # Compare length within the same source, parent freshness, hour and
        # observation window. Descriptive evidence, not a randomized trial.
        age = row.get("parent_age_minutes")
        freshness = "unknown" if age is None else "first_hour" if age <= 60 else "older"
        for window, observed in row.get("observations", {}).items():
            likes, views = _counter(observed.get("likes")), _counter(observed.get("views"))
            if likes is None or not views:
                continue
            key = (row.get("source", "").split("/")[0], freshness, row.get("hour"), row.get("length"),
                   window, row.get("topic", "other"))
            c = cohorts.setdefault(key, dict(source=key[0], freshness=freshness, hour=key[2], length=key[3],
                                            window=window, topic=key[5], replies=0, likes=0, views=0))
            c["replies"] += 1
            c["likes"] += likes
            c["views"] += views
    for c in cohorts.values():
        c["likes_per_1000_views"] = round(c["likes"] * 1000 / c["views"], 2)
        c["enough_to_compare"] = c["replies"] >= 10 and c["views"] >= 1000
    follower_samples = sorted((stamp(r.get("ts")), r.get("count")) for r in followers
                              if isinstance(r, dict) and type(r.get("count")) is int
                              and (at := stamp(r.get("ts"))) and at.astimezone(now.tzinfo).date() == now.date()
                              and at <= now)
    delta = follower_samples[-1][1] - follower_samples[0][1] if len(follower_samples) >= 2 else None
    counts = Counter(r["at"].astimezone(now.tzinfo).date().isoformat() for r in history)
    return dict(as_of=now.isoformat(), replies_today=len(today), daily_targets=[low, high],
                target_is_advisory=True, active_hours=round(total / 3600, 2),
                required_replies_per_active_hour=[round(n / (total / 3600), 1) for n in (low, high)],
                projected_daily_replies=round(len(today) * total / elapsed) if elapsed >= 3600 else None,
                projection_basis="Elapsed scheduled waking time, including downtime; not a promise or a catch-up budget",
                replies_by_day=dict(sorted(counts.items())), receipts_7d=sum(bool(r["url"]) for r in history),
                replies_7d=len(history), sample_every=SAMPLE_EVERY, samples=len(samples),
                sample_urls=sum(bool(r.get("url")) for r in samples),
                observed={w: sum(w in r.get("observations", {}) for r in samples) for w in WINDOWS},
                eligible={w: sum(bool(at := stamp(r.get("sent_at"))) and now >= at + timedelta(hours=b[0])
                                 for r in samples) for w, b in WINDOWS.items()},
                follower_change_between_today_samples=delta, follower_sample_count=len(follower_samples),
                followers_attributed_to_replies=None, cohorts=list(cohorts.values()))


def run_reply_report():
    """At most twelve read-only status visits per pass; no model or social write."""
    from ..x.reply_metrics import observe
    from ..guards.follow_policy import FOLLOWER_HISTORY
    active_hours.require_active()
    now = active_hours.now_local()
    for _, sid, window, row in due(FEEDBACK.read(), now)[:12]:
        active_hours.require_active()
        try:
            observed = observe(row["url"])
        except active_hours.OutsideActiveHours:
            raise
        except Exception:
            log.exception("[REPLY-FEEDBACK] Observation unavailable for %s", row["url"])
            observed = None
        _save_observation(sid, window, observed, active_hours.now_local())
    report = summarize(FEEDBACK.read(), _history(now), FOLLOWER_HISTORY.read(), now)
    REPORT.write(report)
    Path(REPORT_TEXT).write_text(
        "# Reply performance\n\n"
        f"Updated: {report['as_of']}\n\n"
        f"Confirmed replies today: {report['replies_today']}. Advisory target: {report['daily_targets']}.\n\n"
        f"Projected full-day replies: {report['projected_daily_replies']}. {report['projection_basis']}.\n\n"
        f"Own URL coverage over seven days: {report['receipts_7d']}/{report['replies_7d']}. "
        f"One-in-{SAMPLE_EVERY} outcome sample: {report['samples']} replies; "
        f"1h observations {report['observed']['1h']}/{report['eligible']['1h']}, "
        f"24h observations {report['observed']['24h']}/{report['eligible']['24h']}.\n\n"
        "Missing counters are unknown. Observations occur at 1–3h and 24–36h; actual ages are saved. "
        "Views are public counters, not unique people. Likes per 1,000 views describe observed samples. "
        "Source/freshness/hour/length cohorts are observational, not evidence of causation.\n\n"
        f"Follower change between today's samples: {report['follower_change_between_today_samples']}. "
        "Follower growth cannot be attributed to individual replies.\n\n"
        "```json\n" + json.dumps(report["cohorts"], indent=2) + "\n```\n")
    log.info("[REPLY-FEEDBACK] %s confirmed today; target %s; observations %s; follower delta %s.",
             report["replies_today"], report["daily_targets"], report["observed"],
             report["follower_change_between_today_samples"])
    return report

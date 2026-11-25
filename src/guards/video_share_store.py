"""Other accounts' viral AI videos posted with our short take: claims, windows, spacing.

Operator's coach, 2026-11-25: "quote big viral AI videos with a 2-4 word take ...
right click on the actual video ... and click post ... always posts viral video
between 8 and 9, 12 to 1 pm, 5 to 6 and around 10 PM". A window is an
opportunity: nothing is posted without a reviewed clip. A claim is permanent,
by status and by media, so a video is never shared twice.
"""
from datetime import datetime, timedelta
import re

from ..core import account, settings
from ..core.state_errors import StateUnreadable
from ..core.state_store import GUARDED, StateFile
from ..x import x_urls
from . import active_hours

STATE = StateFile("video_shares.json", {}, GUARDED)


def entries():
    data = STATE.read()
    try:
        for sid, row in data.items():
            if (x_urls.status_id(row["url"]) != sid or row["status"] not in ("pending", "shipped")
                    or not datetime.fromisoformat(row["ts"]).tzinfo or not isinstance(row["take"], str)
                    or not isinstance(row["media_id"], str)):
                raise ValueError("invalid share")
    except (TypeError, ValueError, KeyError, AttributeError) as exc:
        raise StateUnreadable("Video share history malformed; preserve and repair it") from exc
    return data


def contains(url, media_id=""):
    data = entries()
    return x_urls.status_id(url) in data or bool(media_id and any(r["media_id"] == media_id for r in data.values()))


def windows():
    """[(start minute, end minute, count)] of the Toronto day; malformed parts are ignored."""
    found = []
    for part in settings.get("VIDEO_SHARE_WINDOWS").split(","):
        match = re.fullmatch(r"\s*(\d\d):(\d\d)-(\d\d):(\d\d)=(\d{1,2})\s*", part)
        if match:
            a, b, c, d, count = map(int, match.groups())
            if a < 24 and c < 24 and b < 60 and d < 60 and a * 60 + b < c * 60 + d:
                found.append((a * 60 + b, c * 60 + d, count))
    return found


def window(now, *, lead=0):
    """The window open at `now`, or one opening within `lead` minutes."""
    minute = now.hour * 60 + now.minute
    return next((w for w in windows() if w[0] - lead <= minute < w[1]), None)


def _times(data, now):
    return [datetime.fromisoformat(r["ts"]).astimezone(now.tzinfo) for r in data.values()]


def eligible(url):
    from .reply_admission import is_blocked_account
    canonical = x_urls.canonical_status_url(url)
    age = x_urls.age(canonical) if canonical else None
    return bool(canonical and x_urls.author(canonical) not in account.own_handles()
                and not is_blocked_account(x_urls.author(canonical)) and age is not None
                and timedelta(0) <= age <= timedelta(hours=settings.get("VIDEO_SHARE_MAX_AGE_HOURS")))


def refusal(url="", media_id="", *, preparing=False):
    """Why nothing may be shared now. `preparing` asks only whether a review is worth starting."""
    if not settings.get("VIDEO_SHARE_ENABLED"):
        return "video shares disabled"
    now = active_hours.now_local()
    data = entries()
    if url and (not eligible(url) or contains(url, media_id)):
        return "video already shared, too old or not shareable"
    times = _times(data, now)
    if sum(t.date() == now.date() for t in times) >= settings.get("VIDEO_SHARE_DAILY_CAP"):
        return "video share daily cap reached"
    opened = window(now, lead=30 if preparing else 0)
    if not opened:
        return "outside the video share windows"
    start = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(minutes=opened[0])
    if sum(start <= t < start + timedelta(minutes=opened[1] - opened[0]) for t in times) >= opened[2]:
        return "this window's video shares are used"
    if preparing:
        return ""
    # An uncertain submission holds the next one for half an hour; it is never sent again.
    if any(r["status"] == "pending" and (now - datetime.fromisoformat(r["ts"])).total_seconds() < 1800 for r in data.values()):
        return "uncertain video share held"
    gap = settings.get("VIDEO_SHARE_SPACING_MINUTES") * 60
    latest = [t.timestamp() for t in times]
    try:
        from ..video.config import legacy_usage
        if own := legacy_usage(now.timestamp())[1]:
            latest.append(own)
    except Exception:
        return "own video history unreadable"
    if latest and now.timestamp() - max(latest) < gap:
        return "video share spacing"
    return ""


def claim(url, take, media_id):
    with STATE._lock:
        data = entries()
        if contains(url, media_id):
            return False
        data[x_urls.status_id(url)] = dict(url=x_urls.canonical_status_url(url), status="pending", take=take,
                                           media_id=media_id, ts=active_hours.now_local().isoformat())
        STATE.write(data)
        return True


def settle(url, *, shipped):
    """Confirm a claim, or release one that provably never reached X."""
    with STATE._lock:
        data = entries()
        sid = x_urls.status_id(url)
        if sid in data:
            if shipped:
                data[sid]["status"] = "shipped"
            else:
                del data[sid]
            STATE.write(data)

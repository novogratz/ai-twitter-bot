"""Helpers shared by test files of several packages."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from src.editorial import editorial_bot as editorial
from src.guards import action_guard as ag, active_hours as hours
from src.x import x_urls


TORONTO = ZoneInfo("America/Toronto")


def clock(monkeypatch, value):
    monkeypatch.setattr(hours, "now_local", lambda: value)
    monkeypatch.setattr(ag, "now_local", lambda: value)
    monkeypatch.setattr(editorial, "now_local", lambda: value)


def stop_requested(monkeypatch):
    import threading
    from src.guards import active_hours

    stop = threading.Event()
    stop.set()
    monkeypatch.setattr(active_hours, "_STOP", stop)


def url(author, n=2063500000000000200):
    return f"https://x.com/{author}/status/{n}"


def numbered_url(n, author="someone"):
    return f"https://x.com/{author}/status/20635000000000{n:05d}"


def fresh(handle, minutes=5, n=0):
    """A status URL posted `minutes` ago; `n` keeps URLs distinct."""
    ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000) - minutes * 60_000
    return f"https://x.com/{handle}/status/{((ms - x_urls._TWITTER_EPOCH_MS) << 22) + n}"


SEARCH = "https://x.com/search?q=gpu&f=live"
FRESH = "https://x.com/infra_one/status/2063500000000000201"
OWN_BEST = "https://x.com/TheAIShrink/status/2063500000000000301"


class SearchPage:
    """Answers `_page_posts` like `_POSTS_JS` would on a search page."""

    def __init__(self, posts, page=SEARCH):
        self.page = page
        self.posts = [dict(p) for p in posts]
        self.clicks = []
        self.click_sticks = True
        self.stop_after_clicks = None
        self.on_click = lambda: None

    def __call__(self, mode, target_id=""):
        from src.guards.active_hours import OutsideActiveHours
        from src.x import x_urls

        if mode == "list":
            return {"page": self.page, "posts": [p["url"] for p in self.posts]}
        if mode == "press" and self.stop_after_clicks is not None \
                and len(self.clicks) >= self.stop_after_clicks:
            raise OutsideActiveHours("stop requested")
        post = next((p for p in self.posts if x_urls.status_id(p["url"]) == target_id), None)
        if post is None:
            return {"url": "", "result": "failed"}
        if post["liked"]:
            return {"url": post["url"], "result": "already_liked"}
        if mode != "press":
            return {"url": post["url"], "result": "not_liked"}
        self.clicks.append(post["url"])
        post["liked"] = self.click_sticks
        self.on_click()
        return {"url": post["url"], "result": "clicked"}


def pin_rows():
    from src.guards import action_guard
    return [r for r in action_guard._load_ledger() if r["action"] == action_guard.PIN]

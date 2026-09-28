"""Helpers shared by test files of several packages."""
import json
import re
import urllib.parse
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from src.core.llm_client import LLMResult
from src.editorial import editorial_bot as editorial
from src.guards import action_guard as ag, active_hours as hours
from src.x import page_session, x_urls


TORONTO = ZoneInfo("America/Toronto")
USAGE_LIMIT = "You've hit your usage limit. Upgrade to Pro or try again at May 16th, 2099 9:22 PM."


class FakeAdapter:
    """Stands in for one provider's adapter in `llm_client.ADAPTERS`:
    records each request in `calls`, shared by all the fakes, and answers
    its `answers` in turn, the last one for good. An answer is raw provider
    output or an LLMResult."""

    def __init__(self, name, calls):
        self.name, self.calls = name, calls
        self.answers = [LLMResult(1, "", f"{name} was not expected")]

    def __call__(self, request):
        self.calls.append((self.name, request))
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        return answer if isinstance(answer, LLMResult) else LLMResult(0, answer, "")


def clock(monkeypatch, value):
    monkeypatch.setattr(hours, "now_local", lambda: value)
    monkeypatch.setattr(ag, "now_local", lambda: value)
    monkeypatch.setattr(editorial, "now_local", lambda: value)


def scheduled_job(job_id):
    """The callable the scheduler runs for `job_id`, wrappers included."""
    import main
    return main.build_scheduler().get_job(job_id).func


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


_POSTS_CALL = re.compile(r'\("(\w+)", "(\d*)"\)\s*$')


def posts_script(page, js):
    """The answer to the `_POSTS_JS` call in `js` of `page`, a SearchPage or
    any callable of (mode, target_id): a MemoryBrowser page is
    `lambda js: posts_script(page, js)`."""
    call = _POSTS_CALL.search(js)
    return json.dumps(page(call.group(1), call.group(2))) if call else ""


def like_searches(browser, page):
    """Put `page` on `browser` at every search URL like_job may open."""
    from src.core import account
    for query in account.current().searches.likes:
        for tab in ("top", "live"):
            browser.pages[f"https://x.com/search?q={urllib.parse.quote(query)}&f={tab}"] = page


def pin_rows(ledger):
    return [r for r in ledger.rows if r["action"] == ag.PIN]


def key_kind(applescript):
    """The write step a keyboard script is: "submit", "reply_key", or
    "keys" for any other."""
    from src.x import twitter_client
    if applescript == twitter_client._SUBMIT_KEYSTROKE:
        return "submit"
    if 'keystroke "r"' in applescript:
        return "reply_key"
    return "keys"


class WritePage(page_session.MemoryBrowser):
    """A MemoryBrowser for the write path, whose page URLs carry the text:
    every page opens, its scripts answer `answers` in turn, "" once
    exhausted, and a step whose kind is in `fail` fails. The kinds are
    "open", "close", "activate", "paste", those of `key_kind`, and
    `script_kind(js)` for a script. `before` receives each step's kind
    before it acts, to trace it or raise a stop. `fail` and `answers` stay
    the caller's objects, so a test may change them between writes."""

    def __init__(self, answers=None, fail=None, before=lambda kind: None,
                 script_kind=lambda js: "js"):
        super().__init__()
        self.answers = [] if answers is None else answers
        self.fail = set() if fail is None else fail
        self.before, self.script_kind = before, script_kind
        self.key_timeouts = []

    def _ok(self, kind):
        self.before(kind)
        return kind not in self.fail

    def open(self, url):
        self.opened.append(url)
        if not self._ok("open"):
            return False
        self.front = url
        return True

    def close(self):
        self.before("close")
        super().close()

    def activate(self):
        self.activations += 1
        return self._ok("activate")

    def paste(self, text):
        self.pasted.append(text)
        return self._ok("paste")

    def keys(self, applescript, timeout_s):
        self.pressed.append(applescript)
        self.key_timeouts.append(timeout_s)
        return self._ok(key_kind(applescript))

    def run_js(self, js, timeout_s, log_prefix, activate, raise_timeout):
        self.scripts.append(page_session.Script(self.front, js, timeout_s, log_prefix, activate,
                                                raise_timeout))
        self.before(self.script_kind(js))
        return self.answers.pop(0) if self.answers else ""

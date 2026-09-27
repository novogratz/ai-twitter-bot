"""Page session: the one way a job reads or acts on an X page.

`session(tag)` takes the Safari lock for its whole life. `page.open(url)`
opens the page on demand: a page that does not open raises `PageNotOpened`
before any read. A job that catches it and goes on still reads nothing:
until an open succeeds, `run_js`, `read_json`, `keys` and `scroll` raise
`PageNotOpened` too, since the front tab is another page. On every path out
of the session, nominal or raising, each tab it opened is closed once.

A session opened inside another one on the same thread is nested: it shares
the outer session's page, opens nothing and closes nothing. Without an
`open` it reads the outer page, and refuses to while the outer open is in
failure. Its `open(url)` checks that the outer session has that page open,
trailing slash and case aside, and raises `PageNotOpened` otherwise: when
the outer session opened nothing, when its open failed, or when it opened
another URL. The nested page then reads nothing either.

A failed open still closes the front tab once, as the writes do: a timed-out
open may have opened its page all the same. Safari's AppleScript gives a
tab no lasting identifier, so the close acts on the front tab, not on the
tab the session opened.

At bedtime or on a stop, the close goes through `safari._run_applescript`,
whose `require_active()` refuses it: the tab stays open until the next Safari
restart and `OutsideActiveHours` reaches the job. Whether to close it anyway
is the Operator's open question of issue #250. The error a job raised
before that close is logged first, so the refusal does not hide it.

Two adapters: `SafariBrowser` drives Safari through the `safari` module, so
the test walls reach it; `MemoryBrowser` scripts pages by URL for tests and
records opens, waits, scrolls, scripts, keys and closes, without waiting.
`BROWSER`, read when a session starts, picks the adapter.
"""
import contextlib
import json
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..core.logger import log
from . import safari


class PageNotOpened(Exception):
    """The page a session asked for did not open: the front tab is another
    page, and nothing may be read or pressed there."""


class Browser(Protocol):
    def open(self, url: str) -> bool:
        """Open `url` in a new front tab; False when it did not open."""

    def close(self) -> None:
        """Close the front tab."""

    def wait(self, seconds: float) -> None:
        """Let the page load for `seconds`."""

    def scroll(self) -> None:
        """Scroll the front tab down one step."""

    def run_js(self, js: str, timeout_s: float, log_prefix: str, activate: bool,
               raise_timeout: bool) -> str:
        """Run `js` in the front tab and return its answer, "" on failure."""

    def keys(self, applescript: str, timeout_s: float) -> bool:
        """Run a System Events keyboard script; False when it failed."""


class SafariBrowser:
    def open(self, url: str) -> bool:
        return safari.open_url(url)

    def close(self) -> None:
        safari.close_front_tab()

    def wait(self, seconds: float) -> None:
        time.sleep(seconds)

    def scroll(self) -> None:
        safari._scroll_page()

    def run_js(self, js: str, timeout_s: float, log_prefix: str, activate: bool,
               raise_timeout: bool) -> str:
        return safari._run_js(js, timeout_s, log_prefix=log_prefix, activate=activate,
                              raise_timeout=raise_timeout)

    def keys(self, applescript: str, timeout_s: float) -> bool:
        return safari._run_applescript(applescript, timeout_s=timeout_s)


@dataclass
class Script:
    """One page script a MemoryBrowser answered."""
    url: str
    js: str
    timeout_s: float
    log_prefix: str
    activate: bool
    raise_timeout: bool


@dataclass
class MemoryBrowser:
    """Pages scripted by URL: `pages[url]` lists the answers the page gives
    its scripts in turn, "" once exhausted; an answer that is an exception
    is raised. A page may instead be a function of the script that returns
    its answer. A URL without a page does not open."""
    pages: dict[str, list | Callable[[str], str]] = field(default_factory=dict)
    opened: list[str] = field(default_factory=list)
    closed: int = 0
    waits: list[float] = field(default_factory=list)
    scrolls: int = 0
    scripts: list[Script] = field(default_factory=list)
    pressed: list[str] = field(default_factory=list)
    front: str = ""

    def open(self, url: str) -> bool:
        self.opened.append(url)
        if url not in self.pages:
            return False
        self.front = url
        return True

    def close(self) -> None:
        self.closed += 1
        self.front = ""

    def wait(self, seconds: float) -> None:
        self.waits.append(seconds)

    def scroll(self) -> None:
        self.scrolls += 1

    def run_js(self, js: str, timeout_s: float, log_prefix: str, activate: bool,
               raise_timeout: bool) -> str:
        self.scripts.append(Script(self.front, js, timeout_s, log_prefix, activate,
                                   raise_timeout))
        page = self.pages.get(self.front, [])
        if callable(page):
            answer = page(js)
        else:
            answer = page.pop(0) if page else ""
        if isinstance(answer, BaseException):
            raise answer
        return answer

    def keys(self, applescript: str, timeout_s: float) -> bool:
        self.pressed.append(applescript)
        return True


BROWSER: Browser | None = None

_active = threading.local()


def _same_page(url: str, opened: str | None) -> bool:
    return opened is not None and \
        url.strip().rstrip("/").lower() == opened.strip().rstrip("/").lower()


class Page:
    """The page of one session. Its reads and keys act on the front tab."""

    def __init__(self, browser: Browser, tag: str, outer: "Page | None"):
        self._browser = browser
        self._tag = tag
        self._outer = outer
        self._opens = 0
        self._url: str | None = None
        self._refused: str | None = None

    def open(self, url: str, settle_s: float = 0) -> None:
        """Open `url` and wait `settle_s` for it to load. A nested session
        opens nothing: its page is the outer session's, which must be `url`."""
        if self._outer is not None:
            if not _same_page(url, self._outer._url):
                self._refuse(url, "Outer session does not have this page open")
            self._refused = None
            return
        self._opens += 1
        self._url = None
        if not self._browser.open(url):
            self._refuse(url, "Page did not open")
        self._url, self._refused = url, None
        if settle_s:
            self._browser.wait(settle_s)

    def _refuse(self, url: str, reason: str) -> None:
        self._refused = url
        log.info(f"[{self._tag}] {reason}; nothing read: {url[:120]}")
        raise PageNotOpened(url)

    def _check_open(self) -> None:
        refused = self._refused or (self._outer and self._outer._refused)
        if refused:
            raise PageNotOpened(refused)

    def wait(self, seconds: float) -> None:
        self._browser.wait(seconds)

    def scroll(self, times: int = 1) -> None:
        self._check_open()
        for _ in range(times):
            self._browser.scroll()

    def run_js(self, js: str, timeout_s: float = 15, *, activate: bool = False,
               raise_timeout: bool = False) -> str:
        """The script's answer, "" when osascript failed; failures are
        logged under the session's tag."""
        self._check_open()
        return self._browser.run_js(js, timeout_s, f"[{self._tag}]", activate, raise_timeout)

    def read_json(self, js: str, timeout_s: float = 15, *, activate: bool = False) -> Any:
        """The script's answer parsed as JSON, None when it is empty or does
        not parse."""
        raw = self.run_js(js, timeout_s, activate=activate)
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            log.info(f"[{self._tag}] Unreadable page answer: {raw[:80]!r}")
            return None

    def keys(self, applescript: str, timeout_s: float = safari.KEYSTROKE_TIMEOUT_S) -> bool:
        self._check_open()
        return self._browser.keys(applescript, timeout_s)


@contextlib.contextmanager
def session(tag: str) -> Iterator[Page]:
    """Hold the Safari lock and yield a Page; `tag` names the session in the
    log and prefixes its scripts' failure lines."""
    browser = BROWSER if BROWSER is not None else SafariBrowser()
    with safari._safari_lock:
        outer = getattr(_active, "page", None)
        page = Page(browser, tag, outer)
        if outer is None:
            _active.page = page
        try:
            yield page
        except Exception as exc:
            if page._opens and not isinstance(exc, PageNotOpened):
                log.warning(f"[{tag}] Session failed, closing its tab: "
                            f"{type(exc).__name__}: {exc}")
            raise
        finally:
            if outer is None:
                _active.page = None
            for _ in range(page._opens):
                browser.close()

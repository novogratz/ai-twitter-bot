"""Safari and AppleScript primitives shared by the X reading and write
modules: the Safari lock, AppleScript runs, paste, tab and keyboard moves.

Other modules call the walled primitives (`_run_applescript`, `_run_js`,
`_paste_text`) through the module (`safari._run_applescript(...)`), never
through a `from` import, so the test walls patched here reach them."""
import os
import subprocess
import tempfile
import threading
import time
from ..core.config import RETRY_DELAY_SECONDS
from ..core.logger import log
from ..guards.active_hours import require_active

# Global lock: only one bot can use Safari at a time.
# Without this, the reply bot and engage bot type over each other. RLock is
# intentional: blank-page recovery can be triggered from inside a scrape that
# already owns the lock, and it must restart Safari before releasing control.
class _AwakeSafariLock:
    def __init__(self):
        self._lock = threading.RLock()

    def __enter__(self):
        require_active()
        self._lock.acquire()
        try:
            require_active()  # queued work may acquire the browser after bedtime
        except BaseException:
            self._lock.release()
            raise
        return self

    def __exit__(self, *exc):
        self._lock.release()


_safari_lock = _AwakeSafariLock()


def _run_applescript(script: str, retries: int = 1,
                     timeout_s: float | None = None) -> bool:
    """Run an AppleScript command with optional retries. Returns True on success.
    With `timeout_s`, a run that outlasts it counts as a failed attempt."""
    for attempt in range(retries):
        require_active()
        try:
            require_active()
            subprocess.run(["osascript", "-e", script], check=True,
                           capture_output=True, text=True, timeout=timeout_s)
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            if attempt < retries - 1:
                log.warning(f"AppleScript failed (attempt {attempt + 1}/{retries}), retrying...")
                time.sleep(RETRY_DELAY_SECONDS)
    return False


def _run_js(js: str, timeout_s: int = 15, *, log_prefix: str = "",
            activate: bool = False, raise_timeout: bool = False) -> str:
    """Run `js` in Safari's front tab and return its result, "" when the
    osascript call fails. The script goes through a temp file, so `js` needs
    no AppleScript escaping. `log_prefix` tags the failure line with the
    caller's prefix, `activate` brings Safari to the front first, and
    `raise_timeout` lets `subprocess.TimeoutExpired` reach a caller that
    retries."""
    require_active()
    prefix = f"{log_prefix} " if log_prefix else ""
    activate_line = 'tell application "Safari" to activate' if activate else ""
    path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".js",
                                         delete=False) as tmp:
            path = tmp.name
            tmp.write(js)
        res = subprocess.run(["osascript", "-e", f'''
        {activate_line}
        set jsCode to (read POSIX file "{path}" as «class utf8»)
        tell application "Safari"
            do JavaScript jsCode in current tab of front window
        end tell
        '''], capture_output=True, text=True, timeout=timeout_s)
        if res.returncode != 0:
            log.info(f"{prefix}Page JavaScript failed (osascript exit {res.returncode}): "
                     f"{(res.stderr or '').strip()[:300]}")
            return ""
        return (res.stdout or "").strip()
    except subprocess.TimeoutExpired as e:
        if raise_timeout:
            raise
        log.info(f"{prefix}Page JavaScript failed: {e!r}")
        return ""
    except (OSError, subprocess.SubprocessError) as e:
        log.info(f"{prefix}Page JavaScript failed: {e!r}")
        return ""
    finally:
        if path:
            try:
                os.unlink(path)
            except OSError:
                pass


def _escape_for_applescript(text: str) -> str:
    """Escape special characters for AppleScript string literals."""
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _paste_text(text: str) -> bool:
    """Copy text to clipboard and paste it. Handles accented characters correctly.
    Returns True when the AppleScript ran."""
    escaped = _escape_for_applescript(text)
    script = f'''
    set the clipboard to "{escaped}"
    delay 0.3
    tell application "System Events"
        keystroke "v" using command down
    end tell
    '''
    return _run_applescript(script)


def _navigate_to_first_tweet():
    """Use Tab+Enter to navigate to the first tweet on a profile/page."""
    script = '''
    tell application "System Events"
        keystroke tab
        delay 0.2
        keystroke tab
        delay 0.2
        keystroke tab
        delay 0.2
        keystroke return
    end tell
    '''
    _run_applescript(script)


def close_front_tab():
    """Close the frontmost Safari tab to save memory."""
    script = '''
    tell application "Safari"
        if (count of windows) > 0 then
            tell front window
                if (count of tabs) > 1 then
                    close current tab
                end if
            end tell
        end if
    end tell
    '''
    if _run_applescript(script):
        log.debug("Tab closed.")


def _scroll_page():
    """Scroll down the page to load more content."""
    _run_applescript('''
    tell application "System Events"
        repeat 5 times
            key code 125
            delay 0.4
        end repeat
    end tell
    ''')
    time.sleep(2)

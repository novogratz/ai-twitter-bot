"""src/x/safari_hygiene: dark-screen recovery."""


def test_safari_warmup_verifies_render_and_retries_blank(monkeypatch):
    """Dark-screen recovery must verify x.com rendered after restart.
    A blank app shell should trigger cache-busted retries and return False if
    Safari never reaches a usable page."""
    from src.x import safari_hygiene as sh

    commands = []
    statuses = iter([
        "BLANK:0:https://x.com/home",
        "BLANK:0:https://x.com/home?bot_recover=1",
        "READY:shell:500",
    ])

    class _R:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(sh.subprocess, "run", lambda *a, **k: commands.append(a) or _R())
    monkeypatch.setattr(sh.time, "sleep", lambda *_: None)

    def fake_js(js_code, timeout_s=15, **_):
        if "serviceWorker" in js_code:
            return ""
        return next(statuses)

    monkeypatch.setattr(sh.safari, "_run_js", fake_js)

    assert sh._warm_up_xcom()
    joined = "\n".join(str(c) for c in commands)
    assert "bot_recover=" in joined, "blank render must trigger cache-busted retry"

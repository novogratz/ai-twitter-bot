"""src/x/twitter_client write chokepoints: replies, posts, follows,
unfollows and pins (issues #100, #101, #141, #142)."""
import json
from datetime import datetime
from types import SimpleNamespace

import pytest

from src.editorial import editorial_bot as editorial
from src.guards import action_guard as ag
from src.guards import replied_store as rs
from src.core import config
from src.core.state_errors import StateUnreadable
from tests.helpers import OWN_BEST, TORONTO, pin_rows, stop_requested, numbered_url, clock


# --- one reply per tweet, EVER (double-reply incident, 2026-06-05) -------------


def _fake_safari(monkeypatch):
    """Live (non-dry) reply path with every Safari step succeeding: the
    Replied store is only claimed when a Reply really ships."""
    import src.x.twitter_client as tc
    from src.x import safari
    monkeypatch.setenv("DRY_RUN", "0")
    monkeypatch.setattr(safari, "_run_applescript", lambda *a, **k: True)
    monkeypatch.setattr(safari, "_paste_text", lambda *a, **k: True)
    monkeypatch.setattr(tc, "_maybe_like_parent", lambda *a, **k: None)
    monkeypatch.setattr(safari, "close_front_tab", lambda: None)
    monkeypatch.setattr(tc.webbrowser, "open", lambda *a, **k: True)
    monkeypatch.setattr(tc.time, "sleep", lambda *a: None)


def test_reply_chokepoint_blocks_second_reply(monkeypatch, tmp_path):
    """Two reply bots racing on the same tweet: the second write MUST be
    refused at the chokepoint regardless of which bot it came from."""
    import src.x.twitter_client as tc
    from src.guards import action_guard

    monkeypatch.setattr("src.core.config.REPLIED_FILE", str(tmp_path / "replied.json"))
    _fake_safari(monkeypatch)
    monkeypatch.setattr(action_guard, "can_post", lambda action: (True, ""))
    recorded = []
    monkeypatch.setattr(action_guard, "record", lambda *a, **k: recorded.append(a))

    url = "https://x.com/Graphseo/status/1234567890123456789"
    reply = "le signal des fautes tient exactement un cycle de finetuning, profites-en tant que ça marche"
    tc.reply_to_tweet(url, reply)
    tc.reply_to_tweet(url, reply + " v2")          # same tweet, second bot
    tc.reply_to_tweet(url + "?s=20", reply + " v3")  # same tweet, different URL form

    assert len(recorded) == 1  # exactly ONE reply ever reached the write


def test_reply_chokepoint_returns_bool(monkeypatch, tmp_path):
    """reply_to_tweet must return True when the reply ships and False on the
    dedup skip — callers gate log_reply on this."""
    from src.x import twitter_client as tc
    from src.guards import action_guard as ag

    monkeypatch.setattr("src.core.config.REPLIED_FILE", str(tmp_path / "replied.json"))
    monkeypatch.setattr(ag, "can_post", lambda kind: (True, "ok"))
    monkeypatch.setattr(ag, "record", lambda *a, **k: None)
    _fake_safari(monkeypatch)

    url = "https://x.com/foo/status/2063500000000000042"
    text = "Naming the fear is step one. The number says 40 billion in capex."
    assert tc.reply_to_tweet(url, text) is True
    # Store was marked by the chokepoint itself — second attempt refuses.
    assert tc.reply_to_tweet(url, text) is False


def test_reply_chokepoint_refuses_on_corrupt_store(monkeypatch):
    from src.guards import action_guard as ag
    from src.x import twitter_client as tc
    recorded = []
    monkeypatch.setattr(ag, "can_post", lambda kind: (True, ""))
    monkeypatch.setattr(ag, "record", lambda *a, **k: recorded.append(a))
    monkeypatch.setenv("DRY_RUN", "1")
    with open(config.REPLIED_FILE, "w") as f:
        f.write("[")
    with pytest.raises(StateUnreadable):
        tc.reply_to_tweet(numbered_url(1), "Batching is the whole margin story: utilisation decides the price.")
    assert recorded == [], "nothing ships on an unreadable store"


def test_reply_chokepoint_strips_em_dashes(monkeypatch, tmp_path):
    """Operator 2026-06-07: an em dash in a published reply is an AI tell
    ('what a shame'). The chokepoint must strip em/en dashes for EVERY
    reply path, even ones that skip humanize()."""
    from src.x import twitter_client as tc
    from src.guards import action_guard as ag

    monkeypatch.setattr("src.core.config.REPLIED_FILE", str(tmp_path / "replied.json"))
    monkeypatch.setattr(ag, "can_post", lambda kind: (True, "ok"))
    recorded = {}
    monkeypatch.setattr(ag, "record", lambda *a, **k: None)
    monkeypatch.setenv("DRY_RUN", "1")
    logged = []
    monkeypatch.setattr(tc, "log", type(tc.log)(tc.log.name)) if False else None
    # Capture the final text via the DRY_RUN log line is brittle — instead
    # verify through the store-marking path: patch _paste? Simplest: spy on
    # the DRY_RUN branch by reading the typo-injection input. We assert via
    # content_guard.validate receiving dash-free text.
    seen = {}
    import src.guards.content_guard as cg2
    real_validate = cg2.validate
    def spy_validate(text, kind="post"):
        seen["text"] = text
        return real_validate(text, kind=kind)
    monkeypatch.setattr(cg2, "validate", spy_validate)

    url = "https://x.com/foo/status/2063500000000000088"
    assert tc.reply_to_tweet(url, "Targets are easy — conviction is the hard part of the trade.") is tc.DRY_RUN_RECORDED
    assert "—" not in seen["text"]
    assert "conviction is the hard part" in seen["text"]


def test_fr_forced_parent_rejects_english_reply(monkeypatch, tmp_path):
    """Operator 2026-06-07: 'i saw some english on Julien response'.
    @Graphseo is always-French; the chokepoint refuses an English reply to
    him from ANY bot, BEFORE the dedup mark (post stays fresh for an FR
    retry). SKIPPED-variant leaks are also pinned here."""
    from src.x import twitter_client as tc
    from src.guards import action_guard as ag
    from src.guards import content_guard as cg

    monkeypatch.setattr("src.core.config.REPLIED_FILE", str(tmp_path / "replied.json"))
    monkeypatch.setattr(ag, "can_post", lambda kind: (True, "ok"))
    monkeypatch.setattr(ag, "record", lambda *a, **k: None)
    monkeypatch.setenv("DRY_RUN", "1")

    url = "https://x.com/Graphseo/status/2063500000000000099"
    english = "The market just told you what your conviction is worth this week."
    assert tc.reply_to_tweet(url, english) is False
    # Post must stay UNMARKED — a later FR draft can still ship.
    assert url not in rs.load_replied()
    french = "Le marché vient de te dire ce que vaut ta conviction cette semaine."
    assert tc.reply_to_tweet(url, french) is tc.DRY_RUN_RECORDED

    # SKIPPED / Skip. variants (live leaks 01:04-04:07) die at content_guard.
    for leak in ("SKIPPED", "Skip.", "skipped", "SKIP — no source context"):
        ok, _ = cg.validate(leak, kind="reply")
        assert not ok, f"{leak!r} must never publish"


def test_parent_like_is_probabilistic_not_every_reply(monkeypatch):
    """2026-06-15 (operator: "hit by automation flag — cool down likes").
    Liking the parent of EVERY reply (743/day) was the automation
    signature. _maybe_like_parent gates the like behind a low env
    probability: prob<=0 disables it; the reply chokepoint must route
    through the gate, not an unconditional like_tweet on the parent."""
    import inspect
    from src.x import twitter_client as tc

    liked = []
    monkeypatch.setattr(tc, "like_tweet", lambda url=None: liked.append(url))

    monkeypatch.setenv("REPLY_LIKE_PARENT_PROB", "0")
    for _ in range(20):
        tc._maybe_like_parent("https://x.com/a/status/1", "REPLY_LIKE_PARENT_PROB", 0.12)
    assert liked == [], "prob=0 must disable parent-likes entirely"

    monkeypatch.setenv("REPLY_LIKE_PARENT_PROB", "1")
    tc._maybe_like_parent("https://x.com/a/status/2", "REPLY_LIKE_PARENT_PROB", 0.12)
    assert liked == ["https://x.com/a/status/2"]

    rsrc = inspect.getsource(tc.reply_to_tweet)
    assert "_maybe_like_parent" in rsrc
    assert "like_tweet(tweet_url)" not in rsrc, \
        "reply must not unconditionally like the parent"


def test_debate_turn_cap_is_owned_by_the_reply_chokepoint(monkeypatch):
    """A Debate turn (CONTEXT.md) is capped per author per Toronto day at
    the reply chokepoint, whichever bot answers: debate_bot and replyback
    share one count. Ordinary replies to the same author stay uncapped, a
    refused turn leaves the tweet unmarked, and the cap is read at call time."""
    from src.guards import action_guard as ag
    from src.guards import content_guard as cg
    from src.x import safari, twitter_client as tc

    monkeypatch.setattr(ag, "spacing_ok", lambda *a: True)
    monkeypatch.setattr(cg, "validate", lambda *a, **k: (True, ""))
    monkeypatch.setattr(safari, "_run_applescript", lambda *a: True)
    monkeypatch.setattr(safari, "_paste_text", lambda *a: True)
    monkeypatch.setattr(tc, "_maybe_like_parent", lambda *a: None)
    monkeypatch.setattr(safari, "close_front_tab", lambda: None)
    monkeypatch.setattr(tc.webbrowser, "open", lambda *a: True)
    monkeypatch.setattr(tc.time, "sleep", lambda *a: None)
    monkeypatch.setenv("DEBATE_MAX_TURNS_PER_AUTHOR_PER_DAY", "2")

    text = "Inference cost falls when batching works, so the margin story depends on utilisation."
    url = lambda author, n: f"https://x.com/{author}/status/{n}"
    assert tc.reply_to_tweet(url("Challenger", 1), text, debate_turn=True)
    assert tc.reply_to_tweet_in_thread(url("challenger", 2), text, debate_turn=True)
    assert not tc.reply_to_tweet(url("challenger", 3), text, debate_turn=True)
    assert url("challenger", 3) not in rs.load_replied(), "refused turn must stay fresh"
    assert tc.reply_to_tweet(url("challenger", 4), text), "plain replies stay uncapped"
    assert tc.reply_to_tweet(url("someone_else", 5), text, debate_turn=True)
    assert ag.debate_turns_today("challenger") == 2
    monkeypatch.setenv("DEBATE_MAX_TURNS_PER_AUTHOR_PER_DAY", "3")
    assert tc.reply_to_tweet(url("challenger", 3), text, debate_turn=True)
    assert not tc.reply_to_tweet("https://x.com/i/web/status/6", text, debate_turn=True), \
        "a turn without a URL handle fails closed"


def test_debate_turn_cap_judged_under_the_safari_lock(monkeypatch):
    """Another thread can ship the Engager's last turn while this one waits
    for the browser: admission, judged under the lock, refuses before Safari."""
    import contextlib
    from src.guards import action_guard as ag
    from src.guards import content_guard as cg
    from src.x import safari, twitter_client as tc

    monkeypatch.setattr(ag, "spacing_ok", lambda *a: True)
    monkeypatch.setattr(cg, "validate", lambda *a, **k: (True, ""))
    monkeypatch.setattr(tc.time, "sleep", lambda *a: None)
    monkeypatch.setenv("DEBATE_MAX_TURNS_PER_AUTHOR_PER_DAY", "1")

    @contextlib.contextmanager
    def contended_lock():
        ag.record(ag.DEBATE_TURN, target="challenger")  # the other thread won
        yield
    monkeypatch.setattr(safari, "_safari_lock", contended_lock())
    # _run_applescript stays walled off by conftest: reaching Safari fails.
    url = "https://x.com/challenger/status/7"
    assert not tc.reply_to_tweet(url, "Batching changes the cost curve.", debate_turn=True)
    assert ag.debate_turns_today("challenger") == 1
    assert url not in rs.load_replied(), "the race loser was never claimed"


# --- validated text, typo and language (issue #101) ----------------------------


def _dry_run_reply_path(monkeypatch):
    from src.guards import action_guard

    monkeypatch.setattr(action_guard, "can_post", lambda *a, **k: (True, ""))
    monkeypatch.setattr(action_guard, "record", lambda *a, **k: None)
    monkeypatch.setenv("DRY_RUN", "1")


def test_human_typo_text_is_the_validated_text(monkeypatch):
    from src.guards import content_guard
    from src.core import humanizer
    from src.x import twitter_client

    _dry_run_reply_path(monkeypatch)
    monkeypatch.setenv("HUMAN_TYPO_HANDLES", "typofriend")
    monkeypatch.setattr(humanizer, "inject_human_typo", lambda text: text + " (typo)")
    validated = []
    real_validate = content_guard.validate
    monkeypatch.setattr(content_guard, "validate",
                        lambda text, kind="post": validated.append(text) or real_validate(text, kind=kind))

    url = "https://x.com/typofriend/status/2063500000000000101"
    assert twitter_client.reply_to_tweet(url, "Compute is the moat, not the model.") is twitter_client.DRY_RUN_RECORDED
    assert validated and validated[-1].endswith("(typo)")


def test_language_check_judges_the_text_before_the_typo(monkeypatch):
    from src.guards import content_guard
    from src.core import reply_language
    from src.core import humanizer
    from src.x import twitter_client

    _dry_run_reply_path(monkeypatch)
    monkeypatch.setenv("HUMAN_TYPO_HANDLES", "typofriend")
    monkeypatch.setenv("FR_FORCED_REPLY_HANDLES", "typofriend")
    monkeypatch.setattr(humanizer, "inject_human_typo", lambda text: text + " (typo)")
    judged, validated = [], []
    monkeypatch.setattr(reply_language, "looks_english", lambda text: judged.append(text) or False)
    real_validate = content_guard.validate
    monkeypatch.setattr(content_guard, "validate",
                        lambda text, kind="post": validated.append(text) or real_validate(text, kind=kind))

    url = "https://x.com/typofriend/status/2063500000000000103"
    assert twitter_client.reply_to_tweet(url, "Le calcul est le vrai fossé, pas le modèle.") is twitter_client.DRY_RUN_RECORDED
    assert judged and not judged[-1].endswith("(typo)")
    assert validated[-1].endswith("(typo)")


def test_refused_typo_text_leaves_the_tweet_fresh(monkeypatch):
    from src.guards import content_guard
    from src.core import humanizer
    from src.x import twitter_client
    from src.guards.replied_store import load_replied

    _dry_run_reply_path(monkeypatch)
    monkeypatch.setenv("HUMAN_TYPO_HANDLES", "typofriend")
    monkeypatch.setattr(humanizer, "inject_human_typo", lambda text: text + " (typo)")
    monkeypatch.setattr(content_guard, "validate",
                        lambda text, kind="post": (not text.endswith("(typo)"), "typo refused"))

    url = "https://x.com/typofriend/status/2063500000000000102"
    assert twitter_client.reply_to_tweet(url, "Compute is the moat, not the model.") is False
    assert url not in load_replied()


def test_dry_run_is_read_at_call_time(monkeypatch):
    from src.guards import action_guard
    from src.core import config
    from src.x import twitter_client

    assert not hasattr(config, "DRY_RUN"), "a frozen module constant must not come back"
    monkeypatch.setenv("DRY_RUN", "0")
    assert config.dry_run() is False
    monkeypatch.setenv("DRY_RUN", "1")
    assert config.dry_run() is True

    # Set after every module is imported: the chokepoint must still see it
    # and never reach Safari (conftest fails the test if it does).
    monkeypatch.setattr(action_guard, "can_post", lambda *a, **k: (True, ""))
    recorded = []
    monkeypatch.setattr(action_guard, "record", lambda *a, **k: recorded.append(k))
    assert twitter_client.post_tweet("A fresh original about inference costs.") is twitter_client.DRY_RUN_RECORDED
    assert recorded == [{"dry_run": True}]


# --- live reply path: log only what shipped ------------------------------------


def _live_browser(monkeypatch, failing_step=None):
    """Live (non-dry) write path with a scripted AppleScript outcome.

    failing_step: "reply_key", "paste" or "submit" makes that step fail;
    "stop_before_submit", "stop_at_submit" and "stop_after_submit" request a
    stop at that point.
    """
    from src.guards import action_guard
    from src.x import safari, twitter_client as tc
    from src.guards.active_hours import OutsideActiveHours

    monkeypatch.setenv("DRY_RUN", "0")
    monkeypatch.setattr(action_guard, "can_post", lambda *a, **k: (True, ""))
    monkeypatch.setattr(action_guard, "can_debate_turn", lambda *a, **k: (True, ""))
    recorded = []
    monkeypatch.setattr(action_guard, "record", lambda *a, **k: recorded.append((a, k)))

    def run_applescript(script, *a, **k):
        if 'keystroke "r"' in script:
            if failing_step == "stop_before_submit":
                raise OutsideActiveHours("stop")
            return failing_step != "reply_key"
        if "keystroke return using command down" in script:
            return failing_step != "submit"
        return True

    monkeypatch.setattr(safari, "_run_applescript", run_applescript)
    def paste(text):
        if failing_step == "stop_at_submit":
            stop_requested(monkeypatch)
        return failing_step != "paste"

    monkeypatch.setattr(safari, "_paste_text", paste)
    monkeypatch.setattr(tc, "_maybe_like_parent", lambda *a, **k: None)
    def close_front_tab():
        if failing_step == "stop_after_submit":
            raise OutsideActiveHours("stop")

    monkeypatch.setattr(safari, "close_front_tab", close_front_tab)
    monkeypatch.setattr(tc.webbrowser, "open", lambda *a, **k: True)
    monkeypatch.setattr(tc.time, "sleep", lambda *_: None)
    return recorded


REPLY = "Batching is where inference margins are won or lost."


def test_reply_ships_and_records_when_every_step_runs(monkeypatch):
    from src.x import twitter_client as tc
    from src.guards.replied_store import load_replied

    recorded = _live_browser(monkeypatch)
    url = "https://x.com/someone/status/2063500000000000110"

    assert tc.reply_to_tweet(url, REPLY) is True
    assert len(recorded) == 1
    assert url in load_replied()


def test_reply_failing_before_submit_records_nothing_and_leaves_tweet_fresh(monkeypatch):
    from src.x import twitter_client as tc
    from src.guards.replied_store import load_replied, save_replied

    other = "https://x.com/else/status/2063500000000000119"
    save_replied({other})
    for n, step in enumerate(("reply_key", "paste")):
        for debate_turn in (False, True):
            recorded = _live_browser(monkeypatch, failing_step=step)
            url = f"https://x.com/someone/status/20635000000000001{n}{int(debate_turn)}"

            assert tc.reply_to_tweet(url, REPLY, debate_turn=debate_turn) is False, step
            assert recorded == [], step
            assert url not in load_replied(), step
    assert other in load_replied()


def test_reply_failing_at_submit_records_nothing_but_stays_marked(monkeypatch):
    from src.x import twitter_client as tc
    from src.guards.replied_store import load_replied

    for n, debate_turn in enumerate((False, True)):
        recorded = _live_browser(monkeypatch, failing_step="submit")
        url = f"https://x.com/someone/status/206350000000000013{n}"

        assert tc.reply_to_tweet(url, REPLY, debate_turn=debate_turn) is False
        assert recorded == []
        assert url in load_replied()


def test_debate_race_loser_leaves_the_tweet_fresh(monkeypatch):
    """Another thread takes the Engager's last turn while this one waits for
    the browser: admission, judged under the lock, refuses before the claim."""
    from src.guards import action_guard
    from src.x import safari, twitter_client as tc
    from src.guards.replied_store import load_replied

    recorded = _live_browser(monkeypatch)
    lock_held = []
    monkeypatch.setattr(action_guard, "can_debate_turn",
                        lambda *a, **k: (False, "turn cap reached") if lock_held else (True, ""))

    class ContendedLock:
        def __enter__(self):
            lock_held.append(True)  # the other thread shipped the last turn meanwhile

        def __exit__(self, *exc):
            lock_held.clear()

    monkeypatch.setattr(safari, "_safari_lock", ContendedLock())
    url = "https://x.com/someone/status/2063500000000000160"

    assert tc.reply_to_tweet(url, REPLY, debate_turn=True) is False
    assert recorded == []
    assert url not in load_replied()


def test_live_reply_pastes_the_validated_text(monkeypatch):
    """The text in the composer is the text admission validated, typo and
    dash cleanup included, never the raw draft."""
    from src.guards import content_guard
    from src.core import humanizer
    from src.x import safari, twitter_client as tc

    _live_browser(monkeypatch)
    pasted, validated = [], []
    monkeypatch.setattr(safari, "_paste_text", lambda text: pasted.append(text) or True)
    monkeypatch.setenv("HUMAN_TYPO_HANDLES", "typofriend")
    monkeypatch.setattr(humanizer, "inject_human_typo", lambda text: text + " (typo)")
    real_validate = content_guard.validate
    monkeypatch.setattr(content_guard, "validate",
                        lambda text, kind="post": validated.append(text) or real_validate(text, kind=kind))
    url = "https://x.com/typofriend/status/2063500000000000165"

    assert tc.reply_to_tweet(url, "Targets are easy — conviction is the hard part.") is True
    assert pasted == [validated[-1]]
    assert pasted[0].endswith("(typo)") and "—" not in pasted[0]


def test_spacing_is_judged_under_the_safari_lock(monkeypatch):
    """A Reply shipped by another thread while this one waited for the
    browser: the spacing check sees it and nothing is claimed."""
    from src.guards import action_guard
    from src.x import safari, twitter_client as tc
    from src.guards.replied_store import load_replied

    recorded = _live_browser(monkeypatch)
    lock_held = []
    monkeypatch.setattr(action_guard, "can_post",
                        lambda *a, **k: (False, "too soon") if lock_held else (True, ""))

    class ContendedLock:
        def __enter__(self):
            lock_held.append(True)

        def __exit__(self, *exc):
            lock_held.clear()

    monkeypatch.setattr(safari, "_safari_lock", ContendedLock())
    url = "https://x.com/someone/status/2063500000000000166"

    assert tc.reply_to_tweet(url, REPLY) is False
    assert recorded == []
    assert url not in load_replied()


def test_overnight_reply_is_refused_not_raised(monkeypatch):
    """_safari_lock raises OutsideActiveHours on entry; the chokepoint must
    refuse with False before it, like any other skip."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from src.guards import active_hours
    from src.core import config
    from src.x import twitter_client as tc

    _live_browser(monkeypatch)
    monkeypatch.setattr(active_hours, "now_local",
                        lambda: datetime(2026, 9, 23, 23, 0, tzinfo=ZoneInfo(config.BOT_TIMEZONE)))
    assert tc.reply_to_tweet("https://x.com/someone/status/2063500000000000167", REPLY) is False


def test_dry_run_reply_never_claims_the_tweet(monkeypatch):
    """A simulated Reply writes a dry_run ledger row only: the Replied store
    holds Replies that shipped, so going live later can still answer it."""
    from src.x import twitter_client as tc
    from src.guards.replied_store import load_replied

    recorded = []
    _dry_run_reply_path(monkeypatch)
    from src.guards import action_guard
    monkeypatch.setattr(action_guard, "record", lambda *a, **k: recorded.append((a, k)))
    url = "https://x.com/someone/status/2063500000000000170"

    assert tc.reply_to_tweet(url, REPLY, debate_turn=True) is tc.DRY_RUN_RECORDED
    assert url not in load_replied()
    assert [k for _, k in recorded] == [{"target": url, "dry_run": True},
                                        {"target": "someone", "dry_run": True}]


def test_refused_reply_never_reaches_safari(monkeypatch):
    """Blocked account, own post and author-less URLs stop at admission:
    conftest fails the test if Safari is touched."""
    from src.guards import action_guard
    from src.core import config
    from src.x import twitter_client as tc

    monkeypatch.setenv("DRY_RUN", "0")
    monkeypatch.setattr(action_guard, "can_post", lambda *a, **k: (True, ""))
    monkeypatch.setattr(config, "BLOCKLIST", {"la pique"})
    for url in ("https://x.com/La_Pique_Off/status/2063500000000000180",
                f"https://x.com/{config.BOT_HANDLE}/status/2063500000000000181",
                "https://x.com/i/web/status/2063500000000000182"):
        assert tc.reply_to_tweet(url, REPLY) is False, url


def test_stop_before_submit_leaves_tweet_fresh_after_submit_keeps_it(monkeypatch):
    import pytest
    from src.x import twitter_client as tc
    from src.guards.active_hours import OutsideActiveHours
    from src.guards.replied_store import load_replied

    _live_browser(monkeypatch, failing_step="stop_before_submit")
    before = "https://x.com/someone/status/2063500000000000140"
    with pytest.raises(OutsideActiveHours):
        tc.reply_to_tweet(before, REPLY)
    assert before not in load_replied()

    _live_browser(monkeypatch, failing_step="stop_at_submit")
    at = "https://x.com/someone/status/2063500000000000142"
    with pytest.raises(OutsideActiveHours):
        tc.reply_to_tweet(at, REPLY)
    assert at not in load_replied()

    import threading
    from src.guards import active_hours
    monkeypatch.setattr(active_hours, "_STOP", threading.Event())
    recorded = _live_browser(monkeypatch, failing_step="stop_after_submit")
    after = "https://x.com/someone/status/2063500000000000141"
    with pytest.raises(OutsideActiveHours):
        tc.reply_to_tweet(after, REPLY)
    assert after in load_replied()
    assert len(recorded) == 1


# --- posts -------------------------------------------------------------------


def test_stale_review_mode_does_not_divert_post_to_a_queue(monkeypatch, tmp_path):
    """REVIEW_MODE queued drafts into review_queue.json that nothing shipped,
    so every editorial slot burned its attempts (#124). A leftover
    REVIEW_MODE=1 in .env must not hold drafts any more: DRY_RUN is the
    only no-publish switch."""
    import os
    import src.x.twitter_client as tc
    from src.guards import action_guard
    import src.core.config as config
    monkeypatch.setenv("REVIEW_MODE", "1")
    monkeypatch.setenv("DRY_RUN", "1")
    monkeypatch.setattr(config, "_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr(action_guard, "can_post", lambda a: (True, ""))
    recorded = []
    monkeypatch.setattr(action_guard, "record", lambda *a, **k: recorded.append((a, k)))
    assert tc.post_tweet("a sponsor-clean original take about the market needing a therapist today") is tc.DRY_RUN_RECORDED
    assert recorded == [((action_guard.POST,), {"dry_run": True})]
    assert not os.path.exists(os.path.join(str(tmp_path), "review_queue.json"))
    assert not hasattr(tc, "_queue_for_review")


def test_post_tweet_returns_bool_for_skip_vs_ship(monkeypatch):
    """2026-06-09: the same hotake appeared 5x in engagement_log though dedup
    blocked the reposts — bot.py logged log_post/log_hotake unconditionally
    because post_tweet returned None on a skip. post_tweet must return False
    on policy/content/dedup skip and True only when it ships, so the caller
    can gate logging (same family as the reply phantom-log fix)."""
    from src.x import twitter_client as tc
    from src.guards import action_guard as ag
    from src.guards import content_guard as cg

    # Dedup skip → False (and no Safari).
    monkeypatch_targets = []
    import types
    orig_canpost = ag.can_post
    orig_validate = cg.validate
    orig_isdup = cg.is_duplicate
    monkeypatch.setenv("DRY_RUN", "1")  # never touch Safari even if it didn't dedup
    try:
        ag.can_post = lambda action: (True, "ok")
        cg.validate = lambda text, kind="original": (True, "")
        cg.is_duplicate = lambda text, threshold=None: True   # force dup
        assert tc.post_tweet("AI capex is the new rent again") is False, \
            "a near-duplicate post must return False, not None"
        # Not a dup, DRY_RUN → recorded, not shipped
        cg.is_duplicate = lambda text, threshold=None: False
        assert tc.post_tweet("a genuinely fresh original take about AI") is tc.DRY_RUN_RECORDED
    finally:
        ag.can_post = orig_canpost
        cg.validate = orig_validate
        cg.is_duplicate = orig_isdup


def test_image_post_that_fails_records_nothing(monkeypatch, tmp_path):
    from src.guards import content_guard
    from src.x import twitter_client as tc

    image = tmp_path / "chart.png"
    image.write_bytes(b"png")
    monkeypatch.setattr(content_guard, "is_duplicate", lambda *a, **k: False)
    noted = []
    monkeypatch.setattr(content_guard, "note_posted", noted.append)
    for step in ("paste", "submit"):
        recorded = _live_browser(monkeypatch, failing_step=step)
        assert tc.post_tweet("Inference is getting cheaper faster than training.",
                             image_path=str(image)) is False, step
        assert recorded == [] and noted == [], step

    recorded = _live_browser(monkeypatch)
    assert tc.post_tweet("Inference is getting cheaper faster than training.",
                         image_path=str(image)) is True
    assert len(recorded) == 1


def test_concurrent_posts_cannot_both_take_last_slot(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from src.x import safari, twitter_client as tc
    clock(monkeypatch, datetime(2026, 9, 20, 12, tzinfo=TORONTO))
    for _ in range(7):
        ag.record(ag.POST)
    monkeypatch.setattr(ag, "spacing_ok", lambda *a: True)
    monkeypatch.setattr(tc.content_guard if hasattr(tc, "content_guard") else editorial.content_guard, "is_duplicate", lambda *a: False)
    monkeypatch.setattr(tc, "_record_posted", lambda *a: None)
    monkeypatch.setattr(safari, "_run_applescript", lambda *a: True)
    monkeypatch.setattr(tc.webbrowser, "open", lambda *a: True)
    monkeypatch.setattr(tc.time, "sleep", lambda *a: None)
    barrier = Barrier(2)
    original_validate = editorial.content_guard.validate
    def simultaneous(*a, **k):
        result = original_validate(*a, **k)
        barrier.wait(timeout=3)
        return result
    monkeypatch.setattr(editorial.content_guard, "validate", simultaneous)
    text = "AI model evaluation needs examples from your real workflow. Test the failure cases your team actually sees before choosing a model."
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: tc.post_tweet(text, editorial=True), range(2)))
    assert sum(1 for result in results if result is True) <= 1
    assert ag.count_today(ag.POST) <= 8


# --- follows -----------------------------------------------------------------


def test_follow_quality_gate_blocks_small_and_offniche(monkeypatch):
    """2026-06-12 operator: "the accounts you follow are trash, very small
    ... not related to AI or investment or crypto". The follow chokepoint
    must refuse small or off-niche profiles (whitelist seeds exempt), and
    must not follow blind when the followers count is unreadable."""
    import inspect
    from src.x.twitter_client import (_parse_follower_count,
                                    _follow_quality_decision, follow_account)

    assert _parse_follower_count("12.3K") == 12300
    assert _parse_follower_count("1,423") == 1423
    assert _parse_follower_count("2.1M") == 2_100_000
    assert _parse_follower_count("") == -1

    monkeypatch.setenv("FOLLOW_MIN_FOLLOWERS", "2000")
    monkeypatch.setenv("FOLLOW_REQUIRE_NICHE", "1")

    ok, why = _follow_quality_decision(150, "AI trader", "x", whitelisted=False)
    assert not ok and "too small" in why
    ok, why = _follow_quality_decision(50_000, "dog photos and recipes", "x",
                                       whitelisted=False)
    assert not ok and "off-niche" in why
    ok, why = _follow_quality_decision(-1, "AI investor", "x", whitelisted=False)
    assert not ok and "unreadable" in why
    ok, _ = _follow_quality_decision(50_000, "Macro investor, AI & crypto",
                                     "x", whitelisted=False)
    assert ok
    # Whitelisted seeds bypass (e.g. Graphseo's SEO bio is off-niche by
    # design — operator-pinned accounts are never gated).
    ok, _ = _follow_quality_decision(10, "SEO expert", "x", whitelisted=True)
    assert ok

    # Structural pin: the chokepoint actually consults the gate.
    src = inspect.getsource(follow_account)
    assert "_follow_quality_decision" in src and "_quality_reject_recent" in src


def test_follow_gate_english_only(monkeypatch):
    """Operator 2026-07-19: 'follow US / english accounts not foreigner
    langage follows' — the quality gate (rides EVERY follow path via the
    follow_account chokepoint) must reject non-Latin-script and foreign-
    language bios."""
    from src.x.twitter_client import _follow_quality_decision
    monkeypatch.setenv("FOLLOW_REQUIRE_ENGLISH", "1")
    monkeypatch.setenv("FOLLOW_REQUIRE_NICHE", "1")
    monkeypatch.setenv("FOLLOW_MIN_FOLLOWERS", "2000")

    ok, _ = _follow_quality_decision(
        50000, "AI investor. Building agents, GPUs and datacenter plays.",
        "Jane Doe", False)
    assert ok, "big EN on-niche account must pass"
    ok, why = _follow_quality_decision(
        50000, "AIと暗号資産の最新情報を毎日配信します。株式投資も。", "田中太郎", False)
    assert not ok and "non-English" in why, "Japanese bio must be rejected"
    ok, why = _follow_quality_decision(
        50000, "Analyse crypto et IA pour les investisseurs. Avec vous dans les marchés.",
        "Jean Dupont", False)
    assert not ok and "non-English" in why, "French bio must be rejected"
    # Whitelisted seeds stay exempt (Graphseo's FR bio is by design)
    ok, _ = _follow_quality_decision(500, "SEO et croissance pour les startups", "Julien", True)
    assert ok, "whitelisted seed must bypass the language gate"


# --- unfollows: read both page answers, record only a confirmed unfollow (#141)


@pytest.fixture()
def unfollow_env(monkeypatch, tmp_path):
    """Unfollow allowed by policy, browser stubbed; `answers` feeds the page
    JavaScript results in order."""
    from src.core import config
    from src.guards import action_guard as ag
    from src.x import safari
    from src.x import twitter_client as tc

    monkeypatch.delenv("DRY_RUN", raising=False)
    monkeypatch.setattr(config, "MAX_UNFOLLOWS_PER_DAY", 5)
    monkeypatch.setattr(config, "FOLLOW_ACTION_JITTER_SECONDS", 0)
    wl = tmp_path / "whitelist.json"
    wl.write_text(json.dumps({"tiers": {"tier1": ["karpathy"]}}))
    monkeypatch.setattr(config, "WHITELIST_FILE", str(wl))
    monkeypatch.setattr(ag, "_WL_CACHE", {})
    monkeypatch.setattr(ag, "_WL_MTIME", 0.0)
    following = tmp_path / "following_count.json"
    following.write_text(json.dumps({"count": 100}))
    monkeypatch.setattr(ag, "_FOLLOWING_COUNT_FILE", str(following))

    answers, scripts, opened, closed = [], [], [], []

    def run_js(js):
        scripts.append(js)
        return answers.pop(0) if answers else ""

    monkeypatch.setattr(safari, "_run_js", run_js)
    monkeypatch.setattr(safari, "close_front_tab", lambda: closed.append(True))
    monkeypatch.setattr(tc.webbrowser, "open", lambda url, *a, **k: opened.append(url) or True)
    monkeypatch.setattr(tc.time, "sleep", lambda *_: None)

    return SimpleNamespace(
        tc=tc, ag=ag, answers=answers, scripts=scripts, opened=opened, closed=closed,
        following=lambda: json.loads(following.read_text())["count"],
        ledger=ag._load_ledger)


@pytest.mark.parametrize("answer", ["NO_FOLLOWING_BTN", ""])
def test_missing_following_button_records_nothing(unfollow_env, answer):
    unfollow_env.answers.append(answer)

    assert unfollow_env.tc.unfollow_account("someaccount") is False

    assert len(unfollow_env.scripts) == 1, "no confirm without a Following click"
    assert unfollow_env.ledger() == []
    assert unfollow_env.following() == 100
    assert unfollow_env.closed


@pytest.mark.parametrize("answer", ["NO_CONFIRM", ""])
def test_missing_confirmation_records_nothing(unfollow_env, answer):
    unfollow_env.answers.extend(["CLICKED", answer])

    assert unfollow_env.tc.unfollow_account("someaccount") is False

    assert unfollow_env.ledger() == []
    assert unfollow_env.following() == 100
    assert unfollow_env.closed


def test_confirmed_unfollow_records_one_row(unfollow_env):
    unfollow_env.answers.extend(["CLICKED", "CONFIRMED"])

    assert unfollow_env.tc.unfollow_account("@SomeAccount") is True

    rows = unfollow_env.ledger()
    assert [(r["action"], r["target"], r["dry_run"]) for r in rows] == [
        (unfollow_env.ag.UNFOLLOW, "someaccount", False)]
    assert unfollow_env.following() == 99
    assert unfollow_env.closed


def test_dry_run_records_a_dry_row_without_the_browser(unfollow_env, monkeypatch):
    monkeypatch.setenv("DRY_RUN", "1")

    assert unfollow_env.tc.unfollow_account("someaccount") is unfollow_env.tc.DRY_RUN_RECORDED

    assert unfollow_env.opened == [] and unfollow_env.scripts == []
    rows = unfollow_env.ledger()
    assert [(r["action"], r["dry_run"]) for r in rows] == [(unfollow_env.ag.UNFOLLOW, True)]
    assert unfollow_env.following() == 100


# --- pins: record only a shipped pin (#142) --------------------------------------


def _scripted_pin_js(monkeypatch, steps):
    """Live pin_own_tweet with each osascript call answering the next step."""
    from src.x import safari, twitter_client as tc

    answers = iter(steps)

    monkeypatch.setenv("DRY_RUN", "0")
    monkeypatch.setattr(tc.webbrowser, "open", lambda *a, **k: None)
    monkeypatch.setattr(tc.time, "sleep", lambda *_: None)
    monkeypatch.setattr(safari, "close_front_tab", lambda: None)
    monkeypatch.setattr(safari, "_run_js", lambda *a, **k: next(answers))


@pytest.mark.parametrize("steps, shipped", [
    (["MORE_CLICKED", "PIN_CLICKED", "CONFIRMED"], True),
    (["MORE_CLICKED", "PIN_CLICKED", "NO_CONFIRM"], False),
    (["MORE_CLICKED", "PIN_NOT_FOUND_4"], False),
    (["NO_ARTICLE"], False),
    (["MORE_CLICKED", "PIN_CLICKED", ""], False),
])
def test_pin_own_tweet_records_only_a_shipped_pin(monkeypatch, steps, shipped):
    """Log only what shipped: one ledger row when the confirm dialog was
    clicked, none when a step failed or no confirm dialog appeared. A pin
    is not a profile publication."""
    from src.guards import action_guard
    from src.x import twitter_client as tc

    _scripted_pin_js(monkeypatch, steps)

    assert tc.pin_own_tweet(OWN_BEST) is shipped
    assert [r["target"] for r in pin_rows()] == ([OWN_BEST.lower()] if shipped else [])
    assert action_guard.profile_count_today() == 0

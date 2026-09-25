"""src/x/twitter_client write chokepoints: replies, posts, follows and pins
(issues #100, #101, #142)."""
import json
from datetime import datetime

import pytest

from src.editorial import editorial_bot as editorial
from src.guards import action_guard as ag
from src.guards import follow_policy
from src.guards import replied_store as rs
from src.core import config
from src.core.state_errors import StateUnreadable
from src.x.confirmed_write import WriteOutcome as W
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
    monkeypatch.setattr(safari, "open_url", lambda *a, **k: True)
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


def test_reply_chokepoint_returns_its_outcome(monkeypatch, tmp_path):
    """reply_to_tweet must return the truthy SHIPPED when the reply ships and
    a falsy REFUSED on the dedup skip — callers gate log_reply on this."""
    from src.x import twitter_client as tc
    from src.guards import action_guard as ag

    monkeypatch.setattr("src.core.config.REPLIED_FILE", str(tmp_path / "replied.json"))
    monkeypatch.setattr(ag, "can_post", lambda kind: (True, "ok"))
    monkeypatch.setattr(ag, "record", lambda *a, **k: None)
    _fake_safari(monkeypatch)

    url = "https://x.com/foo/status/2063500000000000042"
    text = "Naming the fear is step one. The number says 40 billion in capex."
    assert tc.reply_to_tweet(url, text) is W.SHIPPED
    # Store was marked by the chokepoint itself — second attempt refuses.
    assert tc.reply_to_tweet(url, text) is W.REFUSED


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
    assert tc.reply_to_tweet(url, "Targets are easy — conviction is the hard part of the trade.") is W.DRY_RUN
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
    assert tc.reply_to_tweet(url, english) is W.REFUSED
    # Post must stay UNMARKED — a later FR draft can still ship.
    assert url not in rs.load_replied()
    french = "Le marché vient de te dire ce que vaut ta conviction cette semaine."
    assert tc.reply_to_tweet(url, french) is W.DRY_RUN

    # SKIPPED / Skip. variants (live leaks 01:04-04:07) die at content_guard.
    for leak in ("SKIPPED", "Skip.", "skipped", "SKIP — no source context"):
        ok, _ = cg.validate(leak, kind="reply")
        assert not ok, f"{leak!r} must never publish"


def test_parent_like_is_probabilistic_not_every_reply(monkeypatch, settings_override):
    """2026-06-15 (operator: "hit by automation flag — cool down likes").
    Liking the parent of EVERY reply (743/day) was the automation
    signature. _maybe_like_parent gates the like behind a low
    probability: prob<=0 disables it; the reply chokepoint must route
    through the gate, not an unconditional like_tweet on the parent."""
    import inspect
    from src.x import twitter_client as tc

    liked = []
    monkeypatch.setattr(tc, "like_tweet", lambda url=None: liked.append(url))

    settings_override(REPLY_LIKE_PARENT_PROB=0.0)
    for _ in range(20):
        tc._maybe_like_parent("https://x.com/a/status/1")
    assert liked == [], "prob=0 must disable parent-likes entirely"

    settings_override(REPLY_LIKE_PARENT_PROB=1.0)
    tc._maybe_like_parent("https://x.com/a/status/2")
    assert liked == ["https://x.com/a/status/2"]

    rsrc = inspect.getsource(tc.reply_to_tweet)
    assert "_maybe_like_parent" in rsrc
    assert "like_tweet(tweet_url)" not in rsrc, \
        "reply must not unconditionally like the parent"


def test_debate_turn_cap_is_owned_by_the_reply_chokepoint(monkeypatch, settings_override, memory_ledger):
    """A Debate turn (CONTEXT.md) is capped per author per Toronto day at
    the reply chokepoint, whichever bot answers: debate_bot and replyback
    share one count. Ordinary replies to the same author stay uncapped, a
    refused turn leaves the tweet unmarked, and the cap is read at call time."""
    from src.guards import action_guard as ag
    from src.guards import content_guard as cg
    from src.x import safari, twitter_client as tc

    # The Reply spacing has a floor of 8 s (#201); it is not what this test judges.
    monkeypatch.setattr(ag, "too_soon", lambda action: "")
    monkeypatch.setattr(cg, "validate", lambda *a, **k: (True, ""))
    monkeypatch.setattr(safari, "_run_applescript", lambda *a, **k: True)
    monkeypatch.setattr(safari, "_paste_text", lambda *a: True)
    monkeypatch.setattr(tc, "_maybe_like_parent", lambda *a: None)
    monkeypatch.setattr(safari, "close_front_tab", lambda: None)
    monkeypatch.setattr(safari, "open_url", lambda *a: True)
    monkeypatch.setattr(tc.time, "sleep", lambda *a: None)
    settings_override(DEBATE_MAX_TURNS_PER_AUTHOR_PER_DAY=2)

    text = "Inference cost falls when batching works, so the margin story depends on utilisation."
    url = lambda author, n: f"https://x.com/{author}/status/{n}"
    assert tc.reply_to_tweet(url("Challenger", 1), text, debate_turn=True)
    assert tc.reply_to_tweet(url("challenger", 2), text, debate_turn=True)
    assert not tc.reply_to_tweet(url("challenger", 3), text, debate_turn=True)
    assert url("challenger", 3) not in rs.load_replied(), "refused turn must stay fresh"
    assert tc.reply_to_tweet(url("challenger", 4), text), "plain replies stay uncapped"
    assert tc.reply_to_tweet(url("someone_else", 5), text, debate_turn=True)
    assert memory_ledger.count(ag.DEBATE_TURN, ag.now_local().date(), "challenger") == 2
    settings_override(DEBATE_MAX_TURNS_PER_AUTHOR_PER_DAY=3)
    assert tc.reply_to_tweet(url("challenger", 3), text, debate_turn=True)
    assert not tc.reply_to_tweet("https://x.com/i/web/status/6", text, debate_turn=True), \
        "a turn without a URL handle fails closed"


def test_debate_turn_cap_judged_under_the_safari_lock(monkeypatch, settings_override, memory_ledger):
    """Another thread can ship the Engager's last turn while this one waits
    for the browser: admission, judged under the lock, refuses before Safari."""
    import contextlib
    from src.guards import action_guard as ag
    from src.guards import content_guard as cg
    from src.x import safari, twitter_client as tc

    monkeypatch.setattr(cg, "validate", lambda *a, **k: (True, ""))
    monkeypatch.setattr(tc.time, "sleep", lambda *a: None)
    settings_override(DEBATE_MAX_TURNS_PER_AUTHOR_PER_DAY=1)

    @contextlib.contextmanager
    def contended_lock():
        ag.record(ag.DEBATE_TURN, target="challenger")  # the other thread won
        yield
    monkeypatch.setattr(safari, "_safari_lock", contended_lock())
    # _run_applescript stays walled off by conftest: reaching Safari fails.
    url = "https://x.com/challenger/status/7"
    assert not tc.reply_to_tweet(url, "Batching changes the cost curve.", debate_turn=True)
    assert memory_ledger.count(ag.DEBATE_TURN, ag.now_local().date(), "challenger") == 1
    assert url not in rs.load_replied(), "the race loser was never claimed"


# --- validated text, typo and language (issue #101) ----------------------------


def _dry_run_reply_path(monkeypatch):
    from src.guards import action_guard

    monkeypatch.setattr(action_guard, "can_post", lambda *a, **k: (True, ""))
    monkeypatch.setattr(action_guard, "record", lambda *a, **k: None)
    monkeypatch.setenv("DRY_RUN", "1")


def test_human_typo_text_is_the_validated_text(monkeypatch, settings_override):
    from src.guards import content_guard
    from src.core import humanizer
    from src.x import twitter_client

    _dry_run_reply_path(monkeypatch)
    settings_override(HUMAN_TYPO_HANDLES="typofriend")
    monkeypatch.setattr(humanizer, "inject_human_typo", lambda text: text + " (typo)")
    validated = []
    real_validate = content_guard.validate
    monkeypatch.setattr(content_guard, "validate",
                        lambda text, kind="post": validated.append(text) or real_validate(text, kind=kind))

    url = "https://x.com/typofriend/status/2063500000000000101"
    assert twitter_client.reply_to_tweet(url, "Compute is the moat, not the model.") is W.DRY_RUN
    assert validated and validated[-1].endswith("(typo)")


def test_language_check_judges_the_text_before_the_typo(monkeypatch, settings_override):
    from src.guards import content_guard
    from src.core import reply_language
    from src.core import humanizer
    from src.x import twitter_client

    _dry_run_reply_path(monkeypatch)
    settings_override(HUMAN_TYPO_HANDLES="typofriend", FR_FORCED_REPLY_HANDLES="typofriend")
    monkeypatch.setattr(humanizer, "inject_human_typo", lambda text: text + " (typo)")
    judged, validated = [], []
    monkeypatch.setattr(reply_language, "looks_english", lambda text: judged.append(text) or False)
    real_validate = content_guard.validate
    monkeypatch.setattr(content_guard, "validate",
                        lambda text, kind="post": validated.append(text) or real_validate(text, kind=kind))

    url = "https://x.com/typofriend/status/2063500000000000103"
    assert twitter_client.reply_to_tweet(url, "Le calcul est le vrai fossé, pas le modèle.") is W.DRY_RUN
    assert judged and not judged[-1].endswith("(typo)")
    assert validated[-1].endswith("(typo)")


def test_refused_typo_text_leaves_the_tweet_fresh(monkeypatch, settings_override):
    from src.guards import content_guard
    from src.core import humanizer
    from src.x import twitter_client
    from src.guards.replied_store import load_replied

    _dry_run_reply_path(monkeypatch)
    settings_override(HUMAN_TYPO_HANDLES="typofriend")
    monkeypatch.setattr(humanizer, "inject_human_typo", lambda text: text + " (typo)")
    monkeypatch.setattr(content_guard, "validate",
                        lambda text, kind="post": (not text.endswith("(typo)"), "typo refused"))

    url = "https://x.com/typofriend/status/2063500000000000102"
    assert twitter_client.reply_to_tweet(url, "Compute is the moat, not the model.") is W.REFUSED
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
    assert twitter_client.post_tweet("A fresh original about inference costs.") is W.DRY_RUN
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
    monkeypatch.setattr(safari, "open_url", lambda *a, **k: True)
    monkeypatch.setattr(tc.time, "sleep", lambda *_: None)
    return recorded


REPLY = "Batching is where inference margins are won or lost."


def test_reply_ships_and_records_when_every_step_runs(monkeypatch):
    from src.x import twitter_client as tc
    from src.guards.replied_store import load_replied

    recorded = _live_browser(monkeypatch)
    url = "https://x.com/someone/status/2063500000000000110"

    assert tc.reply_to_tweet(url, REPLY) is W.SHIPPED
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

            assert tc.reply_to_tweet(url, REPLY, debate_turn=debate_turn) is W.FAILED, step
            assert recorded == [], step
            assert url not in load_replied(), step
    assert other in load_replied()


def test_reply_failing_at_submit_records_nothing_but_stays_marked(monkeypatch):
    from src.x import twitter_client as tc
    from src.guards.replied_store import load_replied

    for n, debate_turn in enumerate((False, True)):
        recorded = _live_browser(monkeypatch, failing_step="submit")
        url = f"https://x.com/someone/status/206350000000000013{n}"

        assert tc.reply_to_tweet(url, REPLY, debate_turn=debate_turn) is W.UNCONFIRMED
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

    assert tc.reply_to_tweet(url, REPLY, debate_turn=True) is W.REFUSED
    assert recorded == []
    assert url not in load_replied()


def test_live_reply_pastes_the_validated_text(monkeypatch, settings_override):
    """The text in the composer is the text admission validated, typo and
    dash cleanup included, never the raw draft."""
    from src.guards import content_guard
    from src.core import humanizer
    from src.x import safari, twitter_client as tc

    _live_browser(monkeypatch)
    pasted, validated = [], []
    monkeypatch.setattr(safari, "_paste_text", lambda text: pasted.append(text) or True)
    settings_override(HUMAN_TYPO_HANDLES="typofriend")
    monkeypatch.setattr(humanizer, "inject_human_typo", lambda text: text + " (typo)")
    real_validate = content_guard.validate
    monkeypatch.setattr(content_guard, "validate",
                        lambda text, kind="post": validated.append(text) or real_validate(text, kind=kind))
    url = "https://x.com/typofriend/status/2063500000000000165"

    assert tc.reply_to_tweet(url, "Targets are easy — conviction is the hard part.") is W.SHIPPED
    assert pasted == [validated[-1]]
    assert pasted[0].endswith("(typo)") and "—" not in pasted[0]


@pytest.mark.parametrize("dry_run", ["0", "1"])
def test_reply_naming_a_respected_account_writes_nothing(monkeypatch, dry_run, respected):
    """The respect list is judged before the dry-run exit: a Reply naming
    another Respected account is refused, nothing pasted, no ledger row, no
    claim, live or dry run, and the caller hears the refusal. The @handle of
    the author it answers ships."""
    from src.core import humanizer
    from src.guards.replied_store import load_replied
    from src.guards.reply_admission import Refusal
    from src.x import safari, twitter_client as tc

    recorded = _live_browser(monkeypatch)
    monkeypatch.setenv("DRY_RUN", dry_run)
    monkeypatch.setattr(humanizer, "casualize", lambda text: text)
    pasted = []
    monkeypatch.setattr(safari, "_paste_text", lambda text: pasted.append(text) or True)
    respected("kindperson", "otherperson")
    url = "https://x.com/kindperson/status/2063500000000000168"
    refusals = []

    assert tc.reply_to_tweet(url, f"@otherperson {REPLY}", on_refused=refusals.append) is W.REFUSED
    assert refusals == [Refusal.RESPECTED_ACCOUNT]
    assert recorded == [] and pasted == []
    assert url not in load_replied()

    addressed = f"@kindperson {REPLY}"
    shipped = tc.reply_to_tweet(url, addressed)
    assert shipped is (W.DRY_RUN if dry_run == "1" else W.SHIPPED)
    assert pasted == ([] if dry_run == "1" else [addressed])


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

    assert tc.reply_to_tweet(url, REPLY) is W.REFUSED
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
                        lambda: datetime(2026, 9, 23, 23, 30, tzinfo=ZoneInfo(config.BOT_TIMEZONE)))
    assert tc.reply_to_tweet("https://x.com/someone/status/2063500000000000167", REPLY) is W.REFUSED


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

    assert tc.reply_to_tweet(url, REPLY, debate_turn=True) is W.DRY_RUN
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
        assert tc.reply_to_tweet(url, REPLY) is W.REFUSED, url


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
    assert tc.reply_to_tweet(after, REPLY) is W.SHIPPED, "a stop at the final close hides no Reply"
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
    assert tc.post_tweet("a sponsor-clean original take about the market needing a therapist today") is W.DRY_RUN
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
        cg.is_duplicate = lambda text: True   # force dup
        assert tc.post_tweet("AI capex is the new rent again") is W.REFUSED, \
            "a near-duplicate post must return a falsy refusal, not None"
        # Not a dup, DRY_RUN → recorded, not shipped
        cg.is_duplicate = lambda text: False
        assert tc.post_tweet("a genuinely fresh original take about AI") is W.DRY_RUN
    finally:
        ag.can_post = orig_canpost
        cg.validate = orig_validate
        cg.is_duplicate = orig_isdup


def test_post_ships_the_reviewed_text_and_its_source_link(monkeypatch):
    """An Original ships as reviewed: its source link stays, and nothing
    casualizes the wording on the way out."""
    from urllib.parse import parse_qs, urlparse
    from src.guards import content_guard
    from src.x import safari, twitter_client as tc

    _live_browser(monkeypatch)
    monkeypatch.setattr(content_guard, "is_duplicate", lambda *a, **k: False)
    opened = []
    monkeypatch.setattr(safari, "open_url", lambda url, *a, **k: opened.append(url) or True)
    text = ("Inference is getting cheaper faster than training.\n\n"
            "https://huggingface.co/blog/inference-costs")
    assert tc.post_tweet(text) is W.SHIPPED
    assert parse_qs(urlparse(opened[0]).query)["text"] == [text]


@pytest.mark.parametrize("dry_run", ["0", "1"])
def test_post_naming_a_respected_account_writes_nothing(monkeypatch, dry_run, respected):
    """The respect list is judged before the dry-run exit: the Original is
    refused, nothing opened, no ledger row, live or dry run. A neutral text
    ships unchanged."""
    from urllib.parse import parse_qs, urlparse
    from src.guards import content_guard
    from src.x import safari, twitter_client as tc

    recorded = _live_browser(monkeypatch)
    monkeypatch.setenv("DRY_RUN", dry_run)
    monkeypatch.setattr(content_guard, "validate", lambda text, kind="original": (True, ""))
    monkeypatch.setattr(content_guard, "is_duplicate", lambda *a, **k: False)
    monkeypatch.setattr(tc, "_record_posted", lambda *a: None)
    opened = []
    monkeypatch.setattr(safari, "open_url", lambda url, *a, **k: opened.append(url) or True)
    respected("kindperson")

    for text in ("Inference is getting cheaper faster than training, says @kindperson.",
                 "Kindperson calling inference cheap is bullshit."):
        assert tc.post_tweet(text) is W.REFUSED, text
    assert recorded == [] and opened == []

    neutral = "Inference is getting cheaper faster than training."
    if dry_run == "1":
        assert tc.post_tweet(neutral) is W.DRY_RUN
        assert opened == []
    else:
        assert tc.post_tweet(neutral) is W.SHIPPED
        assert parse_qs(urlparse(opened[0]).query)["text"] == [neutral]


def test_concurrent_posts_cannot_both_take_last_slot(monkeypatch, settings_override):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from src.x import safari, twitter_client as tc
    clock(monkeypatch, datetime(2026, 9, 20, 12, tzinfo=TORONTO))
    for _ in range(7):
        ag.record(ag.POST)
    settings_override(MIN_SECONDS_BETWEEN_POSTS=0, POST_JITTER_SECONDS=0)
    monkeypatch.setattr(tc.content_guard if hasattr(tc, "content_guard") else editorial.content_guard, "is_duplicate", lambda *a: False)
    monkeypatch.setattr(tc, "_record_posted", lambda *a: None)
    monkeypatch.setattr(safari, "_run_applescript", lambda *a, **k: True)
    monkeypatch.setattr(safari, "open_url", lambda *a: True)
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
        results = list(pool.map(lambda _: tc.post_tweet(text), range(2)))
    assert sum(1 for result in results if result is W.SHIPPED) <= 1
    assert ag.profile_count_today() <= 8


# --- follows -----------------------------------------------------------------


@pytest.mark.parametrize("dry_run", ["0", "1"])
def test_follow_refused_while_the_followed_accounts_are_unreadable(monkeypatch, settings_override, tmp_path,
                                                                  memory_ledger, dry_run):
    """#171: with no following count and an unreadable followed list, the
    follow chokepoint skipped the ceiling. It now refuses before the page
    opens (conftest fails the test on open_url), writes no ledger row, not
    even a dry-run one, and leaves the file to the Operator. An unreadable
    ceiling counts as reached."""
    from src.x import twitter_client as tc

    monkeypatch.setenv("DRY_RUN", dry_run)
    settings_override(FOLLOWING_COUNT_OVERRIDE=None, FOLLOW_WHITELIST_ONLY=False,
                      MIN_SECONDS_BETWEEN_FOLLOWS=0, FOLLOW_SPACING_JITTER_SECONDS=0)
    follow_policy.record_followers(["someaccount"])
    followed = tmp_path / "followed_accounts.json"
    followed.write_text('["half')

    assert tc.follow_account("someaccount") is tc.FollowOutcome.CAP_REACHED

    assert memory_ledger.rows == []
    assert followed.read_text() == '["half'
    assert not (tmp_path / "following_count.json").exists()


# --- pins: record only a shipped pin (#142) --------------------------------------


def _scripted_pin_js(monkeypatch, steps):
    """Live pin_own_tweet with each osascript call answering the next step."""
    from src.x import safari, twitter_client as tc

    answers = iter(steps)

    monkeypatch.setenv("DRY_RUN", "0")
    monkeypatch.setattr(safari, "open_url", lambda *a, **k: True)
    monkeypatch.setattr(tc.time, "sleep", lambda *_: None)
    monkeypatch.setattr(safari, "close_front_tab", lambda: None)
    monkeypatch.setattr(safari, "_run_js", lambda *a, **k: next(answers))


@pytest.mark.parametrize("steps, outcome", [
    (["MORE_CLICKED", "PIN_CLICKED", "CONFIRMED"], W.SHIPPED),
    (["MORE_CLICKED", "PIN_CLICKED", "NO_CONFIRM"], W.UNCONFIRMED),
    (["MORE_CLICKED", "PIN_NOT_FOUND_4"], W.FAILED),
    (["NO_ARTICLE"], W.FAILED),
    (["MORE_CLICKED", "PIN_CLICKED", ""], W.UNCONFIRMED),
])
def test_pin_own_tweet_records_only_a_shipped_pin(monkeypatch, memory_ledger, steps, outcome):
    """Log only what shipped: one ledger row when the confirm dialog was
    clicked, none when a step failed or no confirm dialog appeared. A pin
    is not a profile publication."""
    from src.guards import action_guard
    from src.x import twitter_client as tc

    _scripted_pin_js(monkeypatch, steps)

    assert tc.pin_own_tweet(OWN_BEST) is outcome
    assert [r["target"] for r in pin_rows(memory_ledger)] == ([OWN_BEST.lower()] if outcome else [])
    assert action_guard.profile_count_today() == 0

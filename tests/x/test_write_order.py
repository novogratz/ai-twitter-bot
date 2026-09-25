"""The confirmed-write sequence of every write chokepoint, step by step
(#157): no page step on a refusal, no ledger row without a confirmed
write, the Safari lock released on every path, one dry-run line per
chokepoint. Every browser primitive is replaced by a tracer, so these
tests never reach Safari."""
from types import SimpleNamespace

import pytest

from src.core.logger import log
from src.core.state_errors import StateUnreadable
from src.guards import action_guard as ag
from src.guards import content_guard as cg
from src.guards import follow_policy as fp
from src.guards import replied_store as rs
from src.guards import reply_admission as ra
from src.guards.active_hours import OutsideActiveHours
from src.x import confirmed_write, safari, scraper
from src.x import twitter_client as tc
from src.x.confirmed_write import WriteOutcome as W
from src.x.twitter_client import FollowOutcome as F

POST_URL = "https://x.com/someone/status/2063500000000000500"
QUALITY = {"followers": "50K", "bio": "AI investor and GPU builder", "name": "Jane"}


def _script_kind(script):
    if script == tc._SUBMIT_KEYSTROKE:
        return "submit"
    if 'keystroke "r"' in script:
        return "reply_key"
    if "activate" in script:
        return "activate"
    return "applescript"


def _js_kind(js):
    for marker, kind in (("confirmationSheetConfirm", "confirm"),
                         ("NO_BTN", "follow"), ("caret", "more"), ("PIN_NOT_FOUND", "pin_item")):
        if marker in js:
            return kind
    return "js"


@pytest.fixture
def trace(monkeypatch):
    """Every browser primitive, guard and store write of the write path,
    traced in call order. `fail` names the AppleScript steps that fail,
    `js` and `likes` queue the page answers, `raise_at` names the step
    that raises OutsideActiveHours; `refuse` the guards that refuse, the
    follow policy with `follow_refusal`."""
    events, logs = [], []
    t = SimpleNamespace(events=events, logs=logs, fail=set(), js=[], likes=[], raise_at=None,
                        refuse=set(), claimed=set(), follow_refusal=fp.Refusal.POLICY)

    def step(name, value=None):
        events.append(name)
        if t.raise_at == name:
            raise OutsideActiveHours("stop")
        return value

    class Lock:
        def __enter__(self):
            events.append("lock")
            return self

        def __exit__(self, *exc):
            events.append("unlock")

    monkeypatch.setenv("DRY_RUN", "0")
    monkeypatch.setattr(safari, "_safari_lock", Lock())
    monkeypatch.setattr(safari, "_run_applescript",
                        lambda script, *a, **k: step(_script_kind(script), _script_kind(script) not in t.fail))
    monkeypatch.setattr(safari, "_paste_text", lambda text: step("paste", "paste" not in t.fail))
    monkeypatch.setattr(safari, "_run_js",
                        lambda js, *a, **k: step(f"js:{_js_kind(js)}", t.js.pop(0) if t.js else ""))
    monkeypatch.setattr(safari, "close_front_tab", lambda: step("close"))
    monkeypatch.setattr(safari, "open_url", lambda *a, **k: step("open", True))
    monkeypatch.setattr(tc.time, "sleep", lambda *_: None)
    monkeypatch.setattr(tc, "_page_posts",
                        lambda mode, target="": step(mode, t.likes.pop(0) if t.likes else {}))
    monkeypatch.setattr(tc, "_maybe_like_parent", lambda *a, **k: step("maybe_like"))
    monkeypatch.setattr(tc, "_mark_liked", lambda url: step("mark_liked"))
    monkeypatch.setattr(tc, "_already_liked", lambda url: False)
    monkeypatch.setattr(tc, "_record_posted", lambda text: step("history"))
    monkeypatch.setattr(fp, "_record_quality_reject", lambda handle: step("quality_reject"))
    monkeypatch.setattr(fp, "record_followed", lambda handle: step("followed_accounts"))
    monkeypatch.setattr(scraper, "_scrape_profile_quality", lambda: step("quality", dict(QUALITY)))

    def record(action, target="", dry_run=False):
        events.append(f"{'dry' if dry_run else 'record'}:{action}")
    monkeypatch.setattr(ag, "record", record)
    monkeypatch.setattr(fp, "adjust_following", lambda delta: step(f"adjust:{delta:+d}"))
    monkeypatch.setattr(ag, "jitter_sleep", lambda *_: step("jitter"))
    monkeypatch.setattr(fp, "is_whitelisted", lambda handle: False)
    monkeypatch.setattr(fp, "is_follower", lambda handle: True)
    monkeypatch.setattr(ag, "can_post", lambda *a, **k: (
        step("guard:can_post", (False, "refused") if "can_post" in t.refuse else (True, ""))))
    monkeypatch.setattr(fp, "judge", lambda *a, **k: step("guard:judge_follow", (
        fp.Verdict(t.follow_refusal, "refused") if "judge_follow" in t.refuse else fp.ADMITTED)))
    monkeypatch.setattr(cg, "validate", lambda *a, **k: (True, ""))
    monkeypatch.setattr(cg, "is_duplicate", lambda *a, **k: False)
    monkeypatch.setattr(cg, "note_posted", lambda text: step("note_posted"))

    def judge_reply(url, text, *, debate_turn=False):
        events.append("judge")
        if "judge" in t.refuse:
            return ra.Verdict(ra.Refusal.SPACING, "too soon", "someone")
        return ra.Verdict(None, author="someone", text=text)
    monkeypatch.setattr(ra, "judge_reply", judge_reply)

    def claim(url):
        events.append("claim")
        if url in t.claimed:
            return False
        t.claimed.add(url)
        return True

    def release(url):
        events.append("release")
        t.claimed.discard(url)
    monkeypatch.setattr(rs, "claim", claim)
    monkeypatch.setattr(rs, "release", release)

    for level in ("info", "warning"):
        monkeypatch.setattr(log, level, lambda msg, *a, **k: logs.append(str(msg) % a if a else str(msg)))
    return t


def _dry_run_line(t, tag):
    return [line for line in t.logs if line.startswith(f"[{tag}][DRY_RUN]")]


# --- post_tweet ---------------------------------------------------------------

TEXT = "Inference is getting cheaper faster than training, and the margin moves to serving."


def test_post_ships_then_records_then_closes(trace):
    assert tc.post_tweet(TEXT) is W.SHIPPED
    assert trace.events == ["guard:can_post", "lock", "guard:can_post", "open", "submit",
                            "record:post", "note_posted", "history", "close", "unlock"]


def test_post_refused_never_opens_the_page(trace):
    trace.refuse.add("can_post")
    assert tc.post_tweet(TEXT) is W.REFUSED
    assert trace.events == ["guard:can_post"]


def test_post_refused_on_recheck_releases_the_lock(trace, monkeypatch):
    answers = [(True, ""), (False, "slot taken")]
    monkeypatch.setattr(ag, "can_post", lambda *a: trace.events.append("guard:can_post") or answers.pop(0))
    assert tc.post_tweet(TEXT) is W.REFUSED
    assert trace.events == ["guard:can_post", "lock", "guard:can_post", "unlock"]


def test_post_failed_submit_records_nothing(trace):
    trace.fail.add("submit")
    assert tc.post_tweet(TEXT) is W.UNCONFIRMED
    assert trace.events == ["guard:can_post", "lock", "guard:can_post", "open", "submit", "close", "unlock"]


def test_post_dry_run(trace, monkeypatch):
    monkeypatch.setenv("DRY_RUN", "1")
    assert tc.post_tweet(TEXT) is W.DRY_RUN
    assert trace.events == ["guard:can_post", "dry:post"]
    assert _dry_run_line(trace, "POST")


# --- reply_to_tweet -------------------------------------------------------------

REPLY = "Batching is where inference margins are won or lost."
REPLY_STEPS = ["activate", "open", "activate", "maybe_like", "reply_key", "paste", "submit"]


def test_reply_ships_then_records_then_closes(trace):
    assert tc.reply_to_tweet(POST_URL, REPLY, debate_turn=True) is W.SHIPPED
    assert trace.events == ["lock", "judge", "claim", *REPLY_STEPS,
                            "record:reply", "record:debate_turn", "close", "unlock"]


def test_reply_refused_never_claims_nor_opens(trace):
    trace.refuse.add("judge")
    assert tc.reply_to_tweet(POST_URL, REPLY) is W.REFUSED
    assert trace.events == ["lock", "judge", "unlock"]


def test_reply_already_claimed_never_opens(trace):
    trace.claimed.add(POST_URL)
    assert tc.reply_to_tweet(POST_URL, REPLY) is W.REFUSED
    assert trace.events == ["lock", "judge", "claim", "unlock"]


@pytest.mark.parametrize("failing", ["reply_key", "paste"])
def test_reply_failing_before_submit_releases_the_claim(trace, failing):
    trace.fail.add(failing)
    assert tc.reply_to_tweet(POST_URL, REPLY) is W.FAILED
    sent = REPLY_STEPS[:REPLY_STEPS.index(failing) + 1]
    assert trace.events == ["lock", "judge", "claim", *sent, "release", "close", "unlock"]


def test_reply_failed_submit_keeps_the_claim(trace):
    trace.fail.add("submit")
    assert tc.reply_to_tweet(POST_URL, REPLY) is W.UNCONFIRMED
    assert trace.events == ["lock", "judge", "claim", *REPLY_STEPS, "close", "unlock"]
    assert POST_URL in trace.claimed


def test_reply_stop_mid_steps_releases_claim_and_lock(trace):
    trace.raise_at = "reply_key"
    with pytest.raises(OutsideActiveHours):
        tc.reply_to_tweet(POST_URL, REPLY)
    assert trace.events == ["lock", "judge", "claim", *REPLY_STEPS[:5], "release", "unlock"]


def test_reply_dry_run(trace, monkeypatch):
    monkeypatch.setenv("DRY_RUN", "1")
    assert tc.reply_to_tweet(POST_URL, REPLY, debate_turn=True) is W.DRY_RUN
    assert trace.events == ["lock", "judge", "dry:reply", "dry:debate_turn", "unlock"]
    assert _dry_run_line(trace, "REPLY")


# --- follow_account -------------------------------------------------------------


def test_follow_ships_then_records_then_closes(trace):
    trace.js.append("CLICKED")
    assert tc.follow_account("someone") is F.FOLLOWED
    assert trace.events == ["guard:judge_follow", "jitter", "lock", "open", "quality", "js:follow",
                            "record:follow", "followed_accounts", "adjust:+1", "close", "unlock"]


@pytest.mark.parametrize("refusal, outcome", [
    (fp.Refusal.BLOCKED_ACCOUNT, F.BLOCKED),
    (fp.Refusal.TOO_SOON, F.TOO_SOON),
    (fp.Refusal.CAP_REACHED, F.CAP_REACHED),
    (fp.Refusal.QUALITY_REJECTED, F.QUALITY_REJECTED),
    (fp.Refusal.POLICY, F.REFUSED),
])
def test_follow_refused_names_its_cause_and_never_opens_the_page(trace, refusal, outcome):
    trace.refuse.add("judge_follow")
    trace.follow_refusal = refusal
    assert tc.follow_account("someone") is outcome
    assert trace.events == ["guard:judge_follow"]
    assert trace.logs == [f"[FOLLOW] policy refuses @someone ({refusal.value}: refused)."]


@pytest.mark.parametrize("dry_run", ["0", "1"])
def test_follow_stops_on_an_unreadable_whitelist_before_the_profile_opens(trace, monkeypatch,
                                                                        dry_run):
    """#172: judge refused on an unreadable whitelist, and follow_engagers
    marked each Engager tried. It raises now, before the lock, the page and
    any ledger row, dry run included."""
    def unreadable(*a, **k):
        trace.events.append("guard:judge_follow")
        raise StateUnreadable("whitelist.json is unreadable")
    monkeypatch.setenv("DRY_RUN", dry_run)
    monkeypatch.setattr(fp, "judge", unreadable)
    with pytest.raises(StateUnreadable):
        tc.follow_account("someone")
    assert trace.events == ["guard:judge_follow"]


def test_follow_quality_refusal_closes_without_clicking(trace, monkeypatch):
    small = {"followers": "12", "bio": "dogs", "name": "x"}
    monkeypatch.setattr(scraper, "_scrape_profile_quality", lambda: trace.events.append("quality") or small)
    assert tc.follow_account("someone") is F.QUALITY_REJECTED
    assert trace.events == ["guard:judge_follow", "jitter", "lock", "open", "quality", "quality_reject",
                            "close", "unlock"]


def test_follow_refused_when_the_whitelist_turns_unreadable_after_admission(trace, monkeypatch):
    """The quality gate reads the whitelist on the open profile: unreadable
    by then, the follow stops before the page is scored, without a click
    or a quality reject."""
    def unreadable(handle):
        raise StateUnreadable("whitelist.json is unreadable")
    monkeypatch.setattr(fp, "is_whitelisted", unreadable)
    assert tc.follow_account("someone") is F.REFUSED
    assert trace.events == ["guard:judge_follow", "jitter", "lock", "open", "close", "unlock"]


@pytest.mark.parametrize("answer", ["NO_BTN", ""])
def test_follow_without_a_click_records_nothing(trace, answer):
    trace.js.append(answer)
    assert tc.follow_account("someone") is F.FAILED
    assert trace.events == ["guard:judge_follow", "jitter", "lock", "open", "quality", "js:follow",
                            "close", "unlock"]


def test_follow_of_an_account_already_followed_keeps_it_without_a_ledger_row(trace):
    """#172: an account already followed never entered the followed
    accounts, so Follow-back visited its profile every cycle. It enters
    them now, still without a ledger row or a count change."""
    trace.js.append("ALREADY")
    assert tc.follow_account("someone") is F.ALREADY_FOLLOWED
    assert trace.events == ["guard:judge_follow", "jitter", "lock", "open", "quality", "js:follow",
                            "followed_accounts", "close", "unlock"]


def test_follow_dry_run(trace, monkeypatch):
    monkeypatch.setenv("DRY_RUN", "1")
    assert tc.follow_account("someone") is F.DRY_RUN
    assert trace.events == ["guard:judge_follow", "dry:follow"]
    assert _dry_run_line(trace, "FOLLOW")


# --- like_tweet -----------------------------------------------------------------


def test_like_confirmed_then_marked_then_recorded(trace):
    trace.likes.extend([{"url": POST_URL, "result": "clicked"}, {"url": POST_URL, "result": "already_liked"}])
    assert tc.like_tweet(POST_URL) is tc.LikeOutcome.LIKED
    assert trace.events == ["lock", "press", "read", "mark_liked", "record:like", "unlock"]


def test_like_blocked_never_touches_the_page(trace, monkeypatch):
    monkeypatch.setattr(ra, "is_blocked_account", lambda handle: True)
    assert tc.like_tweet(POST_URL) is tc.LikeOutcome.BLOCKED
    assert trace.events == []


def test_like_unconfirmed_records_nothing(trace):
    trace.likes.extend([{"url": POST_URL, "result": "clicked"}, {"url": POST_URL, "result": "not_liked"}])
    assert tc.like_tweet(POST_URL) is tc.LikeOutcome.UNCONFIRMED
    assert trace.events == ["lock", "press", "read", "unlock"]


def test_like_without_status_id_never_takes_the_lock(trace):
    assert tc.like_tweet("https://x.com/someone") is tc.LikeOutcome.FAILED
    assert trace.events == []


def test_like_dry_run(trace, monkeypatch):
    monkeypatch.setenv("DRY_RUN", "1")
    assert tc.like_tweet(POST_URL) is tc.LikeOutcome.DRY_RUN
    assert trace.events == ["dry:like"]
    assert _dry_run_line(trace, "LIKE")


# --- pin_own_tweet --------------------------------------------------------------


def test_pin_confirmed_records_then_closes(trace):
    trace.js.extend(["MORE_CLICKED", "PIN_CLICKED", "CONFIRMED"])
    assert tc.pin_own_tweet(POST_URL) is W.SHIPPED
    assert trace.events == ["lock", "open", "js:more", "js:pin_item", "js:confirm",
                            "record:pin", "close", "unlock"]


@pytest.mark.parametrize("answers, steps, outcome", [
    (["NO_ARTICLE"], ["js:more"], W.FAILED),
    (["MORE_CLICKED", "PIN_NOT_FOUND_3"], ["js:more", "js:pin_item"], W.FAILED),
    (["MORE_CLICKED", "PIN_CLICKED", "NO_CONFIRM"], ["js:more", "js:pin_item", "js:confirm"], W.UNCONFIRMED),
    (["MORE_CLICKED", "PIN_CLICKED", ""], ["js:more", "js:pin_item", "js:confirm"], W.UNCONFIRMED),
])
def test_pin_not_confirmed_records_nothing(trace, answers, steps, outcome):
    trace.js.extend(answers)
    assert tc.pin_own_tweet(POST_URL) is outcome
    assert trace.events == ["lock", "open", *steps, "close", "unlock"]


def test_pin_dry_run(trace, monkeypatch):
    monkeypatch.setenv("DRY_RUN", "1")
    assert tc.pin_own_tweet(POST_URL) is W.DRY_RUN
    assert trace.events == ["dry:pin"]
    assert _dry_run_line(trace, "PIN")


# --- the sequence itself --------------------------------------------------------


def test_only_a_shipped_write_is_truthy():
    assert [o for o in W if o] == [W.SHIPPED]
    assert [o for o in tc.LikeOutcome if o] == [tc.LikeOutcome.LIKED]
    assert [o for o in F if o] == [F.FOLLOWED]


@pytest.mark.parametrize("before_lock, under_lock", [
    ((), ()),
    ((confirmed_write.DRY_RUN_EXIT,), (confirmed_write.DRY_RUN_EXIT,)),
])
def test_a_write_without_exactly_one_dry_run_exit_never_runs(trace, before_lock, under_lock):
    """Without its DRY_RUN_EXIT a chokepoint would act live under DRY_RUN."""
    with pytest.raises(ValueError):
        confirmed_write.run("TEST", W, would=lambda: "test", rows=lambda: [],
                            steps=lambda: trace.events.append("steps") or W.SHIPPED,
                            before_lock=before_lock, under_lock=under_lock)
    assert trace.events == []


def test_stop_at_the_final_close_never_hides_a_shipped_write(trace):
    """The cleanup close after a confirmed write is not part of the write: a
    stop raised there returns SHIPPED, so the caller logs what shipped."""
    trace.raise_at = "close"
    assert tc.reply_to_tweet(POST_URL, REPLY) is W.SHIPPED
    assert trace.events == ["lock", "judge", "claim", *REPLY_STEPS, "record:reply", "close", "unlock"]
    assert POST_URL in trace.claimed


def test_stop_at_the_close_after_a_failure_still_raises(trace):
    trace.fail.add("paste")
    trace.raise_at = "close"
    with pytest.raises(OutsideActiveHours):
        tc.reply_to_tweet(POST_URL, REPLY)
    assert trace.events[-2:] == ["close", "unlock"]


@pytest.mark.parametrize("write", [
    lambda: tc.post_tweet(TEXT),
    lambda: tc.follow_account("someone"),
    lambda: tc.pin_own_tweet(POST_URL),
])
def test_a_stop_during_the_page_steps_records_nothing_and_releases_the_lock(trace, write):
    trace.raise_at = "open"
    with pytest.raises(OutsideActiveHours):
        write()
    assert trace.events[-2:] == ["open", "unlock"]
    assert not [e for e in trace.events if e.startswith("record:")]


def test_refusal_and_failure_read_apart_in_the_log(trace, monkeypatch):
    """A refusal keeps the guard's line alone; a failure adds the outcome
    line, and the refusal's outcome line goes to debug."""
    debug = []
    monkeypatch.setattr(log, "debug", lambda msg, *a, **k: debug.append(str(msg)))
    trace.refuse.add("judge_follow")
    tc.follow_account("someone")
    trace.refuse.clear()
    trace.js.append("NO_BTN")
    tc.follow_account("someone")
    assert [line for line in trace.logs if line.startswith("[FOLLOW] Write ")] == [
        "[FOLLOW] Write failed; no ledger row."]
    assert debug == ["[FOLLOW] Write refused; no ledger row."]


def test_a_like_walk_skipping_liked_posts_logs_one_line_each(trace, monkeypatch):
    monkeypatch.setattr(tc, "_already_liked", lambda url: True)
    assert tc.like_tweet(POST_URL) is tc.LikeOutcome.ALREADY_LIKED
    assert trace.logs == [f"[LIKE] already liked {POST_URL[-50:]}; skipping."]

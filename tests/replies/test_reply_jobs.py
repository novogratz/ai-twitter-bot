"""The reply jobs ask Reply admission before paying for a generation
(issue #100). Tested through the jobs' cycles: the generator and the
chokepoint are stubs, the Replied store, the ledger and BLOCKLIST are real.
conftest points the state files at tmp_path, empties each job's `_skipped`
set and fixes the clock at noon Toronto."""
import math
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from src.core import config
from src.guards import replied_store
from src.x import x_urls
from src.core.state_errors import StateUnreadable
from tests.helpers import fresh


DRAFT = "Batching is where inference margins are won or lost, not in the model."


def corrupt_replied_store():
    with open(config.REPLIED_FILE, "w") as f:
        f.write("[")


@pytest.fixture
def blocklist(monkeypatch):
    monkeypatch.setattr(config, "BLOCKLIST", {"pgm_pm"})


# --- direct_reply and feed_sweeper (shared pipeline) ------------------------


@pytest.fixture
def pipeline(monkeypatch, blocklist):
    """direct_reply's pipeline with a stub model and a stub chokepoint."""
    from src.replies import direct_reply as dr

    monkeypatch.setattr(dr, "_is_on_niche", lambda text: True)
    monkeypatch.setattr(dr, "llm_hourly_limit_status", lambda: (False, 0, 999, 0))
    monkeypatch.setattr(dr, "log_reply", lambda *a, **k: None)
    generated, sent = [], []
    drafts = {}

    def generate(author, text, lang="fr"):
        generated.append(text)
        return drafts.get(text, DRAFT)

    def chokepoint(url, text):
        sent.append(url)
        return True

    monkeypatch.setattr(dr, "_generate_single_reply", generate)
    monkeypatch.setattr(dr, "reply_to_tweet", chokepoint)
    return dr, generated, sent, drafts


def test_direct_reply_asks_admission_before_generating(pipeline):
    dr, generated, sent, _ = pipeline
    answered = fresh("someone", n=1)
    replied_store.claim(answered)
    refused = {
        fresh("pgm_pm", n=2): "blocked",
        fresh(config.BOT_HANDLE, n=3): "own",
        answered: "answered",
        "https://x.com/i/web/status/" + x_urls.status_id(fresh("x", n=4)): "no author",
    }
    ok = fresh("someone", n=5)
    tweets = [{"url": u, "text": t, "author": "Display Name"} for u, t in refused.items()]
    tweets.append({"url": ok, "text": "admitted", "author": "Display Name"})

    assert dr._reply_to_tweets(tweets, set(), "SEARCH-HOT") == 1
    assert generated == ["admitted"], "no generation for a post admission refuses"
    assert sent == [ok]
    assert dr._skipped == set(refused) | {ok}, "definitive refusals and answered posts are set aside"


def test_direct_reply_sets_aside_model_skips_but_replays_temporary_refusals(pipeline, monkeypatch):
    dr, generated, sent, drafts = pipeline
    declined, failed, bounced = fresh("someone", n=1), fresh("other", n=2), fresh("third", n=3)
    drafts.update({"declined": "", "failed": None})  # the model said SKIP; the call failed
    monkeypatch.setattr(dr, "reply_to_tweet", lambda url, text: sent.append(url) or False)
    tweets = [{"url": declined, "text": "declined"}, {"url": failed, "text": "failed"},
              {"url": bounced, "text": "bounced"}]

    for _cycle in range(2):
        dr._reply_to_tweets(list(tweets), set(), "SEARCH-HOT")

    assert generated == ["declined", "failed", "bounced", "failed", "bounced"], \
        "a SKIP is not paid twice; a failed call or a chokepoint refusal is replayed"
    assert dr._skipped == {declined}
    assert replied_store.load_replied() == set(), "nothing shipped, nothing marked"


def test_direct_reply_cycle_never_marks_unsent_candidates(pipeline, monkeypatch):
    """Defect 3: the VIP lane and the pipeline both marked candidates that
    never shipped, and the cycle saved them into the Replied store."""
    from src.x import scraper, twitter_client as tc

    dr, generated, sent, _ = pipeline
    vip, searched = fresh("graphseo", n=1), fresh("someone", n=2)
    monkeypatch.setenv("VIP_SCAN_HANDLES", "Graphseo")
    monkeypatch.setattr(scraper, "scrape_x_search", lambda *a, **k: [{"url": vip, "text": "vip post"}])
    monkeypatch.setattr(dr, "scrape_x_search", lambda *a, **k: [{"url": searched, "text": "search post"}])
    monkeypatch.setattr(dr, "_generate_graphseo_reply", lambda text: "réponse précise sur le trafic organique")
    monkeypatch.setattr(tc, "reply_to_tweet", lambda url, text: sent.append(url) or False)
    monkeypatch.setattr(dr, "reply_to_tweet", lambda url, text: sent.append(url) or False)

    dr.run_direct_reply_cycle()

    assert sent == [vip, searched], "each candidate tried once per cycle"
    assert replied_store.load_replied() == set()


def test_direct_reply_cycle_stops_on_unreadable_store(pipeline):
    dr, generated, _, _ = pipeline
    corrupt_replied_store()
    with pytest.raises(StateUnreadable):
        dr._reply_to_tweets([{"url": fresh("someone"), "text": "post"}], set(), "SEARCH-HOT")
    assert generated == []


def test_direct_reply_vip_lane_does_not_swallow_unreadable_store(pipeline, monkeypatch):
    from src.x import scraper, twitter_client as tc

    dr, _, _, _ = pipeline
    searched = []

    def unreadable(url, text):
        raise StateUnreadable("replied store unreadable")

    monkeypatch.setenv("VIP_SCAN_HANDLES", "Graphseo")
    monkeypatch.setattr(scraper, "scrape_x_search", lambda *a, **k: [{"url": fresh("graphseo"), "text": "vip post"}])
    monkeypatch.setattr(dr, "scrape_x_search", lambda *a, **k: searched.append(1) or [])
    monkeypatch.setattr(dr, "_generate_graphseo_reply", lambda text: "réponse précise sur le trafic organique")
    monkeypatch.setattr(tc, "reply_to_tweet", unreadable)
    with pytest.raises(StateUnreadable):
        dr.run_direct_reply_cycle()
    assert searched == [], "the search lane never starts"


def test_direct_reply_cycle_does_not_swallow_unreadable_store(pipeline, monkeypatch):
    dr, generated, _, _ = pipeline
    searched = []
    monkeypatch.setattr(dr, "_run_graphseo_scan", lambda tried: None)
    monkeypatch.setattr(dr, "scrape_x_search",
                        lambda *a, **k: searched.append(1) or [{"url": fresh("someone"), "text": "post"}])
    corrupt_replied_store()
    with pytest.raises(StateUnreadable):
        dr.run_direct_reply_cycle()
    assert searched == [1], "the cycle stops at the first query instead of scraping the rest"
    assert generated == []


def test_feed_sweep_judges_the_url_handle_not_the_display_name(pipeline, monkeypatch):
    from src.replies import feed_sweeper_bot as fs
    from src.x import scraper

    dr, generated, sent, _ = pipeline
    monkeypatch.setattr(fs, "_harvest_active_authors", lambda tweets: None)
    blocked = fresh("pgm_pm", n=1)
    named_like_us = fresh("someone", n=2)
    feed = [
        {"url": blocked, "text": "blocked by handle", "author": "Friendly Name"},
        {"url": named_like_us, "text": "admitted", "author": config.BOT_HANDLE},
    ]
    monkeypatch.setattr(scraper, "scrape_home_feed", lambda **k: list(feed))
    monkeypatch.setattr(scraper, "scrape_following_feed", lambda **k: [])

    fs.run_feed_sweep_cycle()

    assert generated == ["admitted"]
    assert sent == [named_like_us]
    assert fs._skipped == {blocked, named_like_us}
    assert dr._skipped == set(), "each job keeps its own set"


def viral(handle, n):
    return {"url": fresh(handle, n=n), "text": f"OpenAI ships a new model {n}",
            "author": handle, "likes": 50_000, "replies": 900}


def test_feed_sweep_only_replies_even_to_viral_posts(pipeline, monkeypatch):
    from src.replies import feed_sweeper_bot as fs
    from src.x import scraper

    dr, generated, sent, _ = pipeline
    monkeypatch.setattr(fs, "_harvest_active_authors", lambda tweets: None)
    feed = [viral("someone", 1), viral("other", 2)]
    monkeypatch.setattr(scraper, "scrape_home_feed", lambda **k: list(feed))
    monkeypatch.setattr(scraper, "scrape_following_feed", lambda **k: [])

    fs.run_feed_sweep_cycle()

    assert sorted(sent) == sorted(t["url"] for t in feed)


def test_direct_reply_only_replies_on_favourite_profiles(pipeline, monkeypatch):
    from src.x import scraper, twitter_client as tc

    dr, generated, sent, _ = pipeline
    vip, searched = viral("TheBTCTherapist", 1), viral("someone", 2)
    monkeypatch.setenv("VIP_SCAN_HANDLES", "TheBTCTherapist")
    monkeypatch.setattr(scraper, "scrape_x_search", lambda *a, **k: [vip])
    monkeypatch.setattr(dr, "scrape_x_search", lambda *a, **k: [searched])
    monkeypatch.setattr(dr, "generate_vip_reply", lambda *a, **k: DRAFT)
    monkeypatch.setattr(tc, "reply_to_tweet", lambda url, text: sent.append(url) or True)

    dr.run_direct_reply_cycle()

    assert sent == [vip["url"], searched["url"]]


# --- Reply spacing in the pipeline (#131) -------------------------------------


@pytest.fixture
def spacing(pipeline, monkeypatch, memory_ledger):
    """The pipeline on a Toronto noon clock that its sleeps advance. The stub
    chokepoint records each Reply in the ledger, as a ship would."""
    from src.guards import action_guard as ag, active_hours

    dr, generated, sent, _ = pipeline
    s = SimpleNamespace(dr=dr, sent=sent, slept=[], waited_at_send=[], gap_after_send=[],
                        on_sleep=lambda: None, ledger=memory_ledger,
                        now=datetime(2026, 9, 21, 12, tzinfo=ZoneInfo("America/Toronto")))
    monkeypatch.setattr(active_hours, "now_local", lambda: s.now)
    monkeypatch.setattr(ag, "now_local", lambda: s.now)

    def sleep(seconds):
        s.slept.append(seconds)
        # Round up like time.sleep, which never returns early.
        s.now += timedelta(microseconds=math.ceil(seconds * 1_000_000))
        s.on_sleep()

    def chokepoint(url, text):
        s.waited_at_send.append(sum(s.slept))
        assert ag.seconds_until_allowed(ag.REPLY) == 0, "sent before the spacing cleared"
        sent.append(url)
        ag.record(ag.REPLY, url)
        # The clock stands still: the whole gap is left to wait.
        s.gap_after_send.append(ag.seconds_until_allowed(ag.REPLY))
        return True

    monkeypatch.setattr(dr, "_sleep", sleep)
    monkeypatch.setattr(dr, "reply_to_tweet", chokepoint)
    return s


def test_pipeline_waits_out_the_spacing_after_its_own_reply(spacing):
    """Generation N+1 is ready as Reply N ships: it waits out N's gap."""
    s = spacing
    tweets = [{"url": fresh("someone", n=1), "text": "one"}, {"url": fresh("other", n=2), "text": "two"}]

    assert s.dr._reply_to_tweets(tweets, set(), "SEARCH-HOT") == 2

    assert s.waited_at_send == [0, pytest.approx(s.gap_after_send[0])]
    assert all(0 < step <= 1.0 for step in s.slept), "short slices, so a stop cuts the wait"


def test_pipeline_does_not_wait_when_the_spacing_is_clear(spacing):
    from src.guards import action_guard as ag

    s = spacing
    ag.record(ag.REPLY, fresh("earlier"))
    s.now += timedelta(seconds=60)
    url = fresh("someone", n=1)

    assert s.dr._reply_to_tweets([{"url": url, "text": "post"}], set(), "SEARCH-HOT") == 1

    assert s.slept == [] and s.sent == [url]


def test_a_reply_from_another_job_during_the_wait_is_refused_unconsumed(spacing, monkeypatch):
    """The chokepoint stays the judge: another job's Reply lands mid-wait,
    the real reply_to_tweet refuses on spacing before Safari, writes no
    ledger row, and the post stays replayable."""
    from src.guards import action_guard as ag, reply_admission
    from src.guards.reply_admission import Refusal
    from src.x import twitter_client as tc

    s = spacing
    monkeypatch.setattr(config, "REPLY_JITTER_SECONDS", 0)  # every gap is exactly the minimum
    ag.record(ag.REPLY, fresh("earlier"))

    def another_job_replies_after_the_first_slice():
        if len(s.slept) == 1:
            ag.record(ag.REPLY, fresh("elsewhere", n=9))

    s.on_sleep = another_job_replies_after_the_first_slice
    verdicts = []
    judge = reply_admission.judge_reply
    monkeypatch.setattr(reply_admission, "judge_reply",
                        lambda *a, **k: verdicts.append(judge(*a, **k)) or verdicts[-1])
    monkeypatch.setattr(s.dr, "reply_to_tweet", tc.reply_to_tweet)
    url, tried = fresh("someone", n=1), set()

    assert s.dr._reply_to_tweets([{"url": url, "text": "post"}], tried, "SEARCH-HOT") == 0

    assert sum(s.slept) == config.MIN_SECONDS_BETWEEN_REPLIES
    assert [v.refusal for v in verdicts] == [Refusal.SPACING]
    assert s.ledger.count(ag.REPLY, s.now.date()) == 2, "only the earlier Reply and the other job's"
    assert url not in s.dr._skipped and url not in replied_store.load_replied()
    assert url in tried, "tried again next cycle, with a new generation"


@pytest.mark.parametrize("cut", ["stop", "overnight"])
def test_the_spacing_wait_ends_on_a_stop_request_and_overnight(spacing, monkeypatch, cut):
    import threading
    from src.guards import action_guard as ag, active_hours

    s = spacing
    stop = threading.Event()
    monkeypatch.setattr(active_hours, "_STOP", stop)

    def cut_short():
        if cut == "stop":
            stop.set()
        else:
            s.now = s.now.replace(hour=22, minute=0, second=0)

    ag.record(ag.REPLY, fresh("earlier"))
    s.on_sleep = cut_short

    with pytest.raises(active_hours.OutsideActiveHours):
        s.dr._reply_to_tweets([{"url": fresh("someone", n=1), "text": "post"}], set(), "SEARCH-HOT")

    assert len(s.slept) == 1, "the next slice sees the stop or 22:00"
    assert s.sent == [], "nothing ships"
    assert s.ledger.count(ag.REPLY, s.now.date()) == 1


def test_reply_search_skips_a_quote_action_without_any_write(monkeypatch):
    from src.replies import reply_bot as rb

    quoted, answered = fresh("someone", n=1), fresh("other", n=2)
    monkeypatch.setenv("ENABLE_REPLY_SEARCH", "1")
    monkeypatch.setattr(rb, "refresh_feed", lambda: None)
    monkeypatch.setattr(rb, "get_recent_tweets", lambda hours: [])
    monkeypatch.setattr(rb, "generate_replies", lambda **k: [
        {"tweet_url": quoted, "reply": DRAFT, "type": "quote"},
        {"tweet_url": answered, "reply": DRAFT, "type": "reply"},
    ])
    monkeypatch.setattr(rb.time, "sleep", lambda *a: None)
    sent, logged = [], []
    monkeypatch.setattr(rb, "reply_to_tweet", lambda url, text: sent.append(url) or True)
    monkeypatch.setattr(rb, "log_reply", lambda url, *a, **k: logged.append(url))

    rb.run_reply_cycle()

    assert sent == logged == [answered], "a quote item ships nothing and logs nothing"


# --- reply search (one model call finds and drafts) --------------------------


def test_reply_search_surface_disabled_by_default(monkeypatch):
    """2026-07-19: the LLM-web-search reply surface (reply_bot -> reply_agent)
    is retired by default. Web search cannot index <=24h x.com tweets, so the
    path either hallucinated URLs (PR #59) or answered conversationally to its
    own stale FR-era persona prompt — 388 failed Claude CLI calls for 1 reply
    over 35h, plus a refresh_feed() Safari touch every ~3 min. Pin: with
    ENABLE_REPLY_SEARCH unset/0 the cycle returns before ANY side effect
    (no Safari, no LLM); =1 re-arms the path. Env read at call time."""
    from src.replies import reply_bot as rb

    calls = []
    monkeypatch.setattr(rb, "refresh_feed", lambda: calls.append("safari"))
    monkeypatch.setattr(rb, "generate_replies", lambda **kw: calls.append("llm") or None)

    # Default (unset) -> disabled, zero side effects
    monkeypatch.delenv("ENABLE_REPLY_SEARCH", raising=False)
    rb.run_reply_cycle()
    assert calls == [], "disabled surface must not touch Safari or the LLM"

    # Explicit 0 -> same
    monkeypatch.setenv("ENABLE_REPLY_SEARCH", "0")
    rb.run_reply_cycle()
    assert calls == [], "ENABLE_REPLY_SEARCH=0 must short-circuit the cycle"

    # =1 -> the path runs again (env read at call time, no restart needed)
    monkeypatch.setenv("ENABLE_REPLY_SEARCH", "1")
    monkeypatch.setattr(rb, "MAX_REPLIES_PER_CYCLE", 5)
    rb.run_reply_cycle()
    assert calls == ["safari", "llm"], "ENABLE_REPLY_SEARCH=1 must re-arm the surface"


@pytest.fixture
def reply_search(monkeypatch, blocklist):
    """reply_bot with a stub search-and-draft model and a stub chokepoint;
    the model returns `batch`."""
    from src.replies import reply_bot as rb

    batch, searched, sent, logged = [], [], [], []

    def generate(recent_topics=None, already_replied=None):
        searched.append(already_replied)
        return list(batch)

    monkeypatch.setenv("ENABLE_REPLY_SEARCH", "1")
    monkeypatch.setattr(rb, "MAX_REPLIES_PER_CYCLE", 20)
    monkeypatch.setattr(rb, "refresh_feed", lambda: None)
    monkeypatch.setattr(rb, "get_recent_tweets", lambda hours: [])
    monkeypatch.setattr(rb, "generate_replies", generate)
    monkeypatch.setattr(rb, "reply_to_tweet", lambda url, text: sent.append(url) or True)
    monkeypatch.setattr(rb, "log_reply", lambda url, *a, **k: logged.append(url))
    monkeypatch.setattr(rb.time, "sleep", lambda *a: None)
    return rb, batch, searched, sent, logged


def target(url, text=""):
    return {"tweet_url": url, "reply": DRAFT, "type": "reply", "tweet_text": text}


def test_reply_search_asks_admission_before_sending(reply_search):
    rb, batch, searched, sent, logged = reply_search
    answered = fresh("someone", n=1)
    replied_store.claim(answered)
    ok = fresh("someone", n=5)
    batch += [
        target(fresh("pgm_pm", n=2)),
        target(fresh(config.BOT_HANDLE, n=3)),
        target(answered),
        target("https://x.com/i/web/status/" + x_urls.status_id(fresh("x", n=4))),
        target(fresh("someone", minutes=49 * 60, n=6)),
        target(ok),
    ]

    rb.run_reply_cycle()

    assert len(searched) == 1 and answered in searched[0], "the model is told which posts are answered"
    assert sent == logged == [ok], "a post admission refuses never reaches the chokepoint"


def test_reply_search_never_writes_the_replied_store(reply_search, monkeypatch):
    """Defect 3 of #100: the cycle marked candidates before sending and
    saved them into the Replied store at the end, shipped or not."""
    rb, batch, _, sent, logged = reply_search
    refused, shipped = fresh("someone", n=1), fresh("other", n=2)
    batch += [target(refused), target(shipped), target(refused)]
    monkeypatch.setattr(rb, "reply_to_tweet", lambda url, text: sent.append(url) or url == shipped)

    rb.run_reply_cycle()

    assert sent == [refused, shipped], "each target tried once per cycle"
    assert logged == [shipped], "log only what shipped"
    assert replied_store.load_replied() == set(), "only the chokepoint marks the store"


def test_reply_search_stops_on_unreadable_store(reply_search):
    rb, batch, searched, sent, _ = reply_search
    batch.append(target(fresh("someone")))
    corrupt_replied_store()
    with pytest.raises(StateUnreadable):
        rb.run_reply_cycle()
    assert searched == [], "the model is not paid on an unreadable store"
    assert sent == []


def test_reply_search_does_not_swallow_unreadable_store_at_the_chokepoint(reply_search, monkeypatch):
    rb, batch, _, sent, _ = reply_search
    batch += [target(fresh("someone", n=1)), target(fresh("other", n=2))]

    def unreadable(url, text):
        sent.append(url)
        raise StateUnreadable("replied store unreadable")

    monkeypatch.setattr(rb, "reply_to_tweet", unreadable)
    with pytest.raises(StateUnreadable):
        rb.run_reply_cycle()
    assert len(sent) == 1, "the cycle stops at the first unreadable store"


# --- early_bird and mega_watch (profile scans) ------------------------------


def test_early_reply_targets_are_curator_driven():
    """2026-06-07 PM operator mandate: NO static target lists — the scan
    pools come from account_curator.tracked_handles(), pinned with the only
    two operator-mandated keepers (TheBTCTherapist, Graphseo)."""
    from src.replies.early_bird_bot import EARLY_BIRD_ACCOUNTS
    from src.replies.mega_watch_bot import MEGA_ACCOUNTS
    assert EARLY_BIRD_ACCOUNTS == [] and MEGA_ACCOUNTS == [], (
        "static early-reply lists must stay empty — pools come from the curator"
    )
    from src.account.account_curator import PINNED, tracked_handles
    # Mindset4Money_X pinned 2026-06-10: measured 100-like / 13.3K-view
    # reply conversion on his question post (operator: "more things like this").
    assert tuple(PINNED) == ("TheBTCTherapist", "Graphseo", "Mindset4Money_X")
    handles = tracked_handles(limit=5)
    assert handles[0] == "TheBTCTherapist" and handles[1] == "Graphseo"


def _status_url(handle, minutes_ago):
    from datetime import datetime, timezone
    from src.replies.reply_bot import _TWITTER_EPOCH

    ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000) - minutes_ago * 60_000
    return f"https://x.com/{handle}/status/{(ms - _TWITTER_EPOCH) << 22}"


def test_mega_watch_skips_posts_older_than_max_age(monkeypatch):
    from src.replies import mega_watch_bot as mw

    fresh = _status_url("bigai", 1)
    stale = _status_url("bigai", 30)
    monkeypatch.setattr(mw, "_watch_pool", lambda: ["bigai"])
    monkeypatch.setattr(mw, "scrape_profile_tweets", lambda *a, **k: [
        {"url": stale, "author": "bigai", "text": "GPU clusters are the new power plants"},
        {"url": fresh, "author": "bigai", "text": "GPU clusters are the new power plants"},
    ])
    monkeypatch.setattr(mw.x_urls, "is_reply_like_tweet", lambda *a, **k: False)
    monkeypatch.setattr(mw, "_is_on_niche", lambda text: True)
    monkeypatch.setattr(mw, "_generate_single_reply",
                        lambda **k: "Power is the real bottleneck for these clusters.")
    monkeypatch.setattr(mw, "humanize", lambda text: text)
    monkeypatch.setattr(mw, "log_reply", lambda *a, **k: None)
    monkeypatch.setattr(mw.time, "sleep", lambda *_: None)
    replied_to = []
    monkeypatch.setattr(mw, "reply_to_tweet", lambda url, text: replied_to.append(url) or True)

    mw.run_mega_watch_cycle()

    assert replied_to == [fresh]


@pytest.fixture(params=["early_bird", "mega_watch"])
def profile_job(request, monkeypatch, blocklist):
    """A profile-scanning job whose scan pool is `profiles` (handle → posts)."""
    from src.replies import direct_reply as dr
    from src.replies import early_bird_bot as eb
    from src.core import evolution_store
    from src.replies import mega_watch_bot as mw

    module, run = {"early_bird": (eb, eb.run_early_bird_cycle),
                   "mega_watch": (mw, mw.run_mega_watch_cycle)}[request.param]
    profiles = {}
    monkeypatch.setattr(eb, "_scan_pool", lambda: list(profiles))
    monkeypatch.setattr(mw, "_watch_pool", lambda: list(profiles))
    monkeypatch.setattr(dr, "ALWAYS_REPLY_ACCOUNTS", [])
    monkeypatch.setattr(evolution_store, "filter_and_weight", lambda handles: list(handles))
    monkeypatch.setattr(module, "scrape_profile_tweets", lambda handle, **k: list(profiles[handle]))
    monkeypatch.setattr(module, "_is_on_niche", lambda text: True)
    monkeypatch.setattr(module, "log_reply", lambda *a, **k: None)
    monkeypatch.setattr(module.time, "sleep", lambda *a: None)
    generated, sent = [], []
    drafts = {}

    def generate(author, tweet_text, lang="fr"):
        generated.append(tweet_text)
        return drafts.get(tweet_text, DRAFT)

    monkeypatch.setattr(module, "_generate_single_reply", generate)
    monkeypatch.setattr(module, "reply_to_tweet", lambda url, text: sent.append(url) or True)
    return module, run, profiles, generated, sent, drafts


def post(handle, text, n=0):
    return {"url": fresh(handle, minutes=1, n=n), "text": text, "author": handle}


def test_profile_jobs_ask_admission_before_generating(profile_job):
    module, run, profiles, generated, sent, _ = profile_job
    blocked, admitted = post("pgm_pm", "blocked", n=1), post("someone", "admitted", n=2)
    profiles.update({"pgm_pm": [blocked], "someone": [admitted]})

    run()

    assert generated == ["admitted"]
    assert sent == [admitted["url"]]
    assert module._skipped == {blocked["url"], admitted["url"]}


def test_profile_jobs_set_aside_model_skips_but_replay_failed_calls(profile_job):
    module, run, profiles, generated, sent, drafts = profile_job
    declined, failed = post("someone", "declined", n=1), post("other", "failed", n=2)
    profiles.update({"someone": [declined], "other": [failed]})
    drafts.update({"declined": "", "failed": None})

    run()
    run()

    assert sorted(generated) == ["declined", "failed", "failed"], "a SKIP is not paid twice"
    assert sent == []
    assert module._skipped == {declined["url"]}


def test_profile_jobs_stop_on_unreadable_store(profile_job):
    module, run, profiles, generated, _, _ = profile_job
    profiles["someone"] = [post("someone", "post")]
    corrupt_replied_store()
    with pytest.raises(StateUnreadable):
        run()
    assert generated == []


def test_profile_jobs_do_not_swallow_unreadable_store_at_the_chokepoint(profile_job, monkeypatch):
    module, run, profiles, _, _, _ = profile_job
    profiles["someone"] = [post("someone", "post")]

    def unreadable(url, text):
        raise StateUnreadable("replied store unreadable")

    monkeypatch.setattr(module, "reply_to_tweet", unreadable)
    with pytest.raises(StateUnreadable):
        run()


# --- debate (mentions) ------------------------------------------------------


class _Llm:
    def __init__(self, stdout, returncode=0):
        self.stdout, self.returncode, self.stderr = stdout, returncode, ""


@pytest.fixture
def debate(monkeypatch, blocklist):
    from src.replies import debate_bot as db
    from src.x import scraper, twitter_client as tc

    mentions = []
    outputs = {}
    generated, sent = [], []

    def llm(prompt, *a, **k):
        text = next(t for t in outputs if f'"{t}"' in prompt)  # the quoted mention
        generated.append(text)
        return outputs[text]

    monkeypatch.setenv("ENABLE_DEBATES", "1")
    monkeypatch.setattr(scraper, "scrape_mentions", lambda **k: list(mentions))
    monkeypatch.setattr(tc, "reply_to_tweet", lambda url, text, **k: sent.append((url, k)) or True)
    monkeypatch.setattr("src.core.engagement_log.log_reply", lambda *a, **k: None)
    monkeypatch.setattr(db, "run_llm", llm)
    monkeypatch.setattr(db.time, "sleep", lambda *a: None)
    return db, mentions, outputs, generated, sent


def test_debate_asks_admission_with_the_turn_cap_before_generating(debate, monkeypatch):
    from src.guards import action_guard

    db, mentions, outputs, generated, sent = debate
    logged = []
    monkeypatch.setattr("src.core.engagement_log.log_reply", lambda *a, **k: logged.append(a))
    monkeypatch.setenv("DEBATE_MAX_TURNS_PER_AUTHOR_PER_DAY", "1")
    action_guard.record(action_guard.DEBATE_TURN, target="capped")
    blocked, own = fresh("pgm_pm", n=1), fresh(config.BOT_HANDLE, n=2)
    capped, admitted = fresh("capped", n=3), fresh("someone", n=4)
    mentions += [{"url": blocked, "text": "blocked"}, {"url": own, "text": "own"},
                 {"url": capped, "text": "capped"}, {"url": admitted, "text": "admitted"}]
    outputs.update({t: _Llm(DRAFT) for t in ("blocked", "own", "capped", "admitted")})

    db.run_debate_cycle()

    assert generated == ["admitted"]
    assert sent == [(admitted, {"debate_turn": True})]
    assert len(logged) == 1, "log only on a confirmed ship"
    assert db._skipped == {blocked, own, admitted}, "the turn cap is temporary: capped stays replayable"


def test_debate_kill_switch_is_read_at_call_time(debate, monkeypatch):
    from src.x import scraper

    db = debate[0]
    scraped = []
    monkeypatch.setattr(scraper, "scrape_mentions", lambda **k: scraped.append(1) or [])
    monkeypatch.setenv("ENABLE_DEBATES", "0")
    db.run_debate_cycle()
    assert scraped == [], "ENABLE_DEBATES=0 must skip before any Safari work"


def test_debate_sets_aside_skips_but_replays_failed_generations(debate, monkeypatch):
    db, mentions, outputs, generated, sent = debate
    declined, failed, empty = fresh("someone", n=1), fresh("other", n=2), fresh("third", n=3)
    mentions += [{"url": declined, "text": "declined"}, {"url": failed, "text": "failed"},
                 {"url": empty, "text": "empty"}]
    outputs.update({"declined": _Llm("SKIP. nothing to debate"), "failed": _Llm("", returncode=1),
                    "empty": _Llm("")})
    monkeypatch.setenv("DEBATE_MAX_PER_CYCLE", "5")

    db.run_debate_cycle()
    db.run_debate_cycle()

    assert sorted(generated) == ["declined", "empty", "empty", "failed", "failed"]
    assert sent == []
    assert db._skipped == {declined}


def test_debate_stops_on_unreadable_store(debate):
    db, mentions, outputs, generated, _ = debate
    mentions.append({"url": fresh("someone"), "text": "post"})
    outputs["post"] = _Llm(DRAFT)
    corrupt_replied_store()
    with pytest.raises(StateUnreadable):
        db.run_debate_cycle()
    assert generated == []


# --- replyback (replies under our latest post) ------------------------------


@pytest.fixture
def replyback(monkeypatch, blocklist):
    from src.replies import notify_bot as nb

    replies = []
    drafts = {}
    generated, sent = [], []

    def generate(own_tweet, text):
        generated.append(text)
        return drafts.get(text, DRAFT)

    monkeypatch.setattr(nb, "scrape_own_tweet_and_replies",
                        lambda: {"own_tweet": "our post", "replies": list(replies)})
    monkeypatch.setattr(nb, "_influencer_handles", lambda: set())
    monkeypatch.setattr(nb, "_reciprocate_engagers", lambda *a, **k: None)
    monkeypatch.setattr(nb, "generate_replyback", generate)
    monkeypatch.setattr(nb, "reply_to_tweet_in_thread",
                        lambda url, text, **k: sent.append((url, k)) or True)
    return nb, replies, drafts, generated, sent


def test_replyback_asks_admission_with_the_turn_cap_before_generating(replyback, monkeypatch):
    from src.guards import action_guard

    nb, replies, _, generated, sent = replyback
    monkeypatch.setenv("DEBATE_MAX_TURNS_PER_AUTHOR_PER_DAY", "1")
    action_guard.record(action_guard.DEBATE_TURN, target="capped")
    blocked, own = fresh("pgm_pm", n=1), fresh(config.BOT_HANDLE, n=2)
    capped, admitted = fresh("capped", n=3), fresh("someone", n=4)
    replies += [
        {"user": "Friendly @pgm_pm", "text": "blocked handle", "url": blocked},
        {"user": "Us @TheAIShrink", "text": "our own reply", "url": own},
        {"user": "No link @nolink", "text": "no status URL", "url": ""},
        {"user": "Capped @capped", "text": "hard disagree on that one", "url": capped},
        {"user": "pgm_pm fan club @someone", "text": "display name is not an identity", "url": admitted},
    ]

    nb.run_replyback_cycle()

    assert generated == ["display name is not an identity"]
    assert sent == [(admitted, {"debate_turn": True})]
    assert nb._skipped == {blocked, own, admitted}, "the turn cap is temporary"


def test_replyback_sets_aside_model_skips_but_replays_failed_calls(replyback):
    nb, replies, drafts, generated, sent = replyback
    declined, failed = fresh("someone", n=1), fresh("other", n=2)
    replies += [{"user": "@someone", "text": "nothing to add", "url": declined},
                {"user": "@other", "text": "model is down", "url": failed}]
    drafts.update({"nothing to add": "SKIP. no debatable content", "model is down": None})

    nb.run_replyback_cycle()
    nb.run_replyback_cycle()

    assert generated == ["nothing to add", "model is down", "model is down"]
    assert sent == []
    assert nb._skipped == {declined}


def test_replyback_stops_on_unreadable_store(monkeypatch):
    """replyback catches reply errors per engager; an unreadable store must
    end the cycle at the first engager, before paying for a generation."""
    from src.replies import notify_bot as nb
    monkeypatch.setenv("DRY_RUN", "1")
    replies = [{"user": f"@fan{i}", "text": "what about inference margins?",
                "url": f"https://x.com/fan{i}/status/20635000000000{i:05d}"} for i in range(3)]
    monkeypatch.setattr(nb, "scrape_own_tweet_and_replies",
                        lambda: {"own_tweet": "batching is the margin story", "replies": replies})
    monkeypatch.setattr(nb, "_influencer_handles", lambda: set())
    monkeypatch.setattr(nb, "_reciprocate_engagers", lambda *a, **k: pytest.fail("cycle must not finish"))
    monkeypatch.setattr(nb, "humanize", lambda t: t)
    generations = []
    monkeypatch.setattr(nb, "generate_replyback", lambda own, text: generations.append(text) or
                        "Utilisation decides it: a busy H100 earns its price, an idle one never does.")
    with open(config.REPLIED_FILE, "w") as f:
        f.write("[")
    with pytest.raises(StateUnreadable):
        nb.run_replyback_cycle()
    assert generations == [], "Reply admission stops the cycle before the model call"


def test_replyback_reciprocity_never_follows(monkeypatch):
    """Engager follows belong to follow_engagers_job (engager=True). The
    replyback reciprocity pass only visits and likes; its old bare
    follow_account call was refused by the Seed-account rule anyway."""
    from src.replies import notify_bot as nb

    visited = []
    monkeypatch.setattr(nb, "visit_profile_and_like", lambda h, **k: visited.append(h) or [])
    monkeypatch.setattr(nb, "follow_account",
                        lambda *a, **k: pytest.fail("replyback must not follow"), raising=False)
    monkeypatch.setattr(nb.random, "random", lambda: 0.0)
    nb._reciprocate_engagers([{"user": "Fresh @fresh", "url": "https://x.com/fresh/status/12"}], set())
    assert visited == ["fresh"]


def test_engager_likes_count_only_likes_that_shipped(monkeypatch):
    from src.replies import notify_bot as nb
    LikeOutcome = nb.LikeOutcome

    results = {"liker": [LikeOutcome.LIKED, LikeOutcome.ALREADY_LIKED],
               "stale": [LikeOutcome.ALREADY_LIKED], "broken": [LikeOutcome.FAILED],
               "unsure": [LikeOutcome.UNCONFIRMED]}
    monkeypatch.setattr(nb, "visit_profile_and_like", lambda h, **k: results[h])
    monkeypatch.setattr(nb.random, "random", lambda: 0.0)
    lines = []
    monkeypatch.setattr(nb.log, "info", lambda msg, *a, **k: lines.append(msg))
    replies = [{"user": f"@{h}", "url": f"https://x.com/{h}/status/1"} for h in results]
    nb._reciprocate_engagers(replies, set())
    assert "[RECIPROCATE] Engaged back with 1 engager(s): 1 like(s)." in lines
    assert "[RECIPROCATE] Nothing liked on @stale." in lines
    assert "[RECIPROCATE] Nothing liked on @broken." in lines
    assert "[RECIPROCATE] Nothing liked on @unsure." in lines

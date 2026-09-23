"""The reply jobs ask Reply admission before paying for a generation
(issue #100). Tested through the jobs' cycles: the generator and the
chokepoint are stubs, the Replied store, the ledger and BLOCKLIST are real.
conftest points the state files at tmp_path, empties each job's `_skipped`
set and fixes the clock at noon Toronto."""
from datetime import datetime, timezone

import pytest

from src import config, replied_store, x_urls
from src.state_errors import StateUnreadable

DRAFT = "Batching is where inference margins are won or lost, not in the model."


def fresh(handle, minutes=5, n=0):
    """A status URL posted `minutes` ago; `n` keeps URLs distinct."""
    ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000) - minutes * 60_000
    return f"https://x.com/{handle}/status/{((ms - x_urls._TWITTER_EPOCH_MS) << 22) + n}"


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
    from src import direct_reply as dr

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
    assert dr._skipped == set(refused), "definitive refusals are set aside"


def test_direct_reply_sets_aside_model_skips_but_replays_temporary_refusals(pipeline, monkeypatch):
    dr, generated, sent, drafts = pipeline
    declined, bounced = fresh("someone", n=1), fresh("other", n=2)
    drafts["declined"] = None  # the model answered SKIP
    monkeypatch.setattr(dr, "reply_to_tweet", lambda url, text: sent.append(url) or False)
    tweets = [{"url": declined, "text": "declined"}, {"url": bounced, "text": "bounced"}]

    for _cycle in range(2):
        dr._reply_to_tweets(list(tweets), set(), "SEARCH-HOT")

    assert generated == ["declined", "bounced", "bounced"], \
        "a SKIP is not paid twice; a chokepoint refusal gets a new generation"
    assert dr._skipped == {declined}
    assert replied_store.load_replied() == set(), "nothing shipped, nothing marked"


def test_direct_reply_cycle_never_marks_unsent_candidates(pipeline, monkeypatch):
    """Defect 3: the VIP lane and the pipeline both marked candidates that
    never shipped, and the cycle saved them into the Replied store."""
    from src import twitter_client as tc

    dr, generated, sent, _ = pipeline
    vip, searched = fresh("graphseo", n=1), fresh("someone", n=2)
    monkeypatch.setenv("VIP_SCAN_HANDLES", "Graphseo")
    monkeypatch.setattr(tc, "scrape_x_search", lambda *a, **k: [{"url": vip, "text": "vip post"}])
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
    from src import feed_sweeper_bot as fs
    from src import twitter_client as tc

    dr, generated, sent, _ = pipeline
    monkeypatch.setattr(fs, "_harvest_active_authors", lambda tweets: None)
    blocked = fresh("pgm_pm", n=1)
    named_like_us = fresh("someone", n=2)
    feed = [
        {"url": blocked, "text": "blocked by handle", "author": "Friendly Name"},
        {"url": named_like_us, "text": "admitted", "author": config.BOT_HANDLE},
    ]
    monkeypatch.setattr(tc, "scrape_home_feed", lambda **k: list(feed))
    monkeypatch.setattr(tc, "scrape_following_feed", lambda **k: [])

    fs.run_feed_sweep_cycle()

    assert generated == ["admitted"]
    assert sent == [named_like_us]
    assert fs._skipped == {blocked}
    assert dr._skipped == set(), "each job keeps its own set"


# --- early_bird and mega_watch (profile scans) ------------------------------

@pytest.fixture(params=["early_bird", "mega_watch"])
def profile_job(request, monkeypatch, blocklist):
    """A profile-scanning job whose scan pool is `profiles` (handle → posts)."""
    from src import direct_reply as dr
    from src import early_bird_bot as eb
    from src import evolution_store
    from src import mega_watch_bot as mw

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
    assert module._skipped == {blocked["url"]}


def test_profile_jobs_set_aside_model_skips(profile_job):
    module, run, profiles, generated, sent, drafts = profile_job
    declined = post("someone", "declined")
    profiles["someone"] = [declined]
    drafts["declined"] = None

    run()
    run()

    assert generated == ["declined"], "a SKIP is not paid twice"
    assert sent == []
    assert module._skipped == {declined["url"]}


def test_profile_jobs_stop_on_unreadable_store(profile_job):
    module, run, profiles, generated, _, _ = profile_job
    profiles["someone"] = [post("someone", "post")]
    corrupt_replied_store()
    with pytest.raises(StateUnreadable):
        run()
    assert generated == []

"""Each Reply job's source and filters: what it scrapes, which posts it
hands the Reply pipeline, with which budget and log tag. The pipeline's own
rules (admission first, set-aside posts, rate limit, errors that end a
cycle) are tested once in test_reply_pipeline.py. The model is the fake LLM
and the chokepoint a stub, both from tests/replies/conftest.py."""
import ast
from pathlib import Path

import pytest

from src.core import config
from src.core.state_errors import StateUnreadable
from src.guards import replied_store
from src.guards.active_hours import OutsideActiveHours
from src.replies import reply_pipeline
from src.x import x_urls
from src.x.confirmed_write import WriteOutcome
from tests.helpers import fresh
from tests.replies.fakes import EXHAUSTED, REPLY_TEXT, logged


def set_aside(name):
    return reply_pipeline._skipped.get(name, set())


REPLIES = "src.replies"


def _private(name):
    return name.startswith("_") and not (name.startswith("__") and name.endswith("__"))


def private_borrows(source, module):
    """The names `module`, a module of src/replies, takes from another
    reply module that start with an underscore: imported by name (relative
    at any level, or absolute), or read as an attribute of an imported
    sibling module."""
    package = module.split(".")[:-1]
    bound, problems = {}, set()

    def borrow(lineno, dotted):
        parts = dotted.split(".")
        if dotted.startswith(REPLIES + ".") and not dotted.startswith(module + ".") \
                and any(_private(p) for p in parts[2:]):
            problems.add(f"{lineno}: {dotted}")

    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.asname:
                    bound[a.asname] = a.name
                else:
                    head = a.name.split(".")[0]
                    bound[head] = head
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                if node.level - 1 > len(package):
                    continue
                base = package[:len(package) - (node.level - 1)]
                target = ".".join(base + (node.module.split(".") if node.module else []))
            else:
                target = node.module or ""
            for a in node.names:
                dotted = f"{target}.{a.name}"
                borrow(node.lineno, dotted)
                bound[a.asname or a.name] = dotted
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            chain, base = [], node
            while isinstance(base, ast.Attribute):
                chain.append(base.attr)
                base = base.value
            if isinstance(base, ast.Name) and base.id in bound:
                borrow(node.lineno, ".".join([bound[base.id], *reversed(chain)]))
    return sorted(problems)


@pytest.mark.parametrize("source", [
    "from .direct_reply import _skipped",
    "from . import direct_reply\ndirect_reply._skipped.clear()",
    "from . import direct_reply as dr\ndr._sleep(1)",
    "from ..replies.direct_reply import _skipped",
    "from ..replies import direct_reply\ndirect_reply._skipped",
    "from .. import replies\nreplies.direct_reply._skipped",
    "from src.replies.direct_reply import _skipped",
    "from src.replies import direct_reply\ndirect_reply._skipped",
    "import src.replies.direct_reply as dr\ndr._skipped",
    "import src.replies.direct_reply\nsrc.replies.direct_reply._skipped",
    "def run():\n    from . import reply_pipeline\n    return reply_pipeline._skipped",
])
def test_the_private_borrow_guard_catches_every_import_form(source):
    assert private_borrows(source, "src.replies.example_bot")


@pytest.mark.parametrize("source", [
    "from .direct_reply import is_on_niche",
    "from . import direct_reply\ndirect_reply.is_on_niche(direct_reply.__name__)",
    "from ..core.config import _PROJECT_ROOT",
    "from . import example_bot\nexample_bot._own_helper",
])
def test_the_private_borrow_guard_lets_public_names_through(source):
    assert private_borrows(source, "src.replies.example_bot") == []


def test_reply_jobs_never_borrow_each_others_privates():
    """Issue #156: a job uses what another reply module exposes, never its
    underscored helpers."""
    root = Path(__file__).resolve().parents[2] / "src" / "replies"
    problems = [f"{path.name}:{p}" for path in sorted(root.glob("*.py"))
                for p in private_borrows(path.read_text(), f"{REPLIES}.{path.stem}")]
    assert not problems, "private borrows across src/replies:\n  " + "\n  ".join(problems)


# --- direct_reply: the VIP scan, then the search lane -------------------------


@pytest.fixture
def direct(monkeypatch, llm, chokepoint):
    """direct_reply with one VIP handle; `vip` and `search` are what the two
    lanes scrape."""
    from src.replies import direct_reply as dr
    from src.x import scraper

    lanes = {"vip": [], "search": [], "queries": []}
    monkeypatch.setenv("VIP_SCAN_HANDLES", "Graphseo")
    monkeypatch.setattr(scraper, "scrape_x_search", lambda *a, **k: list(lanes["vip"]))

    def search(query, **k):
        lanes["queries"].append(query)
        if isinstance(lanes["search"], BaseException):
            raise lanes["search"]
        return list(lanes["search"])

    monkeypatch.setattr(dr, "scrape_x_search", search)
    monkeypatch.setattr(dr, "is_on_niche", lambda text: "off-niche" not in text)
    return dr, lanes, llm, chokepoint


def test_direct_reply_lanes_share_the_cycle(direct):
    """Defect 3: the VIP lane and the search lane both marked candidates that
    never shipped. A post one lane tried is not tried again by the other."""
    dr, lanes, llm, chokepoint = direct
    vip, searched = fresh("graphseo", n=1), fresh("someone", n=2)
    lanes["vip"] = [{"url": vip, "text": "vip post"}]
    lanes["search"] = [{"url": searched, "text": "search post"}, {"url": vip, "text": "vip post"}]
    llm.answers["vip post"] = "réponse précise sur le trafic organique"
    chokepoint.answer = WriteOutcome.REFUSED

    dr.run_direct_reply_cycle()

    assert chokepoint.sent == [vip, searched], "each candidate tried once per cycle"
    assert [c.label for c in llm.calls] == ["GRAPHSEO_VIP", "DIRECT_REPLY"]
    assert replied_store.load_replied() == set()


def test_direct_reply_search_keeps_fresh_on_niche_posts(direct):
    dr, lanes, llm, chokepoint = direct
    ok, off, old = fresh("someone", n=1), fresh("other", n=2), fresh("third", minutes=5 * 24 * 60 + 1, n=3)
    lanes["search"] = [{"url": off, "text": "off-niche post"}, {"url": old, "text": "old post"},
                       {"url": ok, "text": "post admitted"}, {"url": "https://x.com/nostatus", "text": "no id"}]

    dr.run_direct_reply_cycle()

    assert chokepoint.sent == [ok]
    assert [(r.url, r.source.split("/")[0]) for r in logged()] == [(ok, "SEARCH-HOT")]
    assert set_aside("direct_reply") == {ok}


def test_direct_reply_vip_lane_keeps_posts_under_48_hours(direct):
    dr, lanes, llm, chokepoint = direct
    recent, old = fresh("graphseo", minutes=47 * 60, n=1), fresh("graphseo", minutes=49 * 60, n=2)
    lanes["vip"] = [{"url": old, "text": "vip old"}, {"url": recent, "text": "vip recent"}]
    llm.default = "réponse précise sur le trafic organique"

    dr._run_graphseo_scan(reply_pipeline.Cycle())

    assert chokepoint.sent == [recent]
    assert [r.source for r in logged()] == ["VIP/Graphseo"]


def test_direct_reply_cycle_stops_at_the_rate_limit(direct):
    """A rate limit in the VIP lane ends the whole cycle, the search lane included."""
    dr, lanes, llm, chokepoint = direct
    lanes["vip"] = [{"url": fresh("graphseo", n=i), "text": f"vip post {i}"} for i in (1, 2)]
    llm.default = EXHAUSTED

    dr.run_direct_reply_cycle()

    assert len(llm.calls) == 1 and lanes["queries"] == [] and chokepoint.sent == []


@pytest.mark.parametrize("error", [StateUnreadable("replied store unreadable"), OutsideActiveHours("bedtime")],
                         ids=["unreadable", "bedtime"])
def test_direct_reply_cycle_ends_on_an_error_from_either_lane(direct, error):
    """Both lanes ran inside `except Exception`, which swallowed bedtime."""
    dr, lanes, llm, chokepoint = direct
    lanes["vip"] = [{"url": fresh("graphseo"), "text": "vip post"}]
    chokepoint.answer = error
    with pytest.raises(type(error)):
        dr.run_direct_reply_cycle()
    assert lanes["queries"] == [], "the search lane never starts"

    lanes["vip"], lanes["search"] = [], error
    with pytest.raises(type(error)):
        dr.run_direct_reply_cycle()
    assert len(lanes["queries"]) == 1, "the cycle stops at the first query instead of scraping the rest"


def test_direct_reply_cycle_is_bounded(direct, monkeypatch):
    """2026-09-23: APScheduler skipped direct_reply_job because a cycle could
    outlive its 2-minute interval; the startup warm-up once ran 20+ minutes.
    The cycle stops at its budget and yields Safari."""
    import itertools

    dr, lanes, llm, chokepoint = direct
    numbers = itertools.count()

    def fresh_posts(query, **k):
        lanes["queries"].append(query)
        return [{"url": fresh("someone", n=n), "text": f"post {n}"} for n in itertools.islice(numbers, 5)]

    monkeypatch.setattr(dr, "scrape_x_search", fresh_posts)
    monkeypatch.setattr(dr, "DIRECT_REPLY_MAX_PER_CYCLE", 3)

    dr.run_direct_reply_cycle()
    assert len(chokepoint.sent) == 3 and len(lanes["queries"]) == 1

    chokepoint.calls.clear()
    lanes["queries"].clear()
    dr.run_direct_reply_cycle(max_replies=12)
    assert len(chokepoint.sent) == 12 and len(lanes["queries"]) == 3


# --- feed_sweep -------------------------------------------------------------------


@pytest.fixture
def feed(monkeypatch, llm, chokepoint):
    from src.replies import feed_sweeper_bot as fs
    from src.x import scraper

    feeds = {"FEED": [], "FOLLOWING": [], "read": []}
    monkeypatch.setattr(fs, "_harvest_active_authors", lambda tweets: None)
    monkeypatch.setattr(scraper, "scrape_home_feed",
                        lambda **k: feeds["read"].append("FEED") or list(feeds["FEED"]))
    monkeypatch.setattr(scraper, "scrape_following_feed",
                        lambda **k: feeds["read"].append("FOLLOWING") or list(feeds["FOLLOWING"]))
    return fs, feeds, llm, chokepoint


def test_feed_sweep_replies_to_fresh_on_niche_posts(feed):
    fs, feeds, llm, chokepoint = feed
    ok, thread, off, old = (fresh("someone", n=1), fresh("other", n=2), fresh("third", n=3),
                            fresh("fourth", minutes=5 * 24 * 60 + 1, n=4))
    feeds["FEED"] = [
        {"url": thread, "text": "OpenAI ships a model", "is_reply": True},
        {"url": off, "text": "my sandwich today"},
        {"url": old, "text": "OpenAI ships an old model"},
        {"url": ok, "text": "OpenAI ships a new model", "likes": 50_000, "replies": 900},
    ]

    fs.run_feed_sweep_cycle()

    assert chokepoint.sent == [ok], "only replies, even to a viral post"
    assert [r.source for r in logged()] == ["FEED-SWEEP-FEED"]
    assert set_aside("feed_sweep") == {ok} and set_aside("direct_reply") == set()


def test_feed_sweep_stops_at_the_rate_limit(feed):
    fs, feeds, llm, chokepoint = feed
    feeds["FEED"] = [{"url": fresh("someone"), "text": "OpenAI ships a new model"}]
    llm.default = EXHAUSTED

    fs.run_feed_sweep_cycle()

    assert len(llm.calls) == 1 and feeds["read"] == ["FEED"] and chokepoint.sent == []


def test_feed_sweep_harvests_the_handle_from_the_status_url():
    """Issue #162: the scraped `author` is a display name. One-word names
    ("Claude") landed in dynamic_accounts.json as other accounts' handles."""
    from src.core.dynamic_strategy import get_dynamic_accounts
    from src.replies import feed_sweeper_bot as fs

    fs._harvest_active_authors([
        {"url": "https://x.com/sama/status/1", "author": "Sam Altman", "likes": 500},
        {"url": "https://x.com/someone/status/2", "author": "Claude", "likes": 500},
        {"url": "https://x.com/i/web/status/3", "author": "Tesla", "likes": 500},
        {"url": "https://x.com/pgm_pm/status/4", "author": "Friendly", "likes": 500},
        {"url": "https://x.com/quiet/status/5", "author": "quiet", "likes": 1},
    ])

    assert get_dynamic_accounts()["en"] == ["sama", "someone"]


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
def reply_search(monkeypatch, chokepoint):
    """reply_bot with a stub search-and-draft model returning `batch`."""
    from src.replies import reply_bot as rb

    batch, searched = [], []

    def generate(recent_topics=None, already_replied=None):
        searched.append(already_replied)
        return list(batch)

    monkeypatch.setenv("ENABLE_REPLY_SEARCH", "1")
    monkeypatch.setattr(rb, "MAX_REPLIES_PER_CYCLE", 20)
    monkeypatch.setattr(rb, "refresh_feed", lambda: None)
    monkeypatch.setattr(rb, "get_recent_tweets", lambda hours: [])
    monkeypatch.setattr(rb, "generate_replies", generate)
    return rb, batch, searched, chokepoint


def target(url, kind="reply"):
    return {"tweet_url": url, "reply": REPLY_TEXT, "type": kind, "pattern": "RENAME",
            "provider": "claude", "model": "sonnet"}


def test_reply_search_sends_admitted_targets_once(reply_search, blocked_pgm_pm):
    rb, batch, searched, chokepoint = reply_search
    answered = fresh("someone", n=1)
    replied_store.claim(answered)
    ok, quoted = fresh("someone", n=5), fresh("other", n=7)
    batch += [
        target(fresh("pgm_pm", n=2)),
        target(answered),
        target("https://x.com/i/web/status/" + x_urls.status_id(fresh("x", n=4))),
        target(fresh("someone", minutes=49 * 60, n=6)),
        target(quoted, kind="quote"),
        target(ok),
        target(ok),
    ]

    rb.run_reply_cycle()

    assert len(searched) == 1 and answered in searched[0], "the model is told which posts are answered"
    assert chokepoint.sent == [ok], "no quote, nothing admission refuses, each target once"
    assert [(r.url, r.pattern, r.provider, r.model) for r in logged()] == [(ok, "RENAME", "claude", "sonnet")]


def test_reply_search_stops_on_unreadable_store_before_the_model(reply_search):
    rb, batch, searched, chokepoint = reply_search
    batch.append(target(fresh("someone")))
    with open(config.REPLIED_FILE, "w") as f:
        f.write("[")
    with pytest.raises(StateUnreadable):
        rb.run_reply_cycle()
    assert searched == [] and chokepoint.sent == []


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


@pytest.fixture(params=["early_bird", "mega_watch"])
def profile_job(request, monkeypatch, llm, chokepoint):
    """A profile-scanning job whose scan pool is `profiles` (handle → posts)."""
    from src.core import evolution_store
    from src.replies import direct_reply as dr, early_bird_bot as eb, mega_watch_bot as mw

    module, run = {"early_bird": (eb, eb.run_early_bird_cycle),
                   "mega_watch": (mw, mw.run_mega_watch_cycle)}[request.param]
    profiles = {}
    monkeypatch.setattr(eb, "_scan_pool", lambda: list(profiles))
    monkeypatch.setattr(mw, "_watch_pool", lambda: list(profiles))
    monkeypatch.setattr(dr, "ALWAYS_REPLY_ACCOUNTS", [])
    monkeypatch.setattr(evolution_store, "filter_and_weight", lambda handles: list(handles))
    monkeypatch.setattr(module, "scrape_profile_tweets", lambda handle, **k: list(profiles[handle]))
    monkeypatch.setattr(module, "is_on_niche", lambda text: "off-niche" not in text)
    return request.param, run, profiles, llm, chokepoint


def post(handle, text, minutes=1, n=0, **fields):
    return {"url": fresh(handle, minutes=minutes, n=n), "text": text, "author": handle, **fields}


def test_profile_jobs_answer_fresh_on_niche_posts_only(profile_job):
    name, run, profiles, llm, chokepoint = profile_job
    max_minutes = {"early_bird": 18, "mega_watch": 4}[name]
    ok = post("someone", "post fresh", minutes=max_minutes - 1, n=1)
    profiles["someone"] = [
        post("someone", "post stale", minutes=max_minutes + 1, n=2),
        post("someone", "off-niche post", n=3),
        post("someone", "post in a thread", n=4, is_reply=True),
        {"url": "https://x.com/someone", "text": "no status ID"},
        ok,
    ]

    run()

    assert llm.parents("post fresh", "post stale", "off-niche post", "post in a thread") == ["post fresh"]
    assert chokepoint.sent == [ok["url"]]
    tag = {"early_bird": "EARLYBIRD", "mega_watch": "MEGA"}[name]
    assert [r.source for r in logged()] == [f"{tag}/someone"]
    assert set_aside(name) == {ok["url"]}


def test_profile_jobs_bound_their_replies(profile_job):
    """Early bird: one Reply per scanned account. Mega watch: two per cycle."""
    name, run, profiles, llm, chokepoint = profile_job
    for handle in ("one", "two", "three"):
        profiles[handle] = [post(handle, f"post {handle} {i}", n=i) for i in range(2)]

    run()

    per_account = {"early_bird": 3, "mega_watch": 2}[name]
    assert len(chokepoint.sent) == per_account
    if name == "early_bird":
        assert len({x_urls.author(u) for u in chokepoint.sent}) == 3


def test_profile_jobs_stop_at_the_rate_limit(profile_job):
    name, run, profiles, llm, chokepoint = profile_job
    profiles.update({"someone": [post("someone", "post one", n=1)], "other": [post("other", "post two", n=2)]})
    llm.default = EXHAUSTED

    run()

    assert len(llm.calls) == 1 and chokepoint.sent == []


def test_mega_watch_sends_replies_of_10_to_270_characters(profile_job):
    name, run, profiles, llm, chokepoint = profile_job
    profiles["someone"] = [post("someone", "post", n=1)]
    llm.default = "Yes."

    run()

    assert chokepoint.sent == ([] if name == "mega_watch" else [profiles["someone"][0]["url"]])


# --- debate (mentions) ------------------------------------------------------


@pytest.fixture
def debate(monkeypatch, llm, chokepoint):
    from src.replies import debate_bot as db
    from src.x import scraper

    mentions = []
    monkeypatch.setenv("ENABLE_DEBATES", "1")
    monkeypatch.setattr(scraper, "scrape_mentions", lambda **k: list(mentions))
    return db, mentions, llm, chokepoint


def test_debate_answers_fresh_mentions_as_debate_turns(debate, monkeypatch):
    db, mentions, llm, chokepoint = debate
    monkeypatch.setenv("DEBATE_MAX_PER_CYCLE", "2")
    monkeypatch.setenv("DEBATE_MAX_AGE_HOURS", "24")
    old = fresh("old", minutes=25 * 60, n=1)
    first, second, third = fresh("someone", n=2), fresh("other", minutes=10, n=3), fresh("third", minutes=20, n=4)
    mentions += [{"url": third, "text": "mention three"}, {"url": old, "text": "mention old"},
                 {"url": second, "text": "mention two"}, {"url": first, "text": "mention one"},
                 {"url": fresh("empty", n=5), "text": "  "}]

    db.run_debate_cycle()

    assert [(c.url, c.debate_turn) for c in chokepoint.calls] == [(first, True), (second, True)], \
        "freshest first, DEBATE_MAX_PER_CYCLE Replies"
    assert [r.source for r in logged()] == ["DEBATE/someone", "DEBATE/other"]


def test_debate_kill_switch_is_read_at_call_time(debate, monkeypatch):
    from src.x import scraper

    db = debate[0]
    scraped = []
    monkeypatch.setattr(scraper, "scrape_mentions", lambda **k: scraped.append(1) or [])
    monkeypatch.setenv("ENABLE_DEBATES", "0")
    db.run_debate_cycle()
    assert scraped == [], "ENABLE_DEBATES=0 must skip before any Safari work"


# --- replyback (replies under our latest post) ------------------------------


@pytest.fixture
def replyback(monkeypatch, llm, chokepoint):
    from src.replies import notify_bot as nb

    replies = []
    monkeypatch.setattr(nb, "scrape_own_tweet_and_replies",
                        lambda: {"own_tweet": "our post about GPUs", "replies": list(replies)})
    monkeypatch.setattr(nb, "_influencer_handles", lambda: set())
    monkeypatch.setattr(nb, "_reciprocate_engagers", lambda *a, **k: None)
    return nb, replies, llm, chokepoint


def test_replyback_answers_engagers_in_thread_and_logs_it(replyback, blocked_pgm_pm):
    """Issue #156: replyback logs its shipped Replies like every other job."""
    nb, replies, llm, chokepoint = replyback
    admitted = fresh("someone", n=1)
    replies += [
        {"user": "No link @nolink", "text": "no status URL", "url": ""},
        {"user": "Brief @brief", "text": "ok", "url": fresh("brief", n=2)},
        {"user": "pgm_pm fan club @someone", "text": "display name is not an identity", "url": admitted},
    ]

    nb.run_replyback_cycle()

    assert llm.parents("no status URL", "display name is not an identity") == ["display name is not an identity"]
    assert "our post about GPUs" in llm.prompts[0], "the post they answered is in the prompt"
    assert [(c.url, c.debate_turn) for c in chokepoint.calls] == [(admitted, True)]
    assert [(r.url, r.source) for r in logged()] == [(admitted, "REPLYBACK/someone")]
    assert set_aside("replyback") == {admitted}


def test_replyback_answers_more_engagers_under_a_busier_post(replyback):
    nb, replies, llm, chokepoint = replyback
    replies += [{"user": f"@fan{i}", "text": f"reply number {i}", "url": fresh(f"fan{i}", n=i)}
                for i in range(12)]

    nb.run_replyback_cycle()

    assert len(chokepoint.sent) == 9, "10 to 19 replies under the post: 9 answered"


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


def test_replyback_reciprocity_visits_the_handle_from_the_status_url(monkeypatch):
    """Issue #162, same family: `user` is the display name. A one-word name
    ("Claude") was read as a handle and sent the likes to x.com/claude."""
    from src.replies import notify_bot as nb

    visited = []
    monkeypatch.setattr(nb, "visit_profile_and_like", lambda h, **k: visited.append(h) or [])
    monkeypatch.setattr(nb.random, "random", lambda: 0.0)
    nb._reciprocate_engagers([
        {"user": "Claude", "url": "https://x.com/someone/status/12"},
        {"user": "Sam Altman", "url": "https://x.com/sama/status/13"},
        {"user": "Anonymous", "url": "https://x.com/i/web/status/14"},
        {"user": "Friendly", "url": "https://x.com/pgm_pm/status/15"},
    ], set())
    assert sorted(visited) == ["sama", "someone"]


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

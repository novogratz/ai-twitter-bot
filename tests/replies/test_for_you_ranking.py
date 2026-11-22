"""Fresh ordinary sources keep their order from discovery through dispatch."""
from datetime import datetime, timedelta, timezone
from itertools import count
import time

import pytest

from src.replies import candidate_buffer, direct_reply, reply_pipeline, reply_source
from src.x import x_urls


@pytest.fixture
def posts(monkeypatch, settings_override):
    settings_override(REPLY_BROAD_DISCOVERY=True, REPLY_FOR_YOU_FIRST=True,
                      REPLY_MIN_LIKES=5, DIRECT_REPLY_MAX_AGE_MINUTES=60)
    now = datetime.fromtimestamp(int(time.time() * 1000) / 1000, tz=timezone.utc)
    serial = count(1)

    def age(url, *_args, **_kwargs):
        posted = x_urls.posted_at(url)
        return now - posted if posted is not None else None

    monkeypatch.setattr(x_urls, "age", age)

    def make(author, minutes, likes=5, views=0):
        timestamp = int((now - timedelta(minutes=minutes)).timestamp() * 1000)
        status = ((timestamp - x_urls._TWITTER_EPOCH_MS) << 22) + next(serial)
        return dict(url=f"https://x.com/{author}/status/{status}",
                    text="My SI model project", likes=likes, views=views)

    return make


def select(rows):
    return reply_source.select(rows, reply_source.Declaration(
        max_age=timedelta(hours=1), order=reply_source.Order.FRESH_AND_RISING), "FEED")


def urls(rows):
    return [row.url for row in rows]


@pytest.mark.parametrize("source,priority", [("FEED-SWEEP-FEED", 1), ("SEARCH-FRESH", 2)])
def test_ready_for_you_source_read_precedes_secondary_discovery(
        monkeypatch, settings_override, source, priority):
    from src.core import work_priority
    from src.guards.reply_admission import Verdict
    from src.guards import reply_selection
    from src.x import twitter_client
    from tests.helpers import fresh
    settings_override(REPLY_BROAD_DISCOVERY=True, REPLY_FOR_YOU_FIRST=True, REPLY_INVITED_ONLY=True)
    candidate = reply_pipeline.Candidate(fresh("builder"), "SI model", source)
    observed = []

    def read(url):
        observed.append(work_priority.current_priority())
        return {"text": candidate.text, "likes": 10}

    monkeypatch.setattr(twitter_client, "read_reply_source", read)
    monkeypatch.setattr(reply_pipeline, "_parent_verdict", lambda *args: Verdict(None, author="builder"))
    monkeypatch.setattr(reply_selection, "remember", lambda *args: None)
    job = reply_pipeline.Job("speed", "SPEED", direct_reply.reply_call)
    assert reply_pipeline._prepare_source(job, candidate, reply_pipeline.Cycle()) is not None
    assert observed == [priority]
    assert work_priority.current_priority() == work_priority.BACKGROUND


@pytest.mark.parametrize("pipelined", [False, True])
def test_recent_modest_sources_beat_older_huge_views_through_buffer_and_dispatch(
        posts, monkeypatch, llm, chokepoint, pipelined):
    monkeypatch.setattr(reply_pipeline, "priority_authors", lambda: {"major"})
    older = posts("major", 45, likes=50_000, views=10_000_000)
    modest = posts("newbuilder", 12, likes=20, views=200)
    strongest = posts("another", 8, likes=48, views=50)
    expected = [strongest["url"], modest["url"], older["url"]]
    selected = select([older, modest, strongest])
    assert urls(selected) == expected

    buffer = candidate_buffer.Buffer()
    buffer.offer(selected[::-1], max_age=timedelta(hours=1))
    pending = buffer.pending()
    assert urls(pending) == expected
    assert reply_pipeline.prioritize(pending, ordinary=True, diversify_authors=True) == pending
    job = reply_pipeline.Job("for_you_rank", "FOR-YOU", direct_reply.reply_call, pipelined=pipelined)
    assert buffer.run(job, reply_pipeline.Cycle(), max_generations=2) == 2
    assert chokepoint.sent == expected[:2]
    assert urls(buffer.pending()) == expected[2:]


def test_likes_per_minute_precede_views_and_newest_breaks_equal_rates(posts):
    younger = posts("younger", 10, likes=20, views=100)
    older = posts("older", 20, likes=40, views=1_000)
    newest = posts("newest", 5, likes=10, views=250)
    many_views = posts("manyviews", 29, likes=29, views=10_000_000)
    selected = select([many_views, younger, older, newest])
    expected = [newest["url"], older["url"], younger["url"], many_views["url"]]
    assert urls(selected) == expected
    assert urls(reply_pipeline.prioritize(selected[::-1], ordinary=True)) == expected


def test_posts_under_one_minute_share_the_same_rate_denominator(posts):
    just_posted = posts("newest", .25, likes=5, views=100)
    more_likes = posts("older", .75, likes=6, views=50)
    assert urls(select([just_posted, more_likes])) == [more_likes["url"], just_posted["url"]]


def test_author_diversity_never_promotes_an_older_first_post_over_fresh_seconds(posts):
    first = posts("builder", 5, likes=100, views=1_000)
    second = posts("BUILDER", 6, likes=50, views=900)
    another = posts("another", 15, likes=10, views=20)
    older = posts("oldauthor", 40, likes=1_000_000, views=100_000_000)
    selected = select([older, another, second, first])
    expected = [first["url"], another["url"], second["url"], older["url"]]
    ordered = reply_pipeline.prioritize(selected, ordinary=True, diversify_authors=True)
    assert urls(ordered) == expected
    assert reply_pipeline.prioritize(ordered, ordinary=True, diversify_authors=True) == ordered


def test_thirty_minute_boundary_keeps_fresh_posts_ahead_of_larger_counts(posts):
    fresh = posts("fresh", 30, likes=5, views=10)
    older = posts("older", 30 + 1 / 60, likes=100_000, views=10_000_000)
    assert urls(select([older, fresh])) == [fresh["url"], older["url"]]


@pytest.mark.parametrize("unknown", [None, -1, True, "500", 2.5])
def test_unobserved_likes_do_not_become_popularity_and_still_fail_the_floor(posts, unknown):
    unreadable = posts("unreadable", 10, likes=unknown, views=10_000_000)
    zero = posts("zero", 10, likes=0, views=None)
    eligible = posts("eligible", 10, likes=5, views=1)
    selected = select([unreadable, zero, eligible])
    assert urls(selected) == [eligible["url"], zero["url"], unreadable["url"]]
    assert urls(reply_pipeline.prioritize(selected[::-1], ordinary=True)) == urls(selected)
    buffer = candidate_buffer.Buffer()
    buffer.offer(selected, max_age=timedelta(hours=1))
    assert urls(buffer.pending()) == [eligible["url"]]


@pytest.mark.parametrize("unknown", [None, -1, True, "500", 2.5])
def test_unknown_views_lose_only_the_view_tie_and_never_replace_like_evidence(posts, unknown):
    unreadable = posts("unreadable", 10, likes=5, views=unknown)
    zero = posts("zero", 10, likes=5, views=0)
    more_likes = posts("morelikes", 10, likes=6, views=unknown)
    selected = select([unreadable, zero, more_likes])
    assert urls(selected) == [more_likes["url"], zero["url"], unreadable["url"]]
    assert urls(reply_pipeline.prioritize(selected[::-1], ordinary=True)) == urls(selected)


def test_unknown_future_and_expired_sources_are_not_selected(posts):
    unknown = dict(url="https://x.com/unknown", text="My SI model", likes=10_000, views=1_000_000)
    future = posts("future", -5, likes=10_000, views=1_000_000)
    expired = posts("expired", 61, likes=10_000, views=1_000_000)
    eligible = posts("eligible", 59, likes=5, views=10)
    assert urls(select([unknown, future, expired, eligible])) == [eligible["url"]]
    raw = [reply_pipeline.Candidate(row["url"], row["text"], "TEST", likes=row["likes"], views=row["views"])
           for row in [unknown, future, expired, eligible]]
    ordered = reply_pipeline.prioritize(raw, ordinary=True)
    assert urls(ordered[:2]) == [eligible["url"], expired["url"]]
    assert {row.url for row in ordered[2:]} == {unknown["url"], future["url"]}


@pytest.mark.parametrize("broad,for_you", [(False, False), (False, True), (True, False)])
def test_both_mode_flags_are_required_and_legacy_reach_order_is_preserved(posts, settings_override, broad, for_you):
    settings_override(REPLY_BROAD_DISCOVERY=broad, REPLY_FOR_YOU_FIRST=for_you)
    older = posts("older", 45, likes=100_000, views=1_000_000)
    fresh = posts("fresh", 5, likes=5, views=10)
    selected = select([fresh, older])
    assert urls(selected) == [older["url"], fresh["url"]]
    assert urls(reply_pipeline.prioritize(selected[::-1], ordinary=True)) == urls(selected)


def test_watched_pipeline_and_scraped_source_order_remain_unchanged(posts):
    older = posts("elonmusk", 45, likes=5, views=10)
    fresh = posts("elonmusk", 5, likes=1_000, views=1_000_000)
    selected = reply_source.select([older, fresh], reply_source.Declaration(
        max_age=timedelta(hours=1), author="elonmusk"), "PRIORITY/elonmusk")
    assert urls(selected) == [older["url"], fresh["url"]]
    assert reply_pipeline.prioritize(selected) == selected


pytestmark = pytest.mark.usefixtures("open_topic_account")

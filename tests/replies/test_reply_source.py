"""src/replies/reply_source: the candidates a Reply job's declaration
selects among scraped posts, in its order, without side effects."""
from datetime import timedelta

from src.replies import reply_pipeline, reply_source
from src.replies.reply_source import Declaration, Order
from tests.helpers import fresh

HOUR = timedelta(hours=1)
TEN_MINUTES = timedelta(minutes=10)


def urls(candidates):
    return [c.url for c in candidates]


def test_a_post_without_url_or_text_is_never_a_candidate():
    ok = fresh("someone", n=1)
    tweets = [{"url": "", "text": "post"}, {"text": "post"}, {"url": fresh("other", n=2), "text": "  "},
              {"url": fresh("third", n=3)}, {"url": ok, "text": "post"}]

    assert urls(reply_source.select(tweets, Declaration(max_age=HOUR), "TAG")) == [ok]


def test_a_post_of_unknown_or_negative_age_is_never_a_candidate():
    """Only early bird rejected a post from the future (clock skew); the
    Reply source rejects it for every job."""
    ok = fresh("someone", minutes=9, n=1)
    tweets = [{"url": "https://x.com/someone", "text": "no status id"},
              {"url": fresh("other", minutes=-5, n=2), "text": "from the future"},
              {"url": fresh("third", minutes=11, n=3), "text": "too old"},
              {"url": ok, "text": "in time"}]

    assert urls(reply_source.select(tweets, Declaration(max_age=TEN_MINUTES), "TAG")) == [ok]


def test_reply_max_age_caps_every_declaration(settings_override):
    """Operator request 2026-09-29: a job declaring an older post picks only
    among the posts the Reply admission lets it answer."""
    within = {"url": fresh("a", minutes=14, n=1), "text": "within"}
    over = {"url": fresh("b", minutes=16, n=2), "text": "over"}
    week = Declaration(max_age=timedelta(days=7))

    assert urls(reply_source.select([over, within], week, "TAG")) == [within["url"]]
    settings_override(REPLY_MAX_AGE_MINUTES=10)
    assert urls(reply_source.select([over, within], week, "TAG")) == []


def test_rising_extension_keeps_hot_posts_past_the_default_reply_age():
    quiet = {"url": fresh("quiet", minutes=30, n=1), "text": "OpenAI launch note", "likes": 12}
    hot = {"url": fresh("hot", minutes=30, n=2), "text": "OpenAI launch note", "likes": 90}
    stale_hot = {"url": fresh("stale", minutes=50, n=3), "text": "OpenAI launch note", "likes": 500}

    selected = reply_source.select(
        [quiet, hot, stale_hot],
        Declaration(max_age=HOUR, rising_extension=True),
        "TAG",
    )

    assert urls(selected) == [hot["url"]]
    assert selected[0].oldest == reply_source.rising_max_age()


def test_rising_extension_uses_the_operator_thresholds(settings_override):
    settings_override(REPLY_RISING_MIN_LIKES_PER_MINUTE=4.0, REPLY_RISING_MIN_LIKES=100)
    hot_enough_before = {"url": fresh("almost", minutes=30, n=1), "text": "OpenAI launch note", "likes": 90}
    hot_enough_after = {"url": fresh("hot", minutes=30, n=2), "text": "OpenAI launch note", "likes": 130}

    selected = reply_source.select(
        [hot_enough_before, hot_enough_after],
        Declaration(max_age=HOUR, rising_extension=True),
        "TAG",
    )

    assert urls(selected) == [hot_enough_after["url"]]


def test_root_only_drops_nested_replies():
    root, nested, mention = fresh("a", n=1), fresh("b", n=2), fresh("c", n=3)
    tweets = [{"url": root, "text": "a root post"}, {"url": nested, "text": "a reply", "is_reply": True},
              {"url": mention, "text": "@someone a reply"}]

    assert urls(reply_source.select(tweets, Declaration(max_age=HOUR), "TAG")) == [root, nested, mention]
    assert urls(reply_source.select(tweets, Declaration(max_age=HOUR, root_only=True), "TAG")) == [root]


def test_the_expected_author_is_read_from_the_status_url():
    """A reposted post on a scanned profile names another author in its URL;
    the scraped display name is never compared."""
    own, anonymous = fresh("sama", n=1), f"https://x.com/i/web/status/{fresh('x', n=2).rsplit('/', 1)[1]}"
    tweets = [{"url": own, "text": "own post", "author": "Someone Else"},
              {"url": fresh("other", n=3), "text": "reposted", "author": "sama"},
              {"url": anonymous, "text": "anonymous URL"}]

    selected = reply_source.select(tweets, Declaration(max_age=HOUR, author="@Sama"), "TAG")

    assert urls(selected) == [own, anonymous]


def test_the_niche_keeps_posts_on_the_accounts_niche():
    on, off = fresh("a", n=1), fresh("b", n=2)
    tweets = [{"url": off, "text": "my sandwich today"}, {"url": on, "text": "OpenAI ships a new model"}]

    assert urls(reply_source.select(tweets, Declaration(max_age=HOUR), "TAG")) == [off, on]
    assert urls(reply_source.select(tweets, Declaration(max_age=HOUR, niche=True), "TAG")) == [on]


def test_the_order_is_the_scrape_order_or_fresh_and_rising_first():
    steady = {"url": fresh("a", minutes=14, n=1), "text": "steady", "likes": 100}
    cold = {"url": fresh("b", minutes=12, n=2), "text": "cold", "likes": 2}
    hot = {"url": fresh("c", minutes=10, n=3), "text": "hot", "likes": 400}
    tweets = [steady, cold, hot]

    assert urls(reply_source.select(tweets, Declaration(max_age=HOUR), "TAG")) == [t["url"] for t in tweets]
    ranked = reply_source.select(tweets, Declaration(max_age=HOUR, order=Order.FRESH_AND_RISING), "TAG")
    assert urls(ranked) == [hot["url"], steady["url"], cold["url"]]


def test_the_newest_order_ignores_likes():
    """Debate answers its freshest mentions first (#243): a liked mention
    never jumps ahead of a newer one, as it would fresh and rising first."""
    liked = {"url": fresh("a", minutes=14, n=1), "text": "liked", "likes": 5_000}
    newer = {"url": fresh("b", minutes=5, n=2), "text": "newer"}
    middle = {"url": fresh("c", minutes=10, n=3), "text": "middle", "likes": 1}

    ranked = reply_source.select([liked, newer, middle], Declaration(max_age=HOUR, order=Order.NEWEST), "TAG")

    assert urls(ranked) == [newer["url"], middle["url"], liked["url"]]


def test_reply_candidates_sorted_fresh_and_rising_first():
    """2026-06-07 spec: front-load fresh fast-rising posts. A 20-min riser
    must beat a 60-hour-old tweet; unknown-age URLs go last; within the
    same freshness bucket, higher likes-per-hour wins."""
    fresh_hot = {"url": fresh("someone", minutes=20, n=1), "likes": 400}
    fresh_cold = {"url": fresh("someone", minutes=25, n=2), "likes": 2}
    old = {"url": fresh("someone", minutes=60 * 60, n=3), "likes": 90000}
    unknown = {"url": "https://x.com/someone", "likes": 50}
    ordered = sorted([unknown, old, fresh_cold, fresh_hot], key=reply_source.freshness_sort_key)
    assert ordered[0] is fresh_hot
    assert ordered[1] is fresh_cold
    assert ordered[2] is old
    assert ordered[3] is unknown


def test_a_candidate_carries_the_post_text_and_the_tag():
    url = fresh("someone")

    assert reply_source.select([{"url": url, "text": "a post "}], Declaration(max_age=HOUR), "FEED-SWEEP-FEED") \
        == [reply_pipeline.Candidate(url, "a post ", "FEED-SWEEP-FEED")]


def test_select_leaves_the_scraped_posts_as_they_were():
    tweets = [{"url": fresh("a", minutes=20, n=1), "text": "a", "likes": 1},
              {"url": fresh("b", minutes=10, n=2), "text": "b", "likes": 9}]
    before = [dict(t) for t in tweets]

    reply_source.select(tweets, Declaration(max_age=HOUR, order=Order.FRESH_AND_RISING), "TAG")

    assert tweets == before

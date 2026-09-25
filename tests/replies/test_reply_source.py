"""src/replies/reply_source: the candidates a Reply job's declaration
selects among scraped posts, in its order, without side effects."""
from datetime import timedelta

from src.replies import reply_pipeline, reply_source
from src.replies.reply_source import Declaration, Order
from tests.helpers import fresh

HOUR = timedelta(hours=1)


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
    ok = fresh("someone", minutes=59, n=1)
    tweets = [{"url": "https://x.com/someone", "text": "no status id"},
              {"url": fresh("other", minutes=-5, n=2), "text": "from the future"},
              {"url": fresh("third", minutes=61, n=3), "text": "too old"},
              {"url": ok, "text": "in time"}]

    assert urls(reply_source.select(tweets, Declaration(max_age=HOUR), "TAG")) == [ok]


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
    old = {"url": fresh("a", minutes=300, n=1), "text": "old", "likes": 90_000}
    cold = {"url": fresh("b", minutes=25, n=2), "text": "cold", "likes": 2}
    hot = {"url": fresh("c", minutes=20, n=3), "text": "hot", "likes": 400}
    tweets = [old, cold, hot]
    week = timedelta(days=7)

    assert urls(reply_source.select(tweets, Declaration(max_age=week), "TAG")) == [t["url"] for t in tweets]
    ranked = reply_source.select(tweets, Declaration(max_age=week, order=Order.FRESH_AND_RISING), "TAG")
    assert urls(ranked) == [hot["url"], cold["url"], old["url"]]


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

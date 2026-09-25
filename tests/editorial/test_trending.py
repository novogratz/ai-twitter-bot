"""src/editorial/trending: the Trending posts a Trend slot takes its topic from."""
from datetime import datetime

import pytest

from src.editorial import trending
from tests.helpers import TORONTO


def test_trending_posts_are_fresh_ranked_anonymous_and_cached(monkeypatch):
    from src.core import account, config
    from src.x import scraper
    from tests.helpers import fresh
    monkeypatch.setattr(config, "BLOCKLIST", {"blockedguy"})
    def tweet(handle, minutes, likes, text, n):
        return dict(url=fresh(handle, minutes, n), text=text, likes=likes, views=likes * 10)
    # (age in minutes, likes): likes per minute 10, 6, 4, 3, 2, 1. The
    # fastest is not the newest, and the order below is shuffled.
    speed = [(300, 3000), (100, 600), (200, 800), (50, 150), (30, 60), (20, 20)]
    good = [tweet(f"writer{i}", speed[i][0], speed[i][1], f"New AI model {i} from @lab https://t.co/x", i)
            for i in (3, 5, 0, 4, 1, 2)]
    noise = [
        tweet(config.BOT_HANDLE, 30, 900, "Our AI model take", 10),
        tweet(config.BOT_HANDLE.lower(), 30, 900, "Our other AI model take", 16),
        tweet("blockedguy", 30, 900, "An AI model rant", 11),
        tweet("oldtimer", 30 * 60, 9000, "Old AI model news", 12),
        tweet("replier", 30, 900, "@someone the AI model is fine", 13),
        tweet("shill", 30, 900, "AI agent token airdrop today", 14),
        tweet("chef", 30, 900, "A great pasta recipe", 15),
    ]
    searches = []
    def search(query, **k):
        searches.append((query, k))
        return good + noise
    monkeypatch.setattr(scraper, "scrape_x_search", search)
    now = datetime.now(TORONTO)
    posts = trending.collect_trending_posts(("10:00", "x"), now)
    assert [p["text"] for p in posts] == [f"New AI model {i} from" for i in range(5)]
    assert all(k["tab"] == "top" and k["text_limit"] == trending.TREND_TEXT_LIMIT
               and k["max_tweets"] == trending.TREND_SEARCH_TWEETS for _, k in searches)
    assert [query for query, _ in searches] == list(account.current().searches.trending)
    assert trending.collect_trending_posts(("10:00", "x"), now) == posts
    assert len(searches) == len(account.current().searches.trending)


@pytest.mark.parametrize("raw, kept", [
    ("New AI model, details at t.co/abc123 today", "New AI model, details at today"),
    ("The AI paper lives on site.com/papers/42 now", "The AI paper lives on now"),
    ("Read www.example.org/ai for the model card", "Read for the model card"),
    ("OpenAI posted on openai.com and x.ai answered", "OpenAI posted on and answered"),
    ("GPT-4.5 scores 9.5/10 on the AI eval, e.g. math", "GPT-4.5 scores 9.5/10 on the AI eval, e.g. math"),
])
def test_links_without_a_scheme_never_reach_the_prompt(raw, kept):
    assert " ".join(trending._LINK_OR_MENTION.sub("", raw).split()) == kept

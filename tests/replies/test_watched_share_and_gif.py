"""Operator and coach, 2026-11-25: answer about three watched posts in ten (always liked and reposted),
like and repost half of the others, a GIF when it helps."""
from dataclasses import replace
from datetime import timedelta

import pytest

from src.core import account
from src.guards import watch_curation


@pytest.fixture
def half(monkeypatch, promotion_account):
    profile = replace(promotion_account, watched_action_share=0.5)
    monkeypatch.setattr(account, "current", lambda: profile)
    return profile


def urls(count):
    return [f"https://x.com/elonmusk/status/{2125590588900921000 + i * 7919}" for i in range(count)]


def test_about_half_of_the_other_posts_are_liked_and_reposted_and_the_draw_is_stable(half, monkeypatch):
    monkeypatch.setattr(watch_curation, "selected", lambda url: {})
    monkeypatch.setattr(watch_curation.x_urls, "age", lambda url, *a: timedelta(minutes=10))
    first = [watch_curation.independent_actions(url) for url in urls(400)]
    assert 160 <= sum(first) <= 240
    assert first == [watch_curation.independent_actions(url) for url in urls(400)]


def test_nothing_is_drawn_before_the_reply_window_closes(half, monkeypatch):
    monkeypatch.setattr(watch_curation, "selected", lambda url: {})
    monkeypatch.setattr(watch_curation.x_urls, "age", lambda url, *a: timedelta(seconds=20))
    assert not any(watch_curation.independent_actions(url) for url in urls(50))


def test_a_selected_or_answered_post_is_always_liked_and_reposted(half, monkeypatch):
    from src.guards import replied_store
    monkeypatch.setattr(watch_curation.x_urls, "age", lambda url, *a: timedelta(seconds=20))
    monkeypatch.setattr(watch_curation, "selected", lambda url: {"url": url})
    assert all(watch_curation.independent_actions(url) for url in urls(20))
    monkeypatch.setattr(watch_curation, "selected", lambda url: {})
    answered = urls(1)[0]
    assert replied_store.claim(answered)
    assert watch_curation.independent_actions(answered)


def test_full_share_keeps_the_earlier_every_post_rule(promotion_account):
    assert all(watch_curation.independent_actions(url) for url in urls(20))


@pytest.mark.parametrize("value,query", [("rocket launch", "rocket launch"), ("Mind-blown!!", "Mind blown"),
    ("", ""), (None, ""), ("one two three four five six seven", ""), ("https://evil.example/x.gif", "https evil example x")])
def test_gif_query_is_a_few_plain_words_or_nothing(value, query):
    assert watch_curation.gif_query(value) == query


def test_selector_prompt_carries_the_operator_style_proportion_and_gif_field():
    from src.replies import curated_reposts
    template = curated_reposts.FAST_CALL.template
    assert "three posts in ten" in template and "{watched_style}" in template and "gif" in template
    assert "never a quota" in template


def test_reply_path_attaches_a_gif_only_when_asked_and_never_requires_it():
    import inspect
    from src.x import twitter_client
    source = inspect.getsource(twitter_client.reply_to_tweet)
    assert "if gif_query:" in source and "_attach_gif(gif_query)" in source
    assert "gifSearchGifImage" in inspect.getsource(twitter_client._attach_gif)


def test_candidate_carries_the_gif_to_the_send(monkeypatch):
    from src.replies import reply_pipeline
    assert reply_pipeline.Candidate("u", "t", "s", gif="rocket launch").gif == "rocket launch"
    assert reply_pipeline.Candidate("u", "t", "s").gif == ""


def test_short_watched_reply_with_no_detectable_language_is_admitted(promotion_account, settings_override):
    # 2026-11-25, live test: the selector's line for a watched post was refused as "detected unknown".
    from src.guards import reply_admission
    settings_override(REPLY_BROAD_DISCOVERY=True)
    text = "Passenger seat finally pulls its weight."
    assert reply_admission.judge_text("elonmusk", text, source_url="https://x.com/elonmusk/status/2125516475712844116")
    # the same day: one shared word (" on ") made an English line read as French at 100%
    assert reply_admission.judge_text("elonmusk", "Best passenger on a long drive.", source_url="https://x.com/elonmusk/status/2125516475712844116")
    assert not reply_admission.judge_text("elonmusk", "On est bien sur la route.", source_url="https://x.com/elonmusk/status/2125516475712844116")
    assert not reply_admission.judge_text("someone", text, source_url="https://x.com/someone/status/2125516475712844116")
    assert not reply_admission.judge_text("elonmusk", "Le siège passager sert enfin.", source_url="https://x.com/elonmusk/status/2125516475712844116")


def test_prepared_watched_reply_expires_with_the_configured_window_not_a_fixed_minute():
    import inspect
    from src.replies import reply_pipeline
    source = inspect.getsource(reply_pipeline)
    assert "timestamp() + 60)" not in source and "timestamp() + watch_curation.window())" in source


def test_watched_quote_post_is_matched_on_its_outer_text(monkeypatch, promotion_account, settings_override):
    # 2026-11-25, live test: the opened page joins the quoted post's text; the review holds the outer text.
    from src.guards import reply_selection
    settings_override(REPLY_CURATED_MODE=True, REPLY_BROAD_DISCOVERY=True)
    seen = []
    monkeypatch.setattr(reply_selection, "source_refusal", lambda url, text: "")
    monkeypatch.setattr(reply_selection, "evidence", lambda url, text: {"evidence": {}})
    monkeypatch.setattr(watch_curation, "reviewed", lambda page: seen.append(page["text"]) or page["text"] == "outer")
    url = "https://x.com/elonmusk/status/2125464682580623467"
    assert reply_selection.page_refusal(url, "outer", {"url": url, "text": "outer\nquoted text"}) == ""
    assert seen == ["outer"]

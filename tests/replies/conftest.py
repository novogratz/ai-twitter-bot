"""Fixtures of the reply job tests."""
import pytest

from tests.replies.fakes import FakeChokepoint, FakeLlm


@pytest.fixture
def llm(monkeypatch):
    from src.replies import reply_generator

    fake = FakeLlm()
    monkeypatch.setattr(reply_generator, "run_llm", fake)
    return fake


@pytest.fixture
def chokepoint(monkeypatch):
    """The Reply chokepoint stubbed in twitter_client, where the Reply
    pipeline looks it up; the pipeline's sleeps return at once, and @pgm_pm
    is the one Blocked account."""
    from src.core import config
    from src.replies import reply_pipeline
    from src.x import twitter_client

    fake = FakeChokepoint()
    monkeypatch.setattr(twitter_client, "reply_to_tweet", fake)
    monkeypatch.setattr(reply_pipeline, "_sleep", lambda seconds: None)
    monkeypatch.setattr(config, "BLOCKLIST", {"pgm_pm"})
    return fake

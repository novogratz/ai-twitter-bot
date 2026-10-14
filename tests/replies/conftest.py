"""Fixtures of the reply job tests."""
import threading

import pytest

from tests.replies.fakes import FakeChokepoint, FakeLlm


@pytest.fixture
def llm(monkeypatch):
    from src.replies import reply_generator

    fake = FakeLlm()
    monkeypatch.setattr(reply_generator, "run_llm", fake)
    before = set(threading.enumerate())
    yield fake
    # A pipelined cycle leaves without waiting for the generation in flight:
    # let it reach this fake before the real run_llm comes back, or it calls
    # a provider during the next test.
    for thread in set(threading.enumerate()) - before:
        if thread.name.startswith("ThreadPoolExecutor"):
            thread.join(timeout=5)


@pytest.fixture
def chokepoint(monkeypatch):
    """The Reply chokepoint stubbed in twitter_client, where the Reply
    pipeline looks it up; the pipeline's sleeps return at once."""
    from src.replies import reply_pipeline
    from src.x import twitter_client

    fake = FakeChokepoint()
    monkeypatch.setattr(twitter_client, "reply_to_tweet", fake)
    monkeypatch.setattr(reply_pipeline, "_sleep", lambda seconds: None)
    return fake


@pytest.fixture
def blocked_pgm_pm(monkeypatch):
    """@pgm_pm is the one Blocked account."""
    from src.core import config

    monkeypatch.setattr(config, "BLOCKLIST", {"pgm_pm"})

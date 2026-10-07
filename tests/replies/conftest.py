"""Fixtures of the reply job tests."""
import threading

import pytest

from tests.replies.fakes import FakeChokepoint, FakeLlm


@pytest.fixture
def quality_llm(monkeypatch):
    import json
    from src.core.llm_client import LLMResult
    from src.replies import reply_quality
    # These tests exercise generation/jobs. Evidence and the separate
    # reviewer use independent seams; test_reply_quality tests their real code.
    monkeypatch.setattr(reply_quality, "collect", lambda *a: ())
    monkeypatch.setattr(reply_quality, "run_llm", lambda *a, **k: LLMResult(0, json.dumps({
        "approved": True, "on_topic": True, "answers_parent": True, "adds_value": True, "natural": True,
        "factually_supported": True, "needs_current_evidence": False,
        "evidence_ids": [], "reason": "Useful stable point."}), ""))


@pytest.fixture
def llm(monkeypatch, quality_llm):
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
def always_reply(monkeypatch):
    """`always_reply(*handles)`: the loaded Account's always-reply accounts
    are `handles` alone; its lists, vip_reply included, stay as loaded."""
    from src.core import account

    def swap(*handles):
        monkeypatch.setattr(account.Network, "always_reply", property(lambda self: handles))
    return swap


@pytest.fixture
def blocked_pgm_pm(monkeypatch):
    """@pgm_pm is the one Blocked account."""
    from src.core import config

    monkeypatch.setattr(config, "BLOCKLIST", {"pgm_pm"})

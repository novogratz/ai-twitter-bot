"""Fixtures of the reply job tests."""
import pytest

from tests.replies.fakes import FakeLlm


@pytest.fixture
def llm(monkeypatch):
    from src.replies import reply_generator

    fake = FakeLlm()
    monkeypatch.setattr(reply_generator, "run_llm", fake)
    return fake

"""The one fake at the run_llm seam, for every Reply generator path."""
from types import SimpleNamespace

from src.core.llm_client import LLMResult
from src.x.confirmed_write import WriteOutcome

REPLY_TEXT = "Batching is where inference margins are won or lost, not in the model."


class FakeLlm:
    """Records every prompt and answers the first `answers` entry whose key
    appears in the prompt, `default` (REPLY_TEXT) otherwise. An answer is the
    model's stdout, an LLMResult, an exception to raise, or a function of
    the prompt returning one of those."""

    def __init__(self):
        self.calls = []
        self.answers = {}
        self.default = REPLY_TEXT

    def __call__(self, prompt, model, **options):
        self.calls.append(SimpleNamespace(prompt=prompt, model=model, **options))
        answer = next((a for key, a in self.answers.items() if key in prompt), self.default)
        if callable(answer):
            answer = answer(prompt)
        if isinstance(answer, BaseException):
            raise answer
        return answer if isinstance(answer, LLMResult) else LLMResult(0, answer, "")

    @property
    def prompts(self):
        return [c.prompt for c in self.calls]

    def parents(self, *texts):
        """Which of `texts` each call was about, in call order; a prompt
        must quote exactly one of them."""
        found = []
        for prompt in self.prompts:
            hits = [t for t in texts if t in prompt]
            assert len(hits) == 1, f"ambiguous parent texts {hits} in a prompt"
            found.append(hits[0])
        return found


class FakeChokepoint:
    """Stands in for twitter_client.reply_to_tweet. Records every call and
    answers `answer`: a WriteOutcome, an exception to raise, or a function of
    the URL returning one of those. SHIPPED by default, as the real one."""

    def __init__(self):
        self.calls = []
        self.answer = WriteOutcome.SHIPPED

    def __call__(self, url, text, *, debate_turn=False):
        self.calls.append(SimpleNamespace(url=url, text=text, debate_turn=debate_turn))
        answer = self.answer(url) if callable(self.answer) else self.answer
        if isinstance(answer, BaseException):
            raise answer
        return answer

    @property
    def sent(self):
        return [c.url for c in self.calls]


def logged():
    """The engagement log rows written so far: (target URL, source, text, pattern)."""
    import csv
    import os

    from src.core import config

    if not os.path.exists(config.ENGAGEMENT_LOG_FILE):
        return []
    with open(config.ENGAGEMENT_LOG_FILE, newline="") as f:
        rows = list(csv.reader(f))[1:]
    return [SimpleNamespace(url=r[3], source=r[4], text=r[2], pattern=r[5]) for r in rows]

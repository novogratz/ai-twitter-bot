"""The one fake at the run_llm seam, for every Reply generator path."""
from types import SimpleNamespace

from src.core.llm_client import LLMResult

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

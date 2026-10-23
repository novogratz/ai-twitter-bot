"""Reply terminology leaves research evidence and literal references alone."""
from dataclasses import replace

import pytest

from src.core import account, reply_wording


@pytest.mark.parametrize("before, after", [
    ("AI needs better evals.", "SI needs better evals."),
    ("ai, Ai and AI-based tools", "SI, SI and SI-based tools"),
    ("Artificial Intelligence needs tests, not hype.", "Super Intelligence needs tests, not hype."),
    ("ARTIFICIAL\nINTELLIGENCE and artificial intelligence", "Super Intelligence and Super Intelligence"),
    ("AIs and AI's limits", "SIs and SI's limits"),
    ("OpenAI, xAI, AIR and said", "OpenAI, xAI, AIR and said"),
    ("@AI @OpenAI https://example.ai/AI?q=AI&term=Artificial%20Intelligence AI",
     "@AI @OpenAI https://example.ai/AI?q=AI&term=Artificial%20Intelligence SI"),
    ("example.ai/AI www.example.ai/AI AI@example.ai AI", "example.ai/AI www.example.ai/AI AI@example.ai SI"),
    ("J'ai comparé AI et j’en ai parlé.", "J'ai comparé SI et j’en ai parlé."),
    ("J’AI compris, je vous ai dit, je n'ai rien ajouté. Ai-je fini ?",
     "J’AI compris, je vous ai dit, je n'ai rien ajouté. Ai-je fini ?"),
    ("Je l’ai lu, je ne l'ai pas testé, je t'ai répondu sur AI.",
     "Je l’ai lu, je ne l'ai pas testé, je t'ai répondu sur SI."),
    ('The word "AI" and the phrase \'Artificial Intelligence\'.',
     'The word "SI" and the phrase \'Super Intelligence\'.'),
])
def test_terms_and_references(before, after):
    assert reply_wording.apply(before) == after
    assert reply_wording.apply(after) == after


def test_an_account_without_the_preference_keeps_its_wording(monkeypatch):
    other = replace(account.current(), reply_si_wording=False)
    monkeypatch.setattr(account, "current", lambda: other)
    assert reply_wording.apply("AI means Artificial Intelligence") == "AI means Artificial Intelligence"
    assert reply_wording.prompt_block() == ""

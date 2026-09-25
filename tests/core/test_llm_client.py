"""src/core/llm_client: the fallback ladder, output reading and request routing."""
import json
from datetime import datetime, timedelta

import pytest

from src.core.llm_client import CallProfile, LLMResult, Output, contains_post_unsafe_leak


def read(stdout, output):
    from src.core.llm_client import _read_answer
    return _read_answer(stdout, output)


def test_structured_output_json_array_survives():
    arr = json.dumps([{"tweet_url": "https://x.com/a/status/1", "reply": "calm take"}])
    assert read(arr, Output.JSON).startswith("[")


def test_unstructured_json_array_blocked():
    arr = json.dumps([{"type": "step_start", "sessionID": "x"}])
    assert read(arr, Output.TEXT) == ""


def test_plain_text_passes_unwrap():
    assert read("just a tweet", Output.TEXT) == "just a tweet"


def test_post_unsafe_leak_detection():
    assert contains_post_unsafe_leak('{"type":"step_start","x":1}')
    assert not contains_post_unsafe_leak("a normal tweet about GPUs")


def test_structured_editorial_json_preserves_text_and_evidence():
    draft = {"text": "A useful post", "source_id": "1", "evidence": ["source quote"]}
    assert json.loads(read(json.dumps(draft), Output.JSON)) == draft


# --- The fallback ladder, behind fake adapters --------------------------------

TEXT = "Batching decides the margin, not the model."
ITEMS = [{"tweet_url": "https://x.com/someone/status/1", "reply": "Batching decides the margin.",
          "type": "reply", "pattern": "OTHER"}]
COMPACT = json.dumps(ITEMS, separators=(",", ":"))
USAGE_LIMIT = "You've hit your usage limit. Upgrade to Pro or try again at May 16th, 2099 9:22 PM."


class FakeAdapter:
    """Stands in for one provider's adapter: records each request in
    `calls`, shared by all the fakes, and answers its `answers` in turn,
    the last one for good. An answer is raw provider output or an
    LLMResult."""

    def __init__(self, name, calls):
        self.name, self.calls = name, calls
        self.answers = [LLMResult(1, "", f"{name} was not expected")]

    def __call__(self, request):
        self.calls.append((self.name, request))
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        return answer if isinstance(answer, LLMResult) else LLMResult(0, answer, "")


@pytest.fixture
def providers(monkeypatch):
    """A fake adapter for every provider, each failing until a test gives
    it answers, every CLI installed, the ladder's variables unset."""
    from types import SimpleNamespace
    from src.core import llm_client as llm

    calls = []
    fakes = {name: FakeAdapter(name, calls) for name in ("ollama", "codex", "gemini", "claude", "opencode")}
    monkeypatch.setattr(llm, "ADAPTERS", fakes)
    monkeypatch.setattr(llm.shutil, "which", lambda name: f"/usr/local/bin/{name}")
    for var in ("AI_CLI", "LLM_FALLBACK_CLI", "LLM_FALLBACK_MODEL", "LLM_DISABLE_FALLBACK"):
        monkeypatch.delenv(var, raising=False)
    return SimpleNamespace(calls=calls, **fakes)


def ask(profile=CallProfile(), provider="claude", **options):
    from src.core.llm_client import run_llm
    return run_llm("prompt", "cloud-model", label="TEST", profile=profile,
                   force_provider=provider, **options)


def claude_envelope(text):
    return json.dumps({"type": "result", "subtype": "success", "result": text})


def primary(p, answer):
    p.claude.answers = [claude_envelope(answer)]
    return "claude", ["claude"]


def fallback(p, answer):
    p.claude.answers = [LLMResult(1, "", "claude down")]
    p.codex.answers = [answer]
    return "claude", ["claude", "codex"]


def after_codex_lock(p, answer):
    p.codex.answers = [LLMResult(1, "", USAGE_LIMIT)]
    p.ollama.answers = [answer]
    return "codex", ["codex", "ollama"]


def while_codex_locked(p, answer):
    from src.core import llm_client as llm
    llm._write_codex_lockout(datetime.now() + timedelta(days=1))
    p.ollama.answers = [answer]
    return "codex", ["ollama"]


RANKS = [primary, fallback, after_codex_lock, while_codex_locked]
MODES = {
    Output.TEXT: (TEXT, lambda stdout: stdout == TEXT),
    Output.JSON: (COMPACT, lambda stdout: json.loads(stdout) == ITEMS),
}


@pytest.mark.parametrize("output", list(MODES))
@pytest.mark.parametrize("rank", RANKS)
def test_every_rank_returns_the_answer_read_in_the_declared_mode(providers, rank, output):
    """Issue #175: whichever provider answers, and at whichever rank, the
    caller gets the model's text or its JSON, never a provider's output. A
    compact JSON array is not read as a stream of events."""
    answer, as_expected = MODES[output]
    provider, ladder = rank(providers, answer)

    result = ask(CallProfile(output=output), provider)

    assert [name for name, _ in providers.calls] == ladder
    assert result.returncode == 0 and as_expected(result.stdout), result


def test_a_codex_usage_limit_is_cached_for_the_next_calls(providers):
    after_codex_lock(providers, TEXT)
    assert ask(provider="codex").stdout == TEXT
    providers.calls.clear()
    assert ask(provider="codex").stdout == TEXT
    assert [name for name, _ in providers.calls] == ["ollama"]


@pytest.mark.parametrize("answer", [
    f"Voici les replies :\n```json\n{COMPACT}\n```\nBonne chance !",
    f"Here are the replies: {COMPACT} — enjoy.",
    json.dumps(ITEMS, indent=2),
])
def test_json_mode_finds_the_array_inside_prose(providers, answer):
    providers.claude.answers = [claude_envelope(answer)]
    assert json.loads(ask(CallProfile(output=Output.JSON)).stdout) == ITEMS


@pytest.mark.parametrize("leak", [
    "<function=bash>\n<parameter=command>curl -s https://api.github.com</parameter>\n</function>",
    '{"type":"step_start","timestamp":1,"sessionID":"ses_1"}',
    "⚠️ CRITIQUE: FR_ANCHOR",
])
@pytest.mark.parametrize("rank", RANKS)
def test_text_mode_refuses_a_leak_at_every_rank(providers, rank, leak):
    """A leaked tool call, stream envelope or prompt line is no answer: the
    call falls back, and fails when nothing else answers."""
    provider, ladder = rank(providers, leak)
    result = ask(provider=provider)
    assert ladder[-1] in [name for name, _ in providers.calls]
    assert result.returncode != 0 and result.stdout == ""


def test_a_leak_from_the_primary_falls_back_to_a_clean_answer(providers):
    providers.claude.answers = [claude_envelope("<function=bash>ls</function>")]
    providers.codex.answers = [TEXT]
    assert ask().stdout == TEXT


def test_json_mode_strips_tool_calls_and_keeps_the_json(providers):
    providers.claude.answers = [claude_envelope(f"<function=bash>ls</function>{COMPACT}")]
    assert json.loads(ask(CallProfile(output=Output.JSON)).stdout) == ITEMS


@pytest.mark.parametrize("answer", [LLMResult(1, "", "boom"), LLMResult(0, "", ""),
                                    "I don't need to search, as you have provided the text."])
def test_a_failed_ladder_returns_no_text(providers, answer):
    providers.claude.answers = [answer]
    providers.codex.answers = [answer]
    result = ask()
    assert result.returncode != 0 and result.stdout == ""
    assert [name for name, _ in providers.calls] == ["claude", "codex"]


def test_ollama_never_falls_back_to_itself(providers, monkeypatch):
    monkeypatch.setenv("LLM_FALLBACK_CLI", "ollama")
    monkeypatch.setenv("LLM_FALLBACK_MODEL", "another-model")
    assert ask(provider="ollama").returncode != 0
    assert [name for name, _ in providers.calls] == ["ollama"]


def test_the_fallback_can_be_turned_off(providers, monkeypatch):
    monkeypatch.setenv("LLM_DISABLE_FALLBACK", "1")
    assert ask().returncode != 0
    assert [name for name, _ in providers.calls] == ["claude"]


# --- Timeouts: one place computes them -----------------------------------------

@pytest.mark.parametrize("provider, requested, profile_floor, expected", [
    # Ollama: floored at the default, then at the profile's floor.
    # A claude, codex or gemini primary is capped at 360s, any other CLI
    # primary is not; a CLI after Ollama at 150s; a CLI after a CLI keeps
    # the requested timeout.
    ("ollama", 30, 0, {"ollama": 180, "codex": 30}),
    ("ollama", 30, 300, {"ollama": 300, "codex": 30}),
    ("ollama", 400, 300, {"ollama": 400, "codex": 150}),
    ("ollama", None, 0, {"ollama": 180, "codex": 150}),
    ("claude", None, 0, {"claude": 180, "codex": 180}),
    ("claude", 500, 0, {"claude": 360, "codex": 500}),
    ("opencode", 500, 0, {"opencode": 500, "codex": 500}),
])
def test_each_adapter_gets_the_timeout_computed_for_its_rank(providers, monkeypatch, provider, requested,
                                                               profile_floor, expected):
    from src.core import llm_client as llm
    monkeypatch.setattr(llm, "DEFAULT_LLM_TIMEOUT_SECONDS", 180)
    ask(CallProfile(min_timeout=profile_floor), provider, timeout=requested)
    assert {name: request.timeout for name, request in providers.calls} == expected


def test_every_timeout_stops_at_bedtime(providers, monkeypatch):
    from src.guards import active_hours
    monkeypatch.setattr(active_hours, "seconds_until_bedtime", lambda: 42)
    ask(CallProfile(min_timeout=300), "ollama", timeout=500)
    assert [request.timeout for _, request in providers.calls] == [42, 42]


def test_only_the_timeout_function_reads_the_bedtime_clock():
    import ast
    import inspect
    from src.core import llm_client as llm

    readers = {node.name for node in ast.walk(ast.parse(inspect.getsource(llm)))
               if isinstance(node, ast.FunctionDef)
               and "seconds_until_bedtime" in ast.unparse(node)}
    assert readers == {"_timeout"}


def test_no_caller_reads_provider_output():
    """Issue #175: `run_llm` reads the answer once; nothing else in src/
    touches the reader."""
    from pathlib import Path

    src = Path(__file__).resolve().parents[2] / "src"
    readers = ("_read_answer", "_provider_text", "_unwrap_ndjson", "_json_span", "unwrap_text")
    offenders = [path.relative_to(src).as_posix() for path in src.rglob("*.py")
                 if path.name != "llm_client.py" and any(name in path.read_text() for name in readers)]
    assert offenders == []


# --- Ollama requests follow the profile ----------------------------------------

class OllamaServer:
    """Stands in for Ollama's /api/generate behind urllib: records each
    request body with its HTTP timeout, answers JSON when given a schema."""

    def __init__(self):
        self.requests = []

    def __call__(self, request, timeout=None):
        import io
        body = json.loads(request.data)
        self.requests.append((body, timeout))
        answer = "{}" if "format" in body else TEXT
        return io.BytesIO(json.dumps({"response": answer}).encode())


def test_ollama_requests_follow_the_profile_never_the_label(monkeypatch):
    """Issue #174: the caller's profile sets the model, schema, temperature,
    timeout floor and voice prefix; the label only names the call, the
    suffixes the ladder adds to it included."""
    import urllib.request
    from src.core import llm_client as llm
    from src.editorial import editorial_schemas as schemas

    ollama = OllamaServer()
    monkeypatch.setattr(urllib.request, "urlopen", ollama)
    cloud = []
    for name, answer in (("claude", LLMResult(1, "", "claude down")), ("codex", LLMResult(1, "", USAGE_LIMIT))):
        monkeypatch.setitem(llm.ADAPTERS, name,
                            lambda request, answer=answer: cloud.append(request.label) or answer)
    monkeypatch.setattr(llm.shutil, "which", lambda name: f"/usr/local/bin/{name}")
    monkeypatch.setattr(llm, "OLLAMA_MODEL", "reply-model")
    monkeypatch.setenv("EDITORIAL_OLLAMA_MODEL", "editor-model")
    monkeypatch.setenv("EDITORIAL_LLM_TIMEOUT_SECONDS", "300")
    monkeypatch.setenv("LLM_DISABLE_FALLBACK", "0")
    monkeypatch.delenv("LLM_FALLBACK_MODEL", raising=False)
    review = schemas.review_profile()

    def call(prompt, label, provider, fallback, profile=review):
        monkeypatch.setenv("LLM_FALLBACK_CLI", fallback)
        result = llm.run_llm(prompt, "cloud-model", label=label, timeout=30, profile=profile,
                             force_provider=provider)
        assert result.returncode == 0, result

    call("Review prompt", "EDITORIAL_REVIEW", "ollama", "ollama")
    call("Review prompt", "EDITORIAL_REVIEW", "claude", "ollama")  # "EDITORIAL_REVIEW (ollama fallback)"
    call("Review prompt", "EDITORIAL_REVIEW", "codex", "codex")  # "EDITORIAL_REVIEW (codex locked)"
    call("Review prompt", "EDITORIAL_REVIEW", "codex", "codex")  # cached lock: Ollama alone
    call("Review prompt", "DIRECT_REPLY", "ollama", "ollama")
    call("Draft prompt", "EDITORIAL_REVIEW", "ollama", "ollama", schemas.draft_profile())
    call("Reply prompt", "EDITORIAL_DRAFT", "ollama", "ollama", llm.TEXT_PROFILE)

    assert cloud == ["EDITORIAL_REVIEW", "EDITORIAL_REVIEW"]
    *reviews, (draft, draft_timeout), (reply, reply_timeout) = ollama.requests
    assert len(reviews) == 5 and all(r == reviews[0] for r in reviews)
    request, timeout = reviews[0]
    assert request["model"] == "editor-model" and timeout == 300
    assert request["format"] == schemas.review_schema()
    assert request["options"]["temperature"] == 0.2
    assert request["prompt"] == "/no_think\n\nReview prompt"
    assert draft["format"] == schemas.draft_schema() and draft["options"]["temperature"] == 0.65
    assert reply["model"] == "reply-model" and "format" not in reply
    assert reply_timeout == llm.DEFAULT_LLM_TIMEOUT_SECONDS
    assert reply["prompt"].startswith(llm._FUNNY_FORCER)


def test_core_imports_nothing_from_the_editorial_package():
    import ast
    from pathlib import Path

    core = Path(__file__).resolve().parents[2] / "src" / "core"
    for path in core.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            elif isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            else:
                continue
            assert not any("editorial" in name.split(".") for name in names), path.name

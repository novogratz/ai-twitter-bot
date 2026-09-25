"""src/core/llm_client: the fallback ladder, output reading and request routing."""
import json
from datetime import datetime, timedelta

import pytest

from src.core.llm_client import (TEXT_PROFILE, CallProfile, LLMResult, LLMStatus, Output,
                                 contains_post_unsafe_leak)
from src.editorial.editorial_schemas import draft_profile
from tests.helpers import USAGE_LIMIT


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


# --- Issue #189: no implicit fallback, no unknown provider ---------------------

@pytest.mark.parametrize("fallback", [None, "", "  "])
@pytest.mark.parametrize("provider", ["ollama", "claude", "codex", "gemini"])
def test_without_a_configured_fallback_the_ladder_has_one_rank(providers, monkeypatch, provider, fallback):
    if fallback is None:
        monkeypatch.delenv("LLM_FALLBACK_CLI")
    else:
        monkeypatch.setenv("LLM_FALLBACK_CLI", fallback)
    result = ask(provider=provider)
    assert [name for name, _ in providers.calls] == [provider]
    assert result.status is LLMStatus.FAILED and result.provider == provider


@pytest.fixture
def no_process(monkeypatch):
    """Fails the test on any process or HTTP request a model call starts."""
    import urllib.request
    from src.core import llm_client as llm

    def started(*a, **k):
        raise AssertionError("an unknown provider started something")

    monkeypatch.setattr(llm.subprocess, "Popen", started)
    monkeypatch.setattr(urllib.request, "urlopen", started)


@pytest.mark.parametrize("setting", ["force_provider", "AI_CLI"])
def test_an_unknown_primary_fails_by_name_and_runs_nothing(monkeypatch, no_process, setting):
    """A typo in the Originals' provider sent the Drafts to the Claude CLI.
    The real adapters stay in place, and the configured fallback is not
    tried either."""
    from src.core import llm_client as llm
    monkeypatch.setattr(llm.shutil, "which", lambda name: f"/usr/local/bin/{name}")
    monkeypatch.setenv("LLM_FALLBACK_CLI", "codex")
    monkeypatch.setenv("AI_CLI", "olama")
    force = "olama" if setting == "force_provider" else None
    result = llm.run_llm("prompt", "cloud-model", label="TEST", force_provider=force)
    assert (result.status, result.provider, result.stdout) == (LLMStatus.FAILED, "olama", "")
    assert "unknown LLM provider 'olama'" in result.stderr


def test_an_unknown_fallback_fails_by_name_and_runs_nothing(providers, monkeypatch, no_process):
    monkeypatch.setenv("LLM_FALLBACK_CLI", "codx")
    result = ask()
    assert [name for name, _ in providers.calls] == ["claude"]
    assert (result.status, result.provider) == (LLMStatus.FAILED, "codx")
    assert "unknown LLM provider 'codx'" in result.stderr


def test_the_start_reports_each_provider_setting_that_names_no_adapter(monkeypatch):
    from src.core import config, llm_client as llm
    monkeypatch.setenv("AI_CLI", "ollama")
    monkeypatch.setenv("LLM_FALLBACK_CLI", "codx")
    monkeypatch.setattr(config, "PROFILE_LLM_PROVIDER", "clade")
    monkeypatch.setattr(config, "REPLY_LLM_PROVIDER", " Ollama ")
    assert llm.unknown_providers() == ["PROFILE_LLM_PROVIDER='clade'", "LLM_FALLBACK_CLI='codx'"]
    monkeypatch.setattr(config, "PROFILE_LLM_PROVIDER", None)
    monkeypatch.delenv("LLM_FALLBACK_CLI")
    assert llm.unknown_providers() == []


@pytest.mark.parametrize("profile", [TEXT_PROFILE, draft_profile()], ids=["Reply", "Original"])
def test_an_explicit_fallback_answers_as_before_and_is_named(providers, monkeypatch, profile):
    providers.codex.answers = [TEXT if profile is TEXT_PROFILE else json.dumps({"text": TEXT})]
    result = ask(profile, provider="ollama")
    assert [name for name, _ in providers.calls] == ["ollama", "codex"]
    assert (result.status, result.provider, result.model) == (LLMStatus.ANSWERED, "codex", "gpt-5.4-mini")


# --- Usage limits and who answered ---------------------------------------------

RATE_LIMIT = LLMResult(1, "", "429 Too Many Requests: rate limit reached for this hour")


@pytest.mark.parametrize("rank, provider, model", [
    (primary, "claude", "cloud-model"),
    (fallback, "codex", "gpt-5.4-mini"),
    (after_codex_lock, "ollama", "qwen3.6:35b-a3b"),
    (while_codex_locked, "ollama", "qwen3.6:35b-a3b"),
])
def test_every_answer_names_the_provider_and_model_that_gave_it(providers, monkeypatch, rank, provider,
                                                                  model):
    from src.core import llm_client as llm
    monkeypatch.setattr(llm, "OLLAMA_MODEL", "qwen3.6:35b-a3b")
    first, _ = rank(providers, TEXT)
    result = ask(provider=first)
    assert (result.status, result.provider, result.model) == (LLMStatus.ANSWERED, provider, model)


@pytest.mark.parametrize("fallback_limit", [
    pytest.param(RATE_LIMIT, id="rate limit at both ranks"),
    pytest.param(LLMResult(1, "", USAGE_LIMIT), id="codex usage limit as the fallback"),
])
def test_a_limit_at_every_rank_exhausts_the_call(providers, fallback_limit):
    """Issue #176: the rate limit is a named result, EXHAUSTED, when every
    provider tried hit its usage limit. It names the last one."""
    providers.claude.answers = [RATE_LIMIT]
    providers.codex.answers = [fallback_limit]
    result = ask()
    assert [name for name, _ in providers.calls] == ["claude", "codex"]
    assert result.status is LLMStatus.EXHAUSTED and result.returncode != 0 and result.stdout == ""
    assert (result.provider, result.model) == ("codex", "gpt-5.4-mini")


def test_a_codex_usage_limit_then_an_ollama_limit_exhausts_the_call(providers):
    providers.codex.answers = [LLMResult(1, "", USAGE_LIMIT)]
    providers.ollama.answers = [RATE_LIMIT]
    assert ask(provider="codex").status is LLMStatus.EXHAUSTED
    providers.calls.clear()
    assert ask(provider="codex").status is LLMStatus.EXHAUSTED, "a cached codex lockout counts as a limit"
    assert [name for name, _ in providers.calls] == ["ollama"]


def test_a_lone_provider_at_its_limit_exhausts_the_call(providers, monkeypatch):
    monkeypatch.setenv("LLM_DISABLE_FALLBACK", "1")
    providers.claude.answers = [RATE_LIMIT]
    assert ask().status is LLMStatus.EXHAUSTED


@pytest.mark.parametrize("answers", [
    pytest.param((RATE_LIMIT, LLMResult(1, "", "boom")), id="limit then failure"),
    pytest.param((LLMResult(124, "", "claude timed out"), RATE_LIMIT), id="failure then limit"),
    pytest.param(("I don't need to search, as you have provided the text.", RATE_LIMIT), id="refusal then limit"),
])
def test_a_rank_that_fails_otherwise_leaves_the_call_failed(providers, answers):
    """Another call may still get an answer: the job moves on."""
    providers.claude.answers, providers.codex.answers = [answers[0]], [answers[1]]
    assert ask().status is LLMStatus.FAILED


def test_a_limit_at_the_primary_leaves_the_fallback_answer(providers):
    providers.claude.answers = [RATE_LIMIT]
    providers.codex.answers = [TEXT]
    result = ask()
    assert (result.status, result.stdout, result.provider) == (LLMStatus.ANSWERED, TEXT, "codex")


def both_ranks(p, answer):
    p.claude.answers = [claude_envelope(answer)]
    p.codex.answers = [answer]
    return "claude", ["claude", "codex"]


# Answers about limits, as a model writes them on a zero exit. `_should_fallback`
# refused the first two before #176 and still does: the call fails.
TALK = {
    "Rate limits, not model quality, decide who wins the agent race.": LLMStatus.FAILED,
    "Hit your usage limit? Batching buys you another week.": LLMStatus.FAILED,
    "Too many requests is a pricing problem, not an infra one.": LLMStatus.ANSWERED,
}


@pytest.mark.parametrize("answer, status", list(TALK.items()))
@pytest.mark.parametrize("rank", [both_ranks, after_codex_lock, while_codex_locked])
def test_an_answer_about_limits_is_no_usage_limit(providers, rank, answer, status):
    """Review of #176: only the CLI or the transport reports a limit, never
    the text of an answer, at any rank."""
    provider, ladder = rank(providers, answer)
    result = ask(provider=provider)
    assert result.status is status
    if status is LLMStatus.ANSWERED:
        assert result.stdout == answer
    else:
        assert [name for name, _ in providers.calls] == ladder, "every rank answered"


ECHO_PROMPT = "Reply to this post.\nParent: You've hit your usage limit. Rate limits, too many requests."


def echoed(error):
    """A failed CLI call whose stderr echoes the prompt, as `codex exec` does."""
    return LLMResult(1, "", f"user\n{ECHO_PROMPT}\n\nERROR: {error}")


@pytest.mark.parametrize("error, status", [
    ("stream disconnected before completion", LLMStatus.FAILED),
    (USAGE_LIMIT, LLMStatus.EXHAUSTED),
])
def test_the_prompt_echoed_on_stderr_is_no_usage_limit(providers, error, status):
    from src.core.llm_client import run_llm
    providers.claude.answers = [echoed(error)]
    providers.codex.answers = [echoed(error)]
    result = run_llm(ECHO_PROMPT, "cloud-model", label="TEST", force_provider="claude")
    assert result.status is status


def test_the_prompt_echoed_on_stderr_locks_no_codex_out(providers):
    from src.core.llm_client import run_llm
    providers.codex.answers = [echoed("stream disconnected before completion"), TEXT]
    assert run_llm(ECHO_PROMPT, "cloud-model", label="TEST", force_provider="codex").status is LLMStatus.FAILED
    assert run_llm(ECHO_PROMPT, "cloud-model", label="TEST", force_provider="codex").stdout == TEXT
    assert [name for name, _ in providers.calls] == ["codex", "ollama", "codex"]


def test_an_error_envelope_on_a_zero_exit_is_a_usage_limit(providers):
    """Claude's JSON envelope flags its limit with `is_error`, whatever its
    exit code."""
    providers.claude.answers = [LLMResult(0, json.dumps({
        "type": "result", "subtype": "success", "is_error": True,
        "result": "Claude AI usage limit reached|1790000000"}), "")]
    providers.codex.answers = [RATE_LIMIT]
    assert ask().status is LLMStatus.EXHAUSTED


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

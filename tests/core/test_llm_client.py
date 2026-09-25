"""src/core/llm_client: output unwrapping and request routing."""
import json

from src.core.llm_client import unwrap_text, contains_post_unsafe_leak


def test_structured_output_json_array_survives():
    arr = json.dumps([{"tweet_url": "https://x.com/a/status/1", "reply": "calm take"}])
    assert unwrap_text(arr, structured_output=True).startswith("[")


def test_unstructured_json_array_blocked():
    arr = json.dumps([{"type": "step_start", "sessionID": "x"}])
    assert unwrap_text(arr) == ""


def test_plain_text_passes_unwrap():
    assert unwrap_text("just a tweet") == "just a tweet"


def test_post_unsafe_leak_detection():
    assert contains_post_unsafe_leak('{"type":"step_start","x":1}')
    assert not contains_post_unsafe_leak("a normal tweet about GPUs")


def test_structured_editorial_json_preserves_text_and_evidence():
    from src.core.llm_client import unwrap_text
    draft = {"text": "A useful post", "source_id": "1", "evidence": ["source quote"]}
    assert json.loads(unwrap_text(json.dumps(draft), structured_output=True)) == draft


class OllamaServer:
    """Stands in for Ollama's /api/generate behind urllib: records each
    request body with its HTTP timeout."""

    def __init__(self):
        self.requests = []

    def __call__(self, request, timeout=None):
        import io
        self.requests.append((json.loads(request.data), timeout))
        return io.BytesIO(b'{"response": "{}"}')


def test_ollama_requests_follow_the_profile_never_the_label(monkeypatch):
    """Issue #174: the caller's profile sets the model, schema, temperature,
    timeout floor and voice prefix; the label only names the call."""
    import urllib.request
    from src.core import llm_client as llm
    from src.editorial import editorial_schemas as schemas

    ollama = OllamaServer()
    monkeypatch.setattr(urllib.request, "urlopen", ollama)
    monkeypatch.setattr(llm, "OLLAMA_MODEL", "reply-model")
    monkeypatch.setattr(schemas, "EDITORIAL_OLLAMA_MODEL", "editor-model")
    monkeypatch.setenv("EDITORIAL_LLM_TIMEOUT_SECONDS", "300")
    review = schemas.review_profile()
    for label in ("EDITORIAL_REVIEW", "EDITORIAL_REVIEW (fallback)", "EDITORIAL_REVIEW (codex locked)",
                  "DIRECT_REPLY"):
        llm._run_ollama_http("Review prompt", label, 30, profile=review)
    llm._run_ollama_http("Draft prompt", "EDITORIAL_REVIEW", 30, profile=schemas.draft_profile())
    llm._run_ollama_http("Reply prompt", "EDITORIAL_DRAFT", 30)

    *reviews, (draft, draft_timeout), (reply, reply_timeout) = ollama.requests
    assert all(r == reviews[0] for r in reviews)
    request, timeout = reviews[0]
    assert request["model"] == "editor-model" and timeout == 300
    assert request["format"] == schemas.review_schema()
    assert request["options"]["temperature"] == 0.2
    assert request["prompt"] == "/no_think\n\nReview prompt"
    assert draft["format"] == schemas.draft_schema() and draft["options"]["temperature"] == 0.65
    assert reply["model"] == "reply-model" and "format" not in reply and reply_timeout == 30
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

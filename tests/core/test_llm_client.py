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


def test_editorial_requests_use_dedicated_model_and_strict_schema(monkeypatch):
    import urllib.request
    from src.core import llm_client as llm
    requests = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self):
            return b'{"response": "{}"}'

    def request(req, **kwargs):
        requests.append(json.loads(req.data))
        return Response()

    monkeypatch.setattr(urllib.request, "urlopen", request)
    monkeypatch.setattr(llm, "EDITORIAL_OLLAMA_MODEL", "editor-model")
    monkeypatch.setattr(llm, "OLLAMA_MODEL", "reply-model")
    llm._run_ollama_http("Draft prompt", "EDITORIAL_DRAFT", 30)
    llm._run_ollama_http("Review prompt", "EDITORIAL_REVIEW", 30)
    llm._run_ollama_http("Reply prompt", "DIRECT_REPLY", 30)
    assert requests[0]["model"] == requests[1]["model"] == "editor-model"
    assert "evidence_ids" in requests[0]["format"]["required"]
    assert requests[1]["format"]["properties"]["grounded"] == {"type": "boolean"}
    assert requests[2]["model"] == "reply-model" and "format" not in requests[2]
    assert llm._FUNNY_FORCER not in requests[0]["prompt"]

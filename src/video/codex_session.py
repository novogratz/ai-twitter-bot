"""Fresh, bounded Codex sessions for background media work; no public write tools."""
from contextlib import contextmanager
import json
from pathlib import Path
import shutil
import tempfile
import time
import uuid

from ..core import llm_client, settings, video_pressure
from .media import bounded_command, CommandFailure
from .security import AccessError, Deferred


def model(cfg):
    return cfg.codex_model or llm_client._model("codex", llm_client.ModelSetting("REPLY_MODEL"), llm_client.TEXT_PROFILE)


@contextmanager
def admission(store, cfg, purpose):
    now, token = time.time(), uuid.uuid4().hex
    if llm_client._read_codex_lockout() is not None or not store.circuit_ready("codex_video", now):
        raise Deferred("Codex shared usage lockout or background circuit cooldown")
    reason = video_pressure.pressure(store, cfg, now)
    if reason:
        raise Deferred("Codex deferred: " + reason)
    active = store.rows("SELECT COUNT(*) AS n FROM model_calls WHERE provider='codex' AND finished IS NULL AND lease>?", (now,))[0]["n"]
    if active > cfg.codex_max_reply_calls:
        raise Deferred("Codex deferred: Reply model capacity reserved")
    from .schedule import local, utc_now
    day = local(utc_now()).date().isoformat()
    spent = store.rows("SELECT amount FROM costs WHERE day=? AND provider='codex' AND kind='input_tokens'", (day,))
    # This bounds admission, not a provider's unobservable account-wide allowance.
    # Leave half the token budget inaccessible to public search. A call's measured
    # overrun is recorded and prevents the next call; usage is never guessed.
    ceiling = cfg.codex_daily_input_tokens * (.5 if purpose == "discovery" else 1)
    if spent and spent[0]["amount"] >= ceiling:
        raise Deferred("Codex measured input-token budget exhausted")
    with store.transaction() as db:
        row = db.execute("SELECT value FROM meta WHERE key='codex_background_claim'").fetchone()
        old = json.loads(row[0]) if row else {}
        if old.get("until", 0) > now:
            raise Deferred("another background Codex session is running")
        store.put_meta(db, "codex_background_claim", {"token": token, "until": now + cfg.codex_timeout_seconds + 20})
    try:
        if purpose == "discovery" and not store.budget("codex", "discovery_calls", 1,
                cfg.codex_daily_calls - cfg.codex_inspection_reserve, now):
            raise Deferred("Codex discovery budget exhausted; inspection headroom retained")
        if not store.budget("codex", "background_calls", 1, cfg.codex_daily_calls, now):
            raise Deferred("Codex background daily call budget exhausted")
        yield
    finally:
        with store.transaction() as db:
            row = db.execute("SELECT value FROM meta WHERE key='codex_background_claim'").fetchone()
            if row and json.loads(row[0]).get("token") == token:
                db.execute("DELETE FROM meta WHERE key='codex_background_claim'")


def command(cfg, schema_path, folder, images, *, search=False):
    binary = shutil.which("codex")
    if not binary:
        raise AccessError("Codex CLI is not installed")
    # Ignore inherited hooks, plugins, MCP servers and repo instructions. The
    # existing ChatGPT login is reused, but no existing thread is resumed.
    args = [binary, "-c", "approval_policy=\"never\"", "-c", "project_doc_max_bytes=0",
            "-c", "suppress_unstable_features_warning=true",
            "-c", "features.shell_tool=false", "-c", "features.apps=false", "-c", "features.plugins=false",
            "-c", "features.hooks=false", "-c", "features.multi_agent=false",
            "-c", "features.browser_use=false", "-c", "features.computer_use=false",
            "-c", "features.image_generation=false", "-c", "features.skill_search=false",
            "-c", "features.skip_host_skill_discovery=true",
            "-c", 'web_search="live"' if search else 'web_search="disabled"']
    effort = settings.get("CODEX_REASONING_EFFORT").strip()
    if effort:
        args += ["-c", "model_reasoning_effort=" + json.dumps(effort)]
    args += ["exec", "--ignore-user-config", "--ignore-rules", "--ephemeral", "--skip-git-repo-check",
             "--sandbox", "read-only", "--model", model(cfg), "--cd", str(folder), "--json",
             "--output-schema", str(schema_path)]
    for path in images:
        args += ["--image", str(Path(path).resolve())]
    return args + ["-"]


def call(store, cfg, prompt, schema, *, images=(), purpose="inspection"):
    """Only a completed, schema-valid turn is evidence. Never forward raw errors."""
    from jsonschema import Draft202012Validator
    with admission(store, cfg, purpose), tempfile.TemporaryDirectory(prefix="video-codex-") as directory:
        folder = Path(directory)
        schema_path = folder / "result.schema.json"
        schema_path.write_text(json.dumps(schema, allow_nan=False))
        args = command(cfg, schema_path, folder, images, search=purpose == "discovery")
        try:
            raw = bounded_command(args, prompt, cfg.codex_timeout_seconds, memory_mb=cfg.max_media_memory_mb,
                                  max_output=4_000_000, cwd=folder).decode("utf-8")
        except CommandFailure as exc:
            result = llm_client.LLMResult(exc.returncode, exc.stdout.decode("utf-8", "replace"),
                                          exc.stderr.decode("utf-8", "replace"))
            try:
                llm_client.codex_background_response(result, prompt)
            except ValueError:
                pass
            store.circuit("codex_video", time.time(), failed=True, retry_after=300)
            raise AccessError("Codex session failed; no inspection accepted") from None
        except (TimeoutError, ValueError):
            store.circuit("codex_video", time.time(), failed=True, retry_after=60)
            raise
        answer, events = llm_client.codex_background_response(llm_client.LLMResult(0, raw, ""), prompt)
        # Audit actual tool use as well as configured isolation. Discovery alone
        # may use the read-only web search tool; neither role gets a publisher.
        allowed = {"agent_message", "reasoning"} | ({"web_search"} if purpose == "discovery" else set())
        used = {e.get("item", {}).get("type") for e in events if e.get("type") == "item.completed"}
        if used - allowed:
            raise AccessError("unexpected Codex tool activity; result refused")
        Draft202012Validator(schema).validate(answer)
        completed = next(e for e in reversed(events) if e.get("type") == "turn.completed")
        usage = completed.get("usage", {})
        for key in ("input_tokens", "output_tokens", "cached_input_tokens"):
            count = usage.get(key)
            if type(count) is int and count >= 0:
                store.budget("codex", key, count, 1e12, time.time())
        store.circuit("codex_video", time.time(), failed=False)
        receipt = {"provider": "codex", "model": model(cfg), "fresh_session": True,
                   "completed_at": time.time(), "usage": usage,
                   "thread_id": next((e.get("thread_id") for e in events if e.get("type") == "thread.started"), None),
                   "tools": sorted(used - {"agent_message", "reasoning"}), "cost_usd": None,
                   "billing": "existing CLI login; observed token counts, no invented dollar cost"}
        return answer, receipt

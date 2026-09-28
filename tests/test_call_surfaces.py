"""Cross-cutting: every job's model call, from the job to the adapter.

Issue #247 pins the routing measured on main before the call surfaces:
with AI_CLI, REPLY_LLM_PROVIDER and PROFILE_LLM_PROVIDER all apart, each job
runs its model setting on the provider shown, with its CLI options. Since
#248 (the Operator, 2026-09-28) no Reply runs on AI_CLI while
REPLY_LLM_PROVIDER names a provider: debate, replyback, the VIP scan and a
Relation whose CLI is missing follow it too.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
EN = "Inference batching decides the margin of every model provider this year."
EVIDENCE = ("Chat templates convert conversations into the format expected by the model.",
            "A mismatched template quietly degrades the answers of an instruction tuned model.",
            "The tokenizer applies the chat template before generation starts in the pipeline.")
DEFAULT_TIMEOUT = 120
# The CLI options a call hands its adapter: output_json, allowed_tools and
# timeout. The CLI adapter picks the cwd itself (#249).
DEFAULTS = (True, None, DEFAULT_TIMEOUT)


def _reply(job, author="someone"):
    from src.replies import reply_generator
    reply_generator.generate(job().reply_call(author), author=author, text=EN)


def _vip_author():
    from src.core import account
    return sorted(account.current().network.vip_reply)[0]


def _search(vip=False):
    from src.replies import direct_reply
    _reply(lambda: direct_reply.SEARCH_JOB, _vip_author() if vip else "someone")


def _feed_sweep():
    from src.replies import feed_sweeper_bot, reply_generator
    reply_generator.generate(feed_sweeper_bot.reply_call("someone"), author="someone", text=EN)


def _early_bird():
    from src.replies import early_bird_bot
    _reply(lambda: early_bird_bot.JOB)


def _mega_watch():
    from src.replies import mega_watch_bot
    _reply(lambda: mega_watch_bot.JOB)


def _vip_scan(handle):
    from src.replies import direct_reply
    _reply(lambda: direct_reply._vip_job(handle), handle)


def _debate():
    from src.replies import debate_bot
    _reply(lambda: debate_bot.JOB)


def _replyback():
    from src.replies import notify_bot
    _reply(lambda: notify_bot.REPLYBACK_JOB)


def _reply_search(monkeypatch):
    from src.replies import reply_agent
    monkeypatch.setattr(reply_agent, "_load_discovered_handles", lambda limit=10: [])
    reply_agent.generate_replies()


def _source():
    return dict(id="0", title="Chat templates", url="https://huggingface.co/docs/transformers/chat_templating",
                publisher="Hugging Face", body=" ".join(EVIDENCE), kind="knowledge", published_at="")


def _draft():
    from src.editorial import editorial_bot as editorial
    editorial.draft_post(editorial.slots()[0], [_source()], [])


def _review(monkeypatch):
    from src.editorial import editorial_bot as editorial
    monkeypatch.setattr(editorial.content_guard, "is_duplicate", lambda text, submitted=(): False)
    draft = dict(source_id="0", text="Your model expects a particular conversation format. Check its chat "
                                     "template before changing your prompts; the wrapper around your words "
                                     "matters too.",
                 angle="format before prompting", takeaway="check the model chat template",
                 evidence_ids=["0", "1"])
    editorial.review_draft(draft, [_source()], [])


def _uninstalled(monkeypatch, cli):
    import shutil
    monkeypatch.setattr(shutil, "which", lambda name: None if name == cli else f"/usr/local/bin/{name}")


# job: (run it, model setting, provider called, CLI options)
ROUTES = {
    "search": (lambda mp: _search(), "REPLY_MODEL", "gemini", DEFAULTS),
    "search, VIP author": (lambda mp: _search(vip=True), "PRIORITY_REPLY_MODEL", "gemini", DEFAULTS),
    "feed sweep": (lambda mp: _feed_sweep(), "REPLY_MODEL", "gemini", DEFAULTS),
    "early bird": (lambda mp: _early_bird(), "REPLY_MODEL", "gemini", DEFAULTS),
    "mega watch": (lambda mp: _mega_watch(), "REPLY_MODEL", "gemini", DEFAULTS),
    "VIP scan": (lambda mp: _vip_scan("TheBTCTherapist"), "PRIORITY_REPLY_MODEL", "gemini", DEFAULTS),
    "Relation, CLI installed": (lambda mp: _vip_scan("Graphseo"), "PRIORITY_REPLY_MODEL", "claude",
                                (False, None, 60)),
    "Relation, CLI missing": (lambda mp: _uninstalled(mp, "claude") or _vip_scan("Graphseo"),
                              "PRIORITY_REPLY_MODEL", "gemini", (False, None, 60)),
    "debate": (lambda mp: _debate(), "REPLY_MODEL", "gemini", DEFAULTS),
    "replyback": (lambda mp: _replyback(), "REPLY_MODEL", "gemini", DEFAULTS),
    "reply search": (_reply_search, "REPLY_MODEL", "gemini", (True, ("WebSearch",), DEFAULT_TIMEOUT)),
    "Draft": (lambda mp: _draft(), "NEWS_MODEL", "claude", DEFAULTS),
    "review": (_review, "NEWS_MODEL", "claude", DEFAULTS),
}
MODELS = ("NEWS_MODEL", "REPLY_MODEL", "PRIORITY_REPLY_MODEL")


@pytest.mark.parametrize("job", ROUTES)
def test_each_job_runs_its_model_setting_on_its_provider(providers, job):
    run, model, provider, options = ROUTES[job]
    providers.settings(AI_CLI="codex", REPLY_LLM_PROVIDER="gemini", PROFILE_LLM_PROVIDER="claude",
                       LLM_FALLBACK_CLI="", LLM_TIMEOUT_SECONDS=DEFAULT_TIMEOUT, CONTENT_LANG_PRIMARY="en",
                       **{name: name.lower() for name in MODELS})

    run(providers.monkeypatch)

    [(called, request)] = providers.calls
    assert (called, request.model) == (provider, model.lower())
    assert (request.output_json, request.allowed_tools, request.timeout) == options


REPLIES = [job for job in ROUTES if job not in ("Draft", "review", "Relation, CLI installed")]


@pytest.mark.parametrize("job", REPLIES)
def test_a_blank_reply_provider_leaves_every_reply_on_ai_cli(providers, job):
    """A blank REPLY_LLM_PROVIDER means none: every Reply, a Relation whose
    CLI is missing included, runs on AI_CLI."""
    run, model, _, options = ROUTES[job]
    providers.settings(AI_CLI="codex", REPLY_LLM_PROVIDER="", PROFILE_LLM_PROVIDER="claude",
                       LLM_FALLBACK_CLI="", LLM_TIMEOUT_SECONDS=DEFAULT_TIMEOUT, CONTENT_LANG_PRIMARY="en",
                       **{name: name.lower() for name in MODELS})

    run(providers.monkeypatch)

    [(called, request)] = providers.calls
    assert (called, request.model) == ("codex", model.lower())
    assert (request.output_json, request.allowed_tools, request.timeout) == options


def test_the_jobs_read_no_model_or_provider_setting():
    """The call surface names them, in llm_client: a Reply job or the
    editorial pipeline names a surface instead."""
    setting = re.compile(r"\b(NEWS_MODEL|REPLY_MODEL|PRIORITY_REPLY_MODEL|REPLY_LLM_PROVIDER|"
                         r"PROFILE_LLM_PROVIDER|AI_CLI)\b")
    found = [f"{path.relative_to(ROOT)}:{number}"
             for package in ("replies", "editorial") for path in sorted((ROOT / "src" / package).glob("*.py"))
             for number, line in enumerate(path.read_text().splitlines(), 1) if setting.search(line)]
    assert found == []


class _FailingCli:
    """Stands in for subprocess.Popen: records each CLI's name and cwd,
    then fails, so the ladder reaches its fallback."""

    def __init__(self):
        self.started = []

    def __call__(self, cmd, **kwargs):
        from types import SimpleNamespace
        self.started.append((cmd[0], kwargs.get("cwd"), cmd))
        return SimpleNamespace(pid=0, returncode=1, communicate=lambda timeout=None: ("", "down"))


def _reached_instructions(folder: Path) -> list[str]:
    """The instruction and config files a CLI started in `folder` loads,
    walking up."""
    names = ("CLAUDE.md", "CLAUDE.local.md", "AGENTS.md", "GEMINI.md", ".git",
             ".claude", ".codex", ".gemini", ".opencode", "opencode.json", "opencode.jsonc")
    return [str(parent / name) for parent in (folder, *folder.parents) for name in names
            if (parent / name).exists()]


# job: (run it, primary CLI); each falls back on codex.
NEUTRAL_RUNS = {
    "Relation": (lambda: _vip_scan("Graphseo"), "claude"),
    "debate": (_debate, "gemini"),
    "Draft": (_draft, "claude"),
}


@pytest.mark.parametrize("job", NEUTRAL_RUNS)
def test_every_cli_runs_from_a_neutral_directory_fallback_included(monkeypatch, settings_override, job):
    """Issue #249: run from the project, the Claude CLI loaded its CLAUDE.md
    and git context. The Relation @Graphseo, debate and the Originals had no
    neutral cwd; now the CLI adapter picks it for every call."""
    from src.core import llm_client as llm

    run, primary = NEUTRAL_RUNS[job]
    popen = _FailingCli()
    monkeypatch.setattr(llm.subprocess, "Popen", popen)
    monkeypatch.setattr(llm.shutil, "which", lambda name: f"/usr/local/bin/{name}")
    settings_override(AI_CLI="gemini", REPLY_LLM_PROVIDER="gemini", PROFILE_LLM_PROVIDER="claude",
                      LLM_FALLBACK_CLI="codex",
                      LLM_FALLBACK_MODEL="", LLM_DISABLE_FALLBACK=False, CONTENT_LANG_PRIMARY="en")

    run()

    assert [(name, cwd) for name, cwd, _ in popen.started] == [(primary, str(llm.NEUTRAL_CWD)),
                                                              ("codex", str(llm.NEUTRAL_CWD))]
    neutral = llm.NEUTRAL_CWD.resolve()
    assert neutral.is_dir() and not neutral.is_relative_to(ROOT.resolve())
    assert _reached_instructions(neutral) == []
    # Outside a git repository, codex exec refuses to run without this flag.
    assert "--skip-git-repo-check" in popen.started[1][2]


def test_no_job_hands_a_cwd_to_the_model_call():
    """The CLI adapter alone picks the directory a provider runs from."""
    found = [f"{path.relative_to(ROOT)}:{number}"
             for package in ("replies", "editorial") for path in sorted((ROOT / "src" / package).glob("*.py"))
             for number, line in enumerate(path.read_text().splitlines(), 1) if re.search(r"\bcwd\b", line)]
    assert found == []

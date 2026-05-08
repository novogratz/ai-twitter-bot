# Contributing

This repo runs continuously in production. Changes affect a live X account. Read this before opening a PR.

---

## Ground rules

1. **Process safety > feature parity.** Every cycle must be wrapped in `safe_run_*` so a bug in one bot can't crash the scheduler. See [`docs/ARCHITECTURE.md#3-key-invariants`](docs/ARCHITECTURE.md#3-key-invariants).
2. **No double-posts.** Every reply / post path must lock the URL before publish, against a persistent dedup set.
3. **No metadata leaks.** Any tweet text must pass `humanizer.strip_agent_preamble` + `pattern_tags.extract_pattern` + `_scrub_metadata_leaks` before reaching `post_tweet`.
4. **Hard rules are non-negotiable.** Don't add bots that bypass `personality_store.HARD_RULES_BLOCK` or `respect_list.scrub_text_or_skip`.
5. **No `--no-verify` on commits.** Pre-commit hooks exist for a reason.

---

## Smoke test before pushing

```bash
python3 -c "import main"            # boot path imports cleanly
python3 -c "import src.<module>"    # for any module you touched
./bin/run.sh                        # boots through the AUTONOMY AUDIT block in <10s
```

If `./bin/run.sh` doesn't print the audit block within 10 seconds, something is wrong with imports or the scheduler.

---

## Code style

The codebase is intentionally pragmatic, not over-engineered. A few conventions:

- One bot = one module under `src/` exposing `run_<name>_cycle()` + `safe_run_<name>_cycle()`.
- Settings live in `src/config.py` or `.env`. Never hardcode magic numbers — use `int(os.environ.get("X", "default"))`.
- Persistent state goes in JSON at the repo root, named `<bot_name>_state.json` or `<bot_name>_history.json`.
- New bots that decide strategy must auto-push their state files via `git_ops.auto_push([...], "message")`.
- Comments only when the WHY is non-obvious. Don't restate WHAT the code does.
- No em dashes in user-facing copy (it's a brand consistency thing — see `humanizer.py`).

---

## Adding a bot

See [`docs/ARCHITECTURE.md#6-adding-a-new-bot`](docs/ARCHITECTURE.md#6-adding-a-new-bot).

---

## Documentation updates

If you change behaviour visible to operators or other contributors, also update:

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — module catalog
- [`docs/OPERATIONS.md`](docs/OPERATIONS.md) — runbook + state file table
- [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md) — env var reference
- [`README.md`](README.md) — top-level overview
- [`CLAUDE.md`](CLAUDE.md) + [`CODEX.md`](CODEX.md) — keep in sync

The pre-commit hook will warn if you change source code without touching the docs. Either update the docs or — if the change is genuinely doc-irrelevant — note it in the commit message.

---

## Commit message format

Free-form, but lean toward:

```
Short imperative subject (≤72 chars)

Optional body explaining WHY (not WHAT — diff shows what).
Wrap at ~72 chars. Reference issue numbers if any.

Co-Authored-By: <attribution lines>
```

Autonomous-agent commits use a fixed prefix: `Autonomous <agent> update — <summary>`. Keep them recognisable for log filtering.

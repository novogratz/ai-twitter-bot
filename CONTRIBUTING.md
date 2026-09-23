# Contributing

This repo runs continuously in production. Changes affect a live X account. Read this before opening a PR.

---

## Ground rules

1. **Read [`AGENTS.md`](AGENTS.md) first.** Its invariants (chokepoints own
   the rules, log only what shipped, callers never pre-mark a store the
   chokepoint checks) come from bugs that shipped live.
2. **The policy is a ceiling.** Raising volume, restoring a disabled surface
   or relaxing a check needs an operator request and an update to
   [`docs/EDITORIAL_POLICY.md`](docs/EDITORIAL_POLICY.md).
3. **Hard rules are non-negotiable.** Don't add a path that bypasses
   `personality_store.HARD_RULES_BLOCK` or the respect list.

---

## Check before pushing

```bash
uv run --with pytest --with-requirements requirements.txt python -m pytest tests/ -q
uv run --with-requirements requirements.txt python main.py --dry-run
```

Never use `./bin/run.sh` as a smoke test: it kills any running bot and starts
the real one on the live account.

---

## Code style

The codebase is intentionally pragmatic, not over-engineered. A few conventions:

- One job = one module under `src/` exposing `run_<name>_cycle()` + `safe_run_<name>_cycle()`, registered with `add()` in `main.py:build_scheduler()`.
- Settings live in `src/config.py` or `.env`. Never hardcode magic numbers — use `int(os.environ.get("X", "default"))`, read at call time when it gates a side effect.
- Persistent state goes in JSON at the repo root, named `<bot_name>_state.json` or `<bot_name>_history.json`.
- Comments only when the WHY is non-obvious. Don't restate WHAT the code does.
- No em dashes in user-facing copy (it's a brand consistency thing — see `humanizer.py`).

---

## Adding a job

See [`docs/ARCHITECTURE.md#adding-a-job`](docs/ARCHITECTURE.md#adding-a-job).

---

## Documentation updates

If you change behaviour visible to operators or other contributors, also update:

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — jobs table, editorial pipeline
- [`docs/OPERATIONS.md`](docs/OPERATIONS.md) — runbook + state file table
- [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md) — env var reference
- [`README.md`](README.md) — top-level overview
- [`AGENTS.md`](AGENTS.md) — agent context (`CLAUDE.md` imports it)

No hook enforces this: if a change is genuinely doc-irrelevant, say so in the commit message.

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

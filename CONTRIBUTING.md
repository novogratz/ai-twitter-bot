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
   `personality_store.hard_rules_block()` or the respect list.

---

## Check before pushing

Run the test suite and the dry-run from
[`AGENTS.md#verification`](AGENTS.md#verification). Never use `./bin/run.sh` as a smoke test: it kills any running bot and starts
the real one on the live account.

---

## Code style

The codebase is intentionally pragmatic, not over-engineered. A few conventions:

- One job = one module in a package under `src/` (`src/replies/`, `src/account/`…) exposing `run_<name>_cycle()` + `safe_run_<name>_cycle()`, registered with `add()` in `main.py:build_scheduler()`.
- Settings are declared in `src/core/settings.py`, with their type, default and bounds, and set in `.env`. Never hardcode magic numbers — declare the setting and read it with `settings.get("X")` inside the function that uses it, never into a module constant; the docstring of `settings.py` gives the pattern. No module reads `os.environ` itself. After adding or changing a declaration, regenerate `docs/CONFIGURATION.md` with `uv run python bin/configuration_doc.py --write`.
- What describes the Account, not the engine (its handle, the domain its prompts name, Slots, feeds, trusted hosts, relevance filter, network, niche, X searches, Relations), goes in `accounts/<name>/account.toml`, checked by `src/core/account.py`, and is read with `account.current()` inside the function; its Voice (`voice_fr.md`, `voice_en.md`) and its Relations' prompts (`relations/`) sit next to it. The engine names no account, in code or in a comment that carries neither a date nor an issue number: say "the Account's profile" or "a Relation" (`tests/test_engine_names_no_account.py`).
- A list the Operator curates (the follow whitelist, the respect list) is an Operator file in the Account folder, declared as an `account.OperatorFile`, which has no write. What the bot learns or counts beside it goes in a state file, never back into the Operator file.
- Persistent state goes in JSON under `state/<BOT_ACCOUNT>/`, named `<bot_name>_state.json` or `<bot_name>_history.json`, declared once as a `StateFile` in `src/core/state_store.py` terms: guarded when losing it lets the bot act more or drops an Operator list, disposable otherwise. A state file the store does not read or write (a log, a report) is declared as a `StatePath`; never build a state path by hand.
- Comments only when the WHY is non-obvious. Don't restate WHAT the code does.
- No em dashes in user-facing copy (it's a brand consistency thing — see `humanizer.py`).

---

## Adding a job

See [`docs/ARCHITECTURE.md#adding-a-job`](docs/ARCHITECTURE.md#adding-a-job).

---

## Documentation updates

Which files a behaviour change updates, and what each doc covers, is set in
[`AGENTS.md#documentation`](AGENTS.md#documentation). No hook enforces it: if
a change is genuinely doc-irrelevant, say so in the commit message.

---

## Commit message format

Free-form, but lean toward:

```
Short imperative subject (≤72 chars)

Optional body explaining WHY (not WHAT — diff shows what).
Wrap at ~72 chars. Reference issue numbers if any.

Co-Authored-By: <attribution lines>
```

Stage exact paths, never `git add -A`: the checkout holds live files, such
as `bot.log` and the state under `state/`, that stay out of every commit.
Never pass `--no-verify`.

Autonomous-agent commits use a fixed prefix: `Autonomous <agent> update — <summary>`. Keep them recognisable for log filtering.

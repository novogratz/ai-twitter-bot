# AGENTS.md

@TheAIShrink is a live X account driven by Safari + AppleScript from the
operator's Mac: no X API. Every change here can publish, like or follow on a
real account. Setup and run commands live in [`README.md`](README.md).

## Current policy — the ceiling you never lift

[`docs/EDITORIAL_POLICY.md`](docs/EDITORIAL_POLICY.md) is the source of truth
(2026-09-20) and supersedes every older mandate. It encodes:

- Active 04:30–22:00 America/Toronto only; nothing external happens overnight.
- Six sourced AI originals targeted a day, a seventh only in the exceptional
  slot; seven combined profile publications at most.
- Quotes, reposts, self-recycling, threads and startup bursts stay at zero.
- Replies are uncapped in waking hours, paced and deduplicated per tweet;
  debate turns are capped per engager per day.

A change that raises volume, restores a disabled surface or relaxes a check
needs an explicit operator request, and updates that policy file in the same
change. The same holds for the operator-owned guardrails: `core_identity.md`,
`BLOCKLIST` and the 48-hour `REPOST_MAX_AGE_HOURS` clamp in `src/config.py`,
`respect_list.json`, and `personality_store.HARD_RULES_BLOCK`.

## Active code

`main.py` is the whole scheduler: read `build_scheduler()` for the live jobs.
Modules none of those jobs reach are legacy, kept for reference.

| Concern | Where |
|---|---|
| Originals: sources, evidence, draft, separate review | `src/editorial_bot.py`, `src/editorial_schemas.py` |
| Toronto clock, bedtime checks | `src/active_hours.py` |
| Caps, pacing, write ledger, follow policy | `src/action_guard.py` |
| Replied store: one reply per tweet, keyed on status ID | `src/replied_store.py` |
| Hard ceilings that `.env` and `live_strategy.json` cannot lift | `src/config.py` |
| Pre-publish validation (price targets, dedup, truncation, violence) | `src/content_guard.py` |
| Every browser write (`post_tweet`, `reply_to_tweet`, `follow_account`…) | `src/twitter_client.py` |
| Voice, operator-managed | `core_identity.md` |

## Invariants

Each one is a bug that shipped live. The full incident stories are in
[`docs/HISTORY.md`](docs/HISTORY.md).

- **Chokepoints own the rules.** Enforce a rule inside the `twitter_client`
  write function, so every caller inherits it; a per-bot check leaves the
  other callers open.
- **Log only what shipped.** Write chokepoints return `True` only when the
  action happened. Callers log, count and consume a slot or candidate on
  `True` only.
- **Callers never pre-mark a store the chokepoint checks.** `reply_to_tweet`
  both checks and marks `replied_tweets.json`; a caller-side pre-mark makes
  it refuse its own caller.
- **Handles come from URLs.** The scraper's `author` field is the display
  name. Use `twitter_client.is_own_post` or the `/status/` URL, never
  `author == BOT_HANDLE`.
- **Side-effect switches are read at call time.** An env var gating a post,
  a subprocess or a network write is read inside the function, never as a
  module constant. `DRY_RUN` is read through `config.dry_run()`.
- **Keyboard shortcuts toggle.** A retweet keystroke on a retweeted post
  un-retweets it: know the state before pressing.
- **Trim with `humanizer.smart_trim`.** A bare `[:N]` slice on outgoing
  text once published a reply cut mid-word.
- **Fix the family.** When a bug ships, grep every surface for the same
  shape before closing it.

## Verification

```bash
uv run --with pytest --with-requirements requirements.txt python -m pytest tests/ -q
uv run --with-requirements requirements.txt python main.py --dry-run  # jobs + policy, no browser, no model
```

CI runs the same suite on every PR. `tests/conftest.py` walls tests off from
Safari, `bot.log` and production state files; patch browser primitives at the
`twitter_client` level, because function-local imports bypass mocks placed on
the caller's module. A guard change ships with a test pinning it.

## Live bot and state

- Start, stop and restart only on an explicit operator request
  (`./bin/run.sh`, `bin/stop_bot.sh`). Code and config take effect at restart.
- JSON files at the repo root are live state. `action_ledger.json` already
  counts toward today's ceiling: keep it across deploys, and leave unrelated
  state files out of your commits.
- An editorial slot in `pending` state was submitted ambiguously; it is never
  retried automatically. Check the profile before clearing it
  ([recovery](docs/OPERATIONS.md#recovery)).
- `.claude/skills/` (mirrored in `.codex/skills/`) predates the 2026-09-20 policy: several skills drive
  disabled surfaces (retweet, thread, counter reset). Read a skill against
  the policy before running it.

## Documentation

- [`CONTEXT.md`](CONTEXT.md): domain glossary. Use its terms in code, logs
  and docs, and update it when a term changes meaning.
- [`docs/EDITORIAL_POLICY.md`](docs/EDITORIAL_POLICY.md): current publishing
  rules, recovery, reach target.
- [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md): the top table is current;
  the rest documents legacy env vars.
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md): process, jobs, editorial
  pipeline, write path, known gaps. Trust `main.py` where they disagree.
- [`docs/OPERATIONS.md`](docs/OPERATIONS.md): start, stop, supervisors,
  recovery, state files.
- [`docs/HISTORY.md`](docs/HISTORY.md): dated mandates and incidents,
  June–September 2026.

`CLAUDE.md` imports this file; edit `AGENTS.md` only. A behaviour change
updates this file, `README.md` and the policy in the same commit; adding or
removing a job also updates the jobs table in `docs/ARCHITECTURE.md`, a new
env var goes in `docs/CONFIGURATION.md` and a new state file in the
`docs/OPERATIONS.md` table. The incident narrative goes to `docs/HISTORY.md`.

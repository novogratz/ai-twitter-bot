# AGENTS.md

@TheAIShrink is a live X account driven by Safari + AppleScript from the
operator's Mac: no X API. Every change here can publish, like or follow on a
real account. Setup and run commands live in [`README.md`](README.md).

## Current policy — the ceiling you never lift

[`docs/EDITORIAL_POLICY.md`](docs/EDITORIAL_POLICY.md) is the source of truth
(2026-09-23) and supersedes every older mandate. It encodes:

- Active 04:30–23:30 America/Toronto only; nothing external happens overnight.
- At least three sourced AI originals targeted a day, six planned, and eight
  combined profile publications at most, twenty minutes apart at least.
- Three trend slots (10:00, 13:00, 15:00) and a Startup post on every start
  in waking hours take their topic from rising AI posts on X, and their facts
  from a trusted article.
- Quotes, reposts, self-recycling and threads stay at zero.
- Replies are uncapped in waking hours, paced and deduplicated per tweet;
  debate turns are capped per engager per day.

A change that raises volume, restores a disabled surface or relaxes a check
needs an explicit operator request, and updates that policy file in the same
change. The same holds for the operator-owned guardrails: `core_identity.md`,
`BLOCKLIST` in `src/core/config.py`, the zero-repost rule,
`respect_list.json`, and `personality_store.hard_rules_block()`.

## Active code

`main.py` is the whole scheduler: read `build_scheduler()` for the live jobs.
Every module under `src/` is reached from `main.py`; a test fails on a module
nothing imports, so wire new code into a job or delete it. `src/core/` holds
the shared foundations (config, logger, LLM client, history and engagement
stores), `src/x/` the browser layer, `src/guards/` the clock, caps and
admission checks, `src/editorial/` the originals pipeline, `src/replies/` the
reply jobs, and `src/account/` the follow, like, pin and follower-count jobs.
The top level of `src/` holds only packages.

| Concern | Where |
|---|---|
| Account: handle, language, Slots and angles, feeds, Evergreen topics, trusted hosts, relevance filter, stricter limits | `accounts/<BOT_ACCOUNT>/account.toml`, loaded and checked at start by `src/core/account.py` |
| Originals: sources, evidence, draft, separate review, pending submissions in the ceiling and spacing | `src/editorial/editorial_bot.py` |
| Draft and review limits, their JSON schemas and call profiles | `src/editorial/editorial_schemas.py` |
| Model calls: provider adapters, the one fallback ladder (no fallback unless `LLM_FALLBACK_CLI` names one; an unknown provider fails the call and runs nothing), the CLI model a model setting gives the provider called, timeouts, the answer read once in the profile's text or JSON mode, call profile (the label only names the call in logs), status (answered, failed, provider exhausted) and the provider and model that answered | `src/core/llm_client.py` |
| Trending posts for Trend slots and the Startup post: Top search, filters, ranking, prompt blocks | `src/editorial/trending.py` |
| Reply jobs: direct, feed sweep, early bird, mega watch, debate, replyback, babysit, notify, search | `src/replies/` |
| Reply prompts: Voice, hard rules, dossier, language, SKIP, failure and rate-limit outcomes (provider exhausted) | `src/replies/reply_generator.py` |
| Reply pipeline: admission before generation, set-aside posts, rate-limit stop, spacing wait, write, log after ship with the provider and model that wrote the Reply | `src/replies/reply_pipeline.py` |
| Account jobs: engage, follow engagers, followback, likes, pin, follower count, tracked accounts | `src/account/` |
| Toronto clock, bedtime checks | `src/guards/active_hours.py` |
| Caps, pacing, anti-churn; the ledger facts the follow policy reads | `src/guards/action_guard.py` |
| Follow policy: handle, Blocked account, the account's relation it finds itself (Seed account, follower, Engager; a Stranger never), whitelist, caps, ceiling, quality gate, named Follow refusals, followed accounts and the other follow files | `src/guards/follow_policy.py` |
| Write ledger: today's counts, last write, last follow or unfollow; file and in-memory adapters | `src/guards/ledger.py` |
| Reply admission: Blocked account, own post, one Reply per post, Debate turn cap, spacing, final text, Respected account named | `src/guards/reply_admission.py` |
| Author, status ID and age read from a status URL; nested-reply filter for scraped tweets | `src/x/x_urls.py` |
| Replied store: one reply per tweet, keyed on status ID | `src/guards/replied_store.py` |
| JSON state files: one root, atomic writes, guarded or disposable | `src/core/state_store.py` |
| Engine settings: each `.env` key declared once with type, default, floor or ceiling; `.env` read once at start, an unknown or badly typed key stops it; the `settings_override` fixture's overrides | `src/core/settings.py` |
| Settings served under their old names and read on every access, side-effect switches as functions; fixed ceilings and `BLOCKLIST` that `.env` cannot touch | `src/core/config.py` |
| Pre-publish validation (price targets, dedup, truncation, violence) | `src/guards/content_guard.py` |
| Every browser write (`post_tweet`, `reply_to_tweet`, `follow_account`…) | `src/x/twitter_client.py` |
| The sequence every write runs: dry run, Safari lock, ledger rows only on a shipped Write outcome, tab close | `src/x/confirmed_write.py` |
| Reading X pages: feeds, search, profiles, mentions, blank-page recovery | `src/x/scraper.py` |
| Safari lock, AppleScript, page opening (`open_url`, never `webbrowser`), paste, tab and scroll primitives | `src/x/safari.py` |
| Voice, operator-managed: the one persona every prompt carries, rendered by `personality_store.render_voice` | `core_identity.md`, `core_identity_en.md` |

## Invariants

Each one is a bug that shipped live. The full incident stories are in
[`docs/HISTORY.md`](docs/HISTORY.md).

- **Chokepoints own the rules.** Enforce a rule inside the `twitter_client`
  write function, so every caller inherits it; a per-bot check leaves the
  other callers open. A reply job hands its candidates to the Reply
  pipeline, which asks `reply_admission.judge_parent` before generating;
  the job never copies a rule.
- **Log only what shipped.** Write chokepoints run through
  `confirmed_write.run` and return a `WriteOutcome`, truthy only for
  `SHIPPED`. Callers log, count and consume a slot or candidate on a truthy
  result only. A failed AppleScript step is not a shipped action: it returns
  `FAILED` or `UNCONFIRMED` and writes no ledger row. Neither is a dry run:
  it writes a dry-run ledger row and returns the falsy `DRY_RUN`.
  `like_tweet` returns a `LikeOutcome`, truthy only for `LIKED`, with the
  same `FAILED`, `UNCONFIRMED` and `DRY_RUN`.
- **Callers never pre-mark a store the chokepoint checks.** `reply_to_tweet`
  both checks and marks `replied_tweets.json`; a caller-side pre-mark makes
  it refuse its own caller.
- **Handles come from URLs.** The scraper's `author` field is the display
  name. Use `x_urls.author` on the `/status/` URL, or
  `scraper.is_own_post` on a scraped tweet, never
  `author == BOT_HANDLE`.
- **Side-effect switches are read at call time.** An env var gating a post,
  a subprocess or a network write is read inside the function, never as a
  module constant. `DRY_RUN` is read through `config.dry_run()`.
- **Keyboard shortcuts toggle.** A retweet keystroke on a retweeted post
  un-retweets it: know the state before pressing. A shortcut also acts on
  X's own selection, not on the post you read: likes click the `like`
  button of an article found by status ID instead.
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
Safari, `bot.log` and production state files. Patch a name where it is looked
up: browser primitives in `src/x/safari.py`, and a scrape or write in its
defining module (`src/x/scraper.py`, `src/x/twitter_client.py`) when the
caller imports it inside a function, but on the caller when it imports it at
module level. A guard change ships with a test pinning it. Tests mirror
`src/`: a test goes under `tests/<package>/`, with the module that owns the
rule; cross-cutting invariants stay at the root of `tests/`.

## Live bot and state

- Start, stop and restart only on an explicit operator request
  (`./bin/run.sh`, `bin/stop_bot.sh`). Code and config take effect at restart.
- JSON files at the repo root are live state, ignored by git: a new state
  file goes in `.gitignore` in the same change, and a test fails on one git
  does not ignore. The Operator's files stay tracked: `respect_list.json`,
  `whitelist.json` and `core_identity*.md`. `action_ledger.json` already
  counts toward today's ceiling and git holds no copy of it: keep it across
  deploys. It holds one JSON object per line, not a JSON list: read it line
  by line or through `action_guard`.
- A JSON state file goes through `state_store.StateFile`, declared once with
  its policy. An unreadable guarded file stops the job that needs it and is
  never overwritten: repair it by hand, never delete it
  ([recovery](docs/OPERATIONS.md#recovery)).
- An editorial slot in `pending` state was submitted ambiguously; it is never
  retried automatically, and it counts toward today's ceiling and the post
  spacing until cleared. Check the profile before clearing it
  ([recovery](docs/OPERATIONS.md#recovery)).
- `.claude/skills/` is the one skills source and matches the 2026-09-20
  policy. `.codex/skills` is a relative symlink to it; OpenCode reads
  `.claude/skills` natively. Edit skills there only, and delete a skill
  rather than let it drive a disabled surface. Skills that write to X or
  start, stop or restart the bot run on an explicit operator request only,
  and say so in their body: their `disable-model-invocation: true`
  frontmatter stops only Claude Code from invoking them on its own. Codex
  ignores it, and other harnesses may too.

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

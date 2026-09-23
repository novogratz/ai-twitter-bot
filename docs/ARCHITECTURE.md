# Architecture

How the running bot is built, as of the 2026-09-20 policy (PR #97). The rules
it enforces are in [EDITORIAL_POLICY.md](EDITORIAL_POLICY.md); how to run and
debug it is in [OPERATIONS.md](OPERATIONS.md). `main.py` is the source of truth
for what runs: where this page and the code disagree, trust the code.

The pre-September system (~30 bots, quotes, reposts, self-modifying agents) is
described in [HISTORY.md](HISTORY.md) and in this file's git history before
commit `e7b4d47`.

## Process

One Python process drives Safari through AppleScript and injected JavaScript.
There is no X API client.

`main.py` builds an APScheduler `BackgroundScheduler` with two thread pools:
`editorial` (one thread, originals only) and `default` (twelve threads, every
other job). Reply scans cannot starve the editorial job of a thread, but all
browser work shares `_safari_lock`, so a post can still wait behind a reply.
Every job is an `IntervalTrigger` registered through the local `add()` helper,
which wraps it in `active_hours.awake_job`. There are no cron triggers, no
startup bursts and no warmup phase.

At start, `main()`:

1. takes `bot.lock` with `fcntl.flock` and exits if another instance holds it;
2. installs SIGTERM/SIGINT handlers that call `active_hours.request_stop()`;
3. starts the scheduler paused, then checks `is_active()` every 15 seconds and
   pauses or resumes it at the 04:30 and 22:00 boundaries.

Flags: `--post-only` (editorial job only), `--reply-only` (conversation jobs
only), `--dry-run` (prints timezone, slots and job ids as JSON, then exits
before touching the browser or a model).

## Waking hours

`src/active_hours.py` owns the clock: 04:30 ≤ Toronto time < 22:00, DST
handled by `zoneinfo`. `require_active()` raises `OutsideActiveHours` outside
that window or once a stop was requested; `awake_job()` turns a job into a
no-op in the same cases (`may_act()`), and a job already running halts at its
next `require_active()`. `is_active()` reads the clock only: the scheduler's
pause/resume loop must not treat a stop as a wake-up boundary.

Pausing the scheduler is not enough, because a job queued at 21:59 would still
run. The check is repeated at each point where work leaves the process:

- `twitter_client._AwakeSafariLock`, before and after acquiring the Safari lock;
- `twitter_client._run_applescript` and each direct `osascript` call inside
  `twitter_client`, and in `like_bot`'s like clicks. The read-only
  `osascript` calls in `followback_bot`, `follower_tracker_bot` and
  `safari_hygiene` are only covered by the lock check or by `awake_job`;
- `llm_client.run_llm`, `_run_cmd` and `_run_ollama_http`, whose timeout is
  also capped at the time left before 22:00;
- `action_guard.can_post`, which also refuses once a stop was requested, and
  `editorial_bot` before fetching a source and again before publishing.

A request already sent to X or to a model can finish after 22:00; it cannot
authorize a new action.

## Jobs

`build_scheduler()` registers 17 jobs, plus `reply_job` when
`ENABLE_REPLY_SEARCH=1`. Each `safe_run_*` entry point catches its own
exceptions; all but the editorial and reach-report jobs also report to
`health`.

| Job | Every | What the cycle does today |
|---|---|---|
| `editorial_job` | 10 min | Publishes the due original, if any. See [Editorial pipeline](#editorial-pipeline). |
| `direct_reply_job` | 2 min | Scans the `VIP_SCAN_HANDLES` accounts, then a rotating slice of `DIRECT_REPLY_QUERIES_PER_CYCLE` search queries, and replies. Generation of reply N+1 overlaps the posting of reply N. |
| `feed_sweep_job` | 8 min | Reads For You and Following and replies to every on-niche post. |
| `early_bird_job` | 5 min | Replies to fresh posts from `ALWAYS_REPLY_ACCOUNTS` and the tracked-account list. |
| `mega_watch_job` | 2 min | Replies to posts under four minutes old from the top tracked handles. |
| `replyback_job` | 3 min | Replies under our latest post to people who answered it (debate turns, cap shared with `debate_job`), then visits and likes up to 5 of their profiles. It never follows: `follow_engagers_job` owns engager follows. |
| `babysit_job` | 5 min | Runs an extra replyback cycle while our latest post is under an hour old. |
| `debate_job` | 12 min | Answers fresh mentions, at most 4 debate turns per author per Toronto day, counted by `reply_to_tweet` and shared with `replyback_job` and `babysit_job`. |
| `notify_job` | 20 min | Likes replies under our latest post. It no longer self-retweets. |
| `engage_job` | 8 min | Tries to follow a handful of accounts and likes their posts when profile visits are allowed. |
| `followback_job` | 20 min | Follows back recent followers (`reciprocal=True`). |
| `follow_engagers_job` | 50 min | Follows Engagers: the authors of the ledger's debate turns, then the frozen `replied_back.json` (until about 2026-12-22). |
| `like_job` | 4 min | Likes posts from niche searches. |
| `pin_job` | 60 min | Once a day, pins our best recent post if it beats the current pin. |
| `session_refresh_job` | 120 min | Quits and relaunches Safari to clear a stale x.com session. |
| `follower_tracker_job` | 30 min | Records the follower count in `follower_history.json`. |
| `reach_report_job` | 60 min | Writes `editorial_reach.json` and `.md`. See [Reach report](#reach-report). |

Two settings decide how much of the table does anything:

- `PROFILE_VISIT_ALLOWLIST` (default `TheBTCTherapist,Graphseo`). Profile
  scrapes and profile likes return nothing for other handles, so
  `early_bird_job`, `mega_watch_job`, the like step of `engage_job` and the
  replyback profile likes only act on allowlisted accounts.
- The follow policy in `action_guard.can_follow`. With the code defaults, the
  whitelist and the following ceiling refuse most follows; the live `.env`
  decides what actually passes.

## Editorial pipeline

`src/editorial_bot.py` runs one slot at a time under a non-blocking lock.

1. **Slot.** `SLOTS` lists 05:00, 08:00, 11:30, 14:30, 17:30, 20:30 and an
   optional 21:30. A slot is due for 45 minutes, never past 22:00, and only if
   `editorial_state.json` has no entry for it. A missed slot is not caught up.
2. **Attempts.** Three per slot per day, restarts included. An attempt is a
   draft submitted to review: the counter is saved once a draft exists and
   before review. A pass with no source, a draft model error or an explicit
   skip spends none; the 45-minute window bounds those passes.
3. **Sources.** Six first-party feeds (OpenAI, Google AI, DeepMind, Hugging
   Face, NVIDIA, Microsoft Research) supply AI news under 48 hours old; the
   three newest are kept. Twelve Hugging Face documentation pages rotate daily
   as evergreen topics. URLs used in the last seven days are skipped. Each page
   is fetched over HTTPS from an allowed host, 12-second timeout, 1 MB read.
4. **Draft.** The model sees `core_identity.md`, the hard rules, the slot
   brief, the last rejection reason for this slot, recent posts and numbered
   evidence sentences from each source. It returns JSON matching
   `editorial_schemas.DRAFT_SCHEMA`, or an explicit skip.
5. **Review.** Deterministic checks first: 80–250 characters, trusted source,
   angle and takeaway present, no bait phrasing, URL, hashtag or brackets,
   1–3 evidence ids that resolve to sentences found in the source text, then
   `content_guard.validate` and `is_duplicate`. The 21:30 slot needs news under
   six hours old. A second model call (`REVIEW_SCHEMA`) must approve all six
   criteria, plus `exceptional` at 21:30.
6. **Audit.** An attempt that reaches review appends a line to
   `editorial_review.jsonl`; a rejection stores its reason as feedback for the
   next attempt. Nothing is written when `can_post` refuses (spacing or
   ceiling), when the three attempts are spent, or when the pass yields no
   draft.
7. **Publish.** Waking hours and slot validity are checked again. The slot is
   marked `pending` and saved, then `post_tweet(text, editorial=True)` sends
   the draft plus the source URL. `True` marks it `published`; `False` frees
   the slot; an exception leaves it `pending`, which is never retried
   automatically. With `DRY_RUN` set, the text is logged and nothing is marked.

`editorial=True` skips the URL stripping and the random casualization other
posts get, so the reviewed text ships unchanged. `post_tweet` checks
`can_post(POST)` again under the Safari lock.

Models: drafts and reviews go through `run_llm` with
`force_provider=PROFILE_LLM_PROVIDER`. On Ollama, `EDITORIAL*` labels use
`EDITORIAL_OLLAMA_MODEL` (default `gemma4:31b`) with the JSON schema as
`format`, and a timeout of `EDITORIAL_LLM_TIMEOUT_SECONDS` (300) capped by
bedtime. When Ollama fails, `llm_client` falls back to `LLM_FALLBACK_CLI`,
which defaults to codex even when the variable is empty. `LLM_DISABLE_FALLBACK=1`
turns the fallback off.

## Write path and limits

Every write that should count goes through a function in
`src/twitter_client.py`: `post_tweet`, `reply_to_tweet`,
`reply_to_tweet_in_thread`, `follow_account`, `like_tweet`. `post_tweet`,
the reply functions and `follow_account` return `True` when they submitted the
action, `False` when a rule refused it or an AppleScript step failed, and
callers log or count only on `True`. No ledger row is written on `False`.
Under `DRY_RUN` these functions write a dry-run ledger row and return
`DRY_RUN_RECORDED`, which is falsy: a caller that persists on a truthy
result persists nothing after a dry run, and one that must tell a dry run
from a refusal compares with `is` (`follow_engagers_bot`). One limit:
`True` means `osascript` ran the keystrokes, not that X confirmed them.
`like_tweet` returns nothing.

Three modules sit behind them:

- `src/config.py` holds the ceilings that neither `.env` nor
  `live_strategy.json` can lift: seven profile publications a day, quote and
  repost caps at 0, originals capped at 7 and spaced by at least 3600 seconds,
  replies uncapped, repost age clamped to 48 hours. `get_live_cap` returns
  these fixed values whatever `live_strategy.json` says.
- `src/action_guard.py` keeps `action_ledger.json` (90 days, Toronto
  timestamps) and decides `can_post`, `can_follow` and `can_unfollow`. A
  corrupt ledger refuses the write. Quotes and retweets are always refused;
  replies only need their spacing (`MIN_SECONDS_BETWEEN_REPLIES` plus jitter).
  No active job calls `unfollow_account`, and `MAX_UNFOLLOWS_PER_DAY`
  defaults to 0.
- `src/content_guard.py` validates text before publication: near-term price
  targets, duplicates, truncation, violence, skip rationales.

`reply_to_tweet` takes every rule from `src/reply_admission.py` (Reply
admission, CONTEXT.md). `judge_parent(url)` judges the post alone: author
handle from the URL (`src/x_urls.py`), Blocked account, own post, already
answered, Waking hours, Debate turn cap. `judge_reply(url, draft)` replays
those rules, adds the reply spacing, then builds the exact text that ships
(dashes, `smart_trim`, `casualize`, FR-forced language check, typo) and
validates it last. `reply_to_tweet` calls `judge_reply` once under the
Safari lock, the lock that also records the reply, so the spacing and the
Debate turn cap cannot move between the check and the write. Each refusal
says whether it is definitive for the post or temporary. Neither judgement
writes anything.

The six reply jobs (`direct_reply`, `feed_sweep`, `early_bird`,
`mega_watch`, `debate`, `replyback`) call `judge_parent` before paying for
a generation. `StateUnreadable` passes through their per-query and
per-reply `except Exception` blocks, so an unreadable state file ends the
cycle. They keep only their own selection filters: niche, age
threshold, thread-reply shape, handle pools, per-cycle caps. Each keeps a
module-level `_skipped` set, lost at restart, of posts refused definitively,
declined by the model (SKIP) or answered. A temporary refusal or a failed
model call leaves the post replayable.

After admission, `reply_to_tweet` deduplicates through
`src/replied_store.py`. `claim` re-reads `replied_tweets.json`, refuses a
tweet already answered, and marks it just before writing, all under one lock.
A dry run stops before the claim and writes only a dry-run ledger row.
The store is keyed on status ID, written through a temp file and
`os.replace`, and fails closed like the ledger: an unreadable file raises
instead of reading as empty. If the reply keystroke or the paste fails, or a
stop or 22:00 interrupts the sequence before the submit keystroke, nothing
was sent: `replied_store.release` removes the claim. If the submit keystroke fails,
the outcome is unknown: the claim stays, so the tweet never gets a second
reply.

`personality_store.hard_rules_block()` renders the hard rules and the respect
list from `respect_list.json`. The editorial prompt, the replyback prompt and
`direct_reply._generate_single_reply` (shared by the search, feed-sweep,
early-bird and mega-watch replies) include it; the debate prompt and the VIP generators do
not (see [Known gaps](#known-gaps)). No chokepoint applies the respect list to
outgoing text.

## Reach report

`src/reach_report.py` matches the originals recorded in
`editorial_state.json` over the last seven days against a scrape of our own
profile, sums their public view counts and compares the total with the
500,000-view target. It reports missing coverage and never claims
home-timeline attribution. It does not influence any cap.

## Known gaps

These are how the code behaves today, not design intent:

- `like_job`, `notify_job` and `pin_job` click in Safari without going
  through a chokepoint: no ledger entry and no `can_post`. `DRY_RUN` stops
  them without a dry-run ledger row; `pin_job` still spends its daily pin
  attempt.
  `notify_job` presses the `l` key, which toggles a like.
- `follow_engagers_bot`, `like_bot` and `pin_bot` key their
  daily counters on `date.today()` (machine time), while the ledger uses the
  Toronto day.
- `session_refresh_job` and the `health` recovery restart Safari without
  taking `_safari_lock`. The job has no waking-hours check of its own; it only
  runs while the scheduler is awake.
- `debate_bot` (`DEBATE_PROMPT`) and the VIP generators in `direct_reply`
  (`generate_vip_reply`, `_generate_graphseo_reply`) build prompts without the
  hard rules or the respect list.
- `babysit_job` and `replyback_job` call the same `run_replyback_cycle` and
  can overlap.

## Legacy modules

Most files in `src/` are not reached by any scheduled job: the quote, repost,
thread, boost, signal, self-modification and analytics bots. They stay for
reference and because `tests/test_guards.py` still pins their guards. A
module is live only if a job in `build_scheduler()` reaches it.

## Adding a job

1. Expose `safe_run_<name>_cycle()` in `src/<name>.py`. Catch every exception
   inside it and call `health.record_success` or `record_failure`.
2. Register it in `build_scheduler()` with `add(fn, minutes, "<name>_job")`.
   Never call `scheduler.add_job` directly: `add()` supplies the waking-hours
   wrapper.
3. Take `_safari_lock` for any browser work and close the tab you opened.
4. Write only through the `twitter_client` chokepoints; add a new rule inside
   the chokepoint, not in the job.
5. Key daily counters on the Toronto day (`active_hours.now_local()`).
6. Pin the new behaviour with a test. A job that publishes more, or revives a
   disabled surface, also needs an operator request and an update to
   [EDITORIAL_POLICY.md](EDITORIAL_POLICY.md).

## Tests

`tests/test_editorial.py` covers the current policy: Toronto and DST
boundaries, bedtime checks at the lock and before AppleScript, the daily
budget, slot timing and retries, source evidence, review rejection, ambiguous
submissions, dry-run isolation and reach accounting. `tests/test_guards.py`
pins the chokepoint guards, including those of legacy modules.
`tests/test_imports.py` reads `main.py` and every file under `src/`, `bin/`,
`scripts/` and `tests/`, subfolders included, with `ast`. It fails when an
intra-project import, function-local or inside `try/except` included, names a
missing module or an undefined name, imports a module under `src/` by its bare
name instead of through its package, or crosses a package folder without
`__init__.py`. `tests/test_disabled_surfaces.py` fails when a module that
`main.py` reaches through imports names a quote, repost or thread write;
only `twitter_client`, which defines them, is exempt.

`tests/conftest.py` walls tests off from production: `webbrowser.open`,
`_run_applescript` and `_paste_text` raise, the logger writes to a temporary
file, and the engagement log, tweet history, replied store, ledger and
personality file point to `tmp_path`. A mock placed on a caller module misses
function-local imports; patch the primitive in `twitter_client`.

CI (`.github/workflows/ci.yml`) runs `python -m pytest tests/ -q` on Python
3.12 with only `pytest` and `apscheduler` installed, on every pull request and
every push to `main`.

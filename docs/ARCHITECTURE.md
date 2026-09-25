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
which wraps it in `active_hours.awake_job`. There are no cron triggers and
no warmup phase. The Startup post is not a job: `main()` opens its window and
`editorial_job` publishes it.

At start, `main()`:

1. takes `bot.lock` with `fcntl.flock` and exits if another instance holds it;
2. installs SIGTERM/SIGINT handlers that call `active_hours.request_stop()`;
3. opens the Startup post window (`editorial_bot.open_startup_window`) unless
   `--reply-only`;
4. starts the scheduler paused, then checks `is_active()` every 15 seconds and
   pauses or resumes it at the 04:30 and 23:30 boundaries.

Flags: `--post-only` (editorial job only), `--reply-only` (conversation jobs
only), `--dry-run` (prints timezone, slots and job ids as JSON, then exits
before touching the browser or a model).

## Waking hours

`src/guards/active_hours.py` owns the clock: 04:30 ≤ Toronto time < 23:30, DST
handled by `zoneinfo`. The bounds are the `WAKE` and `BEDTIME` constants;
`window_label()` renders them for messages. `require_active()` raises `OutsideActiveHours` outside
that window or once a stop was requested; `awake_job()` turns a job into a
no-op in the same cases (`may_act()`), and a job already running halts at its
next `require_active()`. `is_active()` reads the clock only: the scheduler's
pause/resume loop must not treat a stop as a wake-up boundary.

Pausing the scheduler is not enough, because a job queued at 23:29 would still
run. The check is repeated at each point where work leaves the process:

- `safari._AwakeSafariLock`, before and after acquiring the Safari lock;
- `safari._run_applescript` and `safari._run_js`, through which every page
  JavaScript runs. A caller that falls back on an unparsable answer still
  lets `OutsideActiveHours` through, and `health.record_failure` does not
  count it toward a Safari restart;
- `safari_hygiene.restart_safari`, so its direct `osascript` quit and the
  relaunch never run outside waking hours;
- `llm_client.run_llm`, `_run_cmd` and `_run_ollama_http`; `llm_client._timeout`
  also caps every model call's timeout at the time left before 23:30;
- `action_guard.can_post`, which also refuses once a stop was requested, and
  `editorial_bot` before fetching a source and again before publishing.

A request already sent to X or to a model can finish after 23:30; it cannot
authorize a new action.

## Jobs

`build_scheduler()` registers 17 jobs, plus `reply_job` when
`ENABLE_REPLY_SEARCH=1`. Each `safe_run_*` entry point catches its own
exceptions; all but the editorial and reach-report jobs also report to
`health`. The reply jobs live in `src/replies/`; `engage_job`,
`followback_job`, `follow_engagers_job`, `like_job`, `pin_job` and
`follower_tracker_job` in `src/account/`; `editorial_job` and
`reach_report_job` in `src/editorial/`; `session_refresh_job` in
`src/x/safari_hygiene.py`.

| Job | Every | What the cycle does today |
|---|---|---|
| `editorial_job` | 10 min | Publishes the due original, if any. See [Editorial pipeline](#editorial-pipeline). |
| `direct_reply_job` | 2 min | Scans the `VIP_SCAN_HANDLES` accounts, then a rotating slice of `DIRECT_REPLY_QUERIES_PER_CYCLE` search queries, and replies up to `DIRECT_REPLY_MAX_PER_CYCLE` times. Generation of reply N+1 overlaps the posting of reply N; reply N+1 then waits out the reply spacing before `reply_to_tweet`. |
| `feed_sweep_job` | 8 min | Reads For You and Following and replies to every on-niche post, pipelined like the `direct_reply_job` search lane. |
| `early_bird_job` | 5 min | Replies to fresh posts from the Account's always-reply accounts (`vip_reply`, then the lists after it in `[network]`) and the tracked-account list. |
| `mega_watch_job` | 2 min | Replies to posts under four minutes old from the top tracked handles. |
| `replyback_job` | 3 min | Replies under our latest post to people who answered it (debate turns, cap shared with `debate_job`), then visits and likes up to 5 of their profiles. It never follows: `follow_engagers_job` owns engager follows. |
| `babysit_job` | 5 min | Runs an extra replyback cycle while our latest post is under an hour old. |
| `debate_job` | 12 min | Answers fresh mentions, at most 4 debate turns per author per Toronto day, counted by `reply_to_tweet` and shared with `replyback_job` and `babysit_job`. |
| `notify_job` | 20 min | Likes replies under our latest post. It no longer self-retweets. |
| `engage_job` | 8 min | Tries to follow the Seed accounts among a handful of pool accounts, and likes the posts of each when profile visits are allowed. The pool comes from the feeds; its followers and Engagers are left to `followback_job` and `follow_engagers_job`. |
| `followback_job` | 20 min | Scrapes the account link of each user cell in the primary column of our followers page, nothing when the tab shows another page, records the real-looking handles in `followers_seen.json`, and follows back the ones missing from the followed accounts; a too-soon or cap-reached refusal ends the cycle. |
| `follow_engagers_job` | 50 min | Follows Engagers through a Follow run: the authors of the ledger's debate turns, then the frozen `replied_back.json` (until about 2026-12-22), less the followed accounts. A too-soon or cap-reached refusal ends the cycle and keeps the Engager for later; a pick that raised keeps it too, counts in the per-cycle bound and fails the cycle for the health watchdog; any other outcome marks it tried. |
| `like_job` | 4 min | Likes posts from one of the Account's `searches.likes`. |
| `pin_job` | 60 min | Once a day, pins our best recent post if it beats the current pin. |
| `session_refresh_job` | 120 min | Quits and relaunches Safari to clear a stale x.com session. |
| `follower_tracker_job` | 30 min | Records the follower count in `follower_history.json`. |
| `reach_report_job` | 60 min | Writes `editorial_reach.json` and `.md`. See [Reach report](#reach-report). |

Two settings decide how much of the table does anything:

- `PROFILE_VISIT_ALLOWLIST` (the Account's `network.profile_visits` unless
  `.env` sets it: `TheBTCTherapist,Graphseo` for @TheAIShrink). Profile
  scrapes and profile likes return nothing for other handles, so
  `early_bird_job`, `mega_watch_job`, the like step of `engage_job` and the
  replyback profile likes only act on allowlisted accounts.
- The follow policy in `follow_policy.judge`. With the code defaults, the
  whitelist and the following ceiling refuse most follows; the live `.env`
  decides what actually passes. A following count that cannot be read
  (`following_count.json`, else `followed_accounts.json`) or a missing or
  unreadable whitelist (the Account's `whitelist.json`, or
  `whitelist_discovered.json`) refuses every follow and stops `bin/mass_unfollow.py`.
  With `FOLLOW_ENFORCE_RATIO` on, an unknown follower count
  (`follower_history.json` empty or unreadable) refuses every follow.

## Editorial pipeline

`src/editorial/editorial_bot.py` runs one slot at a time under a non-blocking
lock. The Slots, feeds, Evergreen topics, trusted hosts and relevance filter
are the Account's: `accounts/<BOT_ACCOUNT>/account.toml`, loaded and checked
at start by `src/core/account.py` and read at each call. The reply, like and
follow jobs read the same way the Account's `[network]` handle lists,
`[niche]` patterns and `[searches]` queries.

The day's editorial state belongs to the Slot journal,
`src/editorial/slot_journal.py`: the day change, Attempts and feedback,
the Pending slot reserved, confirmed or released, the closed Slots, the used
source URLs, the recent texts, the day's submissions and the latest one.
`FileJournal` keeps `editorial_state.json` (guarded, same format as
before); `MemoryJournal` holds it in memory for tests. Each pass reads the
file once, keeps the state in memory and saves it whole at each change; a
new Toronto day is saved with the pass's first change.

1. **Slot.** The `slots` of `account.toml` list 05:00, 07:15, 09:30, 10:00,
   11:45, 13:00, 14:00, 15:00, 16:15, 18:30 and an optional 20:45, the
   exceptional one; those with `trend = true` are 10:00, 13:00 and 15:00. A slot is due for 45 minutes, never past `BEDTIME`, only if
   the Slot journal has not closed it today and its attempts are not spent.
   A missed slot is not caught up. The Startup post, keyed `startup@HH:MM:SS`
   by the process start time, is a trend slot due for 45 minutes after
   `open_startup_window()`, which opens nothing outside waking hours. Each
   pass tries the Startup post first, then every open grid Slot in order
   (09:30 and 10:00 overlap), and moves on while a slot yields no draft; the
   first draft ends the pass, so a pass submits once at most. Before any of
   it, the pass stops when `can_post` refuses or when the pending
   submissions forbid another (see Publish).
2. **Attempts.** Three per slot per day, restarts included. An attempt is a
   draft submitted to review: the counter is saved once a draft exists and
   before review. A pass with no source, a draft model error or an explicit
   skip spends none; the 45-minute window bounds those passes.
3. **Trend.** For a trend slot, `collect_trending_posts`
   (`src/editorial/trending.py`) runs the Account's `[searches] trending`
   queries in the Top tab
   (`TREND_SEARCH_TWEETS` posts each, `text_limit=TREND_TEXT_LIMIT`),
   keeps posts under 24 hours old by status ID, drops own posts
   (`scraper.is_own_post`), Blocked accounts, nested replies, off-topic and
   crypto posts, strips handles, mentions and links, with or without a
   scheme (`t.co/x`, `site.com/page`), and keeps the five with the most
   likes per minute. A
   usable result is cached for the slot's retries; fewer than three posts
   skips the pass without spending an attempt. Trend slots get news sources
   only, never evergreen documentation.
4. **Sources.** Ten trusted feeds (OpenAI, Google AI, DeepMind, Hugging Face,
   NVIDIA, Microsoft Research, Mistral AI, Replicate, The Decoder and arXiv
   cs.AI) supply AI news/articles under 48 hours old; the eight newest are
   tried before evergreen. Twelve Hugging Face documentation pages rotate daily
   as backup teaching topics. URLs used in the last seven days are skipped.
   Each page is fetched over HTTPS from a host of the Account's
   `trusted_hosts`, 12-second timeout, 1 MB read. A news title must match the
   Account's `relevance.topic`.
5. **Draft.** The model sees the Voice (the Account's `voice_en.md`), the hard rules, the slot
   brief, the last rejection reason for this slot, recent posts, numbered
   evidence sentences from each source and, for a trend slot, the trending
   posts as untrusted data that choose the topic. Recent posts include the
   text of every pending submission, which may be live; the review sees the
   same list. It returns JSON matching
   `editorial_schemas.draft_schema()`, or an explicit skip.
6. **Review.** Deterministic checks first: 80–250 characters, trusted source,
   angle and takeaway present, no bait phrasing, URL, hashtag or brackets,
   1–3 evidence ids that resolve to sentences found in the source text, then
   `content_guard.validate` and `is_duplicate`. The 20:45 slot needs news under
   twelve hours old or a useful AI teaching source. A second model call
   (`review_schema()`) must approve all six criteria, plus `exceptional` at
   20:45 and `trending` for a trend slot, which also needs a news source and
   no `@`.

   Four of these limits live once, in `editorial_schemas`: the 250-character
   ceiling (`TEXT_MAX_CHARS`), the 40 numbered evidence sentences per source
   (`EVIDENCE_PASSAGES`), the 3 evidence ids (`EVIDENCE_IDS_MAX`) and the
   review's boolean fields (`APPROVAL_FLAGS`, `EXCEPTIONAL_FLAG`,
   `TREND_FLAG`). The schemas, the draft and review prompts and the
   deterministic checks read them at call time. The 80-character floor and
   the evidence sentence filter (35–700 characters, at least five words)
   stay in `editorial_bot`, the only module that reads them.
7. **Audit.** An attempt that reaches review appends a line to
   `editorial_review.jsonl`; a rejection stores its reason as feedback for the
   next attempt. Nothing is written when `can_post` or the pending check
   refuses (spacing or ceiling), when the three attempts are spent, or when
   the pass yields no draft.
8. **Publish.** Waking hours and the slot's window are checked again, then
   the pending check: an `UNCONFIRMED` submission writes no ledger row, so
   `can_post` cannot see it. Today's pending submissions (in `slots` or in
   `pending_sources`), plus the published count (the ledger's, or today's
   `published` slots when the operator marked more after a check), must stay
   under the ceiling, and the newest pending or published timestamp must be
   `MIN_SECONDS_BETWEEN_POSTS` plus `POST_JITTER_SECONDS` old. A pending
   submission counts until the operator clears it. The Slot journal
   reserves the slot: marked `pending` and saved with its source URL, text
   and time in `pending_sources`. Then `post_tweet(text)` sends
   the draft plus the source URL. `SHIPPED` confirms it `published`. `REFUSED`,
   `FAILED` and `DRY_RUN` sent nothing and release the slot. `UNCONFIRMED` (the
   submit keystroke failed, so the post may be live), any other result and an
   exception leave it `pending`, which is never retried automatically. With
   `DRY_RUN` set, the text is logged and nothing is marked.

`post_tweet` strips no URL and does not casualize, so the source link and
the reviewed wording reach X. `_scrub_metadata_leaks` still runs first: it
removes leaked model output (tool-call markup, bracketed metadata tags,
series headers, echoed prompt lines) and hashtags, a trailing run whole and
the `#` of an inline one. `post_tweet` then checks `can_post(POST)` again
under the Safari lock.

Models: drafts and reviews go through `run_llm` with
`force_provider=PROFILE_LLM_PROVIDER` and a `CallProfile`,
`editorial_schemas.draft_profile()` or `review_profile()`. The profile, not
the label, sets what the call gets on Ollama, whether Ollama answers first
or as a fallback: `EDITORIAL_OLLAMA_MODEL` (default `gemma4:31b`), the
Draft or review schema as `format`, temperature 0.65 or 0.2, and a
timeout of at least `EDITORIAL_LLM_TIMEOUT_SECONDS` (300) capped by
bedtime. A call without a profile, every Reply, gets
`llm_client.TEXT_PROFILE`: `OLLAMA_MODEL`, no schema, temperature 1.0.
A CLI runs the model its caller names: `NEWS_MODEL` for Originals,
`REPLY_MODEL` or `PRIORITY_REPLY_MODEL` for Replies. Each is an
`llm_client.ModelSetting`, read when the call runs for the primary CLI:
its value when set and not blank, else that CLI's default in
`settings.MODEL_DEFAULTS`. Ollama and OpenCode never read them, nor does a
known fallback: it runs `LLM_FALLBACK_MODEL`, else its own
`CODEX_FALLBACK_MODEL` or `GEMINI_FALLBACK_MODEL`. `run_llm` resolves the
model of each provider it calls once, for the call and its logs.
Ollama receives the caller's prompt behind the `/no_think` directive and
nothing else: the client adds no voice of its own. The reply search keeps those settings and only declares
JSON output. The label only names the call in logs.

Ollama over HTTP and the Codex, Gemini, Claude and OpenCode CLIs are
adapters in `llm_client.ADAPTERS`. Each returns its provider's raw output;
`run_llm` alone runs the fallback ladder and reads the answer. The ladder
starts with the primary (`force_provider`, else `AI_CLI`), then tries at
most one fallback, `LLM_FALLBACK_CLI`. Unset or empty, there is no fallback,
and `LLM_DISABLE_FALLBACK=1` turns a configured one off. A provider name no
adapter carries, primary or fallback, fails that rank without running
anything, and an unknown primary tries no fallback; `main.py` logs every
such setting at start (`llm_client.unknown_providers`). A CLI that is not
installed fails its rank by name, and no other CLI stands in. Every provider
can be the primary; `llm_client.FALLBACKS` lists those that can be the
fallback. `_fallback` ignores a fallback that is not one of them (Claude), a
CLI not installed, Ollama behind Ollama, or the primary itself without
`LLM_FALLBACK_MODEL`: the call then fails at the primary, and `main.py` logs
it at start (`llm_client.ignored_fallbacks`). A call
fails on an error, an empty answer, a limit or refusal message
(`_should_fallback`), or an answer that reads empty. A codex usage limit is
cached in `codex_lockout.json`: it sends the call to the fallback labelled
`(codex locked)`, and later codex calls go to Ollama alone until it expires,
`LLM_FALLBACK_CLI` set or not: Ollama is local, so no call leaves the machine.
When every provider tried failed on a usage limit (`_USAGE_LIMIT_PATTERNS`,
a codex lockout seen or cached counting as one), the call comes back
`LLMStatus.EXHAUSTED`. Only the CLI or the transport reports a limit: the
output of a call that exited non-zero, or the error a JSON envelope flags,
with the lines of the prompt dropped since `codex exec` echoes it
(`_cli_signal`). A model's answer that talks about rate limits is never
one, and the codex lockout reads the same signal. A limit at one rank only, or any other failure,
leaves it `FAILED`; an answer is `ANSWERED`. Every result names the provider
and model that answered, or failed last: the fallback's when it answered.
`_timeout` computes every timeout: Ollama at least `LLM_TIMEOUT_SECONDS`
(180) and the profile's floor, a CLI primary at most 360s, a CLI after
Ollama at most 150s, a CLI after a CLI the requested timeout, all capped by
bedtime.

`run_llm` reads the answer once, in the output mode the profile declares,
whatever the provider and the rank. It unwraps NDJSON events and CLI JSON
envelopes and strips tool-call markup. `Output.TEXT` empties anything
`contains_post_unsafe_leak` flags. `Output.JSON` returns the model's JSON
value, whole or taken out of a code fence or surrounding prose. The Reply
generator, the reply search and the editorial `_json_call` use the answer
as it comes: text, or JSON for `json.loads`. A failure has a non-zero code
and no text. The Reply generator reads `EXHAUSTED` as a rate limit; the
editorial `_json_call` reads any status but `ANSWERED` as no Draft or no
approval, so nothing is published and a missing Draft spends no Attempt.

## Write path and limits

The browser layer is three modules in `src/x/`. `safari.py` holds the
primitives: the Safari lock, `_run_applescript`, `_run_js` (page JavaScript
that returns its result), `_paste_text`, tab, scroll and keyboard moves.
Every page JavaScript in `src/` goes through `_run_js`, with the caller's
timeout, log prefix and, when asked, Safari brought to the front first; it
reads the script from a temp file as UTF-8, so the script carries no
AppleScript escaping. Only `safari.py` and the Safari quit in
`safari_hygiene` spawn `osascript` themselves.
`scraper.py` reads pages: feeds, search, profiles, mentions, our latest
post and its replies, and the blank-page recovery those reads trigger.
`twitter_client.py` holds the write chokepoints. Writes use
reading and primitives, reading uses primitives, never the other way. Both
call a primitive through its module (`safari._run_applescript(...)`), never a
`from` import, so the test walls reach every path.

Every write that should count goes through a function in
`src/x/twitter_client.py`: `post_tweet`, `reply_to_tweet`,
`follow_account`, `like_tweet`, `pin_own_tweet`. Each runs one sequence,
written once in `src/x/confirmed_write.py`. The chokepoint supplies its guards, its page
steps and its ledger rows; `confirmed_write.run` owns the order. The guards
come in two sequences, `before_lock` and `under_lock`, and
`confirmed_write.DRY_RUN_EXIT` sits exactly once among them: the guards
before it run in a dry run too, the guards after it run live only. A
chokepoint without it, or with two, raises before any guard runs.

1. Admission before the Safari lock: `can_post` and the content checks,
   `follow_policy.judge`, the Blocked-account and liked-cache checks of
   `like_tweet`.
2. The dry-run exit: under `DRY_RUN`, one `[TAG][DRY_RUN] would …` line and
   the dry-run ledger rows; nothing is opened.
3. A pause or a last check before the lock: the follow jitter,
   `like_tweet`'s status-ID check.
4. The Safari lock, released on every path. `reply_to_tweet` judges Reply
   admission under it, and its dry-run exit follows that judgement;
   `post_tweet` checks `can_post` again under it.
5. `reply_to_tweet` claims the tweet in the Replied store.
6. The page steps.
7. Ledger rows only when the page steps return a shipped outcome, then the
   chokepoint's bookkeeping: `record_followed` and `adjust_following`,
   `note_posted`, tweet history.
8. One tab close, except for `like_tweet`, which acts on the open page. A
   stop raised by that close is swallowed once the write shipped, so the
   caller still learns it; after any other outcome it propagates.

The chokepoints return a `WriteOutcome`: `SHIPPED`, `REFUSED` (a guard, or
the page state, left nothing to write), `FAILED` (a step failed before
anything was sent), `UNCONFIRMED` (the write may have reached X; the page
never confirmed it) or `DRY_RUN`. Only `SHIPPED` is truthy: callers log or
count on a truthy result, and no ledger row is written otherwise. A
`FAILED` or `UNCONFIRMED` write logs `[TAG] Write <outcome>; nothing
recorded.` after the failed step's own line. A refusal keeps the guard's
line alone, its outcome line going to debug, so a refusal and a failure
read apart in `bot.log` and a like walk logs one line per post it skips. A
caller that persists on a truthy result persists nothing after a dry run,
and one that must tell a dry run from a refusal compares with `is
WriteOutcome.DRY_RUN` (`pin_job`) or `is FollowOutcome.DRY_RUN`
(`follow_engagers_bot`). One limit: `SHIPPED`
for a post or a Reply means `osascript` ran the submit keystroke, not that X
confirmed it; a failed submit keystroke returns `UNCONFIRMED`.

`follow_account` runs the same sequence but returns a `FollowOutcome`,
truthy only for `FOLLOWED`, the Follow click. Its refusals name their
cause (Follow refusal, CONTEXT.md): `BLOCKED`, `TOO_SOON`, `CAP_REACHED`,
`QUALITY_REJECTED` and `REFUSED`, from the follow policy before the
profile opens or from the quality gate on it; `ALREADY_FOLLOWED` when the
profile shows the account followed. `FAILED` and `DRY_RUN` keep their
meaning. A follow that shipped writes its ledger row, joins the followed
accounts and adds one to the following count; an account already
followed joins the followed accounts, with no ledger row and no count
change.

`src/account/follow_run.py` runs one cycle's follows for a job. The
`FollowRun` reads the followed accounts when it starts, and raises
`StateUnreadable` while they cannot be read. `fresh(handles)` drops the
followed accounts and the handles the run tried, whatever the case and a
leading `@`;
`follow(handle)` asks `follow_account` and returns its outcome, or `None`
with nothing asked for a handle `fresh` would drop. Once `follow_account`
returned `CAP_REACHED`, the run returns it again without asking: the
daily cap, the ceiling and the ratio brake do not come back within a
cycle, whereas a `TOO_SOON` may elapse. `OutsideActiveHours` and
`StateUnreadable` propagate; any other error is logged with its traceback
and returns `None`, and the job goes on. `failed` counts those picks, which
`follow_engagers_job` counts in its per-cycle bound, and
`raise_failure()` raises the last one's error: the job calls it once its
state is saved, so the cycle reaches `health.record_failure`. The caps, the
order and the persistent memory of tried handles stay in the job. `follow_engagers_job`
uses it; `followback_job` and `engage_job` still run their own loop.

`like_tweet` runs the same sequence but returns a `LikeOutcome`, truthy
only for `LIKED`, which also carries `FAILED`, `UNCONFIRMED` and
`DRY_RUN`. It never presses the `l` shortcut, which
toggles and acts on X's own selection. A post whose URL handle is a
Blocked account, matched as Reply admission matches it, returns `BLOCKED`
before anything is read, clicked or recorded. One JavaScript step finds the
article by the URL's status ID, read from the article's own timestamp link
and not a quoted post's, and clicks its button only when it is `like`,
never `unlike`. A post in `liked_tweets.json` or shown as liked returns
`ALREADY_LIKED`; a post not found returns `FAILED`. After the click it
reads the article again and returns `LIKED` only once the button shows
`unlike`; the ledger row and the cache entry then carry the URL read on the
page. A click the page does not show returns `UNCONFIRMED`, falsy, with no
ledger row or cache entry. `like_tweet` reads and clicks under the Safari
lock, which is reentrant, so a caller that already holds it is unchanged. That read, about a second after the click, sees X's optimistic
interface: it proves the page shows the like, not that X accepted it.
`visit_profile_and_like`, `like_own_tweet_replies` and `like_search_posts`
list the articles on the page and call it with each post's URL: the
profile's own posts for the first, the replies under our latest post for
the second, the posts of a niche search for `like_job` for the third, never
our own posts. A `BLOCKED` post is skipped and the walk goes on; a `FAILED`
or `UNCONFIRMED` one stops it. All three open nothing under `DRY_RUN` and
close their tab even when a like raises. `like_search_posts` starts no like
once `LIKE_BOT_CYCLE_SECONDS` (30 s) have passed since it took the Safari
lock, and fills the caller's outcome list as it goes: `like_job` adds the
`LIKED` and `UNCONFIRMED` outcomes to its daily count, so a stop mid-walk
still counts them, and a click that may have landed on X counts toward the
cap without a ledger row.

`pin_own_tweet` writes a `pin` ledger row and returns `SHIPPED` only when it
clicked X's confirm dialog. With no confirm dialog (`NO_CONFIRM`) it logs
it, writes no row and returns `UNCONFIRMED`: `pin_job` then spends its daily
attempt and leaves its pin history unchanged. Under `DRY_RUN` it writes a
dry-run row; `pin_job` marks the day under `dry_run_date` in
`pin_daily_state.json`, which stops further dry runs that day without
spending the live attempt. A `pin` row is not a profile publication.

No write function exists for quotes, reposts, threads, GIF posts or
self-replies: `quote_tweet`, `quote_tweet_with_gif`, `post_tweet_with_gif`,
`retweet_post`, `retweet_own_latest`, `reboost_tweet`, `post_thread`,
`reply_to_own_latest` and `reply_to_reply` were removed with their helpers
(issue #111). `can_post` refusing quotes and retweets stays as a second
line. The writes no job called went too (issue #168): the unfollow
chokepoint with its cap, the nested-reply alias, and `post_tweet`'s image
path and non-editorial branch. The bot never unfollows;
`bin/mass_unfollow.py` clicks on its own page and writes its ledger rows
itself.

Five modules sit behind them:

- `src/core/config.py` holds the ceilings that `.env` cannot lift: eight
  profile publications a day, originals capped at 8 and spaced by at least
  1200 seconds.
- `src/guards/action_guard.py` decides `can_post`, answers the follow
  policy's ledger questions (today's follows, the follow spacing, anti-churn),
  and records every write through `record`. It asks the action ledger and
  never knows where the ledger stores. Quotes and
  retweets are always refused; replies only need their spacing
  (`MIN_SECONDS_BETWEEN_REPLIES` plus jitter). The jitter of the reply,
  original and follow gaps is drawn once per write, seeded on the
  timestamp of the last write of that action (dry runs excluded): every
  caller sees the same gap, and retrying cannot fish for a smaller draw. `seconds_until_allowed` returns what is left of it,
  capped at one gap so that a ledger row stamped in the future (clock set
  back, copied ledger) cannot park a waiting job; `can_post` still refuses
  until the spacing clears.
- `src/guards/ledger.py` is that ledger (90 days, Toronto timestamps). Its
  interface answers four questions: shipped rows of an action on a Toronto
  day (per target for Debate turns), the last shipped write of an action,
  the last follow or unfollow of a handle (dry runs included), and the
  targets of an action newest first. An index kept up to date row by row
  answers them, with no scan of the rows. Two adapters sit behind it:
  `FileLedger` keeps `action_ledger.json`, `MemoryLedger` holds the rows in
  memory. `action_guard.LEDGER` picks the adapter: `None`, the default,
  stands for the file at `config.ACTION_LEDGER_FILE`, resolved at each call;
  policy tests set a `MemoryLedger` through the `memory_ledger` fixture.
  The file holds one JSON object per line: a write appends and fsyncs one
  line, a check parses only the lines added since the previous read, so
  rows another process appends (`bin/mass_unfollow.py`) count from the next
  check on. A file rewritten or replaced (smaller, another inode, other
  bytes at the head or before the last row read) is read again in full.
  Rows past 90 days go in an atomic rewrite at most once per Toronto day. A
  ledger still in the former single-list format is read as is and converted
  in place at the next write. A corrupt line, a row without a text `ts` or a
  file with no row refuses every check and every write. A last line without
  its final newline counts when it reads as a row, and the next write adds
  the newline; an unreadable one (an interrupted write) is skipped, and the
  next write drops it. The append, the rewrite and its directory are flushed
  with `F_FULLFSYNC` where the system has it.
- `src/guards/content_guard.py` validates text before publication: near-term
  price targets, duplicates, truncation, violence, skip rationales.
- `src/guards/follow_policy.py` is the follow policy and owns the follow
  files: `followed_accounts.json`, `following_count.json`,
  `follower_history.json`, `whitelist_discovered.json`,
  `follow_quality_rejects.json`, `followers_seen.json` and the frozen
  `replied_back.json`. It reads the Operator's `whitelist.json` in the
  Account folder and never writes it; the handles `account_curator`
  promotes go to `whitelist_discovered.json`, through `add_discovered`, and
  a missing one stops its readers as an unreadable one does: before the
  migration of issue #206 it would drop the handles still to carry.
  `relation(handle)` finds what
  the handle is to the account, from its own sources, never from the
  caller: Seed account (the whitelist, both files), follower (`followers_seen.json`, which only the
  followers scrape writes, through `record_followers`), Engager (the
  ledger's Debate turns, then `replied_back.json`), else Stranger.
  `judge(handle)` checks, before the profile opens, the handle (the one
  check of `[A-Za-z0-9_]{1,15}`), the Blocked account (the match of
  `reply_admission.is_blocked_account`, the one Reply admission and
  `like_tweet` use, over the engine's `BLOCKLIST` and the Account's
  `network.blocked_accounts`), the relation (a Stranger is refused in
  every mode), the whitelist (a follower or an Engager passes it while
  `FOLLOWBACK_BYPASS_WHITELIST` is on), anti-churn, the daily cap, the
  spacing, the following ceiling and ratio brake, then the quality-reject
  cache. `judge_profile` runs the quality gate on the open profile, by
  relation (a Seed account is exempt, an Engager skips the size and niche
  checks; the niche is the Account's `niche.bio`), and caches a reject for 30 days. Each
  returns a `Verdict` whose `Refusal` names the cause; `follow_account`
  turns it into its `FollowOutcome`, and the jobs act on that outcome
  without checking a rule again. `followed()` reads the followed accounts
  for the jobs; `record_followed` and `adjust_following` are called by
  `follow_account` alone, and log instead of raising on an unreadable file,
  since the follow already happened.

`reply_to_tweet` takes every rule from `src/guards/reply_admission.py` (Reply
admission, CONTEXT.md). `judge_parent(url)` judges the post alone: author
handle from the URL (`src/x/x_urls.py`), Blocked account, own post, already
answered, Waking hours, Debate turn cap. `judge_reply(url, draft)` replays
those rules, adds the reply spacing, then builds the exact text that ships
(dashes, `smart_trim`, `casualize`, FR-forced language check, typo) and
validates it last. `reply_to_tweet` calls `judge_reply` once under the
Safari lock, the lock that also records the reply, so the spacing and the
Debate turn cap cannot move between the check and the write. Each refusal
says whether it is definitive for the post or temporary. Neither judgement
writes anything.

Every reply job (`direct_reply`, `feed_sweep`, `early_bird`,
`mega_watch`, `debate`, `replyback` and `babysit`, the disabled reply
search) hands its candidates to the Reply pipeline,
`src/replies/reply_pipeline.py`. A job keeps its sub-sources (the feeds,
searches or handle pools it scrapes), its budgets, its Reply call, its pace
after a shipped Reply and its log tag. `feed_sweep` declares what it
answers to the Reply source, `src/replies/reply_source.py`: the oldest post
(`DIRECT_REPLY_MAX_AGE_MINUTES`, read on each pass), root posts only, the
Account's niche, fresh and rising first. `reply_source.select` applies the
declaration without side effects and never keeps a post without a URL or
text, or of unknown or negative age; a declaration can also require the
author a scanned profile's posts carry in their URL. The other jobs still
select their candidates themselves (niche, age threshold, thread-reply
shape) until they move to it. The
pipeline alone calls `judge_parent` before paying for a generation, writes
through `twitter_client.reply_to_tweet`, and calls
`engagement_log.log_reply` after a shipped Reply only, with the provider and
model the Generation names (the reply search's, for its candidates); the
log never guesses them from `AI_CLI`. It keeps, per job and
lost at restart, the posts refused definitively, declined by the model
(SKIP) or answered; `direct_reply`'s VIP and search lanes share theirs. A
temporary refusal, a failed generation or a failed write leaves the post
replayable. A model rate limit, every provider exhausted, ends the job's
generations for the cycle, with the post left replayable; in `direct_reply`
it also stops the search
lane, in `feed_sweep` the Following pass. `StateUnreadable` and
`OutsideActiveHours` end the cycle from any step, a job's scrape included;
any other error in a scrape, a generation or a write is logged and the
cycle moves on.

The `direct_reply` search lane and `feed_sweep` run pipelined: the pipeline
generates reply N+1 while reply N is posted, so its text is ready as soon
as reply N's ledger row is written. Before calling `reply_to_tweet`,
outside the Safari lock, it sleeps `seconds_until_allowed(REPLY)` in
one-second slices and raises `OutsideActiveHours` on a stop request or at
23:30. The chokepoint still judges: when another job's reply lands during
the wait, `reply_to_tweet` refuses on spacing, writes no ledger row, and the
post stays replayable in a later cycle, at the cost of a new generation.
On a rate limit, bedtime or an unreadable state file the pipelined job
returns at once: the generation in flight finishes in the worker thread,
unread, and its post stays replayable.
The other jobs answer their candidates in turn and never wait: a Reply they
send too early is refused on spacing and stays replayable.

After admission, `reply_to_tweet` deduplicates through
`src/guards/replied_store.py`. `claim` re-reads `replied_tweets.json`, refuses a
tweet already answered, and marks it just before writing, all under one lock.
A dry run stops before the claim and writes only a dry-run ledger row.
The store is keyed on status ID, written through a temp file and
`os.replace`, and fails closed like the ledger: an unreadable file raises
instead of reading as empty. If the reply keystroke or the paste fails, or a
stop or 23:30 interrupts the sequence before the submit keystroke, nothing
was sent: `replied_store.release` removes the claim before the Safari lock
is released, so a thread waiting for the lock never sees it. If the submit keystroke fails,
the outcome is unknown: the claim stays, so the tweet never gets a second
reply.

Every Reply prompt is assembled by `src/replies/reply_generator.py`. A job
passes its Reply call, a `ReplyCall` (template, model, label, language
rule, and its `run_llm` options as a frozen `CallOptions`, where a misspelt
option fails when the Reply call is built), and the parent post; `generate` returns a `Generation`: reply text, a decline (the model
said SKIP), a replayable failure, or a rate limit when every provider is
exhausted. Reply text comes with the provider and model that wrote it. The
generator always opens the prompt on the Voice,
`personality_store.render_voice`: the Operator's `voice_fr.md`
(`voice_en.md` for an English reply), in the Account's folder, under a
header naming `BOT_HANDLE`, the one reader of those files. The job's template follows,
with its instructions but no persona, then, for Reply calls with `dossier`, the
author's dossier from `personality.json` (or the fixed dossier of the
author's Relation), and always
`personality_store.hard_rules_block()`, which renders the hard rules and
the respect list from the Account's `respect_list.json`. The editorial Draft opens on the
same Voice. It decides the language in one place, `_language`: the
search and feed-sweep Replies follow `FR_FORCED_REPLY_HANDLES`, then the
parent's words; early-bird and mega-watch the parent's words only;
replyback a word test on the Engager's reply; the reply search English.
`FR_FORCED_REPLY_HANDLES`, the Account's `network.fr_forced_reply` unless
`.env` sets it, is read by `reply_language.is_fr_forced`, shared
with `judge_reply`. An answer opening with SKIP, after quotes are stripped,
is a decline; the bestie and buddy Reply calls also decline "skip" anywhere in
the first 20 characters (`skip_window`). The editorial prompt carries the
hard rules too. The write chokepoints apply the respect list to the
outgoing text, before the dry-run exit: `post_tweet` refuses an Original
and Reply admission a Reply (`RESPECTED_ACCOUNT`) that names a Respected
account by `@handle`, or by its handle in a sentence with a derisive word.
The `@handle` of the author a Reply answers passes. `RESPECTED_ACCOUNT` is
definitive: `reply_to_tweet` hands the refusal to the Reply pipeline
(`on_refused`), which sets the post aside. A dry-run Original stops in the
editorial before `post_tweet`, which judges its text with the same
`respect_list.scrub_text_or_skip`.
While `respect_list.json` is missing or unreadable, `hard_rules_block` raises
`StateUnreadable`: the editorial cycle and the Reply cycles stop before the
model call, and nothing ships. Nothing renders the block at import, so
`main.py` still starts.

## State store

`src/core/state_store.py` reads and writes the JSON state files of `src/`,
except the action ledger and the Replied store. A module declares each file
once as a `StateFile(name, default, policy)`; paths resolve at call time under
`state_store.root()`, `state/<BOT_ACCOUNT>/`, the one place that knows it
(issue #207). The files it does not read or write, the action ledger, the
Replied store, the engagement log, the editorial audit and the reach report,
are declared as a `StatePath(name)`, resolved there too. The state of before
#207 at the project root is `state_store.LEGACY_ACCOUNT`'s, `theaishrink`:
`main.py` refuses to start, whichever Account runs, while one of its files is
missing from `state/theaishrink/` or differs from its copy there
(`state_store.require_migrated()`); `bin/migrate_state.py` moves it there.
`bot.log`, `bot.lock` and `autonomous_log.md` belong to the process and stay
at the root. Every write goes through
`atomic_write_bytes`: a temp file `.<name>.<random>.tmp` in the same
directory, flushed with `F_FULLFSYNC` where available, `os.replace`, then a
flush of the directory. A missing file reads as the
default. An unreadable file (bad JSON, wrong top-level type) under the
*guarded* policy raises `StateUnreadable` on read and on write, so it is
never replaced; under the *disposable* policy it reads as the default and
the next write replaces it. Each file has one lock, and
`StateFile.update(fn)` reads, changes and writes under it. The files that
several scheduler threads change go through it: `followed_accounts.json`
(`follow_account` merges each follow into the file, whichever job asked),
`following_count.json`, `liked_tweets.json`, `follow_quality_rejects.json`,
`followers_seen.json`,
`tweet_history.json`, `safari_health.json` and `personality.json` (the
dossier bump after every Reply). `tweet_history.json` has one reader,
`history.load_history`, for the dedup, the rationed openers and the
babysitter; the editorial cycle reads it before any Draft, so an unreadable
history spends no Attempt. The policy of each file is in the
[OPERATIONS.md](OPERATIONS.md#state-files) tables.

The Operator files (`whitelist.json`, `respect_list.json`,
`following_baseline.json`) are not state: they live in the Account folder,
versioned, and `account.OperatorFile` reads them at each call. It has no
write, and a missing or unreadable file raises `StateUnreadable` instead of
reading as a default, so nothing recreates it.

## Reach report

`src/editorial/reach_report.py` matches the originals the Slot journal
recorded (`editorial_state.json`) over the last seven days against a scrape of our own
profile, sums their public view counts and compares the total with the
500,000-view target. It reports missing coverage and never claims
home-timeline attribution. It does not influence any cap.

## Known gaps

These are how the code behaves today, not design intent:

- Pending editorial submissions count toward the ceiling and the spacing in
  the editorial cycle only (`_pending_refusal`): `post_tweet` and the ledger
  do not see them. The editorial cycle is the only `post_tweet` caller; a new
  caller would not count them.
- `like_tweet` and `pin_own_tweet` have no `can_post`: likes and pins are
  recorded, not capped by the ledger. `like_job` and `pin_job` keep their
  own daily caps in their state files.
- `session_refresh_job` and the `health` recovery restart Safari without
  taking `_safari_lock`.
- The debate, VIP and Graphseo Reply calls (`dossier=False`) carry the Voice and
  the hard rules but not the author's dossier.
- The Graphseo Reply call forces the Claude CLI whenever it is installed
  (his Relation's `provider`, applied by `direct_reply._own_call`), whatever
  `REPLY_LLM_PROVIDER` says: the
  one cloud call without `LLM_FALLBACK_CLI`, pending the Operator's decision.
  It runs `PRIORITY_REPLY_MODEL`, unset `claude-haiku-4-5-20251001`.
- `early_bird` and `mega_watch` ignore `FR_FORCED_REPLY_HANDLES`: an
  English-looking post from @Graphseo gets English reply text, which
  `judge_reply` then refuses.
- The replyback language test matches substrings, so "honestly" or "best"
  ("est") selects the French Voice file.
- `babysit_job` and `replyback_job` call the same `run_replyback_cycle` and
  can overlap.
- Only the pipelined Reply jobs wait out the reply spacing. A Reply that
  `early_bird`, `mega_watch`, `debate`, replyback or the VIP lane generates
  inside the gap is refused on spacing, and its generation is paid again in
  a later cycle.
- The state store lock is per process: `bin/seed_fr_influencers.py`
  following while the bot runs can still lose a follow from
  `followed_accounts.json`.
- The ledger lock is per process, and `FileLedger` assumes the bot is the
  only writer while it runs. A row another process writes while the bot
  rewrites the file (conversion or daily retention pass) or drops an
  unreadable last line is lost: run `bin/mass_unfollow.py` with the bot
  stopped, never with `--force` beside it.

## Legacy modules

The quote, repost, thread, boost, signal, self-modification and analytics
bots that no job reached were deleted (issue #110); git history keeps them.
Every module under `src/` is now reached from `main.py`, and
`tests/test_disabled_surfaces.py` fails when one is not. Live code still reads
some files those bots used to write, as frozen data with no writer left:
`directives.md` (`reply_agent`), `pruned_accounts.json` and
`reinforced_accounts.json` (`evolution_store.filter_and_weight`, used by
`engage_bot` and `early_bird_bot`).

## Adding a job

1. Expose `run_<name>_cycle()` in a module of the package that owns its
   concern: `src/replies/<name>.py` for a reply job, `src/account/<name>.py`
   for a follow, like or pin job. The top level of `src/` holds only
   packages. Let its errors raise: the job wrapper catches them.
2. Register it in `build_scheduler()` with
   `add(health.wrap_job(run_<name>_cycle, "<name>"), minutes, "<name>_job")`.
   `wrap_job` logs an error at ERROR with its traceback in `bot.log`, resets
   the Safari failure counter on success and hands the error to
   `health.record_failure`; `StateUnreadable` and `OutsideActiveHours` never
   count. Pass `safari_health=False` for a job whose failures say nothing
   about Safari, such as a model call or a report: it never touches the
   health file. Never call `scheduler.add_job` directly: `add()` supplies the
   waking-hours wrapper.

   In transition (issue #234): the jobs already registered still expose a
   `safe_run_*` that catches its own errors, and their `record_failure` call
   without an exception reads the one in flight. Issues #236 to #238 move them
   under `wrap_job`; #239 makes the exception required.
3. Take `_safari_lock` for any browser work and close the tab you opened.
4. Write only through the `twitter_client` chokepoints; add a new rule inside
   the chokepoint, not in the job.
5. Key daily counters on the Toronto day (`active_hours.now_local()`).
6. Pin the new behaviour with a test. A job that publishes more, or revives a
   disabled surface, also needs an operator request and an update to
   [EDITORIAL_POLICY.md](EDITORIAL_POLICY.md).

## Tests

The suite mirrors `src/`: `tests/<package>/` holds the tests of one package
(`core`, `x`, `guards`, `editorial`, `replies`, `account`), one file per
module or concern, such as `tests/guards/test_action_guard.py` or
`tests/x/test_write_path.py`. A test that crosses packages sits with the
module owning the rule it pins: a chokepoint rule under `tests/x/`, a job's
use of it under the job's package. Every test folder has an `__init__.py`,
so two packages can hold files of the same name. Helpers shared by several
packages live in `tests/helpers.py`, fixtures in `tests/conftest.py`.
The reply tests share one fake model, `tests/replies/fakes.py`, which the
`llm` fixture puts behind the Reply generator's `run_llm`. The fallback
ladder is tested in `tests/core/test_llm_client.py`, where a fake adapter
replaces each provider in `llm_client.ADAPTERS`. That `providers` fixture,
in `tests/conftest.py`, also puts the real ladder behind the Reply pipeline
and the editorial calls, for the usage-limit tests.

The current policy is pinned across packages: Toronto and DST boundaries in
`tests/guards/test_active_hours.py`, bedtime checks at the lock and before
AppleScript in `tests/x/test_safari.py`, the daily budget and write spacing
in `tests/guards/test_action_guard.py`, and slot timing and retries, source
evidence, review rejection, ambiguous submissions, dry-run isolation and
reach accounting under `tests/editorial/`.

The files at the top of `tests/` pin cross-cutting invariants:
`test_conftest_walls.py` (the walls below), `test_state_file_paths.py` (every
state file resolves under `state/<BOT_ACCOUNT>/`), `test_migrate_state.py`
(the move from the root and the start's refusal), `test_state_untracked.py` (git
ignores every state file and tracks the Operator's), `test_scheduler.py` (the jobs
`build_scheduler()` registers), `test_voice.py` (the Account's Voice files
and the Voice block rendered from them), `test_engine_names_no_account.py`
(no token of `main.py` or `src/` names TheAIShrink, Graphseo or
TheBTCTherapist, save two listed values that name the theaishrink folder,
and a comment or docstring only in a passage dated or numbered),
`test_example_account.py` (the dry run of the fictitious `accounts/example/`,
and theaishrink's jobs and ceilings as they were before #187),
`test_mass_unfollow.py`
(`bin/mass_unfollow.py`), `test_imports.py` and `test_disabled_surfaces.py`.
`tests/test_imports.py` reads `main.py` and every file under `src/`, `bin/`
and `tests/`, subfolders included, with `ast`. It fails when an
intra-project import, function-local or inside `try/except` included, names a
missing module or an undefined name, imports a module under `src/` by its bare
name instead of through its package, or crosses a package folder without
`__init__.py`. `tests/test_disabled_surfaces.py` fails when a module that
`main.py` reaches through imports, the three browser modules included, defines or
names a quote, repost, thread or GIF write. It also fails when a
module in any package under `src/` is not reached from `main.py`,
function-local imports included, and when a package imports the job packages
above it: nothing outside `src/replies/` and `src/account/` imports them, and
`src/account/` never imports `src/replies/`.

`tests/conftest.py` walls tests off from production: `webbrowser.open`,
`_run_applescript`, `_run_js`, `_paste_text` and any subprocess that runs
`osascript` or aims `open`, `pkill` or `killall` at Safari raise (an import
error on `src.x.safari` fails every test rather than dropping the wall), the
logger writes to a temporary file, and the state store root, the engagement
log, the replied store and the ledger point to `tmp_path`. A mock placed
on a caller module misses function-local imports; patch the primitive in
`safari` and a scrape in `scraper`. `tests/test_conftest_walls.py` fails when
a module binds a walled primitive, `webbrowser` or `subprocess.Popen` by name,
past the wall, or binds `_safari_lock`, `_scroll_page` or `close_front_tab`
by name, past the patches tests put on `safari`, and when a module other than `safari.py` runs `do JavaScript`
or spawns `osascript` itself, docstrings aside; the Safari quit in
`safari_hygiene` is the listed exception.
`tests/x/test_page_js.py` pins each page script's timeout, log prefix and
answer on failure, and checks that a test which forgets to mock `_run_js`
fails on the wall. Every test also starts with fresh process memories: the
posts the Reply pipeline set aside, the direct reply's query rotation cursor and the
content guard's dedup memory of this run's posts.

CI (`.github/workflows/ci.yml`) runs `python -m pytest tests/ -q` on Python
3.12 with only `pytest` and `apscheduler` installed, on every pull request and
every push to `main`.

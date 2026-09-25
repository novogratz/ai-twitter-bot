# Operations

Running, watching and recovering the bot under the 2026-09-20 policy. The
design is in [ARCHITECTURE.md](ARCHITECTURE.md), the rules in
[EDITORIAL_POLICY.md](EDITORIAL_POLICY.md).

The bot publishes on a real account. Start, stop and restart it only when the
operator asks.

## Setup

Requirements: macOS, Safari logged in to x.com with **Develop → Allow
JavaScript from Apple Events** enabled (Safari need not be the default
browser: the bot opens every page in Safari by name), Python 3.12+,
[uv](https://docs.astral.sh/uv/), and a local Ollama with the reply model and
`EDITORIAL_OLLAMA_MODEL` (default `gemma4:31b`) pulled.

```bash
uv venv
uv pip install -r requirements.txt
cp .env.example .env
```

The repo has no `pyproject.toml`. `uv run`, used by `bin/run.sh` and the
launchd plist, picks up the `.venv` in the repo root; without it, uv runs a
bare interpreter and the bot fails on `import apscheduler`.

`.env.example` predates the current account. Before the first run, set at
least:

- `BOT_HANDLE=TheAIShrink`: the example still says `CryptoAIDecode`.
- `CONTENT_LANG_PRIMARY=en`: the example says `fr`, and the editorial
  pipeline writes originals in French when it sees `fr`.
- `LLM_FALLBACK_CLI=codex` only to let a failed call fall back to the
  cloud. Unset or empty, as in the example, there is no fallback and no
  call leaves the machine, except the Replies to @Graphseo: they run on
  the Claude CLI whenever it is installed (`direct_reply._graphseo_voice`).
  The start logs a fallback the code ignores, and `--dry-run` lists it
  under `ignored_llm_fallbacks`.

`src/core/config.py` loads `.env` without overriding variables already set in the
shell. Check the setup without a browser or a model with the dry-run command
from [`AGENTS.md#verification`](../AGENTS.md#verification).

## Start

```bash
./bin/run.sh
```

The script:

1. kills every process matching `python.*main.py` on the machine, not only
   this repo's;
2. pre-warms `OLLAMA_MODEL` from the shell environment, during waking hours
   only. It does not warm the editorial model;
3. clears `__pycache__`;
4. runs `uv run python main.py` in the foreground through `tee -a bot.log`.

Because stdout is a pipe, the logger adds no console handler: log lines go
only to `bot.log`, while stdout and tracebacks reach both the terminal and
`bot.log`. Follow `tail -F bot.log`.

Flags for `main.py`: `--post-only`, `--reply-only`, `--dry-run`. There is no
other mode; `--monthly-recap-now` is gone. Every start in waking hours opens
a Startup post: a restart publishes one trend post within 45 minutes when the
daily ceiling and the twenty-minute spacing allow it. `--reply-only` opens none.

Started outside waking hours, the bot logs `[HOURS] Asleep. Next wake: …` and
waits. Nothing external happens until 04:30 Toronto time.

## Stop

| Command | Effect |
|---|---|
| Ctrl-C in the `run.sh` terminal | SIGINT: `request_stop()`, scheduler shutdown |
| `bin/stop_bot.sh` | Touches `.bot_disabled`, then SIGTERMs the `main.py` processes whose working directory is this repo |
| `bin/stop.sh` | SIGTERM then SIGKILL to every `python.*main.py` on the machine |

`main.py` never reads `.bot_disabled`. Only the legacy `bot_watchdog.sh` at
the repo root honours it; a supervisor that restarts the bot ignores it.

## Supervisors

Only one should be active. Check which one before stopping the bot, or it
comes back:

```bash
launchctl list com.kzer.ai-twitter-bot   # exit 0: the launchd job is loaded
pgrep -f bin/watchdog.sh                 # prints a PID: the watchdog runs
```

Query the exact label: `launchctl list | grep com.kzer.ai-twitter-bot` also
matches `com.kzer.ai-twitter-bot-improve`, the daily improve agent.

- **launchd** (`launchd/com.kzer.ai-twitter-bot.plist`, installed by
  `bin/install_autonomous.sh`): `KeepAlive`, `RunAtLoad`, 30-second throttle.
  The plist hard-codes `/Users/benoitfloch/ai-twitter-bot`; fix the paths
  before installing it elsewhere. Stop it with `launchctl unload
  ~/Library/LaunchAgents/com.kzer.ai-twitter-bot.plist` or
  `bin/uninstall_autonomous.sh`.
- **`bin/watchdog.sh`**: every 120 seconds, starts `run.sh` if no bot runs and
  restarts it if `bot.log` has not changed for 15 minutes. It deletes
  `.bot_disabled` at start. `touch .watchdog_off` makes it hands-off. The
  paused scheduler logs almost nothing overnight, so this watchdog restarts
  the bot roughly every 15 minutes between 23:30 and 04:30; each restart
  comes back asleep.
- **`bot_watchdog.sh`** (repo root): legacy, runs from `$HOME/ai-twitter-bot`
  and exports old LLM variables.

## Manual writes

The `engage`, `follow`, `like`, `reply` and `unfollow` skills write to the
real account from a second process. Before any of them:

1. The operator asked for this run explicitly.
2. The bot is stopped: `pgrep -if "python.*main\.py"` prints nothing. The
   Safari lock only serialises writes inside one process, so a manual write
   beside a running bot interleaves with it in Safari. Stop it through
   [Stop](#stop).
3. No supervisor restarts it during the run: see [Supervisors](#supervisors).
4. Waking hours, on the bot's own Toronto clock:
   `uv run python -c "from src.guards.active_hours import is_active; print(is_active())"`
   prints `True`. The `twitter_client` chokepoints refuse writes Overnight,
   and `bin/mass_unfollow.py` refuses to start Overnight and stops at 23:30.

## Watching

| Where | What it tells you |
|---|---|
| `bot.log` | Runtime activity. Useful tags: `[HOURS]`, `[EDITORIAL]`, `[POST]`, `[REPLY]`, `[REPLYBACK]`, `[VIP]`, `[DEBATE]`, `[FOLLOW]`, `[LIKE]`, `[PIN]`, `[HYGIENE]`, `[HEALTH]` |
| `editorial_state.json` | Today's attempts per slot, slots `pending` or `published` (Startup posts as `startup@HH:MM:SS`), each pending submission (`pending_sources`, keyed `YYYY-MM-DD/<slot>`: source URL skipped by later drafts, text treated as a recent post, submission time), recent publications and used sources |
| `editorial_review.jsonl` | One line per reviewed draft: draft, source, approval, rejection reason |
| `editorial_reach.md` | Observed views of the last seven days of originals against the 500,000 target, with missing coverage |
| `action_ledger.json` | Every counted write with its Toronto timestamp, one JSON object per line; the source of today's budget |

```bash
tail -F bot.log | grep -E '\[(HOURS|EDITORIAL|POST)\]'
jq -c 'select(.action == "post" and .dry_run != true)' action_ledger.json | tail -n 5
tail -n 5 editorial_review.jsonl | jq '{ts, slot, approved, reason}'
jq '{date, slots, attempts}' editorial_state.json
```

Silence between 23:30 and 04:30 Toronto time is normal. There is no
heartbeat line.

## Recovery

**A slot is `pending`.** The submission was interrupted or its outcome was
unclear, and the bot will not retry it. Until you clear it, it counts toward
today's eight publications and the twenty-minute spacing, and its text stays
a recent post for later drafts. A failed submit keystroke logs
`[EDITORIAL] <slot> stays pending` in `bot.log`. Check the profile first. If the post
is live, set the slot to `"published"` in `editorial_state.json` and append
a matching entry (`ts`, `text`, `source_url`, `angle`, `slot`) to
`published`, so the source rests for seven days and the reach report counts
the post; the published slot keeps counting toward today's ceiling. If it is
not live, delete the slot entry. Either way, delete its entry (keyed
`YYYY-MM-DD/<slot>`) from `pending_sources`: until then later drafts skip that
source and text, across days too, and today's ceiling counts it. Do this with the bot
stopped.

**Corrupt `editorial_state.json` or `action_ledger.json`.** Both fail closed:
the editorial cycle errors out and the ledger refuses writes. Repair the JSON
by hand, keeping today's entries, or restore a copy taken today. Never delete
the ledger or restore it from git: the committed `action_ledger.json` dates
from July 2026, and either move resets today's count and grants extra posts.

The ledger holds one JSON object per line, each with a text `ts`. A last line
without its final newline still counts when it reads as a row, and the next
write adds the newline, so a hand edit may leave it out. A last line cut short
by an interrupted write is skipped with a `[LEDGER]` warning in `bot.log` and
dropped by the next write; the rows before it still count. Any other bad line,
a row without a text `ts`, and a file holding no row (empty or blank) refuse
every write. With the bot stopped, list the bad lines, fix or delete those
lines only, keeping today's rows, then restart:

```bash
python3 - <<'EOF'
import json
for n, line in enumerate(open("action_ledger.json"), 1):
    if not line.strip():
        continue
    try:
        row = json.loads(line)
        assert isinstance(row, dict) and isinstance(row.get("ts"), str)
    except (ValueError, AssertionError):
        print(n, line[:80].rstrip())
EOF
```

**A guarded state file is unreadable.** `bot.log` names it in a `[STATE]`
error. The job that needs it stops each cycle without counting toward a
Safari restart, and nothing writes over the file:

| File | Stops |
|---|---|
| `tweet_history.json` | `editorial_job` before any Draft, `post_tweet` (dedup and rationed openers), `babysit_job`, `reply_job` when enabled |
| `followed_accounts.json` | `engage_job`, `followback_job`; every follow while `following_count.json` holds no count, as below. A follow that ships or finds the account already followed is not added to the file |
| `following_count.json` | Every follow: `follow_policy.judge` counts the unreadable following ceiling as reached and `follow_account` returns `CAP_REACHED` before opening the profile. The count update after a shipped follow or unfollow is skipped |
| `like_bot_state.json` | `like_job` |
| `pin_history.json`, `pin_daily_state.json` | `pin_job` |
| `follow_engagers_state.json` | `follow_engagers_job` |
| `personality.json` | The Reply cycles whose voice reads the author's dossier (the `direct_reply_job` search lane, `feed_sweep_job`, `early_bird_job`, `mega_watch_job`, `replyback_job`, `babysit_job`): the cycle stops at its first generation, so none ships. `debate_job` and the VIP lane read no dossier and continue; the dossier bump after a Reply is skipped |
| `whitelist.json` | Every follow: `follow_policy.judge` raises, and `follow_account` stops before opening the profile or writing a ledger row, dry run included. `follow_engagers_job`, `followback_job` and `engage_job` end their cycle as a failure at the first account they judge: no account is marked tried, and `engage_job` likes nothing more that cycle. An unreadable `action_ledger.json` stops the same three jobs the same way, since `follow_policy.relation` reads the Debate turns in it. A whitelist or ledger unreadable once the profile is open is a policy refusal: `follow_account` closes the tab and returns `REFUSED`. Also `account_curator` promotions, and `bin/mass_unfollow.py`, which aborts before any unfollow, even on a missing file |
| `respect_list.json` | Every job whose prompt carries the hard rules, before the model call: `editorial_job`, `direct_reply_job`, `feed_sweep_job`, `early_bird_job`, `mega_watch_job`, `replyback_job`, `babysit_job`, `reply_job` when enabled. Also `post_tweet` and Reply admission, before any write, dry run included; `respect_list.add` and `remove`, `bin/mass_unfollow.py` |

An unreadable `respect_list.json` stops every Original and most Replies
until it is repaired; `main.py` still starts, because nothing renders the
hard-rules block at import. A process killed mid-write
can leave a `.<name>.<random>.tmp` file beside a state file: `.gitignore`
covers it, and it can be deleted once the bot is stopped. With the bot stopped, repair the JSON by hand (usually a truncated
tail), check its top-level type (a list for `tweet_history.json` and
`followed_accounts.json`, an object for the others), then restart. Do not
delete a guarded file: a missing file restarts from empty, which resets a
daily cap, forgets follows and pins, drops the following count the follow
ceiling reads, or drops the Operator's lists.

**Rolling back past issue #147.** Older code reads the ledger as one JSON
list and refuses every write on the per-line format. With the bot stopped,
turn the ledger back into a list before deploying the older code:

```bash
jq -s . action_ledger.json > /tmp/ledger.json && mv /tmp/ledger.json action_ledger.json
```

On a bad line `jq` stops with a parse error and the ledger stays as it was:
repair the line as above, then run the command again.

**Corrupt `replied_tweets.json`.** The store fails closed: `reply_to_tweet`
and the reply cycles that read it raise `StateUnreadable` until it is
repaired, so no reply ships. `health` logs these failures without counting
them toward a Safari restart; the same holds for the ledger.
Stop the bot, repair the JSON by hand (usually a truncated tail: cut back to
the last complete entry and close the list), then restart. Never delete it:
an empty store lets every loop answer tweets it already answered. The file is
gitignored, so git holds no copy to restore.

**x.com renders a blank page.** After 3 consecutive empty scrapes across at
least 2 different pages (2 in a row on the home feed), `scraper`
restarts Safari with a 5-minute cooldown. Blank pages in the 120 seconds after
a restart and an empty mentions tab do not count. `health` also restarts
Safari after 3 failed cycles in a row, all jobs counted together, and
`session_refresh_job` does it preventively every 2 hours; both wait 30 minutes
after the last restart. A cycle stopped for bedtime is not a failed cycle,
and no restart runs outside waking hours. Each relaunch
clears x.com service workers and caches. To do it by hand, stop the bot first:

```bash
osascript -e 'tell application "Safari" to quit'
sleep 3 && open -a Safari
```

**No original today.** Read `editorial_review.jsonl` for review rejections,
then the `[EDITORIAL]` and `[POST]` lines of `bot.log` and `attempts` in
`editorial_state.json`. Causes that leave no audit line: the twenty-minute spacing
or the daily ceiling, sources that could not be fetched, attempts spent, a
model error, fewer than three trending posts for a trend slot. A pass that
produces no draft spends no attempt. The evergreen
documentation pages always supplement the news, so a quiet news day alone
does not block a post. Missed slots are not caught up.

**Unwanted content.** Add the handle to the respect list
(`python3 -c "from src.guards.respect_list import add; add('handle', 'reason')"`,
picked up at the next prompt) or to `BLOCKLIST` in `src/core/config.py` (restart
needed). Both are operator-managed. The respect list reaches every Reply
prompt and the editorial prompt, through the hard rules, and the write
chokepoints refuse an Original or a Reply that names a Respected account,
the `@handle` of the author a Reply answers excepted.

## What can be tuned

Changes to `.env` or code take effect at restart.

- Reply pacing and scope: `MIN_SECONDS_BETWEEN_REPLIES`,
  `REPLY_JITTER_SECONDS`, `DIRECT_REPLY_QUERIES_PER_CYCLE`,
  `VIP_SCAN_HANDLES`, `PROFILE_VISIT_ALLOWLIST`, the `DEBATE_*` and
  `FEED_SWEEP_*` variables.
- Follows: `FOLLOW_WHITELIST_ONLY`, `FOLLOW_TOTAL_CAP`, `FOLLOW_GROWTH_MODE`,
  `FOLLOWBACK_CAP`, `FOLLOW_ENGAGERS_*`.
- Models: `REPLY_LLM_PROVIDER`, `PROFILE_LLM_PROVIDER`,
  `EDITORIAL_OLLAMA_MODEL`, `EDITORIAL_LLM_TIMEOUT_SECONDS`.
- Lowering `MAX_ORIGINALS_PER_DAY` below 8.

What cannot be tuned from `.env`: the eight-post
ceiling, the twenty-minute spacing floor between originals, quotes and reposts at
zero, and waking hours. They live in `src/core/config.py`,
`src/guards/action_guard.py` and `src/guards/active_hours.py`; changing them
needs an operator request and an update to
[EDITORIAL_POLICY.md](EDITORIAL_POLICY.md).

To stop one job, remove its `add(...)` line in `build_scheduler()` and
restart.

## State files

JSON files at the repo root are live state. Keep them across deploys and out
of unrelated commits. Git tracks some of them, including `action_ledger.json`,
`following_count.json` and `respect_list.json`, with stale copies: a
`git checkout`, `reset` or `pull` that touches them overwrites live state.
`action_ledger.json` keeps its name but holds one JSON object per line since
issue #147. A ledger in the former format, one JSON list like the committed
copy, is still read, and the first write after a restart converts it in place
without dropping a row (`[LEDGER] Converted N rows` in `bot.log`); the same
write then drops the rows past 90 days. The bot indexes the rows it has read
and, at each check, reads only the lines added since; a restored copy or a
file cut shorter is read again in full. An edit in place that keeps every
line's length can go unseen until the next restart: edit the ledger with the
bot stopped.

The JSON files in `src/` go through the state store
(`src/core/state_store.py`), except the action ledger and the Replied store,
which keep their own implementations. The store
writes atomically (temp file, full fsync, rename, directory flush), changes a
file shared by several jobs under that file's lock, and gives each file one
policy.
A missing file reads as empty or default under both policies. A *guarded*
file that does not parse, or whose top-level JSON type is wrong, raises
`StateUnreadable`: the job that needs it stops, `bot.log` gets a `[STATE]`
error, and the store never writes over the file (see
[Recovery](#recovery)). A *disposable* file in that state reads as empty,
with a `[STATE]` warning, and its next write replaces it.

Files written by active jobs:

| File | Written by | Holds | Policy |
|---|---|---|---|
| `editorial_state.json` | `editorial_bot` | Slots, attempts, feedback, published originals, used sources | guarded |
| `editorial_review.jsonl` | `editorial_bot` | Audit trail of editorial attempts | append-only, outside the store |
| `editorial_reach.json`, `.md` | `reach_report` | Seven-day view report | disposable; `.md` outside the store |
| `action_ledger.json` | `ledger` (`action_guard.record`) | Counted writes and debate turns per author, one JSON object per line, 90 days | own, fails closed |
| `following_count.json` | `follow_policy.adjust_following` (`follow_account`, `bin/mass_unfollow.py`) | Following count used by the follow ceiling | guarded |
| `replied_tweets.json` | `replied_store` (`reply_to_tweet`) | Tweets already answered, by status ID | own, fails closed |
| `tweet_history.json` | `twitter_client` | Published originals, dedup corpus | guarded |
| `engagement_log.csv` | `engagement_log` | Append-only action log | append-only, outside the store |
| `followed_accounts.json` | `follow_policy.record_followed` (`follow_account`) | Accounts followed by the bot or found already followed | guarded |
| `follow_quality_rejects.json` | `follow_policy` quality gate (`follow_account`) | Handles refused by the quality gate, 30 days | disposable |
| `followers_seen.json` | `follow_policy.record_followers` (`followback_job` scrape) | Followers the followers page showed, last seen, 30 days; the proof of a Follow-back | disposable |
| `follow_engagers_state.json` | `follow_engagers_bot` | Daily count, handles already tried | guarded |
| `like_bot_state.json` | `like_bot` | Daily count of like clicks, unconfirmed ones included | guarded |
| `liked_tweets.json` | `like_tweet` | Tweets already liked | disposable |
| `personality.json` | `personality_store` (`engagement_log`) | Per-account interaction dossiers | guarded |
| `pin_history.json`, `pin_daily_state.json` | `pin_bot` | Pin history, one attempt per day; a dry run marks its own `dry_run_date` | guarded |
| `follower_history.json` | `follower_tracker_bot` | Follower count samples | disposable |
| `dynamic_accounts.json` | `feed_sweeper_bot` | Accounts harvested from the feeds | disposable |
| `safari_health.json`, `safari_hygiene_state.json` | `health`, `safari_hygiene` | Failure counters, last Safari restart | disposable |
| `codex_lockout.json` | `llm_client` | End of a codex usage lockout, deleted once past or unreadable | disposable |
| `autonomous_log.md` | `health` | One line per Safari recovery | append-only, outside the store |

Files active code reads but no active job writes:

| File | Read by | Holds | Policy |
|---|---|---|---|
| `respect_list.json` | `respect_list` | Operator-managed respect list | guarded |
| `whitelist.json` | `follow_policy`, `account_curator`, `bin/mass_unfollow.py` | Tiered follow whitelist | guarded |
| `discovered_accounts.json` | `engage_bot`, `reply_agent` | Handles found by the removed discovery agents | disposable |
| `directives.md` | `evolution_store` | Rules the removed evolution agent last wrote | outside the store |
| `pruned_accounts.json`, `reinforced_accounts.json` | `evolution_store` | Handles skipped or weighted by the selectors | disposable |
| `tracked_accounts.json` | `account_curator.tracked_handles` | Scan pool for `early_bird` and `mega_watch` | disposable |
| `engagement_targets_log.json` | `account_curator.run_curator_cycle`, not scheduled | Per-author conversion weights | disposable |
| `replied_back.json` | `follow_policy` (`follow_account`, `follow_engagers_job`) | Frozen Engager list, see below | disposable |

`replied_back.json` has been frozen since 2026-09-23: replyback dedup moved
to the replied store and the Engager list to the ledger's debate turns.
The follow policy still reads it until its entries age out of the
ledger's 90 days; delete it, and the fallback in `follow_policy`,
around 2026-12-22.

The supervisors cite three more root files, kept for them:
`engine_health_alerts.json` (`bin/auto_improve.sh`), `daily_state.json` (a
comment in the launchd plist) and `operator_prompt.md` (`operator_cycle.sh`).
No code reads `live_strategy.json` since issue #170: the operator can
delete it.

A module declares a new state file once, as a `StateFile` with its default
and its policy. Guarded suits a guardrail, or a record that alone stops a
write action from repeating or exceeding a cap; disposable suits what the
bot can lose without acting more. Tests redirect `state_store.ROOT` to a
temp directory, so a declared file never reaches the live one.

Run `git status` before `git pull`: a pull that deletes a file modified in
the checkout stops until that file is moved aside
([2026-09-23 root cleanup](HISTORY.md)). `debate_state.json` is untracked
and unused since debate turns moved to the ledger; it can be deleted.

## Legacy tools

- `bin/auto_improve.sh` exits unless `AUTO_IMPROVE_FORCE=1`; its prompt
  describes the old system. `operator_cycle.sh` runs only with
  `ENABLE_CODEX_OPERATOR=1` or `ENABLE_AI_MAINTENANCE=1`.
- `bin/mass_unfollow.py` unfollows by hand from `/following`. It refuses to
  run while the bot runs, unless `--force`, and records each unfollow in the
  ledger. Keep the bot stopped even with `--force`: the ledger has a single
  writer, and a row written beside the running bot can be lost. It drives
  Safari through the `safari` primitives and checks the bot's Toronto clock:
  it refuses to start Overnight and stops before its next unfollow at 23:30
  or on SIGTERM. A primitive also refuses to start a page script at that
  point; between a click and its confirm, the run then ends with the modal
  open and nothing unfollowed or recorded, and the next run cancels that
  modal before its first pick. A page script that gets no answer prints
  `JS err: OSAERR:no answer from Safari`; the osascript error, when there is
  one, follows in the same output under `[MASS_UNFOLLOW]` and is also in
  `bot.log`. `--max` defaults
  to 150. A rate limit triggers a cooldown, never an abort. A missing or
  unreadable `whitelist.json`, or an unreadable `respect_list.json` with
  `--keep legacy`, aborts the run before Safari; a missing
  `respect_list.json` reads as empty.
  `mass_unfollow_results.json` is rewritten after every unfollow.
- `bin/seed_fr_influencers.py` is a one-off from the French era.

## Skills

The operator skills live in `.claude/skills/` only; `.codex/skills` is a
relative symlink to it and OpenCode reads `.claude/skills` natively. They
match the 2026-09-20 policy: none drives a disabled surface. The manual
write skills follow [Manual writes](#manual-writes).

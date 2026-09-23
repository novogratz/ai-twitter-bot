# Operations

Running, watching and recovering the bot under the 2026-09-20 policy. The
design is in [ARCHITECTURE.md](ARCHITECTURE.md), the rules in
[EDITORIAL_POLICY.md](EDITORIAL_POLICY.md).

The bot publishes on a real account. Start, stop and restart it only when the
operator asks.

## Setup

Requirements: macOS, Safari logged in to x.com with **Develop → Allow
JavaScript from Apple Events** enabled, Python 3.12+,
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
- `LLM_DISABLE_FALLBACK=1` if originals must never leave the machine. An
  empty `LLM_FALLBACK_CLI` still falls back to codex; the
  `LLM_ALLOW_REMOTE_FALLBACK` variable mentioned in the example does not
  exist in the code.

`src/config.py` loads `.env` without overriding variables already set in the
shell. Check the setup without a browser or a model:

```bash
uv run --with-requirements requirements.txt python main.py --dry-run
```

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
other mode; `--monthly-recap-now` and the startup bursts are gone.

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
comes back.

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
  the bot roughly every 15 minutes between 22:00 and 04:30; each restart
  comes back asleep.
- **`bot_watchdog.sh`** (repo root): legacy, runs from `$HOME/ai-twitter-bot`
  and exports old LLM variables.

## Watching

| Where | What it tells you |
|---|---|
| `bot.log` | Runtime activity. Useful tags: `[HOURS]`, `[EDITORIAL]`, `[POST]`, `[REPLY]`, `[REPLYBACK]`, `[VIP]`, `[DEBATE]`, `[FOLLOW]`, `[LIKE]`, `[PIN]`, `[HYGIENE]`, `[HEALTH]` |
| `editorial_state.json` | Today's attempts per slot, slots `pending` or `published`, recent publications and used sources |
| `editorial_review.jsonl` | One line per reviewed draft: draft, source, approval, rejection reason |
| `editorial_reach.md` | Observed views of the last seven days of originals against the 500,000 target, with missing coverage |
| `action_ledger.json` | Every counted write with its Toronto timestamp; the source of today's budget |

```bash
tail -F bot.log | grep -E '\[(HOURS|EDITORIAL|POST)\]'
tail -n 5 editorial_review.jsonl | jq '{ts, slot, approved, reason}'
jq '{date, slots, attempts}' editorial_state.json
```

Silence between 22:00 and 04:30 Toronto time is normal. There is no
heartbeat line.

## Recovery

**A slot is `pending`.** The submission was interrupted or its outcome was
unclear, and the bot will not retry it. Check the profile first. If the post
is live, set the slot to `"published"` in `editorial_state.json` and append
a matching entry (`ts`, `text`, `source_url`, `angle`, `slot`) to
`published`, so the source rests for seven days and the reach report counts
the post. If it is not live, delete the slot entry. Do this with the bot
stopped.

**Corrupt `editorial_state.json` or `action_ledger.json`.** Both fail closed:
the editorial cycle errors out and the ledger refuses writes. Repair the JSON
by hand, keeping today's entries, or restore a copy taken today. Never delete
the ledger or restore it from git: the committed `action_ledger.json` dates
from July 2026, and either move resets today's count and grants extra posts.

**x.com renders a blank page.** After 3 consecutive empty scrapes across at
least 2 different pages (2 in a row on the home feed), `twitter_client`
restarts Safari with a 5-minute cooldown. Blank pages in the 120 seconds after
a restart and an empty mentions tab do not count. `health` also restarts
Safari after 3 failed cycles in a row, all jobs counted together, and
`session_refresh_job` does it preventively every 2 hours; both wait 30 minutes
after the last restart. Each relaunch
clears x.com service workers and caches. To do it by hand, stop the bot first:

```bash
osascript -e 'tell application "Safari" to quit'
sleep 3 && open -a Safari
```

**No original today.** Read `editorial_review.jsonl` for review rejections,
then the `[EDITORIAL]` and `[POST]` lines of `bot.log` and `attempts` in
`editorial_state.json`. Causes that leave no audit line: the one-hour spacing
or the daily ceiling, sources that could not be fetched, attempts spent, a
model error. The evergreen documentation pages always supplement the news, so
a quiet news day alone does not block a post. Missed slots are not caught up.

**Unwanted content.** Add the handle to the respect list
(`python3 -c "from src.respect_list import add; add('handle', 'reason')"`,
picked up at the next prompt) or to `BLOCKLIST` in `src/config.py` (restart
needed). Both are operator-managed. The respect list only reaches prompts that
include the hard rules: debate and VIP replies ignore it (see
[ARCHITECTURE.md](ARCHITECTURE.md#known-gaps)).

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
- Lowering `MAX_ORIGINALS_PER_DAY` below 7.

What cannot be tuned from `.env` or `live_strategy.json`: the seven-post
ceiling, the one-hour spacing floor between originals, quotes and reposts at
zero, and waking hours. They live in `src/config.py` and
`src/active_hours.py`; changing them needs an operator request and an update
to [EDITORIAL_POLICY.md](EDITORIAL_POLICY.md). Among active jobs, only
`like_job` still reads `live_strategy.json`.

To stop one job, remove its `add(...)` line in `build_scheduler()` and
restart.

## State files

JSON files at the repo root are live state. Keep them across deploys and out
of unrelated commits. Git tracks some of them, including `action_ledger.json`,
`following_count.json` and `respect_list.json`, with stale copies: a
`git checkout`, `reset` or `pull` that touches them overwrites live state.
Files written by active jobs:

| File | Written by | Holds |
|---|---|---|
| `editorial_state.json` | `editorial_bot` | Slots, attempts, feedback, published originals, used sources |
| `editorial_review.jsonl` | `editorial_bot` | Audit trail of editorial attempts |
| `editorial_reach.json`, `.md` | `reach_report` | Seven-day view report |
| `action_ledger.json` | `action_guard` | Counted writes, 90 days |
| `following_count.json` | `action_guard` | Following count used by the follow ceiling |
| `replied_tweets.json` | `reply_to_tweet`, `direct_reply` | Tweets already answered |
| `replied_back.json` | `notify_bot` | Replyback dedup, source for `follow_engagers_job` |
| `tweet_history.json` | `twitter_client` | Published originals, dedup corpus |
| `engagement_log.csv` | `engagement_log` | Append-only action log |
| `followed_accounts.json` | follow paths | Accounts followed by the bot |
| `follow_quality_rejects.json` | `follow_account` | Handles refused by the quality gate, 30 days |
| `debate_state.json` | `debate_bot` | Turns per author per day |
| `follow_engagers_state.json` | `follow_engagers_bot` | Daily count, handles already tried |
| `like_bot_state.json` | `like_bot` | Daily like count |
| `pin_history.json`, `pin_daily_state.json` | `pin_bot` | Pin history, one attempt per day |
| `follower_history.json` | `follower_tracker_bot` | Follower count samples |
| `dynamic_accounts.json` | `feed_sweeper_bot` | Accounts harvested from the feeds |
| `safari_health.json`, `safari_hygiene_state.json` | `health`, `safari_hygiene` | Failure counters, last Safari restart |

Most other JSON files at the root belong to legacy jobs and no longer change.

## Legacy tools

- `bin/auto_improve.sh` exits unless `AUTO_IMPROVE_FORCE=1`; its prompt
  describes the old system. `operator_cycle.sh` runs only with
  `ENABLE_CODEX_OPERATOR=1` or `ENABLE_AI_MAINTENANCE=1`.
- `bin/mass_unfollow.py` unfollows by hand from `/following`. It refuses to
  run while the bot runs, unless `--force`, and records each unfollow in the
  ledger.
- `bin/seed_fr_influencers.py` is a one-off from the French era.
- The skills in `.claude/skills/` and `.codex/skills/` predate the policy.
  Several drive disabled surfaces (`retweet`, `thread`) or reset counters
  (`reset`). Read a skill against the policy before running it.

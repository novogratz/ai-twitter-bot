# @TheAIShrink — AI knowledge, useful updates, and conversation

A Safari-driven AI account with the voice of a confident, warm, playfully flirty
40-year-old mom: sexy, funny, sarcastic, and deeply knowledgeable about AI
models and news. She also loves AI-generated videos, which the account has
started publishing. The bot aims to give readers something useful in
every post and respond naturally in conversations. That Voice lives only in
the Account's folder, `accounts/theaishrink/voice_fr.md` (`voice_en.md` for
English prompts): every post and reply prompt carries it as one block.

## Current publishing policy

- **Active daily: 05:00–10:00, 14:00–15:00, 17:00–19:00, 22:00–24:00 America/Toronto**, with daylight saving handled automatically.
- **At least three original posts targeted; six planned; eight is the hard daily ceiling.** Weak drafts are skipped.
- **At most ten replies per Toronto day**, only to other accounts’ standalone posts.
  Never answer our own posts or comments on them. Spacing and duplicate protection remain.
  Reply scans save posts to a shared pool; a ten-minute selector compares them
  and drafts at most one candidate scoring 85/100 or higher. Every reply passes Reply admission before generation (before sending for
  the optional search job, whose one model call finds and drafts together)
  and again at the write: blocked accounts, the account's own posts and links without an
  author handle are refused. Every reply prompt carries the Voice, the
  operator's hard rules and the respect list, and a reply or original that
  names a Respected account is refused at the write, dry run included; a
  reply may still address the Respected account it answers by its `@handle`.
  If the replied store (`replied_tweets.json`) is unreadable, no reply ships until
  it is repaired ([recovery](docs/OPERATIONS.md#recovery)).
- **Replies, likes and follows keep to AI**: `[niche]`, `[searches]` and `[network]`
  in `account.toml` ([policy](docs/EDITORIAL_POLICY.md#niche-of-replies-likes-and-follows)).
- **One Startup post each time the bot starts in waking hours**, restarts included,
  within the daily ceiling and the twenty-minute spacing. A submission with an
  ambiguous outcome counts toward both until the operator clears it.
- **No automatic quote tweets, reposts, self-recycling, or burst threads.**
- Every scheduled original uses a fetched trusted source, prefers fresh AI
  launches/articles when available, carries a specific takeaway, duplicate
  checks, and a separate editorial review before publishing.
- The 500,000-view target is tracked using observed views of originals published
  in the last seven days. Public view counters cannot identify home-timeline views.

The bot stays idle overnight and resumes automatically. Browser operations and
model calls check the waking window too, so a queued daytime task cannot start
a new action outside those four windows. An already-issued request may still finish remotely.

## Daily editorial mix

| Toronto time | Reader value |
|---|---|
| 05:00 | Priority AI update worth understanding |
| 07:15 | A practical AI workflow |
| 09:30 | Priority AI article or model update with a sharp consequence |
| 09:45 | Trend: the AI topic X is talking about, told from a trusted article |
| 14:00 | A clear explanation of an AI concept |
| 14:20 | Trend |
| 14:40 | A model or tool update and its consequences |
| 17:00 | Trend |
| 17:45 | Priority informed take on an AI tradeoff |
| 18:30 | An idea worth saving or sharing |
| 22:15 | Optional post for an exceptional update or unusually useful source |

Each slot has a short retry window and missed slots are not caught up. Every
start in waking hours opens one extra trend post, the Startup post. Eleven
slots plus the Startup post compete for eight publications a day. Trend posts
pick their topic from the five fastest-rising AI posts on X from the last 24
hours; the facts and the link still come from a trusted article.
Originals have their own scheduler worker so reply scans cannot starve them.
See [editorial policy](docs/EDITORIAL_POLICY.md) for review and recovery details.

## Run

Requires macOS, Safari with JavaScript from Apple Events enabled (it need not be
the default browser: the bot opens every page in Safari), Python 3.12+,
[uv](https://docs.astral.sh/uv/), and the configured local Ollama models. Originals use `gemma4:31b` by default
(`EDITORIAL_OLLAMA_MODEL`); replies use `OLLAMA_MODEL` (default
`qwen3.6:35b-a3b`), the model `bin/run.sh` pre-warms. With the
default providers, no call leaves Ollama unless `LLM_FALLBACK_CLI` names a
fallback, codex for instance, with one exception: the Replies to @Graphseo run
on the Claude CLI whenever it is installed (his Relation's `provider` in
`account.toml`). A CLI runs `NEWS_MODEL`,
`REPLY_MODEL` or `PRIORITY_REPLY_MODEL` when set, else its own default
(`settings.MODEL_DEFAULTS`). An unknown provider name fails the
call and is logged at start, as is a fallback the code ignores.

```bash
uv venv && uv pip install -r requirements.txt
cp .env.example .env
# A new install only; an existing checkout migrates (docs/OPERATIONS.md#deploying-issue-207).
mkdir -p state/theaishrink
[ -e state/theaishrink/whitelist_discovered.json ] || echo '[]' > state/theaishrink/whitelist_discovered.json
uv run python main.py
```

`.env.example` describes @TheAIShrink with the policy values, its bounded
settings commented out at their default, since `.env` would win over an
Account's `[limits]`; every setting, its default and bounds are in
[`docs/CONFIGURATION.md`](docs/CONFIGURATION.md).
`.env` is read once at start, so any change needs a restart: a key the engine
does not know, or a badly typed value, stops the start with a message naming
the key, and `--dry-run` names the same keys.

One process runs one Account. `BOT_ACCOUNT` (default `theaishrink`) picks
`accounts/<name>/account.toml`, which holds the handle, the language of the
Originals, the domain its prompts name, the Slots and their angles, the
feeds, Evergreen topics, trusted hosts, the relevance filter and the
searches of the Trending posts, and the network and niche the reply, like and
follow jobs use: handle lists, niche patterns, X searches, and the Blocked
accounts it adds to the engine's `BLOCKLIST`, which it can never shrink. It
also holds the Relations: the prompt, provider or dossier the Replies give a
particular account, by handle, and the default prompt of the VIP scan, in
`relations/`. The Voice files sit next to it. It is read once at start, like
`.env`: a
missing Account, an unknown key or a badly typed value stops the start with a
message naming the file and the key. Its `[limits]` may tighten an engine
ceiling or floor, never lift it; a value past the bound is brought back to it
with a `[SETTINGS]` warning. `.env` still wins over the Account.
The engine names no account: `accounts/example/`, a fictitious gardener with
no Relation, runs with `BOT_ACCOUNT=example` and serves as the template of a
new Account ([Creating an Account](docs/OPERATIONS.md#creating-an-account)).

```bash
uv run --with-requirements requirements.txt python main.py --dry-run  # print policy/jobs/bounded settings and exit; no browser or LLM
uv run --with-requirements requirements.txt python main.py --reply-only  # daytime conversations only
uv run --with-requirements requirements.txt python main.py --post-only   # editorial originals only
uv run --with pytest --with-requirements requirements.txt python -m pytest tests/ -q
```

`bot.log`, at the root, contains runtime activity. The state of the Account
lives in `state/<BOT_ACCOUNT>/`: there, `editorial_review.jsonl` records
decisions; `editorial_state.json` persists attempts, completed slots and
source history; `editorial_reach.md` shows measured reach and missing
coverage. These are local runtime files and are not committed to Git; a
checkout from before issue #207 moves its root copies to
`state/theaishrink/` with `bin/migrate_state.py`, and `main.py` refuses to
start until it has. The
JSON state files go through `src/core/state_store.py`, which writes them atomically; an unreadable
guarded file, such as `personality.json`, stops the job that needs it and
is never overwritten ([recovery](docs/OPERATIONS.md#recovery)). The
Operator's follow whitelist, respect list and following baseline live in the
Account folder, versioned; the bot reads them and never writes them, and one
missing or unreadable stops the job that needs it. While the following count
(`following_count.json`, else `followed_accounts.json`) or the whitelist
(`whitelist.json` in the Account folder, `whitelist_discovered.json` for the
handles the curator promoted) is missing or unreadable, every follow is
refused; it also stops `bin/mass_unfollow.py`.

Scheduled jobs are defined in `main.py`. `src/editorial/editorial_bot.py`
handles source selection, drafting and review, from the Account that
`src/core/account.py` loads. `src/guards/active_hours.py`
owns the Toronto clock. `src/guards/action_guard.py` and
`src/x/twitter_client.py` enforce limits at the browser boundary, from the
writes recorded in the action ledger (`src/guards/ledger.py`).
`src/guards/follow_policy.py` decides every follow and names why one is
refused. It finds the handle's relation with the account itself, from the
whitelist, the ledger's Debate turns and the followers the followers page
showed (`followers_seen.json`): a Stranger is never followed, whichever job
asks, and neither is a Blocked account, matched as Reply admission matches
it. `follow_account` alone adds an account followed, or found already
followed, to `followed_accounts.json`. `follow_engagers_job` follows through
a Follow run (`src/account/follow_run.py`), which skips those accounts
before any profile opens. The reply
jobs live in `src/replies/`, the follow, like, pin and follower-count jobs in
`src/account/`, and shared foundations in `src/core/`. The legacy
content modules are gone (issue #110): every module under `src/` is reached
from `main.py`. The quote, repost, thread and GIF write functions are removed
from `src/x/twitter_client.py` (issue #111), and the scheduled jobs carry no
such branch.

Autonomous prompt/code rewriting is excluded from the active scheduler. Old
`.env` or strategy values cannot lift the eight-post ceiling or restore quotes.
The configured reply provider and browser pacing still apply.

## License

[MIT](LICENSE) — © 2026 Benoit Floch.

2026-10-07 — Operator requested restoration of the code that was on main on
September 26, 2026. The last main commit before September 27 in Toronto time
was 348c82bc (September 25 at 21:18); no September 26 commit exists. Tracked
code, Account files, tests and documentation return to that snapshot. This
explicit rollback supersedes later behavior mandates and restores the snapshot's
checks and settings, including its Reply behavior without the later independent
Reply quality review. Production state, .env and untracked files are preserved.
The running bot is not restarted; deployment takes effect on the next explicitly
requested start or restart.

2026-10-08 — Operator requested selective engagement after account growth.
All external bot activity is limited to Toronto windows 05:00–10:00,
14:00–15:00, 17:00–19:00 and 22:00–24:00 (end exclusive). Replies have a
hard ceiling of ten shipped replies per Toronto calendar day across all jobs;
configuration may only tighten it. Existing shipped ledger rows count.
Reply only to other accounts' standalone posts: never own posts, comments on
own posts, or nested conversation turns. The write chokepoint verifies the
opened target and refuses unreadable or non-standalone pages. Replyback,
Debate, babysitter and notification jobs are no longer scheduled. Their
shared pipeline also refuses conversation-context candidates.
Editorial slots move inside active windows; existing publication caps,
spacing, sourcing and review remain. Replies must earn their place with a
specific insight or apt wit, vary length naturally, use no emojis and skip
unsupported current news claims. The Account Voice is enthusiastically
pro-Elon Musk, Grok, xAI and SpaceX; Grok/Imagine recommendations must be
relevant and grounded, without invented personal use or celebrity engagement
claims. Code/config deployment takes effect at the next explicitly requested
restart; this change does not restart the running process.

Ambiguous Reply submissions are reserved in guarded `reply_submissions.json` before submit and count toward the ten-per-day budget across restarts. Only confirmed writes enter the ledger; confirmed reservations are released after recording. Check X before clearing an ambiguous reservation.

2026-10-08 — Operator requested saving discovered posts and choosing Replies
from a shared pool. Reply scans now collect only: every discovered post is
saved before filters, keyed by status ID, with the full text exposed by the
browser, source and engagement counts. `reply_archive.jsonl` permanently keeps
discoveries and selection decisions. Guarded `reply_candidates.json` holds the
last day’s discoveries and their eligibility, score, reason, proposed angle
and outcome. Own posts, comments and off-niche posts are saved without making
them eligible. A shared `reply_selection_job` runs every ten minutes, after a
one-minute collection delay, and compares up to thirty admitted posts per
review. The batch mixes ten waiting discoveries with twenty fresh opportunities before revisiting reviewed posts; the
highest fresh score across the reviewed pool wins. Only scores of at least
85/100 may reach drafting, one post per selector cycle, and the model may
reject every post. Scans never consume reply budget or draft replies. The
selector rechecks admission before drafting and every write retains the
standalone-page check and the ten-per-day ceiling including ambiguous
submissions. Nothing is automatically retried from `processing` after a crash;
check X and the Replied store before repairing its pool status. An unreadable
pool or an unsavable archive stops collection/selection without overwriting
state. Existing active windows, caps and evidence rules remain. No live X
writes or restart are performed by this implementation.

Reply selection releases the day’s budget gradually across the active windows: with a ten-reply ceiling, one more allowance opens per active hour (05:00, 06:00, 07:00, 08:00, 09:00, 14:00, 17:00, 18:00, 22:00, 23:00). Unspent allowances carry forward that day; no post must be answered to fill them. Tighter daily caps scale the allowance proportionally.

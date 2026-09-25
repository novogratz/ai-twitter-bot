# @TheAIShrink — AI knowledge, useful updates, and conversation

A Safari-driven AI account with the voice of a confident, warm, playfully flirty
45-year-old mom who loves AI. The bot aims to give readers something useful in
every post and respond naturally in conversations. That Voice lives only in
the Account's folder, `accounts/theaishrink/voice_fr.md` (`voice_en.md` for
English prompts): every post and reply prompt carries it as one block.

## Current publishing policy

- **Active daily: 04:30–23:30 America/Toronto**, with daylight saving handled automatically.
- **At least three original posts targeted; six planned; eight is the hard daily ceiling.** Weak drafts are skipped.
- **Unlimited replies during waking hours**, with spacing and duplicate protection.
  Every reply passes Reply admission before generation (before sending for
  the optional search job, whose one model call finds and drafts together)
  and again at the write: blocked accounts, the account's own posts and links without an
  author handle are refused. Every reply prompt carries the Voice, the
  operator's hard rules and the respect list, and a reply or original that
  names a Respected account is refused at the write, dry run included; a
  reply may still address the Respected account it answers by its `@handle`.
  If the replied store (`replied_tweets.json`) is unreadable, no reply ships until
  it is repaired ([recovery](docs/OPERATIONS.md#recovery)).
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
a new action after 23:30. An already-issued request may still finish remotely.

## Daily editorial mix

| Toronto time | Reader value |
|---|---|
| 05:00 | Priority AI update worth understanding |
| 07:15 | A practical AI workflow |
| 09:30 | Priority AI article or model update with a sharp consequence |
| 10:00 | Trend: the AI topic X is talking about, told from a trusted article |
| 11:45 | A clear explanation of an AI concept |
| 13:00 | Trend |
| 14:00 | A model or tool update and its consequences |
| 15:00 | Trend |
| 16:15 | Priority informed take on an AI tradeoff |
| 18:30 | An idea worth saving or sharing |
| 20:45 | Optional post for an exceptional update or unusually useful source |

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
uv run python main.py
```

`.env.example` describes @TheAIShrink with the policy values; every setting,
its default and bounds are in [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md).
`.env` is read once at start, so any change needs a restart: a key the engine
does not know, or a badly typed value, stops the start with a message naming
the key, and `--dry-run` names the same keys.

One process runs one Account. `BOT_ACCOUNT` (default `theaishrink`) picks
`accounts/<name>/account.toml`, which holds the handle, the language of the
Originals, the Slots and their angles, the feeds, Evergreen topics, trusted
hosts and the relevance filter, and the network and niche the reply, like and
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

```bash
uv run --with-requirements requirements.txt python main.py --dry-run  # print policy/jobs and exit; no browser or LLM
uv run --with-requirements requirements.txt python main.py --reply-only  # daytime conversations only
uv run --with-requirements requirements.txt python main.py --post-only   # editorial originals only
uv run --with pytest --with-requirements requirements.txt python -m pytest tests/ -q
```

`bot.log` contains runtime activity. `editorial_review.jsonl` records decisions;
`editorial_state.json` persists attempts, completed slots and source history;
`editorial_reach.md` shows measured reach and missing coverage. These are local
runtime files and are not committed to Git. The JSON state files go through
`src/core/state_store.py`, which writes them atomically; an unreadable
guarded file, such as `personality.json`, stops the job that needs it and
is never overwritten ([recovery](docs/OPERATIONS.md#recovery)). The
Operator's follow whitelist, respect list and following baseline live in the
Account folder, versioned; the bot reads them and never writes them, and one
missing or unreadable stops the job that needs it. While the following count
(`following_count.json`, else `followed_accounts.json`) or the whitelist
(`whitelist.json` in the Account folder, `whitelist_discovered.json` for the
handles the curator promoted) is unreadable, every follow is refused; an
unreadable whitelist also stops `bin/mass_unfollow.py`.

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
followed, to `followed_accounts.json`. The reply
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

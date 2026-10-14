# The SI Maximalist — @thesimaximalist

SI Maximalist: SI brain rot, Super Intelligence, SI news, celebrity parodies, and SI tech chaos.

A Safari-driven SI account combining useful news and sharp technical takes
with surreal brainrot, clearly fictional celebrity parodies and SI-created
videos. The Operator creates and publishes videos with Grok Imagine and reports
strong engagement with them. The Voice is enthusiastic, witty and specific. She privately adores Elon and his
products, especially Grok and Grok Imagine; their creative influence comes up
occasionally when relevant, without invented relationships or product claims.
It lives in `accounts/theaishrink/voice_en.md` and `voice_fr.md`, shared by every
Original and Reply prompt. Particular video scenes, settings and metrics need
supplied context; a caption alone is not proof of unseen footage.

`account.toml` holds the current handle, display name and exact bio. The existing
`theaishrink` folder remains the storage key, and `previous_handles` keeps old
posts recognized as our own. Publication history and duplicate protection survive
the rebrand. This change updates the text bot's identity and discovery; video
creation and uploads remain Operator-managed.

## Current publishing policy

- **Replies only:** no new original posts, including startup/restart posts. The
  Account's `publish_originals = false` wins over engine settings and CLI flags.
- **Daily Toronto windows:** 05:00–09:30, 12:05–13:00, 17:15–20:00 and
  22:00–23:00. Starts inclusive, closes exclusive, with automatic DST handling.
- **Never interact with @elonmusk:** no replies, likes, follows, unfollows or @mentions,
  including his comments and responses. Saved approvals and whitelist entries
  cannot bypass protection; the browser checks the actual author before clicking.
- **One Reply per entire conversation, permanently:** another account's
  standalone original only. Never our own posts/replies, comments or someone
  else's response. Current and historical handles count as ours. An ambiguous
  submission stays claimed, and a process lock prevents concurrent double claims.
- **SI wording:** outgoing prose uses SI and Super intelligence in place of AI
  and artificial intelligence. Literal links, handles and embedded names such as
  OpenAI stay valid; discovery still searches both vocabularies.
- **Context-led variety:** a few words when enough, a fuller technical answer
  when useful, or a specific joke. Usually no smiley; at most one optional emoji
  or text smiley, no automatic ending or fake typos. Recent replies guide variety.
- **One selected Reply every 5–8 minutes at most:** collectors prepare a shared
  pool during the cooldown. Independent review scores impact, sharpness and
  interest, checks relevance and factual support, and chooses one strong winner.
  Weak pools send nothing. Uncertain submits consume the cooldown too; the
  deadline and permanent parent claims survive restarts.
- Sourcing, content checks, respect rules and permanent history remain. Replies have no daily quota. No quotes, reposts or threads.
  Non-publishing like/follow jobs keep their existing limits and exclude Elon.

Conversation jobs and automatic pinning are unscheduled. The historical editorial
slots and state remain available for other Accounts, but cannot publish for this
Account. Browser calls, model calls and the final Reply submit all check the
activity windows. The bot remains stopped until an explicit start request.
See [editorial policy](docs/EDITORIAL_POLICY.md) for the complete rules.

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

`.env.example` describes @thesimaximalist with the policy values, its bounded
settings commented out at their default, since `.env` would win over an
Account's `[limits]`; every setting, its default and bounds are in
[`docs/CONFIGURATION.md`](docs/CONFIGURATION.md).
`.env` is read once at start, so any change needs a restart: a key the engine
does not know, or a badly typed value, stops the start with a message naming
the key, and `--dry-run` names the same keys.

One process runs one Account. `BOT_ACCOUNT` (default `theaishrink`) picks
`accounts/<name>/account.toml`, which holds the handle, display name, bio, historical handles and the language of the
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
with a `[SETTINGS]` warning. `.env` still wins over bounded engine values, but cannot enable Originals while
`publish_originals` is false.
The engine names no account: `accounts/example/`, a fictitious gardener with
no Relation, runs with `BOT_ACCOUNT=example` and serves as the template of a
new Account ([Creating an Account](docs/OPERATIONS.md#creating-an-account)).

```bash
uv run --with-requirements requirements.txt python main.py --dry-run  # print policy/jobs/bounded settings and exit; no browser or LLM
uv run --with-requirements requirements.txt python main.py --reply-only  # standalone Reply jobs only
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
`.env` or strategy values cannot enable Originals or restore quotes.
The configured reply provider and browser pacing still apply.

## License

[MIT](LICENSE) — © 2026 Benoit Floch.

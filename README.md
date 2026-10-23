# The SI Maximalist · @thesimaximalist

A Safari-driven SI account with the voice of a fictional, sharp, warm and funny
45-year-old woman. She loves SI tools and news, the Musk/X/SpaceX ecosystem,
and especially Grok Imagine. Every reply aims for one useful observation in
natural, conversational English. Facts stay grounded and bot identity stays
honest. The Voice lives in `accounts/theaishrink/voice_en.md`; the old folder
name preserves the existing state and history after the account rename.

## Current publishing policy

- **English only:** every Original and Reply, including responses to French
  parents and VIPs. The Account's `english_only` policy controls prompts and
  final publication checks; uncertain language is skipped.
- **Sleep from midnight to 04:30 Toronto time.** The scheduler, browser writes,
  model timeouts and Startup windows all use this boundary.
- **Ten-minute breaks in most waking hours.** A shared, repeatable daily plan
  varies the start within minutes 35–50 and skips roughly one hour in four.
  Jobs, model requests and browser activity stop during a break.
- **Read both For You and Following deeply.** Verify the selected tab, collect
  each screen before scrolling, and deduplicate posts. The Account allows
  up to 20 scrolls and 160 collected posts per feed, stopping if no new posts
  appear. Both reads finish before Reply generation starts, so an exhausted
  model quota cannot skip Following. Generation budgets and publication limits
  still apply; sleep and breaks can interrupt discovery.
- **Watch new Elon Musk originals every minute.** A dedicated Latest search
  attempts one like, repost and Reply independently. First enable starts with
  new posts; later passes inspect up to 20 posts from the past 24 hours.
  Existing content checks, Reply dedup, sleep and breaks apply. Reposts consume
  the same daily publication budget and spacing as Originals; uncertain
  repost submissions remain reserved across restarts. Browser contention can
  delay a poll, and policy limits may defer or skip an action.
- **One Reply per original, ever.** Never answer our own posts or replies,
  comments or ongoing debates. Debate, replyback and babysitter jobs are
  disabled. The browser verifies the actual parent and clicks its own Reply
  button. History survives restarts without eviction; uncertain submissions
  stay claimed. Current and historical account handles are protected.
- **A sharper SI voice:** a fictional 45-year-old mom with confident, playful
  adult charm. Give one technically precise observation or useful implication
  that sparks curiosity, backed by evidence. No invented experience, insider
  claims or pretending to know everything.
- **SI wording everywhere we publish:** standalone AI becomes SI, and Artificial
  Intelligence becomes Super Intelligence. `publication_si_wording` applies
  during drafting, before editorial review, and at final publication checks. URLs, @handles, names such as OpenAI and French verb
  forms such as j'ai stay intact.
- **AI and SI in research:** searches and relevance filters retain AI and
  Artificial Intelligence and also recognize SI, Super Intelligence,
  superintelligence and ASI. Source evidence keeps its original wording;
  the preferred terms are not claims of an achieved capability.
- **Active daily: 04:30–00:00 America/Toronto**, with daylight saving handled automatically.
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
- **Discovery covers SI and the named Musk/X/SpaceX ecosystem**: `[niche]`, `[searches]` and `[network]`
  in `account.toml` ([policy](docs/EDITORIAL_POLICY.md#niche-of-replies-likes-and-follows)).
- **One Startup post each time the bot starts in waking hours**, restarts included,
  within the daily ceiling and the twenty-minute spacing. A submission with an
  ambiguous outcome counts toward both until the operator clears it.
- **No automatic quote tweets, self-recycling, or burst threads.** Reposts are
  restricted to `auto_engage_handles`, currently only `elonmusk`.
- Every scheduled original uses a fetched trusted source, prefers fresh AI
  launches/articles when available, carries a specific takeaway, duplicate
  checks, and a separate editorial review before publishing.
- The 500,000-view target is tracked using observed views of originals published
  in the last seven days. Public view counters cannot identify home-timeline views.

The bot stays idle overnight and resumes automatically. Browser operations and
model calls check the waking window too, so a queued daytime task cannot start
a new action after 00:00. An already-issued request may still finish remotely.

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

The operator's October 23 response configuration uses Codex `gpt-6.1-sol`
with xhigh reasoning effort for all Replies, including VIP Relations.
Set `AI_CLI=codex`, `REPLY_LLM_PROVIDER=codex`, both `REPLY_MODEL` and
`PRIORITY_REPLY_MODEL` to `gpt-6.1-sol`, and `CODEX_REASONING_EFFORT=xhigh`.
`LLM_DISABLE_FALLBACK=1` prevents a quota lockout from routing back to Ollama.
Originals retain `PROFILE_LLM_PROVIDER=ollama`. Codex must be installed and
signed in; these settings take effect at the next explicitly requested restart.

Requires macOS, Safari with JavaScript from Apple Events enabled (it need not be
the default browser: the bot opens every page in Safari), Python 3.12+,
[uv](https://docs.astral.sh/uv/), and the configured local Ollama models. Originals use `gemma4:31b` by default
(`EDITORIAL_OLLAMA_MODEL`). For Accounts selecting Ollama Replies,
`OLLAMA_MODEL` defaults to `qwen3.6:35b-a3b`, the model `bin/run.sh`
pre-warms. The live `.env` and template select Codex Replies as above.
With the engine's default providers, calls use Ollama unless `LLM_FALLBACK_CLI` names a
fallback, codex for instance, with one exception: the Replies to @Graphseo run
on the Codex CLI whenever it is installed (his Relation's `provider` in
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
from `main.py`. The legacy quote, general repost, thread and GIF write functions
remain removed (issue #111). The October 23 operator request adds only the
guarded watched-author `repost_tweet` path in `src/x/twitter_client.py`.

Autonomous prompt/code rewriting is excluded from the active scheduler. Old
`.env` or strategy values cannot lift the eight-post ceiling or restore quotes.
The configured reply provider and browser pacing still apply.

## License

[MIT](LICENSE) — © 2026 Benoit Floch.

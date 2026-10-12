# The SI Maximalist — @thesimaximalist

A Safari-driven SI and technology account: SI brainrot, super intelligence,
news, generated media, clearly fictional celebrity parodies and tech chaos.
The voice is an informed, direct, funny commentator who adds a concrete insight
or an apt original joke. The current identity replaces the former therapist
persona in both Voice files; every generation prompt carries that Voice.

The storage key stays `BOT_ACCOUNT=theaishrink` so existing daily counts, reply
deduplication, ambiguous submissions and history survive the handle change.
`account.toml` names `thesimaximalist` and lists the previous handle for own-post
protection. Remove an old `BOT_HANDLE` override from `.env` or update it too.

## Current publishing policy

- **Nominal daily hours: 05:00–10:00, 12:00–13:00 and 16:45–23:00 America/Toronto.**
  Each start varies by up to ten minutes each day; closing times are fixed.
  Daily times survive restarts, and daylight saving is handled automatically.
- **At least three original posts targeted; six planned; eight is the hard daily ceiling.** Weak drafts are skipped.
- **At least 300 useful replies targeted per full Toronto day; 400 is the hard maximum**, only to other accounts’ standalone posts.
  One reply per post, permanently; no debates, follow-ups, own posts or comments on them.
  Spacing and duplicate protection remain.
  Reply scans save posts to a shared pool; a one-minute selector chooses among them
  across the last **24 hours**, including the frequent priority-profile scans;
  there is no 4-, 15- or 18-minute post-age cutoff. It
  drafts at most one candidate explicitly judged on-topic and scoring 85/100 or higher. Every reply passes Reply admission before generation (before sending for
  the optional search job, whose one model call finds and drafts together)
  and again at the write: blocked accounts, the account's own posts and links without an
  author handle are refused. Every reply prompt carries the Voice, the
  operator's hard rules and the respect list, and a reply or original that
  names a Respected account is refused at the write, dry run included; a
  reply may still address the Respected account it answers by its `@handle`.
  If the replied store (`replied_tweets.json`) is unreadable, no reply ships until
  it is repaired ([recovery](docs/OPERATIONS.md#recovery)).
  Selection reviews at most eight candidates per call so the local model can
  finish its structured answer. Logs report review counts, provider errors and
  allowance waits; a failed refresh can still use a current approved candidate.
- **Replies cover AI, SI and substantive technology, including generated videos and brainrot**, with no VIP topic exemptions.
  A specific insight or apt original joke earns a reply; unrelated posts and empty praise are skipped.
  Profile scans start with Elon, then AI researchers, builders and enthusiasts.
  Former crypto/trading targets are blocked. Bitcoin/crypto posts stay excluded
  even when they mention AI; likes check the actual post text, and discovered
  follows and Engagers need AI/SI or technology bios. The voice favors Elon, Grok and SpaceXSI with
  grounded insight and wit ([policy](docs/EDITORIAL_POLICY.md#niche-of-replies-likes-and-follows)).
- **Replies vary in length:** a few words, a short observation, a fuller
  explanation or an occasional apt smiley. Shipped history prevents repeated
  lengths; a smiley cannot be chosen if one appeared in the last twenty replies.
  Reply prose uses **SI / super intelligence**. Discovery searches both AI and SI,
  including SpaceXAI and SpaceXSI; current profile scans use `@SpaceXSI`.
  Verified names such as OpenAI and Google AI, URLs and handles keep their spelling.
- **Discovery rotates For You, Following Recent and Following Popular**, one view
  plus one Latest topic search and one dedicated video search every two minutes.
  Video queries alternate Latest and Top, including Seedance, Grok Imagine,
  @grok/@imagine, Sora, Veo, Kling, Runway, Hailuo, Luma, Wan, ComfyUI and more. Each native feed selection is
  verified before reading. Posts are saved before and after scrolling, with status
  IDs deduplicated; an unchanged page ends the scan. Latest searches have no like
  minimum, so new posts and small builders can qualify. Top searches rotate across
  SI, models, generated media, software, hardware, security and space engineering.
  Queries keep exclusions without repeating oversized topic expressions.
  Shorter rotating profile scans leave Safari available for Replies; the selector
  has its own scheduler worker. Crypto/trading exclusions and the 85/100 selection
  threshold apply throughout. A subject can be technology without mentioning SI.
- **One Startup post each time the bot starts in waking hours**, restarts included,
  within the daily ceiling and the twenty-minute spacing. A submission with an
  ambiguous outcome counts toward both until the operator clears it.
- **Up to 50 reposts per Toronto day**, separate from Originals and Replies, at least
  ten minutes apart. New standalone Elon posts take priority, including unrelated
  topics except Bitcoin/crypto. Other reposts require an attached generated video,
  popular/rising engagement and caption-based model approval, rechecked against
  the discovery text before sharing. All retain author, age, active-hours and
  crypto checks. Status IDs are kept permanently, including
  uncertain submissions: nothing already reposted is automatically reshared.
- **No automatic quote tweets, self-recycling, or burst threads.**
- Every scheduled original uses a fetched trusted source, prefers fresh AI
  launches/articles when available, carries a specific takeaway, duplicate
  checks, and a separate editorial review before publishing.
- The 500,000-view target is tracked using observed views of originals published
  in the last seven days. Public view counters cannot identify home-timeline views.

The bot stays idle overnight and resumes automatically. Browser operations and
model calls check the waking window too, so a queued daytime task cannot start
a new action outside those three windows. An already-issued request may still finish remotely.

## Daily editorial mix

| Toronto time | Reader value |
|---|---|
| 05:00 | Priority SI update worth understanding |
| 07:15 | A practical SI workflow |
| 09:30 | Priority SI article or model update with a sharp consequence |
| 09:45 | Trend: the SI topic X is talking about, told from a trusted article |
| 12:00 | A clear explanation of an SI concept |
| 12:20 | Trend |
| 12:40 | A model or tool update and its consequences |
| 17:00 | Trend |
| 17:45 | Priority informed take on an SI tradeoff |
| 18:30 | An idea worth saving or sharing |
| 22:15 | Optional post for an exceptional update or unusually useful source |

Each slot has a short retry window and missed slots are not caught up. Every
start in waking hours opens one extra trend post, the Startup post. Eleven
slots plus the Startup post compete for eight publications a day. Trend posts
pick their topic from the five fastest-rising SI posts on X from the last 24
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
fallback, codex for instance. An Account can give a Relation its own provider;
the former finance Relations have been removed and those accounts remain blocked.
A CLI runs `NEWS_MODEL`,
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
one-minute collection delay, and compares up to eight admitted posts per
review. The batch mixes two waiting discoveries with six fresh opportunities before revisiting reviewed posts; the
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

2026-10-08 — Startup now attempts one selected Reply after a 90-second discovery/comparison period. It uses the shared saved pool, quality threshold, active windows, hourly allowance, ten-per-day cap and existing write guards. The draft requests one smart thought in at most 20 words, without emojis or smileys. A weak pool or exhausted allowance sends nothing. No automatic restart is performed.

2026-10-12 — The current policy supersedes the October 8 schedule and Reply
ceiling: active 05:00–10:00, 14:00–15:00 and 17:00–23:00 Toronto time, with
five Replies/day including ambiguous submissions. AI/SI topic review applies
to every author, including VIPs; AI-generated videos and brainrot qualify.
Allowances open at 05:00, 07:24, 09:48, 18:12 and 20:36. See the current
editorial policy for selection, quality and recovery rules.

2026-10-12 — Reply volume was clarified to a target of at least 300 useful
Replies per full Toronto day, maximum 400 including pending submissions. The
selector now runs each minute and reuses recent topic-approved reviews, comparing
new candidates at least every five minutes while approved candidates remain.
Quality, available posts and service speed determine the actual count. The
three Toronto windows and AI/SI/technology selection still apply.

2026-10-12 — Operator moved the midday window to lunch and the evening start
to 16:45. Nominal Toronto windows are 05:00–10:00, 12:00–13:00 and
16:45–23:00. Each window's start varies independently by up to ten minutes
earlier or later each Toronto day; closing times remain exactly 10:00, 13:00
and 23:00, end exclusive. The daily offsets are derived from the Account,
Toronto date and nominal start, so restarts reproduce the same day's schedule
without a new state file. The next wake, browser and model guards, and Reply
allowance all use the actual daily windows. Afternoon Original slots move to
12:00, 12:20 (trend) and 12:40. The Reply target remains 300 per full day,
with a hard maximum of 400 including pending submissions. The Operator
requested a PR merged and pushed to main for the running bot.

Scheduled pauses keep one overdue run of each job available at wake. Missed
intervals coalesce into one current cycle; every activity and publication guard
still applies. This prevents the 60-second misfire grace from skipping the
first collection and editorial cycles after a pause.

2026-10-12 — Operator expanded generated-video discovery and requested automatic
reposts, up to fifty/day, with permanent status-ID deduplication. Search catalogs
include Seedance, Grok Imagine and additional video/image tools, workflows, memes
and fresh AI/SI research. Reply comparison gives qualified video opportunities
more attention. Reposts prioritize new standalone Elon originals (crypto remains
excluded), then popular/rising generated videos with caption-based approval.
This supersedes zero automatic reposts; the fifty-repost budget is separate from
Originals and Replies. Native state checks prevent toggling an existing repost;
uncertain submissions stay reserved across restarts. No bot restart accompanies
this implementation. The operator requested a merged PR and a new release.

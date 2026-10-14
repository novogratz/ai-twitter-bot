# AGENTS.md

@thesimaximalist is a live X account driven by Safari + AppleScript from the
operator's Mac: no X API. Every change here can publish, like or follow on a
real account. Setup and run commands live in [`README.md`](README.md).

## Current policy — the ceiling you never lift

[`docs/EDITORIAL_POLICY.md`](docs/EDITORIAL_POLICY.md) is the source of truth
(updated 2026-10-13) and supersedes every older mandate. It encodes:

- Nominal activity windows: 05:00–10:00, 12:00–13:00 and 16:45–23:00 America/Toronto.
  Each start varies by ±10 minutes per day; closing times are fixed, end exclusive.
- At least three sourced AI originals targeted a day, six planned, and eight
  Original/quote publications at most, twenty minutes apart at least.
- Three trend slots (09:45, 12:20, 17:00) and a Startup post on every start
  in waking hours take their topic from rising AI posts on X, and their facts
  from a trusted article.
- Reposts have a separate hard ceiling of 50/day, including uncertain submissions.
  New Elon originals have priority; generated videos need rising/popular engagement
  and caption-based model approval. Repost IDs persist permanently. Crypto stays out.
  Repost approval checks use the same caption text source as discovery.
  Quotes, self-recycling and threads stay at zero.
- Replies have a hard cap of ten per Toronto day, no minimum quota, standalone posts only, paced and deduplicated per tweet;
  one Reply per post permanently; debates and conversation follow-ups stay disabled.
  Never reply to @elonmusk: originals, comments, responses and follow-ups are
  protected. Account `replies.protected_handles` overrides priority, saved
  approvals and every Reply caller; the write also verifies the opened author.
- Likes, follows, Reply spacing, Debate turns and the content checks carry
  the Operator's bounds (2026-09-25) in their `src/core/settings.py`
  declarations; `.env` and `account.toml` may only tighten them.
- Replies, likes and follows cover AI/SI and substantive technology (2026-10-12), including AI videos.
  Elon is excluded from Replies; eligible authors require exceptional
  opportunities scoring at least 97/100. Former crypto/trading exceptions are blocked;
  Bitcoin/crypto content is excluded even when it mentions AI. Likes check the
  opened post text; discovered follows and Engagers need AI/SI or technology bios. Replies
  require relevance for every author and semantic approval during selection.
- Replies use 2–12 words and at most 120 characters including the ending
  (2026-10-12): one sharp stance or funny punchline. Every Reply ends with exactly one random choice of 😂, 💀 or 😂💀;
  draft bodies and Originals have no emojis or text smileys. The write chokepoint
  enforces the ending without weakening text checks. They use SI/super intelligence in their
  own prose, preserving verified names and literal links. Discovery keeps both
  AI and SI terms; the current SpaceXSI name and profile replace older branding.
- Discovery rotates For You, Following Recent/Popular and Latest topic searches
  every two minutes, plus a dedicated video query alternating Latest and Top;
  native views must be verified. It saves every viewport while
  scrolling, deduplicates posts, and rejects off-topic/crypto candidates. New-post
  searches have no minimum likes. Declared queries keep exclusions without duplicating
  topic scope; ad-hoc queries also get a compact topic scope. Direct scans rotate
  one VIP and three Top queries;
  early-bird scans two profiles, mega-watch one. Selection has its own worker.
- The Account is The SI Maximalist, @thesimaximalist: an informed, witty SI/tech
  commentator covering brainrot, news and clearly fictional celebrity parodies.
  This replaces the therapist persona. Storage stays `theaishrink`; historical
  handles in `previous_handles` remain own posts. Production history is preserved.
- The Voice brings fangirl energy for Elon, Grok and Grok Imagine, with dry, playful teasing of inflated claims, marketing
  or demonstrated limitations (2026-10-12). One gentle jab tied to supplied
  context; no invented flaws, personal insults or forced joke quota. Serious
  questions get useful answers. Named-account and positive-only rules still win.
  Playful SI posts should aim for a laugh through a specific surprising connection
  or absurd image. The punchline can stand alone without an explanatory lecture.


A change that raises volume, restores a disabled surface or relaxes a check
needs an explicit operator request, and updates that policy file in the same
change. The same holds for the operator-owned guardrails: the Account's
Voice files (`accounts/<BOT_ACCOUNT>/voice_*.md`), which only the Operator
edits, `BLOCKLIST` in `src/core/config.py`, the repost ceiling and deduplication,
`accounts/<BOT_ACCOUNT>/respect_list.json`, and
`personality_store.hard_rules_block()`. Removing an Account's
`replies.protected_handles` protection also requires an explicit Operator request.

## Active code

`main.py` is the whole scheduler: read `build_scheduler()` for the live jobs.
Every module under `src/` is reached from `main.py`; a test fails on a module
nothing imports, so wire new code into a job or delete it. `src/core/` holds
the shared foundations (config, logger, LLM client, history and engagement
stores), `src/x/` the browser layer, `src/guards/` the clock, caps and
admission checks, `src/editorial/` the originals pipeline, `src/replies/` the
reply jobs, and `src/account/` the follow, like, pin and follower-count jobs.
The top level of `src/` holds only packages. The engine names no real
account: what one Account says, and who it treats apart, goes in its
folder, and `tests/test_engine_names_no_account.py` fails on a name in the
code of `main.py` or `src/`, or in a comment that carries neither a date nor
an issue number.
`accounts/example/`, fictitious and never run live, is the template of a new
Account.

| Concern | Where |
|---|---|
| Account: handle, language, domain the prompts name, Slots and angles, feeds, Evergreen topics, trusted hosts, relevance filter, stricter limits; network handle lists, French-forced authors, added Blocked accounts, niche patterns, X searches (Trending posts' included); Relations (per-handle Reply prompt, provider or dossier) and the default VIP scan prompt | `accounts/<BOT_ACCOUNT>/account.toml`, loaded and checked at start by `src/core/account.py`; the Voice files and the Relations' prompts next to it |
| Originals: sources, evidence, draft, separate review, pending submissions in the ceiling and spacing | `src/editorial/editorial_bot.py` |
| Slot journal: the day's editorial state (day change, Attempts and feedback, Pending slot reserved, confirmed or released, closed Slots, used URLs, recent texts, the day's submissions and the latest); file and in-memory adapters | `src/editorial/slot_journal.py` |
| Draft and review limits, their JSON schemas and call profiles | `src/editorial/editorial_schemas.py` |
| Model calls: the Call surfaces, each with its model setting, provider setting and CLI options (`SURFACES`; callers name a surface, only a Relation's CLI overrides its provider), provider adapters, the one fallback ladder (no fallback unless `LLM_FALLBACK_CLI` names one; an unknown provider fails the call and runs nothing), the CLI model a model setting gives the provider called, timeouts, the answer read once in the profile's text or JSON mode, call profile (the label only names the call in logs), status (answered, failed, provider exhausted) and the provider and model that answered | `src/core/llm_client.py` |
| Trending posts for Trend slots and the Startup post: Top search, filters, ranking, prompt blocks | `src/editorial/trending.py` |
| Reply jobs: direct, feed sweep, early bird, mega watch, debate, replyback, babysit, notify, search | `src/replies/` |
| Reply prompts: Voice, hard rules, dossier, language, SKIP, failure and rate-limit outcomes (provider exhausted) | `src/replies/reply_generator.py` |
| Reply format: two short lengths from shipped history and a random laughing/skull ending; no standalone reactions | `src/core/reply_style.py` |
| Shared Reply candidate schema and fresh topic evidence for account discovery | `src/core/topic_evidence.py` |
| Reply source: the candidates a job's declaration (oldest post, root posts only, expected author, niche, order) selects among its scraped posts, the niche filter, the fresh-and-rising order | `src/replies/reply_source.py` |
| Reply pipeline: admission before generation, set-aside posts, rate-limit stop, spacing wait, write, log after ship with the provider and model that wrote the Reply | `src/replies/reply_pipeline.py` |
| Reposts: priority-original discovery and caption review | `src/replies/repost_bot.py` |
| Repost admission, permanent history, uncertain submissions, topic/media checks | `src/guards/repost_policy.py` |
| Account jobs: engage, follow engagers, followback, likes, pin, follower count, tracked accounts | `src/account/` |
| Follow run: one cycle's follows, Followed accounts skipped whatever the case, each handle tried once, no call past CAP_REACHED, bedtime and `StateUnreadable` raised, any other error one pick, counted and raised once the job saved its state; follow_engagers uses it | `src/account/follow_run.py` |
| Toronto clock, bedtime checks | `src/guards/active_hours.py` |
| Caps, pacing, anti-churn; the ledger facts the follow policy reads | `src/guards/action_guard.py` |
| Follow policy: handle, Blocked account, the account's relation it finds itself (Seed account, follower, Engager; a Stranger never), whitelist, caps, ceiling, quality gate, named Follow refusals, followed accounts and the other follow files | `src/guards/follow_policy.py` |
| Write ledger: today's counts, last write, last follow or unfollow; file and in-memory adapters | `src/guards/ledger.py` |
| Reply admission: Blocked account, own post, one Reply per post, Debate turn cap, spacing, final text, Respected account named | `src/guards/reply_admission.py` |
| Author, status ID and age read from a status URL; nested-reply filter for scraped tweets | `src/x/x_urls.py` |
| Replied store: one reply per tweet, keyed on status ID | `src/guards/replied_store.py` |
| State files: one folder, `state/<BOT_ACCOUNT>/`, resolved by `root()`; atomic writes, guarded or disposable; the files still at the root before issue #207, which stop the start | `src/core/state_store.py`; the move: `bin/migrate_state.py` |
| Engine settings: each `.env` key declared once with type, default, floor or ceiling; `.env` read once at start, an unknown or badly typed key stops it; the `settings_override` fixture's overrides; the only reader of the environment with `config.dry_run()` | `src/core/settings.py` |
| Settings reference of `docs/CONFIGURATION.md`, generated from the declarations | `bin/configuration_doc.py` |
| Settings served under their old names and read on every access, side-effect switches as functions; fixed ceilings and `BLOCKLIST` that `.env` cannot touch | `src/core/config.py` |
| Pre-publish validation (price targets, dedup, truncation, violence) | `src/guards/content_guard.py` |
| Every browser write (`post_tweet`, `reply_to_tweet`, `follow_account`…) | `src/x/twitter_client.py` |
| The sequence every write runs: dry run, Safari lock, ledger rows only on a shipped Write outcome, tab close | `src/x/confirmed_write.py` |
| Reading X pages: feeds, search, profiles, mentions, blank-page recovery | `src/x/scraper.py` |
| Safari lock, AppleScript, page opening (`open_url`, never `webbrowser`), paste, tab and scroll primitives | `src/x/safari.py` |
| Voice, operator-managed: the one persona every prompt carries, rendered by `personality_store.render_voice` | `accounts/<BOT_ACCOUNT>/voice_fr.md`, `voice_en.md` |

## Invariants

2026-10-13 — The Operator permanently protected @elonmusk from all Replies,
including replies to his comments or responses. Protection is enforced before
drafting, on saved opportunities and at the write, with the actual opened
post's author checked against the requested URL. No priority, score or Debate
flag bypasses it. The existing likes, follows, reposts and Voice rules remain.
This supersedes earlier Reply priority for Elon. No restart accompanies it.

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
- The live state is in `state/<BOT_ACCOUNT>/` (issue #207), which git
  ignores as a whole; every path to it goes through `state_store.root()`,
  a `StateFile` or a `StatePath`, never a path built by hand. `bot.log`,
  `bot.lock` and `autonomous_log.md` stay at the root with the process.
  The root state of before #207 is theaishrink's: `main.py` refuses to
  start, whichever Account runs, while one of its files sits at the root
  and not in `state/theaishrink/`, or differs from its copy there. Move it
  with `bin/migrate_state.py`, bot stopped, never by recreating it
  ([Deploying issue #207](docs/OPERATIONS.md#deploying-issue-207)). The
  Operator's files stay tracked, all in the Account
  folder: the Voice files, `whitelist.json`, `respect_list.json` and
  `following_baseline.json`. The bot reads the three JSON files through
  `account.OperatorFile`, which has no write: a missing one stops its
  reader, never comes back with defaults, and what the bot keeps beside it
  goes in a state file. `action_ledger.json` already
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
- [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md): how settings are read,
  the policy ceilings, and the settings reference generated from
  `src/core/settings.py`.
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md): process, jobs, editorial
  pipeline, write path, known gaps. Trust `main.py` where they disagree.
- [`docs/OPERATIONS.md`](docs/OPERATIONS.md): start, stop, supervisors,
  recovery, state files.
- [`docs/HISTORY.md`](docs/HISTORY.md): dated mandates and incidents,
  June–September 2026.

`CLAUDE.md` imports this file; edit `AGENTS.md` only. A behaviour change
updates this file, `README.md` and the policy in the same commit; adding or
removing a job also updates the jobs table in `docs/ARCHITECTURE.md`, a new
or changed setting regenerates `docs/CONFIGURATION.md`
(`uv run python bin/configuration_doc.py --write`) and a new state file in the
`docs/OPERATIONS.md` table. The incident narrative goes to `docs/HISTORY.md`.

2026-10-07 — Operator requested restoration of the code that was on main on
September 26, 2026. The last main commit before September 27 in Toronto time
was 348c82bc (September 25 at 21:18); no September 26 commit exists. Tracked
code, Account files, tests and documentation return to that snapshot. This
explicit rollback supersedes later behavior mandates and restores the snapshot's
checks and settings, including its Reply behavior without the later independent
Reply quality review. Production state, .env and untracked files are preserved.
The running bot is not restarted; deployment takes effect on the next explicitly
requested start or restart.

2026-10-07 — Operator updated the Account Voice: a sexy, funny, sarcastic
40-year-old woman and mom with deep expertise in AI models and news. AI-generated
videos are a new interest, and the Account has started publishing them. Specific
video descriptions and production claims need supplied context. Flirtation stays
non-explicit and occasional; sarcasm targets claims. Identity honesty, evidence
requirements, publishing limits and scheduling are unchanged. This changes the
Voice only and does not add automated video generation or uploading.

2026-10-07 — Operator changed Toronto sleeping hours to 23:45–05:05.
The shared waking guard now permits external work from 05:05 through 23:44.
The first Original slot moves from 05:00 to 05:05 so it remains in waking hours.
Caps and pacing are unchanged; this takes effect on the next explicit restart.

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

2026-10-12 — Operator requested reactivation with three Toronto activity windows:
05:00–10:00, 14:00–15:00 and 17:00–23:00, end exclusive. This supersedes the
October 8 schedule. The Reply ceiling is halved from ten to five per Toronto
day across all jobs, including ambiguous submissions and existing ledger rows.
Configuration may only tighten it. With five Replies, cumulative allowances
open at 05:00, 07:24, 09:48, 18:12 and 20:36; unused allowance carries forward
that day, with no requirement to fill it. Replies must substantively concern
AI or superintelligence (SI/ASI), including AI-generated videos and brainrot.
Unrelated posts from VIPs have no exemption. The shared pool checks post text,
selection requires an explicit on-topic verdict and a score of at least 85,
and the write checks the opened standalone post's own text for niche terms.
Handles and URLs alone never establish relevance. Previously scored pool rows
without a topic verdict need a fresh review. Account topic instructions guide
selection and drafting; unsupported video details and empty praise are skipped.
The Operator requested the PR merged to main and the bot started after validation.

2026-10-12 — Operator clarified Reply volume: target at least 300 useful Replies
per full Toronto day, with a hard maximum of 400, superseding the five-Reply cap
above. Existing ledger rows and ambiguous submissions count. The selector runs
every minute, one submission attempt per cycle, with its first regular run at
120 seconds after start so the 90-second Startup attempt comes first. It reuses
explicit on-topic approvals younger than one hour and compares queued discoveries
after five minutes, or immediately when no fresh approved candidate remains.
The allowance releases the 400-reply budget proportionally across the twelve
active hours. TARGET_REPLIES_PER_DAY defaults to 300 and is clamped to the
effective maximum; it never forces weak Replies or overrides refusal rules.
The three active windows, AI/SI-only scope, standalone rule, 85/100 selection
threshold, evidence checks, deduplication and write pacing remain in force.
The Operator requested a PR merged and pushed to main for the running bot.

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

2026-10-12 — Operator requested AI/SI-only engagement, led by Elon Musk.
The Account's profile visits, priority scans, pinned tracking and follow seeds
now cover AI researchers, builders and enthusiasts, with Elon first. Former
crypto/trading exceptions, including TheBTCTherapist and Graphseo, are blocked
even when old settings or saved discoveries still list them. Bitcoin/crypto
text is excluded even alongside AI terms. The shared like write checks the
actual post text; Replies retain their pool and opened-target checks. Feed
harvesting and curator promotion require AI evidence; discovered follows and
Engagers require an AI/SI bio, and topic exclusions apply even to manual seeds.
One Reply per standalone post is permanent: reply IDs are never evicted, and
debate, replyback and conversation follow-ups remain disabled. The requested
Voice favors Elon, Grok, xAI and related products when relevant and supported,
with technical insight, apt wit and honest uncertainty. Existing follower
relationships and production state are preserved. Deployment requires restart.

2026-10-12 — Operator requested removal of a suspected fifteen-minute Reply
post-age cutoff. There was no global fifteen-minute limit, but early-bird and
mega-watch scans still rejected posts older than eighteen and four minutes.
Both now use the shared Reply pool's 24-hour age window through Reply source
declarations. Frequent scanning does not require minute-old posts. Topic,
standalone-post, author, score, pacing and permanent dedup checks still apply.
No automatic start or restart accompanies this change.

2026-10-12 — Reply selection stalled after discovery filled its thirty-post
batch: the local model exhausted its 1,800-token output limit and every
incomplete review was discarded. Compare at most eight posts, constrain the
JSON count and IDs, and report provider errors, truncation, review counts and
allowance waits. A failed refresh may use a still-current explicitly approved
candidate after normal rechecks. Never publish a token-truncated model answer.
Topic, score, evidence, daily caps and dedup requirements are unchanged.

2026-10-12 — Operator requested For You and Following (Recent and Popular), more
new opportunities and a complete rebrand to The SI Maximalist, @thesimaximalist.
Substantive technology now qualifies without an SI connection; crypto stays out.
This supersedes the earlier Home-feed removal and therapist persona. Discovery
uses verified native views, viewport collection, direct document scrolling,
rotating profiles and searches without a minimum-like gate in the Latest lane.
The selector's eight-post review and dedicated worker address stalled Replies.
The public handle and both Voices change; the storage key, ledger, reservations,
permanent dedup, 300 target/400 cap, active windows and one-Reply rule remain.
No bot start or restart accompanies this implementation.

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

2026-10-12 — Operator replaced occasional smileys with no emojis at all.
Originals and Replies use words only, including no ASCII smileys appended to
text. Reply format selection no longer offers standalone reactions. Generation
rewrites a decorated Reply once, then fails if it still violates the rule; final
content validation blocks decorated text from every publishing path. The legacy
REPLY_ALLOW_REACTIONS key is retained but clamped off. Voice, length variation,
topic relevance, caps and scheduling otherwise stay in place. No bot restart.

2026-10-12 — Operator requires a laughing/skull ending on every Reply: one
random choice of 😂, 💀 or 😂💀. This supersedes the Reply emoji ban; Originals
remain emoji-free. Models draft words only, with humor in the text itself.
The shared pipeline and write chokepoint preserve a single chosen ending;
body checks still reject filler, truncation and unsupported decorations.
Standalone reactions stay disabled; scheduling, caps, one-Reply-per-post and
protected-account rules remain. No start or restart accompanies this change.

2026-10-12 — Operator replaced high-volume replying with at most ten Replies
per Toronto day and no minimum quota. Existing shipped Replies and ambiguous
submissions still count, including those sent under the earlier policy. Replies
are 2–12 words, at most 120 characters including the required laughing/skull
ending. Elon’s relevant standalone posts lead comparison and selection at 92/100
or higher; exceptional other posts require 97/100. Cached approvals face the new
thresholds. The Voice brings delighted, sharp fangirl energy for Elon, Grok and
Grok Imagine; humor targets hype or the situation, with no invented facts or
personal insults. One Reply per post and topic checks remain. No live publishing
or restart accompanies this change; it takes effect on the next start/restart.

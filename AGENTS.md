# AGENTS.md

@TheAIShrink is a live X account driven by Safari + AppleScript from the
operator's Mac: no X API. Every change here can publish, like or follow on a
real account. Setup and run commands live in [`README.md`](README.md).

## Current policy — the ceiling you never lift

[`docs/EDITORIAL_POLICY.md`](docs/EDITORIAL_POLICY.md) is the source of truth
(2026-09-23) and supersedes every older mandate. It encodes:

- Active 04:30–23:30 America/Toronto only; nothing external happens overnight.
- At least three sourced AI originals targeted a day, six planned, and eight
  combined profile publications at most, twenty minutes apart at least.
- Three trend slots (10:00, 13:00, 15:00) and a Startup post on every start
  in waking hours take their topic from rising AI posts on X, and their facts
  from a trusted article.
- Quotes, reposts, self-recycling and threads stay at zero.
- Replies are uncapped in waking hours, paced and deduplicated per tweet;
  debate turns are capped per engager per day.
- Reply prompts share a technical quality standard (2026-10-04): add a
  precise mechanism, missing assumption or useful test; dry sarcasm targets
  claims, with factual uncertainty explicit. Each parent and supplied context
  can contribute up to 1,200 characters; the short output rule still applies.
- The Account's optional `perspective` guides Originals and Replies, never
  the independent editorial or Reply review. Operator 2026-10-06: favor Grok,
  xAI and Musk's relevant AI work, with occasional enthusiasm. Grok is the
  Account's favorite AI product, an opinion rather than an unsupported ranking;
  it likes Grok Imagine and discusses it when relevant to the actual topic.
  Praise needs evidence, material limits remain explicit, versions are not
  guessed, and no firsthand use is invented. No unrelated promotion or fan spam.
- Natural Replies (2026-10-04) start on the actual point, with specific wit
  rather than stock agreement/pivot or lecture openers. Generation and Reply
  admission refuse narrow canned prefixes such as "Fair, but". Identity
  remains honest; humor never invents a fact or firsthand experience.
- A Reply answers a quiet post under 15 minutes old (2026-09-29), whatever
  the job, mentions and answers to our posts included. The Reply source may
  hand a rising post to admission up to `REPLY_RISING_MAX_AGE_MINUTES` (45
  minutes at most) only when its like velocity clears the operator bounds;
  the per-candidate limit is checked again at the write. `REPLY_MAX_AGE_MINUTES`
  still caps quiet posts.
- Likes, follows, Reply spacing, Debate turns and the content checks carry
  the Operator's bounds (2026-09-25) in their `src/core/settings.py`
  declarations; `.env` and `account.toml` may only tighten them.
- English Originals and Replies take the form of ASD-STE100 Simplified
  Technical English, a hard rule (2026-09-27); the Voice keeps the tone.
- A Reply is one or two short sentences (2026-09-27): every Reply prompt
  asks for about 100 characters and 140 at most, and none sets its own
  length; the Reply admission trims to `REPLY_MAX_CHARS`, 160 at most.
- Replies, likes and follows keep to AI (2026-09-25): the Account's niche
  patterns and searches look for AI, and its lists drop crypto, markets and
  space accounts, save those the Operator picked by hand and a few still to
  confirm. The patterns' known false positives are listed in the policy.

A change that raises volume, restores a disabled surface or relaxes a check
needs an explicit operator request, and updates that policy file in the same
change. The same holds for the operator-owned guardrails: the Account's
Voice files (`accounts/<BOT_ACCOUNT>/voice_*.md`), which only the Operator
edits, `BLOCKLIST` in `src/core/config.py`, the zero-repost rule,
`accounts/<BOT_ACCOUNT>/respect_list.json`, and
`personality_store.hard_rules_block()`.

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
| Account: handle, language, domain the prompts name, Slots and angles, feeds, Evergreen topics, trusted hosts, relevance filter, stricter limits; network handle lists, French-forced authors, added Blocked accounts, niche patterns, X searches (Trending posts' included); Relations (per-handle Reply prompt and provider) and the default VIP scan prompt | `accounts/<BOT_ACCOUNT>/account.toml`, loaded and checked at start by `src/core/account.py`; the Voice files and the Relations' prompts next to it |
| Originals: sources, evidence, draft, separate review, the pending check before the Draft and before the reservation | `src/editorial/editorial_bot.py` |
| Slot journal: the day's editorial state (day change, Attempts and feedback, Pending slot reserved, confirmed or released, closed Slots, used URLs, recent Posts and their texts, the day's submissions and the latest); file and in-memory adapters | `src/editorial/slot_journal.py` |
| Draft and review limits, their JSON schemas and call profiles | `src/editorial/editorial_schemas.py` |
| Model calls: the Call surfaces, each with its model setting, provider setting and CLI options (`SURFACES`; callers name a surface, only a Relation's CLI overrides its provider; every Reply runs on `REPLY_LLM_PROVIDER`, `AI_CLI` when blank, a Relation whose CLI is missing too, with a warning), provider adapters, the neutral directory every CLI runs from, the one fallback ladder (no fallback unless `LLM_FALLBACK_CLI` names one; an unknown provider fails the call and runs nothing), the CLI model a model setting gives the provider called, timeouts, the answer read once in the profile's text or JSON mode, call profile (the label only names the call in logs), status (answered, failed, provider exhausted) and the provider and model that answered | `src/core/llm_client.py` |
| Trending posts for Trend slots and the Startup post: Top search, filters, ranking, prompt blocks | `src/editorial/trending.py` |
| Reply jobs: direct, feed sweep, early bird, mega watch, debate, replyback, babysit, notify, search; direct, feed sweep, early bird, mega watch and debate select through the Reply source; a job reads the Account itself and takes nothing from `direct_reply` but its `reply_call` | `src/replies/` |
| Reply prompts: Voice, the one length rule, hard rules, language, SKIP, narrow bland-praise declines, failure and rate-limit outcomes (provider exhausted) | `src/replies/reply_generator.py` |
| Reply source: the candidates a job's declaration (oldest post, capped by `REPLY_MAX_AGE_MINUTES`, root posts only, expected author, niche, order) selects among its scraped posts, the niche filter, the fresh-and-rising order by conversation heat (likes plus double replies per minute) and newest order; the Account's pinned accounts early_bird and mega_watch scan (`pinned_accounts`) | `src/replies/reply_source.py` |
| Reply pipeline: admission before generation, set-aside posts, rate-limit stop, spacing wait, write, log after ship with the provider and model that wrote the Reply | `src/replies/reply_pipeline.py` |
| Account jobs: engage, follow engagers, followback, likes, pin, follower count | `src/account/` |
| Follow run: one cycle's follows, Followed accounts skipped whatever the case, each handle tried once, no call past CAP_REACHED, bedtime and `StateUnreadable` raised, any other error one pick, counted and raised once the job saved its state; the relations the job follows handed to the chokepoint; follow_engagers, engage and followback use it | `src/account/follow_run.py` |
| Toronto clock, bedtime checks | `src/guards/active_hours.py` |
| Caps, pacing, anti-churn; the ledger facts the follow policy reads; the Original count and spacing over the ledger and the Slot journal's submissions, and the check that a reserved key is the day's Pending slot of that text, which `post_tweet` enforces | `src/guards/action_guard.py` |
| Follow policy: handle, Blocked account, the account's relation it finds itself once per follow (Seed account, follower, Engager; a Stranger never), the relations a caller follows (`SEED_ONLY` for engage and the `follow` skill), whitelist, caps, ceiling, quality gate, named Follow refusals, followed accounts and the other follow files | `src/guards/follow_policy.py` |
| Write ledger: today's counts, last write, last follow or unfollow; file and in-memory adapters | `src/guards/ledger.py` |
| Reply admission: Blocked account, own post, one Reply per post, post over `REPLY_MAX_AGE_MINUTES`, Debate turn cap, spacing, final text trimmed to `REPLY_MAX_CHARS` on a sentence end, Respected account named | `src/guards/reply_admission.py` |
| Author, status ID and age read from a status URL; nested-reply filter for scraped tweets | `src/x/x_urls.py` |
| Replied store: one reply per tweet, keyed on status ID | `src/guards/replied_store.py` |
| State files: one folder, `state/<BOT_ACCOUNT>/`, resolved by `root()`; atomic writes, guarded or disposable; the files still at the root before issue #207, which stop the start | `src/core/state_store.py`; the move: `bin/migrate_state.py` |
| Engine settings: each `.env` key declared once with type, default, floor or ceiling; `.env` read once at start, an unknown key ignored with a warning, a badly typed value stopping it; the `settings_override` fixture's overrides; the only reader of the environment with `config.dry_run()` | `src/core/settings.py` |
| Settings reference of `docs/CONFIGURATION.md`, generated from the declarations | `bin/configuration_doc.py` |
| Settings served under their old names and read on every access, side-effect switches as functions; fixed ceilings and `BLOCKLIST` that `.env` cannot touch | `src/core/config.py` |
| Pre-publish validation (price targets, dedup, truncation, violence) | `src/guards/content_guard.py` |
| Every browser write (`post_tweet`, `reply_to_tweet`, `follow_account`…) | `src/x/twitter_client.py` |
| The sequence every write runs: dry run, a page session (Safari lock, guards under it before the open, the page handed to the steps, a page that does not open FAILED), ledger rows only on a shipped Write outcome, the tab closed on every path, bedtime and a stop included | `src/x/confirmed_write.py` |
| Reading X pages through page sessions, with each scrape's answer when its page does not open: feeds, search, profiles, mentions, blank-page recovery | `src/x/scraper.py` |
| Safari lock, AppleScript, page opening (`open_url`, never `webbrowser`), paste, tab and scroll primitives, each run checking waking hours save the session's tab close; its private names reached by `page_session` only, save `safari_hygiene` and `bin/mass_unfollow.py` | `src/x/safari.py` |
| Page session, for every read and write: the Safari lock held, the page opened on demand (`PageNotOpened`, no read until an open succeeds), scroll, script, JSON read, keys, paste and Safari brought to the front, each tab it opened closed on every path, a nested session opening nothing and reading only the outer session's page; Safari and memory adapters | `src/x/page_session.py` |
| Voice, operator-managed: the one persona every prompt carries, rendered by `personality_store.render_voice` | `accounts/<BOT_ACCOUNT>/voice_fr.md`, `voice_en.md` |

## Invariants

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
- **Pages go through the page session.** A job, a scrape or a write acts
  on a page through `page_session.session`, which closes the tabs it
  opened on every path, bedtime and a stop included, through
  `safari._close_session_tab`, the one AppleScript run that skips
  `require_active()`; a write gets its page from `confirmed_write.run`. No module outside `src/x/safari.py` and
  `src/x/page_session.py` reaches a private `safari._xxx` primitive, save
  the Safari restart in `safari_hygiene.py` and `bin/mass_unfollow.py`:
  `tests/test_browser_layer.py` fails on any other. An exception `src/x`
  defines inherits `page_session.BrowserFailure`, the one kind of error
  `health` counts toward a Safari restart, or is listed in that test
  with its reason.
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
  button of an article found by status ID instead, and replies click that
  article's `reply` button. The `r` key is never pressed (2026-10-04): on a
  thread it answered the account's own reply.
- **Trim with `humanizer.smart_trim`.** A bare `[:N]` slice on outgoing
  text once published a reply cut mid-word.
- **Fix the family.** When a bug ships, grep every surface for the same
  shape before closing it.

## Verification

```bash
uv run --with pytest --with-requirements requirements.txt python -m pytest tests/ -q
uv run --with-requirements requirements.txt python main.py --dry-run  # jobs + policy, no browser, no model
uv run --with-requirements requirements.txt python bin/show_prompts.py  # prompt sizes; add a label (DEBATE…) for the full text
```

CI runs the same suite on every PR. `tests/conftest.py` walls tests off from
Safari, `bot.log` and production state files. Code on a page session, reads
and writes alike, needs no patch of a browser primitive: the `memory_page`
fixture scripts its pages by URL, and `tests.helpers.WritePage` opens every
page of a write and fails or traces its steps. Patch a scrape or write in
its defining module (`src/x/scraper.py`, `src/x/twitter_client.py`) when the
caller imports it inside a function, but on the caller when it imports it at
module level. Patch a primitive of `src/x/safari.py` only to test
`safari.py`, the Safari adapter or a listed exception, the real primitive
restored from the `unwalled` fixture included, or to prove that a refusal
never opens a page (`safari.open_url` in `tests/test_blocked_account.py`).
The write tests also patch the lock, `safari._safari_lock`, to trace it or
make it contended. A guard change ships with a test pinning it. Tests
mirror `src/`: a test goes under `tests/<package>/`, with the module that
owns the rule; cross-cutting invariants stay at the root of `tests/`.

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


Reply quality (2026-10-04): all Reply lanes, including prewritten search drafts,
use `src/replies/reply_quality.py` before the write. The pipeline reads at most
two HTTPS links from trusted hosts: links in the parent and context first, then
matching optional `[[reply_sources]]` Account entries (`pattern`, `url`). It uses
the editorial source reader, rejects untrusted redirects, applies a four-second
socket timeout per fetch, and caches successes and failures in memory for 60
seconds. It supplies at most twelve exact passages. Shortened links are not
expanded; absent evidence permits stable knowledge or clear conditional points,
not unsupported current claims.

A separate JSON review uses the ordinary Reply model and provider, without the
Account's brand perspective or Voice. Each provider attempt is capped at twenty
seconds. The reviewer checks relevance, added value, natural phrasing and factual
support; current claims need supporting passage IDs. This is an additional model
call per draft and may reduce reply volume. Model review reduces errors but does
not prove a claim true. Malformed, failed or negative review sends nothing and
leaves the parent retryable; exhausted providers stop the cycle. The approval
binds the exact prepared draft to its parent status ID, and `reply_to_tweet`
checks that approval under the page lock before claiming or opening the post.
The existing own-post, duplicate, age, spacing, length and waking-hours rules
still apply. No new persistent state or change to publishing ceilings.

2026-10-05 — Neutral AI analysis replaces the recurring pro-Grok/xAI stance.
Replies answer the parent's actual subject, use the same standard across labs,
and praise specific supported progress when relevant. The independent reviewer
rejects unrelated brand/executive mentions and promotional pivots. Discovery
queries now cover evaluation, inference, research, training and reasoning; the
extra ecosystem-only priority entries are removed. Existing AI coverage, trusted
sources, Voice files, guardrails, caps and pacing remain in force.

2026-10-05 — Reply and like page selectors use the outer post's unquoted
User-Name header for its status link. A quote embedded in the same article is
never the surrounding post's identity. A Reply also checks the clicked status
and author against admission before pasting; an own author is refused, and an
unknown or mismatched target fails without submission. Existing dedup and
publication rules apply. Missing unquoted headers fail closed.

2026-10-05 — Reply quality also requires one useful observation tied to the
parent. Generic advice, empty contrarian claims, jargon without a point and
jokes that do not fit the parent are rejected. Missing essential context means
skip, not invention. The tone stays clear and conversational; wit is optional
and no human identity or lived experience is fabricated.

2026-10-05 — Operator requested broader Reply coverage. Six additional AI-only
search queries discover quiet technical questions and builder posts without a
minimum like count: retrieval, tuning, agent debugging, inference, prototypes
and reliability. They join the existing rotating query pool; the per-cycle
slice, schedule, root-post selection, age limits, quality review, own-post and
duplicate refusal, pacing and waking hours are unchanged. Original, like and
follow discovery are unchanged. This expands eligibility, not a promise of a
specific reply count.


2026-10-06 — Replies verify the actual open composer parent before paste and
again before submission. Its status ID and author must match admission;
missing, ambiguous, changed or own targets send nothing. Replied status IDs
are retained without eviction: one reply per tweet, regardless of author or
URL alias, for the lifetime of the account. Existing caps and pacing apply.


2026-10-06 — Positive Grok/xAI preference supersedes the 2026-10-05 neutral
stance. Grok is the Account's favorite AI product and it likes Grok Imagine;
express this occasionally and only when relevant, with supported strengths,
honest limits and no invented firsthand use. Imagine joins one existing query
in each Reply, hot-tab and Trend pool, evergreen research and official Reply
sources. Independent review, query counts, publishing caps, pacing, Voice and
self-reply/per-tweet dedup protections remain unchanged. Applies at restart.


2026-10-06 — Operator added Elon Musk, Elon, Optimus, xAI, Grok and Grok
Imagine to research discovery. One dedicated keyword query joins each Reply,
hot-tab and Trending pool (19, 7 and 4 queries respectively). Musk, Elon,
Optimus and from:elonmusk branches require AI; branded AI terms remain explicit.
The queries keep the respective 30/300/50 like thresholds and English language;
Trending still excludes replies. Reply searches retain their per-cycle rotating
slice; Trend/Startup research reads one additional query. Relevance, fresh age,
independent review, publishing caps, pacing and self-reply/per-tweet dedup checks
remain in force. Likes and follows are unchanged. Applies at the next start.


2026-10-06 — Operator requires all speech to stay on AI and AI posts, including
superintelligence/SI. VIP candidates now use the Account niche filter and
expected author. Every Reply review requires an explicit `on_topic: true` for
both the actual parent subject and the draft; names, brands or SI letters alone
are insufficient, and unrelated chatter must not be turned into an AI thought.
Missing or negative topic verdicts send nothing, including prewritten search
and Replyback drafts. Shared generation instructions ask for SKIP on unrelated
posts. Originals' existing `ai_relevant` review explicitly checks source and
published text. Super intelligence and superintelligence join the topic filter;
the dedicated research queries also include these phrases and SI with AI.

To reduce repeated search reloads across jobs, successful X search reads share
a bounded in-memory 30-second cache, scoped to Account, query, Top/Live mode and
read limits. Queued readers recheck it under the page-session lock. Results are
copied, failed/blank reads are not cached, and hits still check waking hours and
stop. Admission rechecks actual post age at the write. Separate legitimate
Top/Live searches remain distinct; no automatic tab-toggle retry is added.
No new persistent state, model call, schedule, cap, pacing or Voice change.

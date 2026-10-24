# Editorial policy — October 24, 2026

## Fewer daytime breaks

The October 24 Operator request reduces break frequency to one ten-minute
pause about every three waking hours, replacing pauses in roughly three of
four hours. The six daily windows start in hours 07, 10, 13, 16, 19 and 22
Toronto time, between minutes 35 and 50. The Account/date/hour still determines
the start minute, so workers and restarts agree. `HOURLY_BREAK_MINUTES=10`
continues to control duration. Midnight–04:30 sleep and every publication,
like and Reply admission limit remain. No environment edit, restart or state
migration accompanies this change.

## Always like before a Reply

The latest Operator request requires a like before every Reply. The common
`reply_to_tweet` write path first verifies the eligible standalone parent and
author, then confirms that parent's own like on the page before opening the
composer. An existing visible like satisfies this requirement without another
click or daily allowance. Otherwise the shared like chokepoint must succeed,
and the parent's like is checked again before composition. Historical cache
entries, other posts' likes and embedded quoted controls cannot authorize it.

If the like is refused, fails or cannot be confirmed, the Reply stays unsent
and its pre-submit claim is released for a later attempt. Sleep, breaks,
unreadable guarded state and the daily like ceiling still stop new likes.
Reposts remain independent, but no Reply route, including the priority watch,
can bypass the confirmed-like prerequisite. Replies have no separate daily
cap; exhausting the like allowance can defer Replies to unliked parents.
The former `REPLY_LIKE_PARENT_PROB` setting remains accepted for compatibility
and has no effect. No environment edit, bot restart or state migration is
included in this update.

## Both feeds before drafting; new Elon originals

The Operator explicitly requests automatic likes, reposts and Replies to new
Elon Musk posts. The Account's `auto_engage_handles = ["elonmusk"]` authorizes
this named exception to the former zero-repost rule. A dedicated priority
watch checks a Latest search every 60 seconds during active time, independently
of random account pools. Browser contention or an ongoing cycle can delay a
poll. First enable persists a timestamp and skips earlier posts; restarts keep
that boundary. Later polls read up to 20 recent originals, no older than 24
hours, with at most two Reply generations per cycle. As an explicitly picked
author, this watch does not require a niche-keyword match. Blocked accounts,
own identities, comments and unreadable parent pages still refuse; source
content checks, respect rules, English output and Reply admission remain.

Each discovered original gets independent like, repost and Reply attempts.
Existing likes and reposts are never toggled off. Only the verified original's
explicit controls are clicked. Repost claims are permanent and process-locked;
an uncertain confirmation stays claimed across restart and reserves publication
budget and spacing. Only a proven pre-submit failure releases the claim.
Unreadable history stops the affected action. All like callers share the
existing daily like ceiling at the write chokepoint.

Reposts and Originals share the combined daily profile ceiling (eight or a
tighter configured limit) and at least twenty-minute spacing. Pending editorial
submissions and uncertain reposts also reserve capacity. There is no guarantee
of an action on every post: caps, pauses, source checks, model SKIP and failures
may defer or skip it. A native repost preserves its author's words; SI wording
applies to our own prose. Quotes, general reposts, own-post recycling, threads,
comments and follow-up exchanges remain disabled. Sleep and scheduled breaks
apply. No live restart or state migration is part of this change.

The feed sweep completes both bounded For You and Following reads before any
model generation. Each read retains its verified tab, 20-scroll/160-post limit
and stalled-feed stop. A quota failure can end drafting but cannot retroactively
skip Following discovery. Activity boundaries and unreadable state still stop
the cycle; ordinary scrape failures leave the other feed eligible.

## The SI Maximalist: voice, discovery and breaks

The latest Operator request sets the Account handle to `thesimaximalist` and
the brand to The SI Maximalist. The old `TheAIShrink` handle remains an own
identity; `BOT_ACCOUNT=theaishrink` and all state paths remain. Both Voice files
are English and describe a fictional 45-year-old woman with technical depth,
sharp humor, warmth and natural conversational rhythm. She has no therapist
role. She favors Elon Musk, Twitter/X, X products, SpaceX and xAI/Grok; Grok
Imagine is her personal favorite. Preferences are opinions, never fabricated
benchmarks, experiences or superiority claims. Kindness does not require
false agreement; no fabricated biography, impersonation or concealed bot identity.

`publication_si_wording` extends SI / Super Intelligence to every Original and
Reply. Originals are normalized before length checks, independent review and
at the final write. Source evidence, URLs, handles and embedded names remain
literal. The editor understands this vocabulary does not assert a new capability.
Research retains both AI and SI and now includes Grok Imagine, SpaceX,
Starship, Starlink, Elon Musk, Twitter and named X products. Bare X is not a
niche match. Query counts and minimum engagement filters are preserved.
The named ecosystem expansion supersedes the September space exclusion;
general politics, crypto and markets remain outside the niche.

The Operator requests deeper browsing of both Home feeds. The scraper selects
and verifies For You or Following, reads each viewport before scrolling,
deduplicates by status ID, and stops after three screens with no new posts.
The Account's discovery budget is 20 scrolls and 160 posts per feed. Failed
tab selection skips that feed. No Reply or publication budget is raised.

The Account sets `HOURLY_BREAK_MINUTES=10`. Under the October 24 amendment,
breaks start between minute 35 and 50 every three waking hours. Their
account/day/hour plan is deterministic across workers and restarts and creates
no state file. The scheduler pauses, running jobs stop at the next activity
check, model timeouts end at the next break, and no new external request or
browser action starts during the break. An already-issued request may finish
remotely. Breaks are expected pauses and never trigger Safari failure recovery.
Midnight–04:30 sleep, permanent standalone Reply deduplication, English-only
validation and all publication ceilings remain. The Operator requests push,
PR, merge and a release afterward; activation requires a requested restart.

## English output and midnight sleep

The latest Operator instructions extend Waking hours to midnight and require
English for every Original and Reply. Overnight is 00:00–04:30
America/Toronto, including daylight-saving transitions. At midnight the
scheduler pauses, queued jobs refuse new work, model timeouts expire and any
Startup post window closes; work may resume at exactly 04:30. No editorial
slot, daily ceiling, pacing or disabled publication surface is added.

The Account enables `english_only`. The English Voice and explicit output
instructions apply even to French sources and VIPs; the former French-forced
handle list is empty. An environment override cannot change this policy.
Final content validation applies to Originals, Replies and prepared texts,
including dry runs: French, mixed-language or unidentified prose is refused.
URLs and @handles are excluded from language detection. Other Accounts may
retain their configured language behavior by omitting this preference.

The Operator requests a PR, merge, push and release. Activation still needs
an explicitly requested restart; no production state is migrated or reset.

## Codex Sol for Replies

The latest October 23 request switches responses to Codex `gpt-6.1-sol`
with xhigh reasoning effort. The operator's `.env` selects Codex for both
the shared primary and the Reply provider, pins both Reply model settings,
and sets `CODEX_REASONING_EFFORT=xhigh`. VIP Relations use Codex too.
Originals retain their Ollama provider and model. Fallbacks remain disabled;
`LLM_DISABLE_FALLBACK=1` also applies during cached Codex quota lockouts,
which return a rate-limit outcome instead of generating locally.
The CLI receives the effort explicitly, uses a read-only sandbox, and accepts
the Reply routes' temporary working directory outside a Git repository.
Publication rules, prompts, pacing and disabled jobs remain in force.
This configuration takes effect at the next explicitly requested restart;
the setup does not start or restart the bot or migrate production state.

## One Reply per original and a sharper SI Voice

The later October 23 instructions supersede the restored baseline's
conversation behavior. The live Account enables `standalone_replies_only`:
answer another account's standalone original at most once, permanently.
Never answer our own originals or replies, another comment, or an ongoing
debate. Separate standalone originals by the same author can still qualify.
Debate, replyback and first-hour babysitter jobs are absent from the schedule;
manual entry points also return before reads, drafting or engagement work.
`ENABLE_DEBATES` cannot override the Account policy.

Admission rejects known replies and follow-up context before drafting,
including VIP discoveries. The final browser check requires the exact status
ID and author on the opened page, a standalone original, no visible prior
Reply by us, and that original's own Reply button. Unreadable, ambiguous,
redirected or nested targets are skipped before required parent likes and
checked again before clicking Reply. Both the configured and runtime handles,
plus `previous_handles`, identify our own posts even after a rename. A visible
earlier own Reply permanently retains the claim even if it later disappears.

The Replied store keeps every retained status ID without eviction. Its
read/merge/write and claim operations share a process lock. Alternate URLs,
parallel workers and restarts cannot authorize another submission to a claimed
post. Corrupt history refuses publication. A failed or uncertain submission
keeps its claim; only failure before submission releases it. Existing history
is preserved, with no production-state migration or reset.

Both Voice files and the Relation prompts now support a fictional 45-year-old woman and mom of one,
with confident, playful adult charm and deep SI technical perspective. A
Reply should earn attention through a precise mechanism and consequence,
supported tradeoff, illuminating connection or useful question. Technical
depth spans models, training, inference, evaluation, hardware and real deployment,
but each response picks the relevant point instead of displaying jargon.
Warmth, wit and occasional subtle flirtation can spark curiosity or delight.
Kindness, honest bot identity and factual support remain. No invented family
anecdotes, tests, credentials, private access, hidden internals or omniscience.
No question authorizes a follow-up exchange. SI wording and both research
vocabularies remain. This change does not start or restart the bot.

## SI Reply wording and AI / SI research

On the hard-reset September 26 baseline, the Operator requests SI instead of
AI and Super Intelligence instead of Artificial Intelligence in every Reply.
The Account enables the optional `reply_si_wording` boolean; Accounts that
omit it retain their existing wording. The Reply generator guides the model
and normalizes plain text before its length limit. The pipeline normalizes
prepared Replies, including those extracted from search JSON, before length
checks and logging. Final Reply admission enforces the wording before its
length check and again after formatting, before content validation.

Replace whole terms and their case variants, including AIs → SIs. Literal
URLs, domains, email addresses, @handles, embedded names such as OpenAI and
xAI, and French verb forms such as j'ai, je l'ai and ai-je remain intact.
Source evidence retains its original text. SI / Super Intelligence is a
terminology preference, never evidence that a system has achieved that capability.

Research retains AI and Artificial Intelligence and includes SI, Super
Intelligence, superintelligence and ASI in all Account search lists and in
post, bio and editorial relevance filters. Standalone SI is uppercase in
relevance filters so the French conjunction si does not qualify a post.
The optional Reply-search job reads its research queries from the Account.
Existing Account query counts, engagement filters and collection budgets
remain. Publication surfaces, hours, pacing, the Voice and other baseline
rules remain as described below. No start, restart, `.env` edit or
production-state migration accompanies this change.

## September baseline

The operator requested at least three valuable AI posts a day, up to eight
profile posts, uncapped replies, a more natural voice, and a working day from
04:30 to 23:30 (22:00 until 2026-09-23; the later bedtime added no slot and
changed no cap or pacing). The schedule aims for six originals, with more opportunities
than the ceiling allows when sources are strong enough. Quality can reduce the actual count.
The same day the operator added three trend slots and a Startup post on every
start; they compete for the same eight publications (see below).
There is no guarantee of virality or a minimum post count on a day with weak
sources or service failures.

## Value and voice

The character is a confident 45-year-old mom and AI enthusiast: warm, clear,
witty and occasionally flirty. AI knowledge, news and updates are the focus.
She explains a consequence, teaches something, or offers a useful action. A
question, joke, emoji or flirty line is optional. Forced formulas, engagement
bait, stale numbers, copied headlines and fabricated lived experience are out.
The AI identity remains honest; the therapist name is a brand persona.
That character is the Voice, written only in the Account's folder,
`accounts/theaishrink/voice_fr.md` (`voice_en.md` for English prompts). Every
Original and Reply prompt opens on it, under `BOT_HANDLE`; the prompts keep
their task instructions but no copy of the persona, and the model client adds
none (#192). The per-person relations (Graphseo, bestie, buddy) are the
Account's Relations, in `account.toml` and `relations/`: the engine names no
one (#203).

Originals use `EDITORIAL_OLLAMA_MODEL` (default `gemma4:31b`) with a
strict output schema and a bounded cold-load timeout. The reply model retains
its own configuration. The draft generator sees fetched primary-source text. The generator selects numbered source
passages; the application attaches their exact text as evidence. It cannot
substitute a fabricated quotation for the supplied source text. A separate editor must explicitly approve
factual grounding, AI relevance, added value, natural voice, and novelty. Any
missing/malformed approval, rejection, stale item, duplicate or provider error
skips publishing. An LLM review reduces risk but is not proof that a claim is true.
The checked draft and its source link survive publishing without random rewrites.

Trusted AI feeds supply news and articles no older than 48 hours: first-party
labs, model/tool launch blogs, The Decoder and arXiv. Fresh launches, methods,
projects and sharp recent articles are preferred; on quiet days, curated AI
documentation supplies practical, evergreen topics, without calling them new
announcements. Used source URLs are rested for seven days. The optional 20:45
slot needs news from the last twelve hours or a useful AI teaching source, plus
an exceptional-value approval.

## Niche of Replies, likes and follows

Operator, 2026-09-25: AI only, like the Originals. The Account's `[niche]`
patterns, `[searches]` queries and `[network]` lists in
`accounts/theaishrink/account.toml` keep to AI (issue #205). A post that
speaks only of crypto, markets or space is off the niche for the search
lane, the feed sweep, early bird and mega watch; the follow quality gate
refuses a non-Engager whose bio shows no AI term; the reply and like
searches look for AI posts only. Crypto, markets and space accounts left
the reply and scan lists. The accounts the Operator picked by hand stay
whatever their topic: Graphseo, TheBTCTherapist and McnallieM, and
Mindset4Money_X in the curator's pins, and so do the few handles whose
topic is still to be confirmed by the Operator. The VIP scan still answers
Graphseo's and TheBTCTherapist's posts without the niche filter, and
answers to Engagers still follow the conversation.

The search lane, the feed sweep, early bird and mega watch answer root
posts only: a post X marks as a reply, or whose text opens on a mention,
never reaches the model, which would see it without the post it answers
(issue #241). The VIP scan still answers everything its accounts post,
their replies included.

The `post` and `bio` patterns name AI itself (AI, IA, AGI, LLMs, GenAI,
artificial intelligence, machine and deep learning, computer vision,
superintelligence, agentic, context windows, open weights, vibe coding),
its labs and models (OpenAI, Anthropic, DeepMind, Mistral, Llama, Qwen,
Veo, Sora, Midjourney, Apple Intelligence…), its hardware (Nvidia, GPUs,
TPUs, data centers) and robotics. Some words no longer suffice alone:
`token`, `coding`, `agent`, `meta`, `google`, `apple`, `software`, `tech`,
`engineer`, `founder`; a post or bio needs an AI term beside them (AI
agents, coding agents, Meta AI). `ai` in lower or mixed case skips the
French verb (j'ai, J’ai, je vous ai, ai-je); AI in capitals always counts.
`bio` leaves out the model names that are also first names or common
words (Claude, Sora, Gemini, Cursor), since it reads the display name too.
Known false positives, kept: Nvidia, an AI hardware maker, keeps its stock
and earnings chatter on the niche, and `robot` keeps a trading robot.

Every reply and like query finds posts `post` keeps, read with AND before
OR or OR before AND: a company or energy word goes with AI (TSMC AI,
CoreWeave AI, megawatt AI). The like job checks no niche, so its queries
are its only filter.

## Trend slots and the Startup post

The 10:00, 13:00 and 15:00 slots, and the Startup post, take their topic from
X. Two Top-tab searches for AI and "artificial intelligence" (`[searches]
trending` in `account.toml`) supply posts from
the last 24 hours; the five with the most likes per minute are kept. Own posts,
Blocked accounts, nested replies, posts without AI vocabulary and crypto or
ticker posts are dropped. Handles, mentions and links, with or without a
scheme, are stripped before the text reaches the model. Fewer than three usable posts skips the pass.

The trending posts choose the topic and never supply a fact. The generator must
write from a fresh news article from the trusted feeds that covers their shared
topic, with the usual evidence and source link; evergreen documentation is not
offered. The draft carries no @mention. The editor must also approve
`trending`: the published text covers the topic the trending posts share. No
covering article, no post.

The Startup post (operator, 2026-09-23) is a trend slot opened for 45 minutes
each time the bot starts in waking hours, restarts included: a crash, a
watchdog relaunch or a deploy each opens one. It has its own three attempts
and pending guard per start, goes before a slot whose window is open, and
obeys the waking hours, the eight-publication ceiling and the post spacing. A
pass that gives it no draft falls through to the open slots in the same pass,
so a restart never hides a slot. A start overnight opens nothing, even just
before 04:30. A restart loop in daytime therefore publishes
up to one post every twenty minutes until the daily ceiling, at the expense of
later slots. An ambiguous submission counts as a publication for that: the
next Startup post waits twenty minutes after it, the day's pending submissions
count toward the eight, and its text is a recent post the next draft and review
must not repeat.

## Runtime rules

- Toronto time is explicit and used for budgets and waking hours, including DST.
- The scheduler pauses overnight. Queued jobs, browser-lock acquisition,
  AppleScript execution and model calls also check the window. Already-issued
  remote work can finish; it cannot authorize a later out-of-hours submission.
  A stop request (SIGTERM, Ctrl-C) counts as overnight: no job starts and no
  write is admitted after it.
- Slots: 05:00, 07:15, 09:30, 10:00 (trend), 11:45, 13:00 (trend), 14:00,
  15:00 (trend), 16:15, 18:30, optional 20:45, plus the Startup post.
  Eleven slots and the Startup post compete for eight publications: on a full
  day the evening slots are the ones left out.
- A slot permits at most three attempts over 45 minutes, and no window runs
  past midnight: the 20:45 slot ends at 21:30, a Startup post window at bedtime.
  An attempt is a draft submitted to the editor; a pass without a draft
  spends none. A slot out of attempts, or one whose pass yields no draft, no
  longer holds an overlapping one; a pass still submits once at most.
  There is no backlog catchup. At least twenty minutes separate originals.
- Eight profile publications per local day is absolute. The ledger includes
  originals, quotes and reposts already made that day. Deploying this change
  does not erase history or grant extra slots. A `pending` submission, whose
  outcome was ambiguous, has no ledger row: it counts toward the day's eight
  and toward the twenty-minute spacing until the operator clears it, and so
  does a slot the operator marked published after a check.
- Quotes and general reposts remain disabled, including urgency and mega-viral
  exceptions. The October 23 priority-watch request above permits reposts only
  for the explicitly watched author, within the existing combined budget.
  The legacy quote, repost, thread, GIF-post and self-reply functions remain
  removed (issue #111); `tests/test_disabled_surfaces.py` pins those removals.
  The new `repost_tweet` chokepoint enforces the narrow exception independently
  of its caller. Further expansion needs an operator request and policy update.
- Replies have no daily cap. Browser pacing and permanent status-ID dedup
  apply. The live Account accepts standalone originals only: self-replies,
  comments, debate turns and follow-up exchanges are refused.
  The per-tweet dedup store fails closed: while it is unreadable, no reply
  ships. The gap after each reply is `MIN_SECONDS_BETWEEN_REPLIES` plus a
  jitter drawn once per reply, the same for every caller: retrying cannot
  shorten it. The direct-reply and feed-sweep pipeline waits out that gap
  before sending instead of discarding a paid generation; the chokepoint
  still judges, and the wait ends on a stop request or at midnight.
- Reply admission (`src/guards/reply_admission.py`) runs at the reply chokepoint
  for every job: a reply is refused when the author handle in the parent's
  URL contains a `BLOCKLIST` token or one of the Account's
  `network.blocked_accounts`, which add to it and never remove from it
  (case, spaces, dashes and underscores ignored on both sides), when the parent is the account's own post, or
  when the URL carries no author handle. The scheduled reply jobs ask
  the same admission before paying for a generation and keep no copy of
  these rules (issue #100). The legacy `reply_job`
  (`ENABLE_REPLY_SEARCH=1`) finds and drafts in one model call, so it asks
  admission for each target before sending (issue #109). `BLOCKLIST` is matched on the URL
  handle only: `direct_reply`, `feed_sweep`, `mega_watch` and `replyback`
  no longer match it against the scraper's display name, which is not an
  identity. The replyback profile likes read the Engager's handle from
  the reply's URL and still check both. `like_tweet`
  refuses a post whose URL handle is a Blocked account with the same match,
  and so does the follow policy for every `follow_account` caller, jobs and
  seeding script alike (issue #188).
  `early_bird` and `mega_watch` keep a watched account's post when its URL
  handle is that account, whatever its display name: comparing the display
  name dropped every account whose name differs from its handle (#162).
- Every Reply prompt, in every job, opens on the Voice and carries the hard
  rules and the respect list (`personality_store.hard_rules_block()`):
  `src/replies/reply_generator.py` assembles them all (issues #155, #192). A model SKIP sets the post aside for good;
  a model rate limit, every provider at its usage limit, ends the job's
  generations for the cycle. The prompt names every Respected account.
- Model calls stay on their configured provider, Ollama by default. Only an
  explicit `LLM_FALLBACK_CLI` adds a fallback: without it, a failed call
  fails, for Originals and Replies alike. A provider name the code does not
  know fails every call it routes and runs nothing, and the start logs it
  (issue #189). One exception, pending the Operator's decision: the Replies
  to @Graphseo run on the Claude CLI whenever it is installed (his
  Relation's `provider` in `account.toml`), with
  `PRIORITY_REPLY_MODEL`, unset Claude's default `claude-haiku-4-5-20251001`
  (issue #197).
- An outgoing text that names a Respected account, by `@handle` or by its
  handle in a sentence with a derisive word, is refused at the write
  chokepoint, dry run included: `post_tweet` for an Original, Reply
  admission for a Reply. A Reply may carry the `@handle` of the Respected
  account it answers, never mock it by name nor name another one. A
  refused Reply sets the post aside for good, as a model SKIP does, and
  leaves the replied store unmarked. A dry-run Original never reaches
  `post_tweet`: the editorial judges its text with the same check
  (issue #190).
- Publishing checks the budget again after obtaining the browser lock.
  Preview and dry-run records do not consume the real daily budget.
- `DRY_RUN=1` stops every browser write. The profile likes (`engage_job`,
  and replyback's likes to Engagers), the notify likes and the `like_job`
  likes go through `like_tweet` and its ledger: under `DRY_RUN` they open
  nothing. `like_job` likes at most 10 posts a cycle and 500 a day, and
  starts no like 30 s after taking the browser. A dry-run pin writes a
  dry-run ledger row through `pin_own_tweet` and leaves `pin_job`'s live
  daily attempt unspent. A
  dry-run reply never marks the tweet as answered, and a dry-run follow
  never enters `followed_accounts.json` or the follow-engagers state.

## Bounds on volume and check settings

The Operator set these bounds on 2026-09-25 (issue #201). They live in the
declarations of `src/core/settings.py`; `.env` and an Account's `[limits]`
may only tighten them. A value past a bound is brought back to it with a
`[SETTINGS]` warning at start; `main.py --dry-run` lists every bounded
setting under `bounded_settings`, with its effective value, and the
warnings under `settings_warnings`.

| Setting | Bound | Default |
|---|---|---|
| `DEBATE_MAX_TURNS_PER_AUTHOR_PER_DAY`, Debate turns per Engager per day | 0 to 4 | 4 |
| `MIN_SECONDS_BETWEEN_REPLIES`, gap between Replies | at least 8 s | 8 |
| `REPLY_JITTER_SECONDS`, Reply jitter | at least 0 | 7 |
| `LIKE_BOT_PER_CYCLE`, likes per `like_job` cycle | 0 to 10 | 10 |
| `LIKE_BOT_DAILY_CAP`, `like_job` likes per day | 0 to 500 | 500 |
| `FOLLOW_TOTAL_CAP`, accounts followed in total | 0 to 3500 | 300 |
| `MAX_FOLLOWS_PER_DAY`, follows per day | 0 to 20 | 20 |
| `FOLLOWBACK_CAP`, Follow-backs per cycle | 0 to 8 | 8 |
| `FOLLOW_ENGAGERS_PER_DAY`, Engagers followed per day | 0 to 10 | 10 |
| `FOLLOW_ENGAGERS_PER_CYCLE`, Engagers followed per cycle | 0 to 2 | 2 |
| `BAN_SHORT_TERM_PRICE_TARGETS`, short-term price target ban | always on: 0 reads as 1 | 1 |
| `DUP_JACCARD_THRESHOLD`, duplicate Jaccard | at most 0.45 | 0.45 |
| `DUP_CONTAINMENT_THRESHOLD`, duplicate containment | at most 0.6 | 0.6 |
| `DUP_SHARED_BIGRAMS`, shared bigrams that make a duplicate | 1 to 3 | 3 |
| `DUP_TOPIC_SHARED_WORDS`, shared words that make a same story | 0 to 3 | 3 |
| `DUP_TOPIC_WINDOW_HOURS`, same-story window | at least 24 h | 24 |
| `DUP_TEXT_WINDOW_HOURS`, text-similarity window | at least 48 h | 48 |
| `REPLY_MIN_CHARS`, shortest Reply | at least 25 characters | 25 |

The duplicate settings may only get stricter: a lower threshold or count, or
a longer window, catches more duplicates; `DUP_SHARED_BIGRAMS` stops at 1,
since at 0 any recent Original would make every new one a duplicate. The
other counts stop at 0: a negative one is brought back to 0 with a warning,
where `FOLLOWBACK_CAP=-1` used to take every candidate but one.
A float setting takes a finite number only: `nan` or `inf` stops the start
like a badly typed value. The older bounds hold as before:
`MAX_ORIGINALS_PER_DAY` from 0 to 8, `MIN_SECONDS_BETWEEN_POSTS` at least
1200, `POST_JITTER_SECONDS` at least 0. Lifting any bound needs an explicit
Operator request and an update of this table in the same change.

## Inspection and recovery

The dry-run command ([`AGENTS.md#verification`](../AGENTS.md#verification))
shows jobs and policy without browser/model calls. `editorial_review.jsonl`
stores accepted and rejected draft decisions. `editorial_state.json` stores
attempts, slots and recent publication/source history. A `pending` slot is never
retried automatically; clear it by hand as described in
[`OPERATIONS.md#recovery`](OPERATIONS.md#recovery). Corrupt editorial state
fails closed and is reported in the log.

The active scheduler omits autonomous code/prompt rewriting and older profile
publishing jobs. Hard caps in `src/core/config.py` also override stale strategy data.
Reply pacing remains configurable within its floors. Restart after changing code or configuration.

## Reach target

`editorial_reach.md` and `.json` show observed lifetime views of original posts
published in the last seven days against a 500,000-view target. The report counts
each observed post once, excludes replies and reports missing coverage. It does
not claim unique viewers or home-timeline attribution, which public counters do
not expose. This goal never relaxes the post ceiling or quality checks.

## Verification

CI runs the guard suite plus scheduler, Toronto/DST boundaries, queued browser
work at bedtime, cap concurrency, source evidence and review rejection, restart
idempotency, unsuccessful submission, dry-run isolation, and reach accounting.
No test may drive Safari or publish a post.

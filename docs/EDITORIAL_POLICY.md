# Editorial policy — October 12, 2026

The operator's current mandate (2026-10-12) targets at least 300 useful replies per full
Toronto day and permits at most 400, to other accounts' standalone posts only. Never answer own
posts or comments on them. Nominal activity windows are 05:00–10:00,
12:00–13:00 and 16:45–23:00 Toronto time. Each start varies independently
by ±10 minutes per Toronto day, stable across restarts. Closing times are fixed
and end exclusive. All external activity uses those actual daily windows.
Reposts have a separate 50/day maximum, permanent duplicate protection and
the priority-author/generated-video admission rules below.
The schedule aims for six originals, with more opportunities
than the ceiling allows when sources are strong enough. Quality can reduce the actual count.
The same day the operator added three trend slots and a Startup post on every
start; they compete for the same eight publications (see below).
There is no guarantee of virality or a minimum post count on a day with weak
sources or service failures.

Operator, 2026-10-12: the shared Reply pool considers standalone posts from
the last 24 hours. Early-bird and mega-watch profile scans use that same
window; their former eighteen- and four-minute cutoffs are removed. Frequent
scans can discover new posts promptly without excluding useful older ones.
There is no fifteen-minute post-age limit. All topic, quality and write checks
still apply; this changes neither job cadence nor publication spacing.

2026-10-12 reliability correction: selection compares at most eight posts per
model call, mixing two waiting discoveries and six fresh ones before revisiting
reviewed posts. The schema fixes the response count and permits only supplied
IDs; incomplete or token-truncated output cannot approve a candidate. A failed
comparison refresh does not invalidate an existing explicit approval less than
one hour old. Reload the pool and apply every normal check before using it.
Quality remains 85/100, with no guaranteed minimum number of replies.

## Value and voice

The Account is **The SI Maximalist, @thesimaximalist** (Operator, 2026-10-12).
The Voice covers SI brainrot, super intelligence, news, generated media, clearly
fictional celebrity parodies and substantive technology. It is direct, informed,
funny and specific: explain the mechanism, tradeoff or useful implication, or make
an original joke tied to the post. It replaces the therapist/mom/flirtation persona.
Identity stays honest: no fabricated human life, experiments or personal product
use. Media descriptions need supplied context. Parody is never presented as real
news, endorsement or a quote. No automatic video generation/upload is introduced.
The Voice lives in `accounts/theaishrink/voice_en.md` and `voice_fr.md`; every
Original and Reply prompt carries it. Older learned examples cannot override it.
The pro-Elon/Grok preference, hard rules and respect list still apply.

The storage identity remains `BOT_ACCOUNT=theaishrink`; changing the public handle
does not reset ledger counts, reservations, permanent Reply IDs or history.
Optional `previous_handles` in the Account protects saved own-post URLs from before
the rename. `.env` must not retain a stale public `BOT_HANDLE` override.

Operator, 2026-10-12: vary Reply format with weighted choices: a few words
(2–8 words, 35), a short observation (9–23, 40), or an explanation (24–50, 20).
These are relative weights, not quotas. All prose stays within 278 characters.
Recent shipped Replies exclude a third consecutive format. Startup Replies keep
their twenty-word limit. A format that does not suit the post yields SKIP.
Generic textual praise stays blocked; `REPLY_MIN_CHARS` is five.

Later clarification, 2026-10-12: **no emojis or text smileys in Originals or
Replies**, including decorations appended to otherwise substantive text. This
supersedes the earlier permission for occasional smileys. Standalone reaction
formats are removed. The legacy `REPLY_ALLOW_REACTIONS` key remains accepted for
compatibility but always clamps to false. Reply generation requests plain text
and gives a decorated draft one rewrite; persistent violations publish nothing.
Final content validation applies the ban to every publishing path. Ordinary
punctuation, mathematical notation, URLs and literal code remain usable. No
silent deletion of a smiley that could alter the intended meaning.

Reply prose uses SI or super intelligence for the generic field. This editorial
choice does not assert that every model has superhuman general intelligence.
Discovery retains AI, artificial intelligence, SI/ASI, super intelligence and
both historical and current company aliases. [The official site](https://x.ai/)
was checked on 2026-10-12: it presents SpaceXSI and links `@SpaceXSI`.
Current profile lists and Reply prose use that name. Other verified names,
legal names, URLs, handles and inline code retain their spelling; no automatic
company renames or altered source quotations. Optional Account patterns
`niche.reply_forbidden` and `niche.reply_preserve` enforce this distinction in
generation and final Reply validation. Invalid format or wording gets one
rewrite, then no Reply if it still fails. No schedule, volume or restart change.

Originals use `EDITORIAL_OLLAMA_MODEL` (default `gemma4:31b`) with a
strict output schema and a bounded cold-load timeout. The reply model retains
its own configuration. The draft generator sees fetched primary-source text. The generator selects numbered source
passages; the application attaches their exact text as evidence. It cannot
substitute a fabricated quotation for the supplied source text. A separate editor must explicitly approve
factual grounding, topic relevance, added value, natural voice, and novelty. Any
missing/malformed approval, rejection, stale item, duplicate or provider error
skips publishing. An LLM review reduces risk but is not proof that a claim is true.
The checked draft and its source link survive publishing without random rewrites.

Trusted AI feeds supply news and articles no older than 48 hours: first-party
labs, model/tool launch blogs, The Decoder and arXiv. Fresh launches, methods,
projects and sharp recent articles are preferred; on quiet days, curated AI
documentation supplies practical, evergreen topics, without calling them new
announcements. Used source URLs are rested for seven days. The optional 22:15
slot needs news from the last twelve hours or a useful AI teaching source, plus
an exceptional-value approval.

## Niche of Replies, likes and follows

Operator, 2026-10-12, expanded discovery: substantive technology now qualifies
without an AI connection. This supersedes the earlier SI-only scope and the
removal of Home discovery. Keywords and searches cover AI/SI plus software,
hardware, security, chips, robotics, space engineering and autonomous vehicles.
Generated media, brainrot and clearly fictional tech celebrity parodies qualify;
unrelated celebrity gossip, lifestyle, politics, sports and trading do not.

Every two minutes, the sweeper rotates one native view (For You, Following Recent,
Following Popular), one Latest topic query and one dedicated generated-video query.
Each video query is searched in Latest, then Top; no minimum-like gate applies. Feed tabs and Following sort state
must be verified; missing controls skip the view rather than mislabel a fallback.
Scraping collects each viewport before scrolling, deduplicates status IDs and stops
at a bounded scroll count or two unchanged reads. Scrolling moves the document
rather than relying on keyboard focus. All discoveries are archived before filters.
Latest queries remove minimum-like gates; Top queries retain their popular lane.
All searches receive crypto exclusions; declared topic queries are not duplicated
inside a second topic expression. Ad-hoc queries receive a compact topic scope. Direct discovery
rotates one priority profile and three Top queries by default; early-bird scans
two profiles and mega-watch one. The Reply selector has a dedicated worker and
keeps its one-minute cadence, one candidate per cycle and 85/100 approval threshold.

Saved tracked handles still require current topic evidence. A new discovery needs
fresh explicit topic approval in the shared pool; legacy saved handle lists alone
are insufficient. Unreadable guarded state stops jobs that depend on it. A post
previously rejected solely by the keyword gate can re-enter on rediscovery after
a topic expansion, but an explicit model rejection is not recycled.

Crypto, Bittensor, staking, memecoins, token sales and trading/stock content
are excluded even when they mention SI. Exclusions apply to feed news titles,
trends, profile quality and every outgoing text as well as Reply parents.
Generated stock photography/footage is allowed. Historical state, follow
relationships and permanent one-Reply records are retained; old crypto
relationship prompts, positive seeding lists and contradictory maintenance
instructions are removed. No live follows, unfollows, posts or restart are
part of this cleanup.

All authors, including VIPs, must meet the topic rules. Only other accounts'
standalone posts qualify; conversation turns stay disabled. Every status ID stays
protected permanently, including when a URL's handle changes.

The profile allowlist, priority scans, pinned tracking and manual follow seeds
now focus on AI researchers, builders and enthusiasts, led by Elon Musk, SpaceXSI
and Karpathy. Former crypto/trading exceptions, including TheBTCTherapist and
Graphseo, are blocked even if stale `.env` lists or saved discoveries name them.
The optional Account `niche.excluded` pattern rejects Bitcoin/crypto text even
when AI words are present. `like_tweet` checks actual parent text before any
click and does not borrow text from quoted posts. Feed author harvesting and
curator promotion require on-niche evidence. Followers, Engagers and discovered
seeds require an AI/SI or technology bio; only manual seeds bypass positive bio/size/language
checks. Topic exclusions apply to everyone. `FOLLOW_REQUIRE_NICHE` cannot be
disabled. Existing following relationships are not automatically removed.

Every discovery is saved. The shared pool rejects off-niche text before model
selection and rechecks older saved candidates. URLs and handles are stripped
before matching. Selection requires a boolean `on_topic=true` and at least 85/100;
a negative topic verdict forces the score to zero, and an absent or malformed
verdict cancels the review. Cached scores without a topic verdict cannot win.
The actual opened post is checked again for standalone status and niche text
before a Reply is typed or its parent liked. An unreadable target is refused.
The Account's `niche.reply_instructions` supplies the same topic and quality
requirements to selection and drafting. Model review reduces relevance errors;
keywords alone cannot prove that a post fits the topic.

The `post` and `bio` patterns cover SI/AI terms and substantive technology.
Names, URLs and ambiguous keywords alone never establish relevance; semantic
selection still rejects an incidental mention, an unrelated meaning of SI or
ordinary French “si”. Generic founder/agent labels alone remain insufficient.

## Video discovery and reposts — Operator 2026-10-12

This mandate supersedes the earlier zero-repost rule. Reposts have a separate
hard ceiling of **50 per Toronto day**, including ambiguous submissions and
already-reposted posts first observed that day. The operator welcomes 40–50
when supply supports it; there is no forced minimum. Originals retain their
8/day ceiling and twenty-minute spacing; Replies retain 300 target/400 maximum.
Reposts are at least ten minutes apart and only within the same active windows.
The job checks every two minutes and attempts at most two targets, stopping
immediately after a shipped or ambiguous submission. Already-recorded status
IDs are never reposted again, even after a restart, a handle change or a new day.
Quotes, threads and self-recycling remain disabled.

New standalone posts from the Account's `reposts.priority_handles` (Elon Musk)
take priority, oldest first within 24 hours. The requested “all” allows their
subjects outside AI/SI/technology, but Bitcoin/crypto, blocked/own authors and
conversation replies remain excluded. This exception applies to reposts only.
The shared 50/day ceiling always wins if more priority posts arrive. A dedicated
Latest search improves discovery of new originals rather than recycling history.

Other authors require an attached video belonging to the actual parent post,
caption evidence of generated video, and either 500 likes, 100 reposts, or rapid
engagement (at least 75 likes with weighted velocity >=5/min, or 20 reposts with
velocity >=4/min; velocity is `(likes + 4 * reposts) / age_minutes`). Views alone
cannot qualify. A separate caption review must approve the context; uncertain,
unrelated, misleading, promotional or insufficiently described clips are skipped.
The review has caption/engagement metadata, not decoded video frames or audio.
Approvals expire after one hour and are bound to the exact caption. The write
reads the same DOM text content as discovery, avoiding presentation-only differences, and
rechecks actual post text, media, author, standalone state and current counts.
A quoted video's media cannot stand in for the parent's own attachment.

Searches cover AI/SI video generation, Seedance, Grok Imagine, Grok AI/image,
@grok/@imagine, Sora, Veo, Kling, Runway, Pika, Luma, Hailuo, Wan, Hunyuan,
LTX, PixVerse, Higgsfield, ComfyUI, workflows, prompts, lip sync, camera control,
image-to-video, animation, memes, brainrot and clearly fictional parodies.
Broader Latest searches also cover new models, research, reasoning, agents,
MCP, RAG, multimodal inputs, open weights, inference, distillation and robotics.
Short grouped queries preserve search reliability. Model/tool names and current
claims still need context; adding a keyword never proves factual expertise.
Explicit video-generation credits such as “Video generated with @grok” qualify
as caption evidence; bare handles and unrelated videos do not. Keywords were
checked against primary references including [Seedance](https://seed.bytedance.com/en/seedance2_0/),
[Grok Imagine](https://docs.x.ai/developers/models/grok-imagine-video), and
[Diffusers video pipelines](https://huggingface.co/docs/diffusers/main/using-diffusers/cogvideox).

Up to four positions in each eight-post Reply comparison prioritize video
candidates, alongside two older waiting discoveries and fresh general posts.
Approved video candidates receive a three-point ordering preference; raw scores
below 85, off-topic verdicts and expired approvals remain ineligible. Reply
length varies with the existing style choices. Replies never invent having
watched a clip, model versions, benchmarks, visual details or production tools.

The repost write clicks only the matched post's native `retweet` and explicit
`retweetConfirm` controls, never a toggle shortcut or undo control. Before the
possible submit it reserves the status ID in guarded `repost_history.json`.
Only a confirmed native `unretweet` state records a shipped ledger row. An
uncertain result stays reserved and consumes budget; check X before repairing it.
An unreadable history stops reposting without replacement. A temporary browser
failure pauses that candidate for ten minutes so others can still be considered.
Code/config changes take effect on the next explicitly requested start/restart.

## Trend slots and the Startup post

The 09:45, 12:20 and 17:00 slots, and the Startup post, take their topic from
X. Top-tab searches for AI, "artificial intelligence", SI, "super intelligence"
and the SpaceXAI/SpaceXSI aliases (`[searches]
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
so a restart never hides a slot. A start outside the actual daily windows opens
nothing. A restart loop in daytime therefore publishes
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
- Slots: 05:00, 07:15, 09:30, 09:45 (trend), 12:00, 12:20 (trend), 12:40,
  17:00 (trend), 17:45, 18:30, optional 22:15, plus the Startup post.
  Eleven slots and the Startup post compete for eight publications: on a full
  day the evening slots are the ones left out.
- A slot permits at most three attempts over 45 minutes, and no window runs
  past the active window: the 22:15 slot ends at 23:00; a Startup post window
  ends at the next pause.
  An attempt is a draft submitted to the editor; a pass without a draft
  spends none. A slot out of attempts, or one whose pass yields no draft, no
  longer holds an overlapping one; a pass still submits once at most.
  There is no backlog catchup. At least twenty minutes separate originals.
- Eight Original/quote publications per local day is absolute. The ledger includes
  originals and historical quotes already made that day; reposts use a separate budget. Deploying this change
  does not erase history or grant extra slots. A `pending` submission, whose
  outcome was ambiguous, has no ledger row: it counts toward the day's eight
  and toward the twenty-minute spacing until the operator clears it, and so
  does a slot the operator marked published after a check.
- Quotes remain disabled. Reposts use the separately authorized 50/day policy above.
  The legacy quote, toggle-repost, thread, GIF-post and self-reply writers remain
  absent (issue #111), as `tests/test_disabled_surfaces.py` pins. Only the newly
  authorized `repost_tweet` path restores reposting with independent guards.
- Replies have a hard 400-per-day cap, with a target of at least 300 useful Replies. Browser pacing, per-tweet dedup and bounded
  standalone-post verification protect conversation quality. Conversation
  turns and comments on our posts are no longer scheduled or admitted by the
  Reply pipeline.
  The per-tweet dedup store fails closed: while it is unreadable, no reply
  ships. The gap after each reply is `MIN_SECONDS_BETWEEN_REPLIES` plus a
  jitter drawn once per reply, the same for every caller: retrying cannot
  shorten it. The direct-reply and feed-sweep pipeline waits out that gap
  before sending instead of discarding a paid generation; the chokepoint
  still judges, and the wait ends on a stop request or at the active window’s end.
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
  (issue #189). Account Relations can select their own provider with
  `PRIORITY_REPLY_MODEL` (issue #197); the old finance Relations cannot run
  because their authors are blocked.
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

The Operator set these bounds on 2026-09-25 (issue #201), with the Reply
ceiling revised on 2026-10-12. They live in the
declarations of `src/core/settings.py`; `.env` and an Account's `[limits]`
may only tighten them. A value past a bound is brought back to it with a
`[SETTINGS]` warning at start; `main.py --dry-run` lists every bounded
setting under `bounded_settings`, with its effective value, and the
warnings under `settings_warnings`.

| Setting | Bound | Default |
|---|---|---|
| `MAX_REPLIES_PER_DAY`, Replies per Toronto day, ambiguous submissions included | 0 to 400 | 400 |
| `TARGET_REPLIES_PER_DAY`, useful Replies targeted per Toronto day, clamped to the effective cap | 0 to 400 | 300 |
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
| `REPLY_MIN_CHARS`, shortest text Reply | at least 5 characters | 5 |
| `REPLY_ALLOW_REACTIONS`, legacy reaction switch | always off: true reads as false | false |

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

2026-10-07 — Operator requested restoration of the code that was on main on
September 26, 2026. The last main commit before September 27 in Toronto time
was 348c82bc (September 25 at 21:18); no September 26 commit exists. Tracked
code, Account files, tests and documentation return to that snapshot. This
explicit rollback supersedes later behavior mandates and restores the snapshot's
checks and settings, including its Reply behavior without the later independent
Reply quality review. Production state, .env and untracked files are preserved.
The running bot is not restarted; deployment takes effect on the next explicitly
requested start or restart.

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

2026-10-12 — Reply volume clarification supersedes the five-per-day limit:
at least 300 useful Replies targeted over a full Toronto day, at most 400
including ambiguous submissions. The target depends on eligible posts and model
and browser availability; it never lowers the quality or topic threshold. A
partial day need not reach 300. The selector runs every minute and attempts one
Reply at most; its first regular run is 120 seconds after start, after the
90-second Startup attempt. Reviews remain usable for less than one hour;
queued discoveries are compared after five minutes or as soon as approved
candidates run out. Each selected candidate passes admission again. The day's
400 allowances accrue proportionally across the twelve active hours (about
33 per active hour); unused allowances carry forward that day, with no burst
catchup. Original publication, Reply topic and evidence rules are unchanged.

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

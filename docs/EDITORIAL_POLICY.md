# Editorial policy — September 23, 2026

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
  past 23:30: the 20:45 slot ends at 21:30, a Startup post window at bedtime.
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
- Quote/repost caps are zero, including urgency and mega-viral exceptions.
  Feed sweeps now reply. The quote, repost, thread, GIF-post and self-reply
  write functions are removed from `src/x/twitter_client.py` (issue #111), and
  no scheduled job carries such a branch (issue #107):
  `tests/test_disabled_surfaces.py` pins both. Bringing one back takes new
  code and an operator request, not a config change.
- Replies have no daily cap. Browser pacing, per-tweet dedup and bounded
  per-author debate turns protect conversation quality. Every answer to
  someone who answered the account is a debate turn, whichever job sends it.
  The per-tweet dedup store fails closed: while it is unreadable, no reply
  ships. The gap after each reply is `MIN_SECONDS_BETWEEN_REPLIES` plus a
  jitter drawn once per reply, the same for every caller: retrying cannot
  shorten it. The direct-reply and feed-sweep pipeline waits out that gap
  before sending instead of discarding a paid generation; the chokepoint
  still judges, and the wait ends on a stop request or at 23:30.
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

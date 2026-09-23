# Editorial policy — September 20, 2026

The operator requested 5–7 valuable posts a day, uncapped replies, a more natural
voice, and a working day from 04:30 to 22:00. The schedule aims for six originals,
with one optional exceptional-news slot. Quality can reduce the actual count.
There is no guarantee of virality or a minimum post count on a day with weak
sources or service failures.

## Value and voice

The character is a confident 45-year-old mom and AI enthusiast: warm, clear,
witty and occasionally flirty. AI knowledge, news and updates are the focus.
She explains a consequence, teaches something, or offers a useful action. A
question, joke, emoji or flirty line is optional. Forced formulas, engagement
bait, stale numbers, copied headlines and fabricated lived experience are out.
The AI identity remains honest; the therapist name is a brand persona.

Originals use `EDITORIAL_OLLAMA_MODEL` (default `gemma4:31b`) with a
strict output schema and a bounded cold-load timeout. The reply model retains
its own configuration. The draft generator sees fetched primary-source text. The generator selects numbered source
passages; the application attaches their exact text as evidence. It cannot
substitute a fabricated quotation for the supplied source text. A separate editor must explicitly approve
factual grounding, AI relevance, added value, natural voice, and novelty. Any
missing/malformed approval, rejection, stale item, duplicate or provider error
skips publishing. An LLM review reduces risk but is not proof that a claim is true.
The checked draft and its source link survive publishing without random rewrites.

First-party lab feeds supply news no older than 48 hours. On quiet days, curated
AI documentation supplies practical, evergreen topics, without calling them new
announcements. Used source URLs are rested for seven days. The optional seventh
slot needs news from the last six hours and an exceptional-value approval.

## Runtime rules

- Toronto time is explicit and used for budgets and waking hours, including DST.
- The scheduler pauses overnight. Queued jobs, browser-lock acquisition,
  AppleScript execution and model calls also check the window. Already-issued
  remote work can finish; it cannot authorize a later out-of-hours submission.
  A stop request (SIGTERM, Ctrl-C) counts as overnight: no job starts and no
  write is admitted after it.
- Slots: 05:00, 08:00, 11:30, 14:30, 17:30, 20:30, optional 21:30.
- A slot permits at most three attempts over 45 minutes (the last ends at 22:00).
  An attempt is a draft submitted to the editor; a pass without a draft
  spends none.
  There is no backlog catchup. At least one hour separates originals.
- Seven profile publications per local day is absolute. The ledger includes
  originals, quotes and reposts already made that day. Deploying this change
  does not erase history or grant extra slots.
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
  ships.
- Reply admission (`src/guards/reply_admission.py`) runs at the reply chokepoint
  for every job: a reply is refused when the author handle in the parent's
  URL contains a `BLOCKLIST` token (case, spaces, dashes and underscores
  ignored on both sides), when the parent is the account's own post, or
  when the URL carries no author handle. The six scheduled reply jobs ask
  the same admission before paying for a generation and keep no copy of
  these rules (issue #100). The legacy `reply_job`
  (`ENABLE_REPLY_SEARCH=1`) finds and drafts in one model call, so it asks
  admission for each target before sending (issue #109). `BLOCKLIST` is matched on the URL
  handle only: `direct_reply`, `feed_sweep`, `mega_watch` and `replyback`
  no longer match it against the scraper's display name, which is not an
  identity. The replyback profile likes still check both. `like_tweet`
  refuses a post whose URL handle is a Blocked account with the same match.
- Publishing checks the budget again after obtaining the browser lock.
  Preview and dry-run records do not consume the real daily budget.
- `DRY_RUN=1` stops every browser write, including the `like_job` likes and
  the pins that bypass the ledger. The profile likes (`engage_job`, and
  replyback's likes to Engagers) and the notify likes go through
  `like_tweet` and its ledger: under `DRY_RUN` they open nothing. A
  dry-run reply never marks the tweet as answered, and a dry-run follow
  never enters `followed_accounts.json` or the follow-engagers state.

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
Reply pacing remains configurable. Restart after changing code or configuration.

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

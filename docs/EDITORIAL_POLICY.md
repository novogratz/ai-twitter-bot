# Publishing policy — October 14, 2026

2026-10-14 — The Operator now requires Replies only. `publish_originals = false`
in the Account prevents Originals at the scheduler, Startup path, editorial entry
point and browser write; `.env` and `--post-only` cannot restore them. Conversation
jobs and automatic pinning are unscheduled. Daily Toronto activity windows are
05:00–09:30, 12:05–13:00, 17:15–20:00 and 22:00–23:00, start inclusive and end
exclusive, without jitter. Never interact with @elonmusk: no Reply, like, follow,
unfollow or @mention. Both `replies.protected_handles` and `network.blocked_accounts`
protect him, regardless of saved priorities or whitelist entries. Actual opened
authors are checked before browser clicks; a Reply parent mentioning a Blocked
account is refused too. Only another account's standalone original qualifies,
once per entire conversation permanently. Our current and historical handles,
comments, replies and follow-ups are forbidden. Permanent claims use a process
lock, and uncertain submissions stay claimed across restarts.

Outgoing prose replaces standalone AI with SI and artificial intelligence
(including Airtificial intelligence) with Super intelligence. Literal URLs,
@handles, embedded names such as OpenAI and French verbs are preserved. Discovery
still searches both vocabularies. Reply length and tone follow context: very short,
fuller technical, sharp or funny; no fixed suffix, automatic smiley or manufactured
typo. At most one optional emoji/text smiley. The minimum length floor is lowered
from 25 to 2 characters; generic reactions and all factual/content checks remain.
Recent shipped replies guide variation. Production history, pending state and
`.env` are preserved. This implementation does not start or restart the bot.

## Reply targets and no-contact protection

The Account is The SI Maximalist, @thesimaximalist; its existing `theaishrink`
storage key and all production history remain. Only another account's standalone
original may receive one Reply. Comments, responses, Debate turns, replyback,
conversation context, and our own posts/replies are refused. Historical handles
remain ours. Scrapers reject nested candidates; admission runs before drafting
and again at the write. The opened target must match the requested author and
status ID, be first in the conversation, have no reply context and no visible
prior answer by us. Unknown or mismatched pages cannot authorize a click.

@elonmusk is protected from all interaction, including replies to his comments,
likes, follows, unfollows and direct mentions in our text. A root post mentioning a Blocked
account is not answered, to avoid including that account in reply recipients.
His engagement with us grants no exception. URL misattribution cannot bypass
the browser's actual-author check. This is enforced at every write, including
manual calls and dry runs. Previously saved whitelist entries do not authorize
interaction. Manual unfollow selection checks both the profile link and button's
author label and skips Blocked accounts regardless of its keep-set. No unfollow
or change to an existing relationship is requested by this mandate.

Permanent `replied_tweets.json` IDs are never evicted. Claims are serialized by
both a thread lock and `replied_tweets.lock` across processes. Only a known
pre-submit failure may release its own claim. A possibly submitted Reply keeps
its claim forever until an Operator verifies and repairs it; no automatic retry.
An unreadable guarded store stops admission and is never overwritten.

## Wording, variety and evidence

Every outgoing message uses SI and Super intelligence instead of the standalone
acronym AI and the phrase artificial intelligence, including the misspelling
Airtificial intelligence. `text_replacements` in the Account declares this
wording; the shared Reply pipeline and final write normalize it before content
validation. Links and handles are literal identifiers, embedded product names
such as OpenAI/xAI remain exact, and French verbs are not technology acronyms.
This is Account terminology, not a factual assertion that every model has
achieved super intelligence. Searches and incoming source evidence retain both
AI and SI vocabulary.

The Voice is informed, playful and specific about SI news, models, research,
Grok Imagine video creation, brainrot and clearly fictional celebrity parodies.
The Operator's video work and reported strong engagement are supplied context;
particular scenes, settings, authorship and metrics still need evidence. Never
pretend a caption establishes unseen footage or that parody is real conduct.
No invented personal identity, capabilities, benchmarks or current news facts.
Respect-list and positive-only subject rules still apply.

Let the parent determine length and tone: a sharp few words, a fuller technical
explanation, a useful answer or an apt joke. Maximum 278 characters, not a target.
The 2-character floor permits meaningful brevity; generic praise and standalone
reactions remain refused. Normally no smiley, at most one optional emoji or text
smiley when appropriate, at any natural position. No automatic ending, random
case/period changes or manufactured spelling errors. Recent shipped replies are
shown as untrusted examples to avoid repeating, never as instructions or facts.

## Niche of Replies, likes and follows

SI/Super intelligence and related models, research, infrastructure and generated
videos remain the focus. Discovery uses the Account's niche patterns, configured
searches and network lists; video or celebrity mentions alone do not establish
relevance. Standalone SI/ASI terms are case-sensitive to avoid the French `si`.
Existing on-topic and content checks remain. Protected authors, our own content
and nested replies have no VIP exception.

## Scheduler and publishing permissions

The four Toronto windows apply every day without jitter: 05:00–09:30,
12:05–13:00, 17:15–20:00 and 22:00–23:00. Browser locks, browser scripts, model
calls, queued jobs and the final submit all check the clock. Closing is exclusive;
a request already issued may finish remotely but cannot authorize another write.

The live Account publishes Replies only. `publish_originals = false` gives an
effective original ceiling and target of zero, omits the editorial job, prevents
Startup windows and refuses direct `post_tweet`/editorial calls before browser,
model or publication-state work. `--post-only` errors. Original permission is
Operator-owned; `.env` cannot override it. Stored editorial slots, pending
submissions and history are preserved, not cleared or retried. Their old
three/six/eight targets are inactive for this Account. Quotes, reposts, threads
and self-recycling stay disabled.

Direct search, feed sweep, early bird and mega watch continue to discover root
posts. The optional search job retains its switch and the same final guards.
Replyback, Debate, babysitter and notification jobs remain unscheduled; their
retained manual paths cannot publish conversation replies. Automatic pinning is
unscheduled. Non-publishing likes, follows, browser upkeep and measurement jobs
keep their existing limits and respect the no-contact rule. Reply volume has no
new daily target or cap; existing spacing and per-cycle bounds remain.

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
| `REPLY_MIN_CHARS`, shortest Reply | at least 2 characters | 2 |

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

## Verification

Run the full isolated test suite and the scheduler dry run from `AGENTS.md`.
Validate all four activity boundaries, no startup or direct originals, protected
and misattributed authors, own/historical handles, nested targets, permanent and
concurrent deduplication, SI normalization, short and long replies and optional
smileys. Tests must not open Safari, call live models or change production state.
No start, restart, live profile edit or video upload accompanies implementation.

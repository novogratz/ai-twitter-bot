# @TheAIShrink

A persona-driven X account that publishes a few sourced AI posts a day and
converses through replies, within a ceiling set by the operator.

## Language

### Publishing

**Original**:
A top-level post the account writes itself from a source, carrying the source
link. At least three are targeted per day, six planned, eight at most.
_Avoid_: post, tweet, profile post

**Profile publication**:
Anything that appears on the account's profile timeline as its own: Originals,
quotes and reposts. Eight per Toronto calendar day, all kinds combined.
_Avoid_: profile post, post

**Slot**:
A fixed daily time window, with an Angle, in which at most one Original may be
published.
_Avoid_: window, schedule entry

**Angle**:
The brief a Slot gives its Original, set by the Account; every Trend slot
shares the Account's trend angle.
_Avoid_: purpose, brief

**Exceptional slot**:
The optional 20:45 Slot, reserved for news under twelve hours old or a useful
teaching source that the Editor judges exceptional.
_Avoid_: eighth post, breaking slot

**Trend slot**:
A Slot whose topic is the common thread of the Trending posts, told from a
fresh trusted article: 10:00, 13:00, 15:00 and the Startup post.
_Avoid_: viral slot, hot take

**Trending posts**:
The five fastest-rising AI posts on X from the last 24 hours, stripped of
handles, mentions and links. They choose a Trend slot's topic and never supply
a fact.
_Avoid_: top tweets, viral posts

**Startup post**:
A Trend slot opened for 45 minutes each time the bot starts in waking hours,
restarts included, keyed by the start time.
_Avoid_: startup burst, boot post

**Pending slot**:
A Slot whose Original was submitted without a definite outcome; it is never
retried until the operator clears it, and until then it counts as a Profile
publication for the day's ceiling and the post spacing.

**Write outcome**:
What one write to X (post, Reply, follow, like, pin) came to:
shipped, refused, failed before anything was sent, unconfirmed (it may have
reached X, the page never showed it), or dry run. Only a shipped write is
recorded in the ledger or counted by a job. A like names its outcomes
finely: liked is its shipped write, already liked and blocked are its
refusals; failed, unconfirmed and dry run keep their meaning. A follow
too: followed is its shipped write, already followed and each Follow
refusal are its refusals.
_Avoid_: success, result, ok

### Drafting and review

**Draft**:
A candidate Original produced for a Slot, tied to one source and to exact
passages quoted from it.

**Evidence**:
The exact source sentences a Draft relies on, attached by the application
rather than written by the generator.
_Avoid_: quote, citation

**Editor**:
The review, separate from drafting, that must explicitly approve a Draft
before it can be published: fixed checks on the text and its Evidence, then an
independent judgement of grounding, relevance, value, voice and novelty.
_Avoid_: reviewer, critic, gate

**Attempt**:
One Draft submitted to the Editor for a given Slot; a Slot allows three. A pass
that yields no Draft is not an Attempt.
_Avoid_: try, cycle, poll

### Conversation

**Reply**:
A post answering someone else's post. Never a Profile publication, and no
daily total applies to Replies.
_Avoid_: comment, response, draft (reserved for Originals)

**Voice**:
The account's persona, written by the Operator in the Account's folder,
`voice_fr.md` for a French reply and `voice_en.md` for an English reply or an
Original, and rendered as one block, under the
configured handle, at the top of every Original and Reply prompt. A prompt
says what to write; only the Voice says who writes it.
_Avoid_: core identity, persona prompt, spine

**Reply call**:
What a Reply job asks of the model: its prompt template, model, log label,
language rule and call options (`reply_generator.ReplyCall`). It says what
to write; the Voice, never the Reply call, says who writes it.
_Avoid_: voice (reserved for the persona)

**Relation**:
How the Replies treat one particular account, set by the Account under its
handle: its own Reply prompt and the CLI that writes it, or a fixed dossier.
The Account also sets the VIP scan's bestie and buddy prompts. The engine
names no one.
_Avoid_: VIP prompt, persona, special case

**Reply generator**:
The one step that turns a post and a job's Reply call into reply text: it always
opens the prompt on the Voice and adds the hard rules, picks the reply language, and reads the
model's answer as reply text, a decline (SKIP), a failure or a rate limit.
Reply text comes with the provider and model that wrote it.
_Avoid_: reply drafter, reply writer

**Provider exhausted**:
A model call on which every provider tried, the primary and its fallback,
hit its usage limit, as the CLI or the transport reported it; a model's
answer about rate limits never counts. The Reply generator reads it as a rate limit, and the
Reply pipeline ends the job's cycle with the post left replayable. A limit
on the primary alone is no exhaustion: the fallback answers, and the Reply
is recorded under the fallback's provider and model.
_Avoid_: rate-limit code, quota error, exit 75

**Reply pipeline**:
The one path from a job's candidates to shipped Replies: Reply admission
before the Reply generator, the write, then the engagement log for a Reply
that shipped. It sets aside, until restart, the posts a job is done with
(refused for good, declined, answered) and leaves the others replayable.
_Avoid_: reply loop, reply engine

**Debate turn**:
A Reply to an Engager, in answer to what they said to the account; capped per
Engager per day.
_Avoid_: rally, round, comeback

**Reply admission**:
The Operator's rules a Reply must pass before it ships: first on the post
it answers (author, Blocked account, own post, already Replied, Waking hours,
Debate turn cap), then again with the spacing since the last Reply and the
final text. Only a Reply it admits is sent.
_Avoid_: gate, prefilter, reply filter

**Replied store**:
The record of every post the account has Replied to, keyed on the post's
status ID: one Reply per post, ever. While it is unreadable, no Reply ships.
_Avoid_: replied set, replied cache, dedup file

### Accounts

**Account**:
The X account the bot runs, one per process, chosen at start by
`BOT_ACCOUNT`. Its folder `accounts/<name>/` holds `account.toml`: the
handle and language, the Slots and their angles, the feeds, Evergreen
topics and trusted hosts, the relevance filter, its network and niche:
the accounts the jobs answer, scan, visit or skip, the niche patterns and
the X searches, and the Relations; and next to it the Voice files and the
Relations' prompts. An Account may tighten an engine ceiling or floor,
never lift it, and add Blocked accounts, never remove one.
_Avoid_: profile (the account's page on X), bot, persona

**Engager**:
Someone who replied to or mentioned the account. The follow policy knows
narrower: only the authors the account answered with a Debate turn (and,
until about 2026-12-22, the frozen `replied_back.json`).
_Avoid_: commenter, fan

**Seed account**:
An account the Operator lists as worth following; the only kind the account
follows without a prior relationship, and never unfollows.
_Avoid_: whitelisted account, tier, discovered account

**Follow-back**:
Following an account that already follows this one.
_Avoid_: reciprocal follow, reciprocity

**Stranger**:
An account that is neither a Seed account, a follower, nor an Engager; never
followed, whoever asks. The follow policy finds the relation itself; no job
declares it.
_Avoid_: discovered account, feed account

**Follow refusal**:
The named cause of a follow the follow policy stops before the click:
Blocked account (matched as Reply admission and likes match it), too soon
(the follow spacing), cap reached (the daily cap, the following
ceiling or the ratio brake, reached or unreadable), quality rejected (the
quality gate, on the profile or within 30 days), or refused (every other
rule: handle, Stranger, whitelist, anti-churn). Too soon and cap reached concern the
account's follow budget, so a later cycle may follow the same account. A
whitelist or action ledger unreadable before the profile opens is no
refusal: it stops the job, and no account is marked tried.
_Avoid_: policy transient, follow error, skip

**Followed accounts**:
The record of the accounts the account followed, or found already followed,
kept by the follow chokepoint alone; the follow jobs read it to skip them.
_Avoid_: followed list, registry, follow cache

**Blocked account**:
An account the Operator bars from any interaction: a token of the engine's
`BLOCKLIST`, or one the Account adds to it.
_Avoid_: banned, blacklisted

**Respected account**:
An account engaged normally but never criticised or named in the account's
own commentary. A Reply to its post may address it by its `@handle`, never
mock it by name.
_Avoid_: protected account, influencer

### Time and people

**Waking hours**:
The only period when the account acts externally, 04:30 to 23:30 Toronto
time. `active_hours.WAKE` and `active_hours.BEDTIME` hold the two bounds.
_Avoid_: active hours, working day, awake

**Overnight**:
The rest of the Toronto day, when nothing external happens.
_Avoid_: bedtime, asleep, off hours

**Operator**:
The person who owns the account and alone sets its ceiling, voice and
guardrails.
_Avoid_: user, owner, admin

### Sources

**News item**:
A source from a first-party AI lab feed, published within the last 48 hours.
_Avoid_: article, story

**Evergreen topic**:
A curated AI documentation page used for teaching on quiet news days, never
presented as new.
_Avoid_: knowledge doc, knowledge source, curated documentation

### State

**Guarded state file**:
A JSON state file the bot cannot lose without acting more or dropping an
Operator list: a guardrail, a cap counter, a record of what already shipped.
While it is unreadable, the job that needs it refuses and nothing overwrites
it.
_Avoid_: critical file, protected file, strict file

**Disposable state file**:
A JSON state file the bot can lose without acting more: a cache, a report,
a harvested list. Unreadable, it reads as its default and the next write
replaces it.
_Avoid_: cache file, temp file, optional file

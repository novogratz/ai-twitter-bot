# AGENTS.md

2026-11-25, first live sends and what they caught — On the Operator's "lets go",
one thank-you (https://x.com/thesimaximalist/status/2125622302717177919), one
watched Reply with a GIF (https://x.com/thesimaximalist/status/2125626095772786968)
and one video share (https://x.com/thesimaximalist/status/2125632102364315980)
shipped, the two-minute window lifted for that one test on an older post. Nine
defects surfaced and are fixed with tests: the submission reservation applied
ordinary Reply text rules to a thank-you; a short watched Reply with no
detectable language, or with one word both languages share (" on "), was refused
as not English; the prepared watched Reply still expired after a fixed sixty
seconds; a watched quote post was compared with its quoted text included and
always refused; that refusal was silent and now logs its reason; the selector's
twenty-second model limit cut two of seven calls (thirty now); the video
history was asked with a float where it wants an aware time, which stopped every
share and the thirty-minute thank-you pace; a fresh share claim held its own
submit back; the share receipt was looked for on the source page instead of our
profile, and the composer text check counted an emoji X draws as an image.
Share searches use plain words plus the job's own `since:` date (emoji
alternatives returned nothing), and the cast in the video taste is a preference
for shares, never a requirement.

2026-11-25, viral AI videos from X with a short take — The Operator's coach:
"quote big viral AI videos with a 2-4 word take ... right click on the actual
video ... and click post. do it at least for 4 to 6 videos a day ... between 8
and 9, 12 to 1 pm, 5 to 6 and around 10 PM", with an example of the Operator's
own that reached 24K views. `VIDEO_SHARE_ENABLED` (on locally) adds
`video_share_job`: one X Top search per turn from the Account's
`video_share_queries`, a like floor read on the exact page (500), the existing
sampled-frame review with two added answers (`take`, `brand_fit` under the
video taste, so Trump and Elon are never mocked), then `post_video_share`
opens the player's own "Post Video" menu, checks that the composer holds
exactly that media beside `postVideoRemove`, pastes the take and requires an
own-status receipt. `video_shares.json` keeps one permanent claim per status
and per media. Windows (`VIDEO_SHARE_WINDOWS`): 08:00-09:00 five, 12:00-13:00
three, 17:00-18:00 six, 21:45-22:30 two; ten minutes between shares and from
our own video posts; sixteen a day at most. A window is an opportunity, never a
quota: "at least 4 to 6" is the aim, not a promise. This is the second profile
publication allowed beside restricted Replies, and it is separate from our own
uploads, which still come from outside X. Verified live up to the paste step,
without submitting; no share has been posted yet.

2026-11-25, thank every commenter; answer about three watched posts in ten — The
Operator, with notes from a coach: "always reply 1 time when people reply on our
posts ... Thanks and ... the emoticon ... do it naturally like dont spam", "first
30 minutes of a post, reply to every comment"; for Elon "Dont auto retweet like
and comment all his posts. Do it maybe for 30% ... the one that are relevant to
us ... within 2 minutes ... Ideally add a GIF", "Always like and retweet the ones
you respond to. the other 70%, retweet and like 50% of them", "be nice and sharp
... you are a fan". The bot stays paused; this loads on the next requested start.

- `thank_commenters = true` (Account): `commenter_thanks_job` reads the mentions
  tab and sends one short Reply under each comment that sits directly under one
  of our posts. This is the one conversation turn `standalone_replies_only` now
  allows; debate, replyback and babysitter stay off. The browser refuses a
  comment whose parent is not ours, a thread where we already appear twice (a
  reply to our answer) and a thread we already answered. `judge_comment` and
  `judge_thanks` own the rules: opt-in, Blocked account, own post, opt-out, one
  per comment for ever (Replied store), one per author per day, daily ceiling,
  spacing, at most 12 words and 80 characters, no link, mention or hashtag,
  never the same line as one of the last three. `thank_commenter` ships only
  with an own-status receipt. A full pass runs every three minutes, every minute
  for thirty minutes after one of our video posts (`THANKS_HOT_MINUTES`), then
  up to ten per pass. `thanks_style` carries the Operator's own recent answers.
- Watched author: `watched_action_share = 0.5`. A post the selector approved or
  that we answered is always liked and reposted; of the other posts a stable
  draw on the status ID takes half, once the Reply window has closed. The
  selector prompt asks for about three posts in ten, the relevant ones, with no
  quota; `watched_reply_style` holds the tone (his own short register, a fan,
  nice and sharp). The Reply window is `PRIORITY_WATCH_REPLY_WINDOW_SECONDS`
  (default 60, 120 locally): a goal, late work is still discarded.
- GIF: the selector may return a two or three word `gif` search;
  `reply_to_tweet(gif_query=...)` picks the first result of X's own GIF search
  in the composer. Best effort: the Reply ships without one when the picker
  fails. Verified live on an empty draft; no GIF has been sent yet.

2026-11-25, hourly videos from outside X, no mark but ours — After a pause at
09:16 Toronto (the bot stays stopped until an explicit start), the Operator sets
the video rules: "1 post every 1 hour", the best candidate, never a duplicate,
"cleanly remove all watermarks and only keep @thesimaximalist", "from outside X
and not be on X yet", 1080p 60 fps, an AI meme or AI song with Trump, Elon,
Jensen, Sam, Dario or Zuckerberg, Trump and Elon "in good posture", "the most
viral on another platform ... OR an underdog if our rating is high", ideally on
the current trend ("right now jensen is a solid trend").

- Seventeen windows, hourly from 07:00 to 23:00 Toronto (`scheduled_daily_cap = 17`).
  A window is still an opportunity: an empty reserve skips.
- `x_exclusive = true`: an X source is refused and the final gate accepts only
  `checked_no_match`. This ends the 2026-11-04 allowance for X sources and for
  copies under 50,000 views. `[platforms.x]` is disabled. The check is a bounded
  X search, not proof of global absence.
- `clean_watermarks_only = true`: the source inspector locates logos, icons and
  credits (`foreign_marks`, small boxes only) and the render removes them with
  the OCR-measured ones; the output inspector must report
  `foreign_watermark_visible = false`, and another account's handle that OCR
  still reads in the output overrides it. Subtitles and scene text stay. This
  narrows the 2026-11-01 "overlays may remain" allowance for marks.
- Underdog: an Instagram reel below the audience floors but with 5,000 plays or
  200 likes reaches inspection, then needs 75/100 on the inspector's own
  judgments (`underdog_min_editorial`), in source and output. Posted clips
  scored 64 to 79.
- `trend_cast = ["jensen"]`: every other Instagram search turn reads a trend
  query, and among comparable ready clips the trend cast is chosen first. The
  list is the Operator's; nothing measures the trend.
- 1080p60, cast, portrayal and permanent dedup were already in force.

The morning's three skipped slots had a cause: the X duplicate check failed on
every turn at one search result with no playable video ("native video duration
unavailable"), so approved clips never became ready. After three reads such a
post is recorded in `novelty.unreadable_posts` and the check moves on; any other
read failure still fails it.

2026-11-24, twenty windows, creator credits removed, the real capture cause —
The Operator asks "lets do 20 posts a day", "GO push hard today", and "please
remove watermark why do we see evolving ai ... fix it for future". Twenty video
windows now run every fifty minutes from 07:00 to 22:50 Toronto
(`scheduled_daily_cap = 20`, bound raised to 24); each stays an opportunity, an
empty reserve still skips and no gate is lowered. Inspection gets 600 Codex
calls and 30M input tokens a day. `remove_source_logos` also removes a
persistent creator handle or name anywhere in the frame (text starting with "@",
or matching the creator), never a title or subtitle. The capture failure was a
redirect race: the first poll answered on `/reel/ID`, the read then asked only
that address, and Instagram had moved the tab to `/reels/ID`. Every poll now
tries all three addresses. This supersedes the five-window schedule above.
With captures flowing the inspector became the limiter: a 258K-like reel was
refused for a 5.5/10 opening against the floor of 6. `min_hook_score = 5`; the
audience floor and every other gate are unchanged.

2026-11-24, Instagram captures died beside Replies — After two posts the reserve
was empty: every Instagram capture since 01:03 (twelve reels, one at 994K plays)
ended "source player unavailable: ValueError". The reel tab was gone on every
poll ("Requested source tab is not open"), the empty answer reached `canonical('')`
and raised. Capture now opens the page again when the tab is missing for four
polls (twice at most), ignores a not-yet-JSON answer, and names the failure
"source page did not stay open". What closes the tab beside Replies is not yet
identified. The failed reels were queued again.

2026-11-24, 1080p 60 fps and no source corner logo — After the reopened 07:00
post the Operator says "you left the watermark top right", "i wanted 1080p 60 fps
upscale" and "always do the upscale". `upscale = true` renders a 1080-pixel short
side (Lanczos) at a constant 60 fps; repeated frames, no invented
motion, and technical QC expects 60. `remove_source_logos = true` removes small
OCR-measured text that stays in one corner on at least 60% of the cut's sampled
frames (platform logo, creator credit) with ffmpeg `delogo`; subtitles and centred
text are never touched, and a logo with no readable text is not detected. The
output inspector is told both edits are approved. This narrows the 2026-11-01
"overlays may remain" allowance for corner logos only. The Operator also says
"you are the one running the bot do it": while he is away the agent restarts
through `bin/run.sh` when a merged fix needs loading. Asked for "the most trendy
video" and "thousands of views": ranking already prefers the most-played leads;
views are not something the bot can promise.
The first upscaled render was held ("output overlay quality uncertain"): the
retained-overlay pixel proof compared a 960-wide output sample with a 720-wide
source sample and found no frame of equal size. Both are now compared on the
output's raster when proportions agree; the sharpen filter was dropped so the
upscale stays verifiable against the source.

2026-11-24, short captions died at the Post click — Reopening the missed 07:00
slot on the Operator's "lets do the 7 AM slot right now" showed the third and
decisive cause: the upload was ready, then `authorize_submit` refused the caption
("English-only account: detected unknown"). A name and three words have no
detectable language, so no short caption could ever ship; the midnight post used
the long form. The video publisher now passes `short_title` for a short-caption
Account: an unknown result of at most 45 characters passes for that caller only;
detected French, French cues, Replies and ordinary Originals are unchanged. The
refusal reason is logged instead of a bare `ValueError`.

2026-11-24, empty 07:00 slot: two starvation causes — The Operator reports no
video this morning. The 07:00 slot closed with no eligible clip. (1) Every
publisher read turn first reopened Home to prove the Safari account, waiting
eight seconds; beside Replies that failed 61 times overnight and each failure
stopped preparation. The proof now waits up to 25 seconds and a read turn reuses
it for fifteen minutes; a publication still needs one under sixty seconds and
another account still refuses. (2) `request_budget` is one daily total across
platforms: X video segments spent all 460 by 07:00 and every Instagram capture
deferred ("source request budget exhausted", 212 times). The Account sets 3,000;
the 4 GB download ceiling is unchanged. No publication gate changes.

2026-11-24, five daily videos, short captions, Replies continue — After the first
confirmed Instagram repost (https://x.com/i/status/2125098583040881083, 00:26
Toronto, posted on the Operator's explicit "can you post one?"), the Operator
sets one video at 07:00, 09:00, 12:00, 17:00 and 21:00 Toronto every day
(`windows`, `scheduled_daily_cap = 5`), asks for short captions "like Jensen VS
Dario + one heart emoji" (`short_caption`: a cast name, a few words, exactly one
closing heart, at most 45 characters, still verified against the output), and
says Replies continue as before and that he restarts the bot himself. `POST_ONLY`
is now a setting any launcher honors and is off again. The legacy launchd
watchdog (`bot_watchdog.sh`) starts the bot through `bin/run.sh`: a bare
`main.py` had started the full bot without the video requirements. Instagram
search uses plain "<name> ai" queries, creators of reels with five times the
like floor join the grid rotation, and inspection gets 240 Codex calls a day.
The Operator also sets sleep from 23:30 to 04:30 Toronto: `BEDTIME = time(23, 30)`.
A skipped night now starts at 23:30 of its evening date. Requested and still
open: more Replies.

2026-11-23, Instagram bangers again: four breaks repaired while paused — The
Operator, leaving for two weeks, asks to fix video posting and find Instagram
bangers, then widens the cast and leaves the bar to the agent: Trump, Elon,
Jensen, Dario, Sam or Zuckerberg; Trump and Elon must look good; prefer funny,
short and songs. The audit found no video since November 18 and four causes.

1. The curated/broad Reply modes return from `build_scheduler` before the video
   job and `video.config.live()` refused them; `VIDEO_LIVE` was also 0. New
   `VIDEO_WITH_REPLIES=1` runs the one video publisher beside restricted Replies.
   The reserved `VIDEO` write is the only added publication; manual review mode
   still writes nothing. News, editorial, quotes and startup requests stay off.
2. Codex web search cannot see Instagram: two leads in three weeks. With
   `safari_browse`, the publisher's source turn reads Instagram's own pages in
   the signed-in Safari session: a creator's Reels grid with its displayed play
   counter, and keyword search. One page per fifteen minutes, six leads per
   read, most-played first. Creators whose inspected reel showed a target in a
   synthetic parody join the grid rotation. Leads only; every gate still decides.
3. Instagram redirects `/reel/ID` to its `/reels/ID` player: no JSON-LD, no
   `og:video`, blob-backed players, and the tab-bound read found no tab. Capture
   now follows the redirect and reads this exact reel's page-embedded data,
   bound by shortcode: media URL, upload time, creator, caption, likes.
4. A blank `codex_model` reused `REPLY_MODEL`, a Grok model since November 21;
   Codex refused every inspection and search. The Account pins `gpt-6.1-sol`,
   and a blank value now fails with its cause when Replies use another provider.

The ultra floors had never passed one clip: 45 inspected, best 8/10, and a
1.7M-play reel scored 5.5. `ultra_bangers_only=false`. An Instagram audience now
proves the banger (50,000 displayed plays or 2,000 likes, checked on the exact
page before any download), and the inspector's floors are Account settings:
hook/performance/quality 5.5/10, fit 7/10, 14/12/9 source floors, opening 6/10,
62/100 total, inspector confidence 0.85 (it reported 0.89 on a clean 1.7M-play
reel). `editorial_taste` carries the cast and portrayal rule into the
inspector as trusted policy: a clip that mocks or weakens Trump or Elon is
`brand_fit=false`. `zuck` joins the qualifying cast. Cast attribution, synthetic
performance, audio, safety, output QC, watermark, novelty,
permanent dedup, spacing and receipts are unchanged. No posting quota.

"Cleanly": the render stamped the handle across the source's bottom subtitles
on every frame. Measured source OCR inside the cut now picks the quieter band,
top or bottom, and output QC confirmed the handle and retained subtitles apart.

Validated live without publishing: 12 leads in two reads, four reels captured
and downloaded, inspection, render and output QC completing in about two
minutes a clip. The first rendered reel was held on a weak opening shot: the
output gate still refuses a clip, an audience alone never publishes one. A cut clip with retained subtitles also crashed output review (`KeyError:
'source_at'`: the exact same-sample match reports `source_sample_at`); fixed.

Asked whether to start, the Operator chooses "Videos only, no replies". This
lifts the 21:50 pause for a post-only start: `POST_ONLY=1` makes `bin/run.sh`
pass `--post-only`, which keeps `video_health_job` and its workers and schedules
no Reply, watched like or repost job. Started through `bin/watchdog.sh` with a
120-minute stall window so a crash does not cost the two weeks. A plain
`./bin/run.sh` later brings the Replies back. Later stop requests override this.

The Operator then reports "so many bangers" on Instagram and no post. The first
hour showed the inspector as the bottleneck (37 Codex calls spent the 2M-token
day) and half the search leads below the audience floor. The Account now reads
one Instagram page per five minutes, takes twelve leads per read, allows 240
Codex calls and 8M input tokens a day with 200 reserved for inspection, and cuts
public web search to one call an hour. A clip the agent had set aside as a
suspected repeat was compared with the earlier post, found different and restored.

2026-11-23, Operator pause at 21:50 Toronto — Stop and keep the bot stopped
until a new explicit start/restart request. This overrides the latest resume
authorization. The worker stopped at 21:50:35; no main process or active
supervisor remained, and `.bot_disabled` is armed. Preserve configuration,
publication history, uncertain submissions, opt-outs and manual decisions.
The day closed at 529 confirmed Replies after the pic-alias, affiliation-badge
and reply-restricted-skip refinements; all merged code loads on the next
explicitly requested start.

2026-11-21, resume at 23:45 after the link-card alias fix — The Operator says
"ok restart go", lifting the 23:43 pause. The normal launcher started the
worker at 23:45:04 Toronto on the merged code, including the trailing
link-card URL extension to the composer copy check. X confirmed a Reply with
an own receipt at 23:50:20:
https://x.com/thesimaximalist/status/2124364826616979478 — no composer
refusals since the resume. All publication, uncertain-send, opt-out and
manual records were preserved. Normal midnight sleep applies; the worker
wakes at 04:30. Later stop/pause requests override this authorization.

2026-11-21, Operator pause at 23:43 Toronto — Stop and keep the bot stopped
until a new explicit start/restart request. This overrides tonight's resume
authorization. The worker stopped at 23:43:04; no main process or active
supervisor remained, and `.bot_disabled` is armed. Preserve configuration,
publication history, uncertain submissions, opt-outs and manual decisions.
After the restart, the evening ran 28 confirmed Replies in 90 minutes with
two residual composer refusal classes; the validated trailing link-card
alias extension to the composer copy check is merged but loads only on the
next explicitly requested start.

2026-11-21, warmer emotional voice and repaired composing throughput — The
Operator reports only 50–100 actual Replies against the 1,400 target, asks for
at least 500 today, more emotion — hearts, blue hearts, a thumbs up — warmer
feminine delivery, Grok responses, and accepts a plain "Love it!!" on an
artistic slopcore post. They request fix, PR, merge, push, release, restart
and monitoring. This explicit restart request lifts the 21:35 pause.

The day's audit found 250 shipped Replies from 655 attempts: 280 drafts died at
the final composing check ("Invitation or exact source changed"), each wasting
its full browser cycle. A live empty-composer reproduction showed X's compact
parent copy appends alias display text the standalone source never renders in
its own text: the quoted-status permalink, usually ellipsis-truncated
("x.com/GiorgioPatrini…"), and a glued pic.x.com token for native media; short
copies expose no Show more control. Exact equality could therefore never pass
on a quote or short media parent, and the two reads also render whitespace
around inline mentions differently. The composing comparison now strips only
those trailing alias tokens and compares the copy with whitespace removed —
every letter, digit and symbol in order; the standalone source behind the
dialog is still strictly exact-matched in the same read, Show more expansion
remains, a bare prefix still refuses, and every composer DOM refusal now logs
a labeled branch reason with the first divergence. Grok `grok-4.7-build-fast` at low effort
remains the Reply route.

Both Voice files put feeling first: hearts ❤️/💙/🩷 lead for affection (blue
suits tech and SI art), one 👍 can carry simple agreement or support, and
"Love it!!" with or without a heart can be a whole reply to artist slopcore.
The heart gap drops to two heartless sends between hearts; hearts extend from
artist reactions to warm share replies; a single thumbs up is allowed on
ordinary lanes and never for watched authors. The artist short-reaction closed
set adds "so good", "so cute", "love it so much" and "love everything about
this". Unbound generic hype ("Beautiful", "Amazing") still refuses; no emoji
quota, rotation or filler follows. All caps, pacing, parent likes, opt-outs,
permanent histories and repetition checks remain unchanged.

Validation also repaired a latent test-clock inconsistency: the suite froze the
Toronto clock at noon while fixtures and buffer TTLs used the real clock, so
afternoon runs falsely refused watch fixtures. Tests keep the real clock in
daytime and clamp only the 23:00–05:00 edge; `x_urls.age` defaults to the
shared Toronto clock, and numpy joins requirements for video fingerprints.
4,003 tests and the dry-run schedule check passed. Restart through the normal
launcher, verify an actual own-X Reply receipt, and monitor the composing
refusal rate.

2026-11-21, Operator pause at 21:35 Toronto — Stop and keep the bot stopped
until a new explicit start/restart request. This overrides the latest resume
authorization. The worker stopped at 21:35:55; no main process or active supervisor
remained, and `.bot_disabled` is armed. Preserve configuration, publication history,
uncertain submissions, opt-outs and manual decisions unchanged.

2026-11-21, like before every Reply and resume priority watched actions — The Operator
requests a confirmed parent like before every Reply, automatic likes/native reposts
for new Elon originals, faster relevant Replies and short natural wording, then
says “go push harder.” This lifts the 08:14 pause and authorizes restart after
validation. Keep the restored broad discovery routine and Grok at low effort.

`REPLY_REQUIRE_PARENT_LIKE=true` requires an observed liked state on the exact
admitted parent before opening its Reply composer. A short-lived source-bound
Reply context authorizes this ordinary like; generic ordinary likes remain off.
Failed, unreadable or uncertain likes refuse the Reply. Do not trust history alone
as proof that the live parent is liked. Preserve exact source and own-receipt checks.

Elon remains the sole watched author. `auto_engage_all_topics=true` and independent
watched reposts authorize likes/native reposts for verified new originals across
topics, inside the existing first-enable boundary and maximum source age. These
actions no longer wait for AI selection or the former three/day, six-hour limits.
The configured watched Reply and repost ceilings are 1,400 each; watched Replies
also consume the overall 1,400/day Reply ceiling. Reposts retain at least sixty
seconds between confirmed or uncertain attempts. Watched Replies use the ordinary
eight-second minimum plus jitter and still require the existing AI/SI, Grok,
slopcore, Starlink or SpaceX topic filter, excluding politics and unclear/weird
content. Only Replies retain the sixty-second source deadline. Prioritize them
as soon as discovered; browser/model availability prevents a delivery guarantee.

Prefer a few words: agreement, a natural reaction, an understandable joke or a
useful concrete question. “Facts” and “Agree” may fit supported statements; they
are optional, source-bound and subject to recent-text repetition checks. Ordinary
Replies have one sentence, at most 24 words/140 characters; watched Replies usually
use one or two words, at most twelve words/ninety characters. Refuse overlong drafts
rather than cutting them. No obscure added references, unsolicited lectures,
invented experience, unseen-media claims or filler to meet the daily target.

Keep five observed parent likes, ordinary one-author/day, permanent original
claims, uncertain-send budgets, opt-outs and normal 04:30–00:00 Toronto hours.
Other follows, likes, reposts, quotes and profile publications remain disabled.
Preserve all runtime/publication/manual records. Validate, use the normal launcher,
and verify an actual own-X Reply receipt plus the preceding confirmed parent like.
Later stop/pause requests override this resume authorization.

Validation: 3,994 tests passed, plus the generated configuration and nonpublishing
schedule checks. Publication/history files matched their pre-change hashes before
launch. The normal launcher started PID 18291 at 08:41:57 Toronto. Independent
watched likes and native reposts were confirmed after launch. The parent at
https://x.com/bobolv235824/status/2124053546828259606 was confirmed liked at
08:50:37, before the Reply click at 08:50:38. X confirmed the short Grok question
“When does the face start drifting?” at 08:50:48, with a permanent confirmed
submission and own receipt: https://x.com/thesimaximalist/status/2124138453269164129.
The worker remains running; all earlier publication/uncertainty records were preserved.

2026-11-21, Operator pause at 08:14 Toronto — Stop and keep the bot stopped
until a new explicit start/restart request. This overrides the latest broad-routine
resume authorization. The worker stopped at 08:14:04; no main process or active
supervisor remained, and `.bot_disabled` is armed. Preserve all configuration,
publication history, uncertain submissions, opt-outs and manual decisions.

2026-11-21, restore the earlier broad Reply routine and resume — The Operator
asks to go ahead, push toward 1,400/day and do what the bot was doing before,
keeping the new style of short reactions or useful questions. This replaces the
For You first experiment and lifts the 07:15 pause. `REPLY_FOR_YOU_FIRST=false`.
Restore the two-minute direct search cycle: sixteen reads split across four major
author Latest queries, two creator Latest queries, six Top and four general Latest,
with the earlier eighty-Reply cycle budget. Both Home feeds return to the combined
eight-minute cycle, up to 160 posts/twenty scrolls and eighty generation attempts
per feed. The one-confirmed-Reply-per-feed-turn restriction is off. Unused sources
keep the earlier thirty-minute local TTL; the ordinary maximum source age returns
to twenty-four hours. General Latest searches retain their existing one-hour limit.

Keep Grok `grok-4.7-build-fast` at low effort and the latest plain conversational
Voice: short agreement, reaction, understandable joke or a relevant concrete
question chosen from the full post. No forced questions, recycled filler or return
to elaborate punchlines and unsolicited lessons. The 1,400/day target and ceiling
include uncertain sends; actual output still depends on eligible sources. Keep
eight seconds plus 0–4 jitter, existing hours, five observed parent likes, one
ordinary author/day, permanent original claims, opt-outs and source/receipt checks.
Preserve all runtime/publication/manual records and the selected watched limits.
Validate, start through the normal launcher and confirm an actual own-X Reply.
Later pause/stop requests override this resume authorization.

Validated with 700 relevant tests and the configuration/schedule preview. The normal
launcher started the restored worker at 07:56:35 Toronto, and X confirmed a new Grok
Reply at 08:04:17: https://x.com/thesimaximalist/status/2124126748224913554.
The worker remains running; earlier confirmed and uncertain records were preserved.

2026-11-21, For You first and first-hour Replies while paused — The Operator
wants most discovery on For You, focused on hot, new posts instead of old ones.
`REPLY_FOR_YOU_FIRST=true` keeps broad discovery but makes a verified For You scan
the primary turn, every minute after restart: at most twenty posts/two scrolls
and three generation attempts, with one confirmed Reply before refreshing the feed.
The Operator clarifies that fast responses are the goal. End the scan after the
first viewport containing an eligible first-half-hour parent, then read its full
source and draft/send before preparing another source. Give that source read Reply
priority over background discovery; active browser transactions still finish and
watched deadlines retain priority. Following is read only every twentieth completed
For You cycle, after its Reply turn. Secondary search waits thirty minutes after startup, then runs two
rotating Latest queries every thirty minutes, with at most three confirmed Replies.
No routine Top or major-author search sweep precedes For You. Watched jobs and the
separate ten-minute opt-out read retain their existing scopes and checks.

Ordinary sources must be at most sixty minutes old; a tighter configured limit
wins. Verify age from the exact status ID before generation and immediately before
submission, including prepared/alternate paths. Unknown/future dates refuse; a
queued draft crossing the deadline is not sent. Prefer sources in their first
thirty minutes, then observed likes per minute, views per minute for ties and age;
these snapshot ratios are ranking signals, not measured growth. Author diversity
stays within freshness tiers. Old total views or designated authors cannot displace
fresh work in the buffers. Keep at least five observed parent likes, ten-minute
source-buffer TTL without extension on rediscovery, exact-source/media/receipt and
all opt-out, language, repetition, author/day and permanent-original checks.

Keep Grok, the plain short-reaction Voice, existing hours and the 1,400/day advisory
target/ceiling unchanged. Preserve publication, uncertain-send and manual records.
The 07:15 pause remains binding: implement and validate only; do not restart or
publish without a new explicit start/restart request.

Validated with 3,905 passing tests, the generated configuration reference and a
nonpublishing schedule preview. A read-only For You sample found sixteen posts,
three under an hour, and no fresh AI originals meeting the observed-like floor;
it generated and published nothing. Bot remains stopped with `.bot_disabled` armed.

2026-11-21, Operator pause at 07:15 Toronto — Stop the bot and keep it stopped
until a new explicit start/restart request. This supersedes earlier restart
instructions. The worker stopped at 07:15:05; no main process or active supervisor
remained, and `.bot_disabled` is armed. Preserve configuration, publication history,
uncertain submissions, opt-outs and manual decisions unchanged.

2026-11-21, resume the Grok reply worker — The Operator explicitly requests
restart and automatic replying after reviewing the plain-response Grok previews.
This lifts the prior pause. Start through the normal launcher with Grok
`grok-4.7-build-fast`, low effort, the revised conversational Voice and the existing
1,400/day advisory target/ceiling. Preserve all publication, uncertainty, opt-out
and manual-review records. Confirm the running process and an actual own-X Reply
receipt. Later stop/pause requests still override this authorization.

The restart exposed a composer rendering mismatch: X replaces native media links
with `pic.x.com` text in the compact parent. Verify the unchanged exact standalone
source, then permit the sole author-verified copy's Show more control to expand.
Require the complete original text again afterward; never accept a prefix or infer
link equivalence. An empty-composer live reproduction confirmed exact text restored
without submitting. Preserve all publication and uncertain-send history.

Validation: 620 browser, Reply-target, curated-source and budget tests passed.
The worker confirmed a Grok Reply at 06:49:01 Toronto:
https://x.com/thesimaximalist/status/2124107805263094125 — "Coding is the one I'd grab."
The normal launcher resumed at 06:49:54 after diagnosis, with history intact.
Compact link cards with no expansion or exact destination proof still refuse;
no URL stripping or guessed link equivalence is permitted.

2026-11-21, plain reactions and understandable humor while paused — The Operator
rejects an elaborate latency quip, an unsolicited editor-workflow counterargument
and a P-vs-NP joke. They want ordinary conversation: simple agreement about slowness,
a playful tool preference and an obvious joke that follows the author's irony.
They explicitly approve the concrete question asking which problems separated two
models. Keep that curiosity; do not ban questions or make them mandatory endings.

Both Voice files, the broad/direct/structured drafting prompts, shared delivery and
Relation now prefer a few words or one short line. Read the whole post, including
an ironic ending; a source-lane label is only a hint. A rhetorical question inside
a rant is not a help request. A real help request can still receive the explanation
it needs. Remove the universal demand for a novel insight, detail recap or technical
counterexample. No polished punchlines, obscure new references, elaborate metaphors,
unsolicited debates, fake typos, fabricated experience or concealed bot identity.
Plain agreement, fitting warmth, subjective taste and concrete questions are valid.

The scoped ordinary short-reaction exception permits fresh source-bound artist
warmth and resource thanks. Compact playful comparisons require a short named
subject present in the original source and closed English wording/emoticon form;
no global brand-as-English or generic-hype exemption. English/SI, exact-source,
opt-out, recent confirmed/pending repetition, heart spacing and publication checks
remain. Keep the 1,400/day advisory target/ceiling and existing schedule unchanged.

Validate with local tests and isolated model drafts of the supplied examples plus
new cases. Do not publish previews or change publication history. The Operator's
pause remains in force: keep the bot stopped and do not restart until asked.

The Operator subsequently connects Grok and asks to retry. Reply drafting is
configured with `REPLY_LLM_PROVIDER=grok`, both Reply models
`grok-4.7-build-fast`, and `GROK_REASONING_EFFORT=low`. The signed-in Grok CLI
runs one draft-only turn in an isolated temporary directory, with tools, web,
subagents, memory, workflows and coding skill bundles disabled. Accept only a
completed result for the requested model; errors, partial output and unexpected
tool/context activity yield no draft. Fallback remains disabled. Ordinary text
and watched structured selection both use this route. The pause is still binding.

Short-English validation treats a closed set of ASCII faces as punctuation, not
language evidence; natural slow-day/slow-answer phrases retain known-word, length
and French/mixed checks. Faces also cannot hide generic text or pad minimum length.
A per-call drafting deadline now handles routes with no separate timeout value;
the smaller limit wins when both exist. No publication or history changes.

2026-11-21, restore the live automatic worker and 1,400/day — The Operator
reports no Replies, sets a 1,400/day target and explicitly authorizes the agent
to restart the bot. The last launch (November 20 at 23:34:50 Toronto) still loaded
manual ordinary mode, 200/day and 180-second spacing; later disk edits never
reached that process. It was no longer running when diagnosed.

Set the Account and local daily target/ceiling to 1,400 including uncertain sends;
keep ordinary manual/review flags off and the automatic direct/search and Home-feed
jobs on. Keep eight seconds plus 0–4 seconds jitter, exact-source/receipt checks,
five parent likes, one ordinary author/day, permanent original history, opt-outs,
selected watched limits and existing hours. No filler or guaranteed daily delivery.
Preserve all state, pending claims and manual decisions. Validate, restart through
the normal launcher, confirm the loaded automatic schedule and verify an actual
own-X Reply receipt. This explicit restart instruction supersedes manual-only
restart directions below. The startup pacing message must describe loaded settings.

The first restarted feed worker produced a real Reply receipt at 05:01:38 Toronto:
https://x.com/thesimaximalist/status/2124080782264226190. Another draft exposed a
short-English false refusal: "Family tech support now includes verifying reality."
Add only family/tech/includes/verifying/reality to the existing closed short-Reply
vocabulary and verifying as an English cue. Keep its 80-character bound, complete
vocabulary check, Reply-only scope, French/mixed refusals and all content/repetition
rules. Validate that exact final-admission case, then restart with the fix while
preserving the newly confirmed publication and all earlier records.

2026-11-20, restore automatic Replies at 1,500/day — The Operator explicitly
requests going back to 1,500 replies/day and actual automatic replies before a
manual restart. `REPLY_MANUAL_ORDINARY=0`, `REPLY_MANUAL_DISCOVERY=0` and
`REPLY_REVIEW_ONLY=0` restore the broad direct/search and combined Home-feed
Reply workers. `MAX_REPLIES_PER_DAY=1500` and both advisory targets are 1500.
The broad-mode hard ceiling is 1,500, counting confirmed and uncertain sends;
the normal minimum is eight seconds plus 0–4 seconds jitter. Targets are advisory,
not a filler quota or a guarantee of delivery. Smaller configured limits still hold.

Clear the temporary workload boost start date: there is no later return to 200,
80 or 70. The optional manual inbox, its decisions and thread drafts remain
separate and never become an automatic outbox. One Reply per exact standalone
original permanently, one ordinary author/day, five observed parent likes,
full source/recipient/media checks, opt-outs, English/SI, content and repetition
rules, uncertainty claims and exact own-post receipts remain. Keep the latest
specific ordinary writing style and the selected watched one- or two-word path;
watched Reply/repost ceilings remain three each/day, six hours apart.

Tonight's fixed `SKIP_SLEEP_NIGHT_DATE=2026-11-20` exception remains: skip the
November 21 00:00–04:30 Toronto sleep window, then normal midnight sleep resumes
November 22. No permanent all-day mode or history reset. Validate and report ready
for the Operator's manual restart; do not start or restart the bot here.

2026-11-20, temporary 200-message plan and one awake night — For four Toronto
calendar days, November 20–23 inclusive, the advisory plan and planning ceiling
are 200 messages/day. The plan returns to a 70 target, 60–80 range and 80 ceiling
on November 24 without a restart. The fixed start date never advances on restart.
Ordinary replies remain manual-review drafts; selected watched replies remain the
automatic exception. Reserve the watched allowance inside the day's draft planning
capacity: at most 197 ordinary drafts plus the three watched Reply slots during
the boost (77 plus three afterward), reduced by other known automatic submissions.
Four draft sessions allow up to 50 attempts/selections during the boost, then 20.
Quality, genuine follow-up context and uncertainty/history checks still apply;
200 is a target, not a guarantee or permission to publish filler.

`SKIP_SLEEP_NIGHT_DATE=2026-11-20` skips only the November 21 00:00–04:30 Toronto
sleep window. Normal midnight sleep resumes November 22 at 00:00, with the usual
04:30 wake. Stop requests still win; no permanent all-day or 72-hour override.
The Operator will restart manually after validation. Do not start the bot.

2026-11-20, fast selective watched reactions and a 70-reply routine — The combined
setup keeps Elon as the automatic exception and prepares ordinary replies for the
Operator's review and manual posting. `REPLY_MANUAL_ORDINARY=1` blocks ordinary
Reply submissions at shared admission, including alternate jobs;
`REPLY_MANUAL_DISCOVERY=1` schedules read-only discovery and drafts at 05:00, 10:00,
15:00 and 20:00 Toronto. `REPLY_REVIEW_ONLY=0` allows the scoped watched actions.
The Operator retains manual restart. Prepare and validate; do not start the bot.

Elon's selected standalone originals may cover AI/SI, slopcore, Grok/Grokbot,
Starlink and SpaceX. Account-owned watched topics do not inherit ordinary gaming
or film discovery. Politics, inflammatory/sexual material, unsupported bizarre
claims and unclear context refuse. Likes, native reposts and Replies share one
exact-source selection. A single shared model call produces the review and a
one- or two-word Reply, at most 40 characters. FACTS is eligible only when supported
and fresh, never a stock response to every post. Its short English exception is
source-bound; other authors cannot borrow it. All repetition checks remain.

Watch discovery polls every five seconds; selection, action and Reply workers
check every two seconds. The first-minute deadline is measured from the original
status timestamp, not discovery. Late work is discarded, including at submission.
A scoped model deadline and priority browser turns reduce delay; active transactions,
model latency, unavailable context and X can still prevent a timely response.
The existing three Replies/day and three reposts/day, six-hour spacing per action,
five observed parent likes, overall uncertainty accounting and active hours remain.
No promise of views, growth or delivery within a minute is made.

Ordinary work aims for 70 external replies, with an advisory 60–80 range and no
minimum. At most 80 selected manual drafts/day including dismissals, at most 20
attempts/selections per scheduled session; the automatic Reply ceiling is also 80.
The illustrative 45 new/25 follow-up split is not a quota. Prefer people outside the
recent circle and include both smaller and prominent authors. Topics now include
AI/SI video, music and filmmaking; builders/technology; gaming, film and internet
comedy. Ordinary drafts usually use one to three concise sentences, up to 278
characters. Each needs a specific supported contribution, not interchangeable praise,
caption recaps, unsolicited homework or a compulsory question. Actual media evidence
or relevant linked-source text is required when the point depends on it; otherwise
skip. No invented experience, technical fact, relationship or human identity.

Manual follow-up drafts require a genuine incoming response, the external thread
root and our prior reply with supplied context. Those snapshots and manually reported
own-post URLs stay explicitly unverified; they never authorize automatic thread
replies, publication ledger rows or confirmed receipts. Four sessions organize work;
they do not claim ranking or restriction benefits. A fourteen-day report separates
optional operator-reported responses, interactions, views, attributable visits/follows
and time from captured confirmed receipts. Keep all publication, uncertain-send,
opt-out and manual decision history intact. Other X writes remain disabled.

2026-11-20, intent before technical expertise — After an unsolicited evaluation
lesson on a shared learning roadmap, the Operator asks for natural appreciation
instead. In broad mode, actual questions/help requests may get one concise technical
answer. Shared roadmaps, tutorials, resources and announcements get a brief reaction
or thanks: usually 2–6 words, at most eight words/60 characters. No unsolicited
correction, tip, warning or manufactured technical takeaway. Artist reactions keep
their existing short warmth and occasional heart. Source intent is recomputed from
the full post; a caller's technical label cannot override it. A scoped short-reaction
exception permits ordinary thanks without globally allowing generic technical
answers. Common unsolicited imperative advice refuses on shares, and recent-text
repetition checks still apply. All caps, likes, histories, receipts and restart
controls remain unchanged. The posted roadmap Reply stays in permanent history;
no automatic deletion, correction or second contact is authorized by this change.


2026-11-20, restored broad discovery with short Replies — The Operator replaces the
silent curated worker with the earlier rotating major-author, artist, Top/Latest
and combined Home/Following discovery. `REPLY_BROAD_DISCOVERY=1` retains curated
write restrictions and the exact-source/own-receipt transport. The advisory target
is 250–300; the hard ceiling is 300 Replies per Toronto day including uncertain
submissions. Never generate filler to reach it. At least five observed exact-parent
likes are required before generation and again at submission; zero, lower and
unreadable counts refuse. Prefer configured larger accounts without a mandatory
5,000-follower profile lookup. One Reply per ordinary author/day and permanent
one-Reply-per-original history remain. Three-minute minimum plus 0–60 seconds jitter;
normal 04:30–00:00 Toronto hours remain.

Artist discovery includes slopcore and the existing creator pool, with up to 24-hour
creator originals. Replies are usually a few affectionate words or an occasional
single heart, at most 12 words/90 characters. Technical Replies make one sharp
point in one sentence, at most 24 words/140 characters. Simple appreciation does
not require an eight-point video review, but no unseen visual/audio details or
fabricated human experience are allowed. A source-bound closed set of brief artist
reactions may pass the minimum-length/language gate; technical posts cannot borrow
that exception. Hearts require five intervening Replies without hearts; existing
confirmed and uncertain-text repetition checks remain. No forced rotation.

The live silence exposed truncated search cards: every restricted pipeline reads
the full exact original before drafting and rechecks its niche, opt-outs, history,
likes and freshness. Prepared text cannot silently switch evidence. X also truncates
the parent in its Reply composer. Only that verified parent's Show more control
may be expanded, followed by a full exact source/recipient check; a matching prefix
alone never authorizes sending. Missing or changed sources still refuse.

Scoped watched-author likes, at most three selective AI reposts/day and three AI
Replies/day inside the total retain their existing six-hour spacing and claims.
Other writes remain off. A separate ten-minute mentions read honors objections even
when Reply capacity is exhausted. Keep runtime state and publication memory intact.
Implementation and validation prepare the next manual restart; do not start the bot.


2026-11-20, paused pivot to short slopcore artist Replies — The Operator requests
implementation and validation, then a readiness report for manual restart. Keep the
bot stopped and automatic restart disabled until an explicit start/restart request.
This supersedes request-only discovery, 250/day, the long specialist style and the
previous withdrawal of all Elon actions. Preserve all publication/uncertain history.

`REPLY_CURATED_MODE` selects strong AI artist videos and occasional sharp technical
AI/LLM/video-tool posts. A public question is optional. Start with at least 5,000
observed followers, bound to the exact author's profile and cached for at most six
hours, and twenty exact-parent likes. Unknown/expired counts refuse. Likes are
checked before generation and again at the final browser source. No manual VIP
label substitutes for follower evidence. Prefer stronger observed posts among
eligible sources. Claudia, Astra Blue, Tetsuo and Kaia Venta are taste/search
references; an ambiguous name never authorizes a guessed handle or identity.

Two artist search turns per technical turn, with a mentions/opt-out read every fifth
turn, run every three minutes. Public turns read Top and Latest with at most forty
results/eight scrolls per tab. Keep sources at most thirty minutes, bounded by 400,
without extending expiry on rediscovery; exact source age cannot exceed 24 hours.
At most six author preparations, two visual reviews, three Reply generations and
one confirmed Reply per cycle. Queue preference uses recent submitted lanes to
bring technical posts into the artist-led mix; no forced alternation or filler.

Artist reactions need an exact source/native-media-bound visual review: six to
sixteen timestamped samples across an artist video up to 300 seconds, within the existing
25-second browser sampling turn and shared model/read budgets. Require artist
contribution, AI context, style fit, safety and quality >=8/10; likes never supply
quality. Missing necessary audio or incomplete samples refuse. Use observed visual
moments only; no full-playback, unheard-audio, fabricated technique or personal claims.
Final composition checks the same media identity and unchanged exact source.

Replies are a few words or one sentence: at most 140 characters/24 words overall,
and 90 characters/12 words for artist reactions. Reject overlong drafts rather than
cutting a thought. Hearts are optional for reviewed artist reactions only, at most
one, with two intervening Replies without hearts. Confirmed writing memory and
uncertain submissions both constrain repetition. Keep the fictional warm voice,
without pretending to be human, fake typos, invented experience or closeness.

The hard ceiling is 100 Replies per Toronto day, including unresolved submissions;
there is no daily minimum. Keep ten minutes plus 0–4 seconds jitter. Ordinary authors
receive at most one/day; permanent one-Reply-per-standalone-original history remains.
Elon is the only configured watched author: independently like eligible new originals
across topics, but allow at most three AI-related Replies/day within the hundred,
six hours apart. Native reposts have a separate three/day ceiling and six-hour gap,
including uncertain claims, and require a source-bound selective AI relevance/value
review. The fast like dispatcher cannot blanket-repost. Exact-author exceptions
are enforced at the shared write gates; follows, other likes/reposts, quotes, news,
self-reposts and original/video publishing stay disabled. Hours remain 04:30–00:00
Toronto. Opt-outs, content/language/source checks, stop requests, exact own Reply
receipts and permanent/uncertain claims remain binding. No volume or growth promise.

2026-11-20, repair search starvation after the live restart — The bot ran from
06:21 without a publication: its shallow searches typically returned five to nine
sources and early model candidates were unrelated or promotional. One query was
polluted by LLM law-degree assignment ads. The Operator again reports no activity.
Public discovery now reads Latest and recent Top for each rotating request query,
at most forty results and eight overlapping scrolls per tab. Every fourth turn
remains the single twenty-result, one-scroll mentions/opt-out check. A coarse
`since:` date bounds Top discovery; exact source age still cannot exceed 24 hours.
Queries exclude quoted cards and the observed assignment/WhatsApp advertisements.

Keep admitted but unused sources in a separate instance of the existing disposable
candidate buffer, capped by its configured count and thirty-minute local TTL.
Rediscovery cannot extend expiry. The buffer stores sources, never drafts or Reply
claims, and reuses the shared pipeline and final source verification. Confirmed,
declined and definitively refused work leaves the queue. Three generations and one
confirmed Reply per cycle, the 250/day ceiling, one author/day and four-minute pacing
remain. Accept ordinary request forms such as "I need help", "How are people... ?"
and a standalone "Thoughts?" about a described creative work. Rhetorical promotion,
missing evidence, opt-outs and all other source/content/history checks still refuse.

The live model also declined an open model-evaluation discussion after its author
shared an approach. Clarify the drafting rule: a genuine public technical question
is eligible without the words "help me", and a partial view from the author does
not disqualify a distinct useful contribution. Practical questions about using or
learning SI tools may receive grounded guidance. Keep rejecting advertising headlines,
rhetorical promotion, recaps, filler, invented personal experience and missing evidence.
This clarifies generation; source admission, publishing caps and pacing do not loosen.

The first live generated reply then exposed a final-check bug: X changes the URL
to `/compose/post` when its Reply dialog opens. The pre-submit source read rejected
that expected transition. In the final composing-only check, permit `/compose/post`
or `/compose/tweet` only with one editor, one exact parent copy with the correct
URL-derived author, and the unchanged standalone source behind the dialog. Initial
reads/clicks still require the exact status route. Missing/changed sources, wrong
recipients, ambiguous composers and unrelated routes refuse. An empty-composer live
reproduction verifies the fix without submitting a diagnostic reply.

In this requested-Reply mode, a successful submit keystroke no longer confirms a
publication. Read the exact recent own-status receipt up to three times before
recording success. Missing/failed receipt reads leave the submission pending and
permanently claimed; they consume the budget and never trigger an automatic resend.
Reuse the verified URL for feedback bookkeeping and log it for the Operator.

Validate before applying the repair to the running bot through the normal restart
workflow, under the Operator's earlier explicit restart instruction. Verify an actual
own-X receipt, not only searches, tests or a local draft. Preserve publication and
uncertain-send history. No likes, reposts, follows or profile posts are enabled.

2026-11-20, repair public-request discovery — The live run searched only for the
Account's handle and returned nineteen nested replies, with no eligible requests.
That restriction missed the Operator's requested public technical questions. Enable
`REPLY_PUBLIC_REQUESTS=true`: fresh standalone posts may ask their public audience
or this Account for technical help or creative feedback. A mention is optional.
A topic, ordinary announcement, quoted request, tutorial answering its own headline,
rhetorical promotion or question addressed to another person is insufficient.
The exact outer source is checked again before sending; no-bot/no-contact requests
remain binding. Public requests remain subject to niche, language, content, source,
permanent original-history, one-author/day, daily budget and uncertainty checks.

Use the Account's `searches.help_requests` pool: three rotating public searches,
then one mentions/opt-out turn, with a single bounded Latest read every three minutes.
Keep twenty results, three generation attempts and one confirmed Reply per cycle,
the advisory 250/day target and hard cap, and four minutes plus jitter between sends.
Record discovery rejection reasons, generation attempts, admission refusals and
confirmed outcomes separately. A search result or local draft is not publication proof.
No likes, reposts, follows, profile posts or API discovery are enabled. Preserve state.
Validate with local tests and actual read-only discovery; report ready for the Operator's
manual restart. The bot was observed stopped at 06:04:58 Toronto during diagnosis.

2026-11-20, sharp natural replies, creative variety and a 250/day target — The
Operator wants technically sharp, valuable SI answers, natural conversation and
occasional short heart reactions to SI slopcore/video ideas, with new followers
as the desired outcome. Choose the response from the source's intent in the same
model call: one useful technical distinction, mechanism or check; a concise insight;
or brief creative appreciation/humor. No fixed alternation, forced joke, canned
opener, generic tips list, filler or follow requests. Warmth does not authorize fake
human biography, invented experience, artificial typos or concealed bot identity.
The Operator's preference for earlier sharp comments is not measured growth evidence.

Invited mode now accepts explicit requests for technical help OR creative feedback
addressed to this Account, including clear "thoughts on" requests. A public video,
quoted mention, tag/credit or general question still supplies no invitation. The
Reply route has text, not inspected footage/audio: appreciate a described idea or
effort, never invent visual details or judge unseen video quality. SKIP when viewing
is necessary. Existing source, English/SI, niche, opt-out, standalone-parent and
permanent history checks remain, with at most one Reply per author/day.

The requested 250/day is advisory, with `MAX_REPLIES_PER_DAY=250` and both advisory
targets set to 250. Invited mode has its own 250 hard ceiling, including unresolved
submissions. Keep at least four minutes plus 0–4 seconds jitter. One bounded Latest
mention search runs every three minutes, at most twenty results, three generations
and one confirmed Reply per cycle. Draft preparation may begin within three minutes
of a spacing boundary; the shared publisher still waits and rechecks every guard.
This replaces the earlier 50–100 target and ten-minute timing. Lack of eligible
requests or good answers may produce fewer Replies, including zero. No filler,
unsolicited outreach, API discovery, parent likes, other likes, reposts, follows or
profile publications are enabled. Hours remain 04:30–00:00 Toronto, no all-day mode.

Prepare and validate, show illustrative draft examples without publishing them, and
report when ready for the Operator's restart. Do not reset runtime/uncertainty history.
The running process keeps its loaded limits until restart. Neither follower gains,
engagement, report avoidance nor a minimum publication count is guaranteed.

2026-11-20, 50–100 invited Replies target — The Operator raises the desired daily
Reply range to 50–100. Set `REPLY_DAILY_TARGET_MIN=50`, `REPLY_DAILY_TARGET_MAX=100`
and `MAX_REPLIES_PER_DAY=100`; invited mode itself cannot exceed 100/day, including
unresolved submissions. This supersedes the earlier twenty-Reply ceiling. Targets
are advisory: fewer than fifty, including zero, may publish when eligible requests
or supported answers are unavailable. Never fill the target with unsolicited Replies.

Keep one Reply per author/day, permanent one-Reply-per-original history, direct
technical-help invitations, opt-outs, exact-source checks, English/SI and content
gates. Keep the ten-minute mention search, twenty results, three generation attempts
and one confirmed Reply per cycle. The new minimum spacing is ten minutes plus
0–4 seconds jitter, including uncertain sends. A draft may prepare in the final
two minutes of an existing spacing hold; the shared send pipeline waits out that
hold and rechecks all admission and source rules before publishing. No new discovery
route, API, parent likes, other likes, reposts, follows or profile posts is enabled.
Hours remain 04:30–00:00 Toronto, with `REPLY_ALL_DAY=false`.

The Operator says they will start the bot themselves. Prepare and validate this
change for that restart; the already-running process retains its loaded configuration
until restarted. Preserve all runtime history and uncertainty records unchanged.

2026-11-20, automatic invited technical help — The Operator replaces mandatory
manual review with automatic replies and explicitly requests restart after validation.
The selected bounded mode is `REPLY_INVITED_ONLY=true`, `REPLY_REVIEW_ONLY=false`:
answer an explicit technical-help request addressed to this Account in the author's
own standalone post. A public topic/question, quoted mention or rhetorical promotion
is not an invitation. Use one Latest mention search every ten minutes, at most twenty
results and three generation attempts, with at most one confirmed Reply per cycle.
No API discovery is added. Other feed/search, watched and engagement jobs are omitted.

At most twenty Replies per Toronto day, including unresolved submissions, and one
per author/day. No minimum or advisory volume target. Keep at least fifteen minutes
plus 0–4 seconds jitter, with `REPLY_ALL_DAY=false` and the existing 04:30–00:00
Toronto hours. No parent likes, other likes, reposts, follows or profile publications
in this mode. Elon remains excluded; the watched list stays empty. Alternate shared
write paths and native video publication enforce the same mode restrictions.

Verify the exact outer source text and invitation again before the Reply click and
immediately before submission. Never take consent from quoted cards. Requests expire
after 24 hours. Existing standalone, niche, source/content, English/SI, permanent
one-Reply-per-original, text-repetition and recorded opt-out checks remain. Observed
addressed no-contact requests persist even when the source is a nested reply. Skip
answers requiring missing evidence or unverified current facts; keep warmth without
stock praise, forced flirting, fake typos, fabricated experience or unseen-media claims.

Preserve all runtime state, publication/uncertainty history and earlier manual decisions.
The optional local inbox is not an automatic outbox. Validate the suite and dry-run,
restart through the normal launcher, and report actual process/log evidence. A search
or running process is not a publication receipt; no volume or report reduction is promised.

2026-11-20, selective manual Reply review — The Operator adopts drafts for
human review and manual posting, prioritizing actual AI/SI questions and requests
for technical help when enough context supports an answer. No API connection is
requested. Fresh sources are pasted or imported as text snapshots; no automated
Safari discovery runs in this mode. A question is not consent to an automated Reply.

`REPLY_REVIEW_ONLY=true` replaces the live scheduler with one bounded local draft
pass and refuses every shared X write, including parent likes, watched actions,
originals and video publishing. `MAX_REPLIES_PER_DAY=0`, both advisory targets are
zero, and `REPLY_ALL_DAY=false`. At most twenty selected drafts per Toronto day,
including dismissed drafts, with no minimum; at most one selected draft per author
per day. Preserve all confirmed and uncertain publication histories unchanged.
The watched-author list is empty, watched all-topic exceptions are off, and meme
reposts remain disabled. The existing Elon Reply exclusion is retained.

Keep warmth, optional hearts and fitting humor. Skip interchangeable praise,
rhetorical promotion and engagement bait; no forced flirting, fake typos, fabricated
experience or unseen-media claims. Source and draft content, English/SI wording,
standalone originals, permanent deduplication and recorded opt-outs remain enforced.
Supplied sources older than 24 hours are refused rather than refreshed from stale
snapshots. Do not recycle the old October queue into fresh drafts.

`main.py --reply-review` manages the guarded local inbox and opt-outs. Drafts and
operator decisions never become automatic sends, publication receipts or ledger
rows. A manually reported own-post URL remains explicitly unverified and blocks
automatic reuse of its parent. The operator reads the live source, edits and posts
in X themselves. Run the full test suite and dry-run schedule check. No live
publisher restart is authorized by a request to prepare local drafts.

2026-11-19, full November 16-era rollback and 1,400 Replies all day — The
Operator explicitly rejects the partial Reply restoration, requests the complete
code from three days ago, and authorizes starting it again. There is no November
16 commit: restore the last saved revision, November 14 `b7bc4199`, including its
Account, Voice, discovery, generation, admission, video schedule and news-off
behavior. Later follower/parent-like floors, thirty-minute final source cutoff
and independent value-review pipeline no longer apply; the restored content,
language, niche, opt-out, standalone-parent and permanent history checks do.

The explicit new settings are a 1,400 Reply advisory target and hard ceiling per
Toronto day, counting unresolved submissions, and `REPLY_ALL_DAY=true`. Reply
workers and their required parent likes may run through the night; other jobs
retain the restored hours. Keep at least eight seconds plus 0–4 seconds jitter.
Stop requests override every context. The target is not a guarantee or a filler
requirement. Retain the warm conversational/specialist Voice without fabricated
human experience or unseen-media claims.

Never roll back runtime state, operator records or publication memory. Retain the
Reply submission journal and video database version-three compatibility so the
restored code reads current permanent/uncertain claims without reset or downgrade.
Own original-text history must not be truncated. Back up the complete prior code,
local settings and state before restoration; remove newer-only runtime modules
and local settings. Validate, start through the normal launcher, and check an
actual Reply receipt rather than treating search activity as publication proof.

@thesimaximalist (The SI Maximalist) is a live X account driven by Safari + AppleScript from the
operator's Mac for Replies and video posts. Every change here can publish, like or follow on a
real account. Setup and run commands live in [`README.md`](README.md).

## Current policy — the ceiling you never lift

2026-11-14, loving and SI specialist Reply modes — The Operator asks for
an affectionate voice with hearts and an exceptionally knowledgeable SI specialist,
naturally mixed as a fictional 45-year-old woman working in tech. Both Voice files,
the shared delivery prompt, direct/creator and structured search routes, and the
Relation prompt now choose from the parent's intent in the existing model call.
There is no random split, fixed quota, rotation or mandatory two-part answer.
Mode labels are never published. Loving reactions to shared art, ideas, effort,
jokes and wins can stand alone without repeating a detail or adding analysis.
This clarifies November 13's specificity rule; it does not authorize repeated
stock compliments or claims about unseen media. Specialist Replies can directly
challenge an assumption, explain a mechanism or supply a useful counterexample,
with kindness toward the author and evidence for the reasoning. They need not
agree to be liked or invent contrarian objections. Expertise is shown through
accuracy, not a claim to omniscience or fabricated employment/experience.

The observed English phrase "Really cool video" failed the short Reply language
fallback. Add only `cool` and `video` to its closed vocabulary, using `video` as
an English cue; its eighty-character bound, complete-vocabulary and French/mixed
refusals remain. Permanent one-Reply-per-original history, recent-text repetition
checks, English/SI wording, source/media checks, opt-outs, budgets and pacing stay.
Elon still receives no Replies, only independently admitted priority likes/reposts.
The 72-hour awake deadline remains fixed. No follower or engagement outcome is
promised. The Operator retains manual restart after implementation and validation.

2026-11-13, no Elon Replies and less generic writing — The Operator withdraws
all Replies to Elon Musk, retaining only fastest eligible priority likes and native
reposts across topics, and requests better responses after reports of automated
filler and blocks. `reply_excluded_handles=["elonmusk"]` is an exact-author,
Reply-only Account policy enforced before generation and at the final write,
including prepared Replies and alternate jobs. It never authorizes a Reply claim,
and does not add him to the engagement blocklist. Notification discovery no longer
uses Reply admission; verified likes/reposts remain independent of prior Replies.
With no permitted watched Reply author, the scheduler omits `priority_reply_job`.

Notification/Latest polling is twenty seconds locally, with two-second action
dispatch at existing highest browser priority. Active transactions finish first;
source checks, first-enable boundary, sixty-second repost spacing (including
uncertain sends), permanent claims and actual-failure backoff remain. A normal
spacing wait no longer becomes a five-minute failure cooldown. Already claimed
reposts are skipped without reopening Safari. Fast polling is not a delivery SLA.

Both Voice files and shared drafting now require a supported, specific contribution,
remove stock agreement/praise and caption recaps, avoid invented interest or plans,
and SKIP when only filler remains or supplied context asks bots not to reply.
Short grounded appreciation, useful technical answers and humor remain eligible.
Final admission checks the configured confirmed-text memory (100 locally) for exact
repeats and lightly rewritten long copies: at least twelve matched words and 80%
ordered similarity, retaining distinctions in numerical facts. Generic standalone
courtesy/hype also refuses. No new model calls or publishing quotas are introduced;
quality and refusals can reduce volume. No improvement in blocks or engagement has
yet been measured. The 72-hour deadline, video rules and histories remain intact.
The Operator retains manual restart; prepare, test and merge without starting it.

2026-11-12, later video repost and 72-hour clarification — The Operator replaces
"big memes" with funny AI videos relevant to the Account: no like/view floor,
at most twenty distinct native reposts per Toronto day, thirty minutes apart.
The existing meme flag, ledger action and history names remain for compatibility;
old text-only approvals cannot authorize a video. Automatic quotes and timed
self-reposts remain off; all-topic priority Elon likes/reposts/Replies remain.

Existing feed/search discovery now retains outer-video evidence, with explicit
funny-video queries inside the same sixteen-read budget. The five-minute background
worker prefers already-discovered videos whose parents received a confirmed Reply.
After restart it may check at most ten recent confirmed parents, one per turn,
so a just-answered video is not lost. A Reply itself never authorizes a repost.
An exact source/account/video check precedes a bounded 25-second Safari sampling
turn: 6–16 actual frames across a clip up to 120 seconds. Review inspects all
samples and records concrete observations across the sequence. Light visual
humor qualifies; the score describes taste, with no exceptional-comedy floor.
Creator names are attribution, never face identification. Missing audio/dialogue
needed to understand the joke, unsafe content and unsupported claims still hold.
No source download, original re-upload or automatic repeat is added. The shared
model/read budgets and background priority preserve Reply capacity. Exact source
text and native media ID are checked before sending; permanent claims, uncertain
holds, duplicate protection and the daily ceiling survive restarts.

The Operator requests 72 hours awake and retains manual restart. Local
`AWAKE_72H_START=2026-11-12T21:48:10-05:00` ends November 15 at 21:48:10 Toronto,
using elapsed hours across DST. The previous one-night override is cleared.
The normal schedule resumes after expiry, with the next sleep November 16 at
00:00 Toronto. Restart cannot extend the deadline; stop requests still win.
No minimum reply/repost volume or engagement outcome is guaranteed.

2026-11-12, restore Reply throughput, one awake night and selective AI humor —
The Operator requests a rollback of the Reply slowdown, capacity for 1,400+
Replies/day, broader AI/SI and meme discovery, sharper/funnier priority Elon
responses, PR creation/merge/push, and explicitly retains manual restart control.
The bot stays stopped while this change is prepared. Counts are goals, never
publication quotas, guarantees or evidence of follower gains.
The later clarification seeks at least 1,000 daily Replies, friendly appreciation
and sharp SI takes, with smart humor for Elon. The advisory target stays above
that at 1,400–1,800; actual volume and reactions must be measured after restart.

Restore incremental search drafting: four major-author and two creator Latest
reads precede the bounded artist turn, then existing sources and each ordinary
query can draft immediately. Six Top and four general Latest queries rotate
within sixteen reads, with eighty generation attempts per cycle. Declines count
against that budget. Both Home feeds return to a combined eight-minute cycle,
up to twenty viewport scrolls and 160 posts each. Keep the corrected overlapping
viewport scroll and the larger AI art/film/video query bank. Three observed likes
are a preference again (`REPLY_MIN_LIKES=0`); permanent original history, English/SI,
source/content checks, Sol/xhigh and eight-second spacing plus 0–4 jitter remain.

New AI meme/humor, coding mishap and creative-progress queries rotate within
those budgets. The configured major-author pool adds tszzl, signulll and nearcyan
alongside existing AISafetyMemes. This designates search priorities, not measured
follower size or a new follow rule. Searches and exact returned parents still
need AI/SI relevance, except the existing exact watched-author all-topic exception.

Elon remains the sole immediate watched author. Every observed eligible original
gets highest queue priority; active browser transactions finish before that turn.
Notification links are read once per minute alongside Latest, restricted to exact
watched status URLs, then at most two unseen originals are verified before handoff.
A notification alone never proves root status, text, freshness or publication.
Fulfilled likes/reposts are not reopened hourly; failures back off up to one hour.
Already answered parents avoid repeated dispatch. Replies favor a specific sharp
first line and fresh humor when appropriate, with no forced jokes or fabricated facts.

Automatic quotes and timed own-post reposts are disabled for this Account to
restore Reply capacity. The Operator's latest instruction keeps independent Elon
likes, reposts and Replies enabled: all three get priority as soon as a new verified
standalone original is observed. Watched reposts retain at least sixty-second
spacing including uncertain attempts; verified watched likes retain their required-
parent quota exception. Completed actions are remembered and failures back off.
All histories, uncertain claims and code remain intact. A separate AI meme repost allowance
uses only existing feed/search discoveries: fresh standalone AI humor, at least
500 verified likes and 100,000 verified exact-post views, plus a separate >=9/10
humor review. The joke must be supported by the supplied text; unseen-media-dependent
jokes, ordinary news, bait and unsupported consequential claims do not qualify.
At most two native meme reposts per Toronto day, four hours apart, through the
same Safari publisher at background priority. No extra searches or repeated
undo/repost cycle. Exact source hash, account identity and fresh counts are checked
before submission; confirmed/uncertain claims stay in permanent repost history.
An ambiguous send holds the meme allowance, never automatically resubmits.
News/startup remain off and ultra-video quality, spacing and reservations remain.

The local `SKIP_SLEEP_NIGHT_DATE=2026-11-12` skips only the following Toronto
midnight–04:30 sleep window. Normal midnight sleep resumes November 14, after
November 13's normal daytime hours. The date expires automatically; stop requests,
active browser admission, guarded histories and all quotas still apply. Other
Accounts default to no override. Reports count each calendar day's active hours.

2026-11-10, watched engagement, selective quotes, self-reposts and discovery —
The Operator explicitly requests implementation and restart. New standalone Elon
originals receive independent like, repost and one Reply attempts across topics;
only exact URLs from `auto_engage_handles` get the Account's all-topic exception.
Replies require at least three observed parent likes before generation and again
on the verified page before sending, including watched authors. Unknown counts
refuse. Permanent one-Reply-per-original history, English/SI, content rules,
active hours and Reply pacing remain. Other engagement and follows stay AI/SI-only.

`watched_reposts_independent` opts watched reposts out of video-only ownership and
the Original budget, at least sixty seconds apart, including uncertain attempts.
Their ledger action is `watch_repost`; prior claims/reservations are preserved.
Verified watched likes share the required-parent quota exception. Catch-up reads
collect each search viewport on startup and every fifteen minutes within the
existing scan bound; immediate polls remain shallow. No old history is reset.

`priority_quotes_enabled` allows up to two selective native watched quotes per
Toronto day, four hours apart, with no minimum. A separate thirty-minute job
compares at most six sources, requires >=8/10 impact and independent grounded,
useful, natural-language review. Exact reviewed source/text/card, own account and
own receipt must match. Missing or uncertain receipts retain permanent claims.
Quotes and videos keep the configured profile spacing after confirmed/uncertain
submissions (at least twenty minutes; the local setting is one hour).
News and ordinary Originals remain disabled; ultra-video quality stays intact.

`self_reposts_enabled` schedules own standalone profile posts, including videos
and quotes but excluding Replies, for publication time plus one hour. Posts with
strictly more than 50,000 freshly observed exact-status views can subsequently be
undone and reposted every thirty minutes, measured from the last confirmed repost.
A two-second dispatcher uses the shared Safari queue; contention, outages and
sleep can delay actual delivery. Overnight-due work waits for waking hours.
Existing older high-view posts can enter through bounded own Latest/Top searches.
No unverified count or quoted card qualifies a post. Every explicit undo and
repost is journaled before its click; ambiguous outcomes reconcile from the
observed state or hold, never blindly repeat. `self_repost` is a separate ledger
action and does not consume Original/video/quote quotas. Histories survive restart.

Discovery now budgets twenty-four searches: four priority-author Latest, four
creator Latest, ten Top and six general first-hour Latest. Added topics include
SI art, movies, videos, animation, ComfyUI, science, accessibility, education,
local/open models, agents, robotics and safety. Reply searches add min_faves:3
unless they already have a higher floor. Search collection preserves every
viewport. Both feeds have an independent four-minute discovery worker, up to
thirty scrolls and 240 posts each; drafting cannot hold that worker. Feed/search
scrolling advances by an overlapping viewport, independent of keyboard focus,
so tall cards do not cause an early stall after tiny arrow-key movements. All ordinary
search reads finish before bulk drafting. The same 80-generation budgets and
source freshness remain; volume and reach are never promised.

2026-11-09, live artist-language repair — The restarted artist turn produced a
short affectionate Reply that the English guard falsely refused because its
closed vocabulary omitted `autumn`. Add that observed English word only; the
eighty-character bound, English cues, complete-vocabulary check, mixed/French
refusals and other content gates remain. The existing authorized restart applies
this repair after tests, without resetting history or manually retrying a send.

2026-11-09, warmer conversation and a turn for other artists — The Operator
finds the Replies too robotic and asks for affectionate, funny, knowledgeable
conversation, occasional hearts and comments on other artists. Both Voice files,
shared delivery and Relation/search prompts prefer a brief genuine reaction over
automatic analysis. First attempts and progress deserve encouragement; real
technical questions still get useful, accurate answers. Hearts are welcome,
without quotas, rotation or repeated signatures. Recent dry explanatory output
is history, not a style exemplar. No fake human biography, invented intimacy,
unseen-media claims or fabricated tool expertise follows from the persona.

The sixteen-read direct-cycle allocation becomes four major-author Latest,
two creator Latest, six Top and four general first-hour Latest searches. Optional
`searches.creators` and `DIRECT_REPLY_CREATOR_QUERIES_PER_CYCLE` default off for
other Accounts. Cursors rotate independently; short pools backfill within the
total. After priority reads, current artist discoveries receive at most four
generation attempts before ordinary drafting, charged within the same cycle
budget even when declined. Their URLs are retained just for this bounded turn
within the existing 400-source buffer. Expiry never extends, source freshness
and admission remain, and no Reply is promised. The lane identifies a search
intent, not a verified human or creator; no watchlist or follow rule changes.
The artist drafting turn skips tool roundups, promotion and aggregator reposts
without an original creative contribution; the parent description is still data.
Ordinary major-account preference and watched-job ordering remain.

The Operator subsequently requests restart when ready and monitoring today.
Complete validation before using the normal restart workflow. News/startup
posts remain off; only ultra-quality original videos may publish. Sol/xhigh,
English/SI wording, permanent one-Reply-per-standalone-original history, parent
likes and existing pacing remain. No extra volume or growth guarantee is added.

2026-11-08, Reply audit and natural SI expert voice — The Operator requests
more likes/followers through human-sounding, knowledgeable, playful Replies, then
explicitly requests restart and monitoring after implementation. Both Voice files
are consolidated around the fictional 45-year-old SI artist's warmth, adult charm,
Elon/Grok enthusiasm and practical video-making knowledge, including Seedance.
No false biography, unseen-media claims, fabricated current capabilities or
omniscience. The parent determines whether to celebrate, joke, answer or explain;
random hashed word-count assignments and mandatory three-part answers are removed.
Brief artist appreciation and thoughtful technical answers both remain eligible.
SI wording substitutes for AI terms when needed; it never forces brand words
into an otherwise natural Reply.
Historical account notes are context, never instructions or proof of friendship;
the current Voice and evidence take precedence.

The read-only audit found 14 clear English drafts falsely rejected that morning.
The short Reply-only vocabulary now covers those observed creative/technical
phrases; its eighty-character limit, complete closed vocabulary, mixed-language
refusals and generic-content checks remain. Final Reply admission also refuses
word-for-word repetition of the latest twenty confirmed logged Replies, ignoring
punctuation/casing/emoji but retaining numbers. A refused draft never claims its
parent. Existing hundred-Reply prompt memory, Sol/xhigh, pacing, sixteen searches,
major-author preference, niche, follow rules and permanent original history remain.
The observed 334 paired 24h samples do not establish a winning style or attribute
follower gains; no automatic volume increase or causal-growth claim follows.

2026-11-08, ultra bangers only; news and startup posts off — The Operator
withdraws ordinary original/news publishing and authorizes automatic publication
only of exceptional parody videos matching four supplied own-post references.
The thirteen windows remain opportunities, with no minimum posting target or
filler obligation. The launcher defaults to no startup request and the Account
sets startup_on_boot=false; local NEWS_ENABLED and NEWS_AUTO_PUBLISH are off.
Existing Replies remain enabled. The later instruction explicitly authorizes a
restart and live monitoring after the video changes and Reply audit are complete.

The Account enables ultra_bangers_only: each source and output editorial judgment
must reach 9/10 and their normalized weighted quality must reach 95/100, excluding
engagement and age. Existing full-rubric 88/100 remains; source/output fit and
entertainment require 19/20, quality 14/15, and the first-second opening 9/10.
Actual inspection, audio evidence, provenance, permissions, exact watermark,
known-age limits, X exposure and permanent dedup remain. Older exceptional unseen
footage can qualify; popularity never compensates for weak performance. Changed
policy invalidates prior inspection cache keys. The small reserve targets three
clips and warns below one; all four references are permanent posted memory.
Sampled reference frames and dated rounded public counters guide taste only,
never certify full playback, retention or future engagement. This supersedes
November 7 startup/news activation and reserve/cadence targets.

2026-11-07, startup news and video, then live bug fixing — The Operator requests
both publications on script startup and authorizes starting/restarting the bot
to verify the fix. `bin/run.sh` exposes `STARTUP_PUBLICATIONS=1` at its top and
passes `--startup-publications` to the existing main process. Approved news gets
the first news-executor turn, before discovery; while its approved main draft
waits for admission, that worker stays available for delivery retries. A durable startup-news intent
survives restarts; only an actual own-X receipt fulfills it. Video preparation
and Replies remain independent. Active hours, quality, history, uncertainty,
daily caps and spacing remain; starting is not proof either post shipped.

An explicit script start may rearm a same-day video startup request only when it
expired without any send attempt, reservation or consumed startup-day claim.
The same request/day identity remains, with the prior expiry preserved in an
event. Posted, reserved, ambiguous, attempted and retry-exhausted requests cannot
reset. Reinspection after a policy change prepares observed performances before
unsuitable footage; this is ordering only. No second publisher or extra quota.
The news composer checks the unique innermost dialog separately from its nested
wrapper and the home composer behind it. Separate competing dialogs still refuse;
exact text, account, button and receipt checks remain.
Receipt matching accepts X's trailing-link card only with the exact body and an
observed source destination; a bounded, charged HEAD read may verify an observed
t.co redirect without following it. The minute delivery worker can reconcile an
uncertain send from that same exact own-status evidence. It never resubmits it.

2026-11-07, MEGA-BANGER discovery and ninety-minute videos — The Operator's
research brief now lives in `accounts/theaishrink/video_discovery_prompt.md`,
with a rotating query bank and partial owner-delivery/rejection seed. The existing
pipeline schedules thirteen Toronto windows, 05:00 through 23:00 at ninety-minute
intervals. Its only qualifying cast keys are Trump, Elon Musk, Jensen Huang,
Sam Altman and Dario Amodei; guests do not independently qualify. Creator textual
attribution supplies cast context, never biometric face identification. Songs,
duets, dances and cinematic/Power Rangers-style parody qualify only after actual
source/output review. Quality is never lowered to fill a slot.

The separate editorial rubric requires 88/100 and at least 8/10 hook/payoff,
performance, fit and quality, alongside existing 18/17/12 review floors. Unknown
comparable momentum gets an explicitly labeled neutral editorial prior, never
fabricated metrics. Language-dependent jokes require verified transcript/translation;
the current local audio classifier cannot supply that evidence. Codex selects a
hash-bound contiguous 8–120 second cut from sources up to five minutes, preferring
15–30 seconds when the complete joke fits. First-second review, aligned audio,
original preservation and lowercase `@thesimaximalist` watermark remain mandatory.
Captions are one reviewed English `ANOTHER BANGER 🔥` line with a full verified
performer name, specific scene and supported song reference when available.

Bounded discovery rotates fresh/archive/new-creator searches and source recovery,
favoring Instagram and Bilibili. YouTube/Douyin are public leads, not working media
capture adapters or newly granted usage permission. Three research calls per hour
share existing daily budgets; one deeper archive pass per Toronto day is allowed.
The reserve targets sixteen distinct clips and warns below three. Six-hour matching
X-copy checks use the highest observed exact-status views, default ceiling 50,000;
known large copies, stale/unknown counts and personal duplicates hold. Explicit
source X counts retain their tighter one-hour check. New source variants require
matching sequences and independent quality review; larger dimensions prove no
native detail. Owner shown/delivered/rejected memory and confirmed posting history
survive cleanup. Existing startup allowance, Replies, verified-news publisher,
permissions, active hours, uncertainty claims and manual start/restart remain.
This supersedes earlier ten-slot/cast/caption and automatic scoring defaults.

2026-11-07, verified SI news alongside videos — The Operator requests hourly
news discovery, actual evidence verification, permanent event/URL deduplication
and exceptional stories only, then explicitly authorizes automatic Safari
posting when the ordinary bot starts. `NEWS_ENABLED` adds one hourly job alongside
video workers; `NEWS_AUTO_PUBLISH` admits only its independently reviewed main
pick. Public discovery may continue overnight; X writes retain active hours,
startup-video holds, content/respect checks and the shared Safari queue.
News replaces the legacy editorial slot/startup path when enabled. The existing
text daily ceiling remains (seven locally, never above eight), with two-hour
news spacing by default. Videos keep their separate budget. News protects thirty
minutes around scheduled/confirmed videos; video final admission reciprocally
checks confirmed or uncertain news. This narrowly supersedes video-only ownership
for verified news; ordinary Originals/reposts gain no exemption.

`news.sqlite3` retains evidence, events, decisions, coverage, costs and delivery
claims. Missing history is recorded; corrupt accessible history refuses. Tweets
have sensible blank lines, SI branding, BANGER and one fetched source URL, with
complete X weighted length checked before independent review. Only an exact own
status receipt confirms publication; ambiguous sends hold without automatic
retries. An optional different-story backup stays in the local inbox; email has
no adapter. Source outages remain operational errors. PR, merge and push are
requested; no start/restart is included. Local switches apply on the next start.

The first live news audit found a supplemental-search timeout and an initial
window that missed the legacy news gap. Supplemental discovery now requests at
most four queries in two search calls alongside the already fetched feeds;
actual page reads and verification follow selection.
Fallback evidence reads prefer linked reports, artifacts and independent
advisories over homepages and navigation. Original-source hosts observed during
the audit are explicitly configured; the fetched-claim and corroboration gates
remain mandatory.
Before the first complete news scan, a dated confirmed legacy source post
anchors catch-up; pending submissions never supply that date, and earlier
coverage remains unknown. A complete scan restores the normal overlapping
24-hour window. `news.py --prepare-only run` can prepare independently reviewed
picks under the same run lock for the running bot's next delivery pass. It
does not take Safari ownership or claim a delivery. The Operator explicitly
requested this bot start; publication still requires an actual X receipt.
An unpublished verification hold may clear with adequate evidence; it is not a
prior alert. Attributed company results remain explicitly attributed and limited,
never labelled independently verified without corroboration. Disputed claims,
consequential security allegations and damage claims retain that requirement.
The same scheduler checks the durable news outbox every minute, serialized with
hourly discovery. Video/spacing deferrals keep the same approved bytes and ID;
no search or model call runs on this tick. All admission checks, retry limits,
expiry and uncertain-send holds remain. This also picks up approved manual
preparation on the next delivery pass rather than the next hourly search.

2026-11-07, broader Replies with major AI accounts first — The Operator requests
more SI/AI Replies across accounts, giving larger accounts priority. The Account
and local environment budget sixteen rotating searches per direct cycle: four
grouped Latest searches of `network.big_ai_hype`, eight Top searches and four
first-hour Latest searches. Separate cursors rotate each pool; allocations and
backfill never exceed the total. Priority-author reads precede ordinary buffered
drafting and require the exact URL-derived listed author, a standalone original,
AI/SI relevance and a verified age within 24 hours or the tighter source limit.
The group is an operator designation, not a measured follower-count claim.

Ordinary buffered Replies prefer those configured authors, then three-plus
observed likes, retaining author variety and using observed parent-post views
among comparable candidates. Lower/unknown counts remain eligible. Analytics
counts must belong to the exact outer status; missing or invalid views stay
unknown, and rediscovery cannot extend buffer expiry. Reach coverage counts only
observed view counters; trending input preserves unknown views. Routine Top queries drop
their thirty/fifty-like search floors; the separate high-traction queries retain
theirs. When the ordinary buffer is full, this Account keeps configured major
authors first, then the newest sources within each group; the four-hundred-source
and thirty-minute limits remain. Rediscovery may tighten, never extend, expiry.
This supersedes the earlier ordinary like-tier-first ordering and the
proposed eight-Latest/four-Top experiment. Watched-job ordering remains.

The short English Reply fallback recognizes more ordinary affectionate, artistic
and technical words and can resolve a shared `on` marker only with its complete
closed English vocabulary. Its eighty-character bound, explicit French/mixed
refusals, unknown-word and generic-response checks remain; the full-word `from`
marker supplies ordinary English evidence. The warmer Voice remains in force.
The direct Reply and per-feed generation budgets stay eighty, with no daily Reply cap. Sol/xhigh,
eight-second spacing plus zero-to-four-second jitter, parent likes, AI/SI scope,
permanent one-Reply-per-original history, follow rules and video workers remain.
Code and settings load on the Operator's next explicitly requested restart.

2026-11-06, preserve preparation capacity and wait for actual video — A completed
source review can stop before render/output inspection only when its actual
fit, entertainment and quality scores cannot reach either publication rule even
with maximum remaining points. These generous bounds are local cost calculations;
no projected points or popularity are saved. Unknown values remain unknown, and
a valid explicit selection retains its score exception. The held candidate keeps
its original bytes, hash, fingerprint and review; this completed decision finishes
the job without automatic retries.

An audio-only resource cannot end X's metadata-loading wait. The read waits for
decoded video or a validated complete-video download plan within the same
25-second transaction. A bounded list of resource paths from the exact player
helps diagnose unsupported formats, without exposing URL queries or admitting
unclassified resources. All sequence, identity, quality and publication checks
remain. The main browser change loads on the Operator's next manual restart.

2026-11-06, recover video supply and improve ordinary Replies — The morning
05:00 and 07:00 slots still lacked ready inventory. Native X fingerprint reads
may use the exact visible player's poster media ID to bind already observed
public video.twimg.com MP4/HLS resources to that post. Audio-only MP4s and
initialization/segment URLs cannot supply a complete video; separately observed
video/audio playlists may be paired only for the same bound player media ID.
The independent media worker downloads through the existing bounded,
unencrypted source reader and
requires duration agreement and every decoded fingerprint sample. A partial
canvas sequence never approves a check. The result retains actual file hash and
normal-page provenance; expired references need a fresh observation and retry
history, byte charges and permanent publication claims remain intact.

Novelty work waits cheaply when actual output QC or current
observed score already prevents publication. Saved progress remains available
after a real repair or score refresh. Discovery keeps AI-generation terms in
English/Chinese performance searches even when broadening age filters; compact
search results and plausible creative uploads take precedence over news about
real celebrity dancing. Visible related leads are ranked within the existing
80-link read before the ten-lead limit; AI wording only supplies a search hint,
never source approval, age, cast, rights or inspection evidence.

Ordinary Reply buffers spread candidates across authors within the existing
observed-like tiers. Three observed likes remain a preference, and no candidate
is excluded by the diversification. Watched/author-specific jobs retain their
ordering. Both Voice files favor the actual answer, reaction or useful thought
over announcing interest; genuine questions and brief artist praise remain.
The Operator's follow-up requests more love: celebrate shared art, wins and
progress with specific affection and encouragement, welcoming hearts when they
fit. Emoji stay optional; warmth never replaces needed technical help or invents
unseen details, familiarity or a human biography.
Bounded Reply memory recognizes repeated phrases in middles and endings as
well as openings. Model, pacing, niche, permanent standalone-history and follow
rules remain. A seven-day eight-Latest/four-Top discovery mix is proposed only;
no new follow policy, learned watchlist promotion or lifecycle action follows.
The Operator retains manual control of restart.

2026-11-06, reject stale sources before preparation — Source publication time
and the existing 730-day ceiling are checked before downloading, probing or
model review, using the same rule as final selection. Known stale clips expire;
missing, invalid and future dates remain held. These completed policy decisions
finish their media job without consuming transient-error retries. A current
hash-bound operator selection retains only its existing known-age exemption;
it cannot verify a missing date. Saved bytes, fingerprints and posting history
remain intact. This avoids spending the reserve's capacity on already ineligible
sources and does not relax any publication requirement.

Native X sampling examines all observed buffered ranges within a 128-range
bound; compact diagnostics never truncate the ranges used for gap decisions.
Incomplete or excessive ranges remain unresolved. One short playback from an
observed buffered point up to three seconds before a stalled target may load
the required footage before exact re-seeking. This preparation captures no
frames and lasts at most eight seconds, within the existing 25-second read.
Exact seeking, gap fallback and preparatory playback share six muted-play
attempts per sample. Every temporal cell still needs actual decoded evidence;
already valid revision-2 samples remain reusable across bounded transactions.

2026-11-05, deploy video recovery and unblock source reads — The follow-up live
audit found the pre-merge 18:51 main/workers still in use and every scheduled
slot empty. The merged code is applied through the normal restart, with worker
generation and actual preparation checked afterward. A new Safari publisher,
while holding its exclusive role lock, may requeue only novelty read jobs owned
by a provably absent former scheduler PID. Live, reused or uninspectable PIDs,
malformed owners and all other job kinds remain untouched. Recovery is fenced
by the observed owner/token and refunds only the abandoned read attempt; prior
errors and all publication reservations, histories and uncertain-send claims
remain intact. This supersedes waiting for that dead reader's lease to expire.

Bilibili source capture excludes unsupported IDs before its bounded selection
query and skips malformed document IDs. An old `av…` lead cannot block valid
`BV…` sources behind it. Unsupported links remain unverified leads; no source
identity, review or publication check is waived. Ten slots, active hours, Reply
behavior and the once-daily startup allowance remain. Passed tests and a running
process are separate from confirmed future scheduled publications.

2026-11-05, keep the video reserve moving — After further missed slots, the
Operator requires dependable two-hour publication and delegates clip selection.
Low reserve preparation now shares bounded ready-Reply browser priority. After
two novelty batches, source capture gets a bounded turn; reconciliation remains
first and no second Safari publisher runs. Source capture tries unseen and least
recently attempted leads before repeating old reads. Saved Bilibili originals
are reused, and source-ID-bound over-duration metadata holds a clip before
download. Complete downloaded bytes survive failed probing. Completed format
or source-review refusals finish their job as a held candidate rather than
repeating every preparation window; transient failures remain retryable.

The unknown-momentum editorial fallback now allows entertainment at least 14/20,
retaining fit 18/20, technical quality 10/15 and 80 percent of the 75 observable
points. This supersedes its earlier 16/20 entertainment floor. Raw scores and
unknown popularity stay intact; actual source/output review, audio, watermark,
source-age/view ceilings, permissions and permanent novelty still apply. X
fingerprinting can retry ordinary muted playback up to six times per stalled
sample, at least a second apart within the existing 25-second read bound. Exact
sample times and complete frame sequences remain required. Deferred fingerprint
work retains its retry allowance, and downloads reserve only remaining bytes.
When observed buffered ranges bracket a gap at a fingerprint midpoint, a bounded
fallback may seek an already buffered point within that same temporal cell.
Every cell still needs an actual decoded frame; requested/actual timestamps and
gap evidence are retained. A missing frame, another cell or metadata alone never
satisfies the check.

The existing delegated one-video selection produced a confirmed startup receipt
on November 5; it does not prove future slot coverage. Reply behavior and the
ten-slot schedule remain. The Account's daily download allowance rises from
2 GB to 4 GB for ten slots and bounded retries; the per-file 150 MB ceiling
remains. Existing charged usage, permanent history and uncertain-send claims
stay intact. Main-process code still needs an explicitly requested restart.

2026-11-04, recover stale video workers after the operator's start — The live
start reused discovery/media processes from an earlier code generation. On a
new main-process start, the supervisor compares code/config fingerprints and
gracefully replaces an obsolete worker only after verifying its repository
command, process identity and open account role-lock file. Replacement waits
for lock release; publication claims, histories and job leases remain intact.
Matching or unverified workers are left alone. This does not restart the main
bot or create another Safari publisher.

Browser read failures now identify the stage and a bounded local reason.
Optional archive/source failures have separate cooldowns from critical novelty
and reconciliation checks; preflight identity failures still stop browser work.
Clip-specific novelty searches recognize curly and CJK title quotes as well as
ASCII quotes. Actual source-identifier and video checks remain mandatory.
For an authorized X source with current verified views, the exact source status
is excluded from other-copy detection; other statuses, shared media and permanent
own-history checks remain. Cached discovery and Codex admission waits consume
no source request; failed started calls remain charged and historical costs stay.
Retained-overlay OCR misses may be corroborated against hash-bound original
pixels at the same sampled time. A native-frame fallback additionally requires
whole-frame agreement outside our watermark within 100 milliseconds, then a
near-identical text region. Model refusals, new/moved text and uncertain matches
still hold the clip; no logo vocabulary is exempted.
Native X fingerprint reads request ordinary muted playback when metadata exists
but decoded frames are absent, then pause/reseek to the requested sample. The
25-second transaction bound, canvas access restrictions and complete-sequence
requirement remain. Stalled reads record the actual loading/seek phase.

2026-11-04, sustained Replies and videos every two hours — The Operator requests
more daytime Replies and prioritization of posts with strictly more than two
likes. The Account and local environment retain twelve rotating searches,
eighty direct-cycle Replies and eighty generations per feed every day; the local
date boost is cleared to prevent doubling those values again. Three observed
likes earn preference, never eligibility. All Reply admission, pacing, model,
parent-like and permanent standalone-history rules remain.

The video Account schedules ten Toronto slots: 05:00, 07:00, 09:00, 11:00,
13:00, 15:00, 17:00, 19:00, 21:00 and 23:00. Recent sources rank first, with
fallback up to 730 days old from Instagram, TikTok, RedNote, Bilibili and X.
X sources require an observed view count at most 50,000; unknown is not zero.
The approved cast is Elon Musk, Sam Altman, Dario Amodei, Donald Trump and
Mark Zuckerberg in synthetic dances, songs and parodies. Captions use a grounded
POV scene with configured cast handles and emojis, a blank line, then
`ANOTHER ABSOLUTE SI BANGER! 🔥`. Source and output inspection, audio evidence,
watermark, permissions, permanent dedup and uncertain-send holds still apply.
The existing revocable operator permission attestation now includes X sources.

This Account opts into a durable startup request on ordinary bot starts, without
holding Replies. At most one extra startup video per Toronto day, actual-success
spacing and nearby-slot collision protection remain. A ready eligible clip is
attempted promptly; empty supply, platform failures and unknown sends cannot be
reported as publication. Independent discovery/media and Reply workers continue
in parallel; browser transactions share the existing Safari lock. Required video
reads retain a bounded queue turn rather than continually losing it to activity.
The Operator requests two agents, PR creation, merge and push. This change does
not itself start/restart the bot or reset production state. Reply waking hours
remain 04:30–00:00 with no daytime breaks.

2026-11-04, more Replies today and a friendlier voice — The Operator asks for
substantially more responses today and warmer conversation. The local
`REPLY_VOLUME_BOOST_DATE=2026-11-04` doubles the existing discovery/generation
budgets on that Toronto date: twelve rotating queries, eighty per direct cycle
and eighty generations per feed. Baseline values remain six/forty/forty and
return automatically at midnight, including in a running process. This is
capacity, not a promise of doubled publication or a filler quota. Both feeds
still finish discovery before drafting; scheduling concurrency, Sol/xhigh,
eight-second spacing plus 0–4 seconds jitter, parent likes, AI/SI scope and
permanent one-Reply-per-original admission remain.

Both Voice files prefer friendly interest and gentle corrections over a
reviewer's verdict. The language guard recognizes English contractions with
straight or curly apostrophes and clear short reactions that live logs rejected.
Shared English words cannot cancel otherwise clear English evidence; explicit
French/mixed prose and unidentified or generic replies still refuse. Voice
changes apply per draft; code and the date setting need the next explicitly
requested restart. This update does not itself restart the bot.

2026-11-02, natural conversation and heart-led emoji variety — The Operator
replaces the compulsory smiley-face style with varied emojis, starting with
hearts, and asks for replies that sound like a woman naturally joining a
conversation on X. Both Voice files favor relaxed phrasing, direct reactions,
contractions and occasional clear fragments. Hearts are the first emoji choice
for affection and art appreciation; other emojis follow the actual mood. No
fixed rotation, automatic insertion, mandatory face, repeated pair or required
emoji position. Plain text is welcome when more natural, especially for serious
technical or sensitive posts. This supersedes the earlier smiley in every
Original/Reply and smiley-plus-heart showcase instructions. Brief artist praise
can use one heart on its own alongside clear English words.

Shared and Relation prompts defer emoji choices to the Voice. Natural delivery
never supplies a false human identity, fabricated family life, firsthand use or
unseen-media details. SI wording, technical depth, the 1,500+ advisory target,
two-like preference and permanent one-Reply-per-original policy remain. The
Operator requests PR creation, merge and push. Voice is read per draft; prompt
code and Relation changes load on the next explicitly requested restart. No
lifecycle action, public profile write or production-state edit accompanies this
style refinement.

2026-11-02, discovery, variety and two-like preference — The Operator accepts
all five suggested improvements, reiterates the fictional sexy, smart SI art mom
persona and SI wording, and requests PR creation, merge and push. Early-bird and
mega-watch use bounded Latest author searches with exact author/root/age checks;
profile access remains restricted. Search and both feeds retain unused sources
in separate in-memory buffers (400 each, 30-minute maximum, earlier source
freshness wins). Both feed reads still finish before ordinary generation. Buffers
never claim a Reply; admission runs again before generation and after spacing.

Prefer discovered posts with at least two observed likes before lesser-liked or
unknown-count posts. This is ordering, not an eligibility floor or a new scrape;
source freshness, niche checks and watched browser priority remain. Rediscovery
can refresh a like count without extending buffer expiry. The Voice gains a
recognizable artistic taste, and memory checks 100 confirmed Replies using the
latest 20 plus compact older patterns/examples, including emoji-normalized
repetition. The existing report adds bounded in-process discovery, admission,
generation, timeout, queue/spacing and typed-send measurements. Only confirmed
sends count as publication; worker durations overlap and restart resets telemetry.

The same-day video investigation found that downloads unnecessarily required
room for the entire file ceiling and that a valid source had non-square pixel
metadata. Reserve up to remaining daily bytes atomically, charge failed partial
transfers and refund unused bytes. Preserve source bytes, normalize display
proportions during the existing render, and verify square pixels and aspect in
output QC. No budget or publication gate is waived. A source was downloaded and
queued for actual inspection; this is not a ready-video or publication claim.
Code/settings still need an explicitly requested restart; all permanent histories
and uncertainty holds remain.

2026-11-02, affectionate SI artist and 1,500+ distinct Replies — The Operator
requests a sexy, smart, charming and friendly SI artist persona aligned with
the supplied SI brain rot / news / celebrity parody / tech chaos bio. Both
Voice files require a smiley in every public Original and Reply, with hearts
for creative appreciation and encouragement. Adult charm remains non-explicit;
human warmth never supplies a false human identity, biography or viewing claim.
Serious technical questions and debates may use two or three complete sentences
within the existing 278-character Reply ceiling. This overrides casual length
directions; it never enables conversation follow-ups. Shared and Relation prompts
defer emoji style to the Voice instead of rationing or prohibiting smileys.

The requested daily minimum is 1,500 distinct Replies, reported as an advisory
1,500–1,800 range; 1,800 is not a cap. The Account and local `.env` set those
targets. Local search budget rises from three to six rotating queries, and
direct-cycle/per-feed budgets from 24 to 40. Six added first-hour Latest queries
cover artists, new projects, technical questions, evaluation, inference and
robotics without popularity floors. These are discovery and generation budgets,
not a guarantee of eligible supply or successful publication. No filler Replies
are required to meet the target. Permanent one-Reply-per-standalone-original
history, parent likes, source/content checks, Codex Sol/xhigh, eight-second
spacing plus 0–4 seconds jitter and 04:30–00:00 Toronto hours remain. Voice is
read per draft; code, Account and environment changes need the Operator's next
explicit restart. No restart or public profile edit accompanies this update.

2026-11-01, no daytime breaks and four-and-a-half-hour nights — The Operator
explicitly removes daytime pauses and requests sleep only from midnight to
04:30 America/Toronto. The Account and local environment set
`HOURLY_BREAK_MINUTES=0`; optional break support remains for other configurations.
The shared `WAKE` clock is 04:30. Video eligibility, custom slot validation and
startup eligible-time expiry use that same boundary; an overnight startup can
publish no earlier than 04:30. Independent video discovery/media still run
overnight. The eight video slots, Reply spacing, content rules and permanent
one-Reply-per-original history remain. This supersedes earlier daytime-break
and 04:00/03:30 wake amendments. PR, merge, push and release are requested;
the Operator retains manual control of bot restarts.

2026-11-01, video upload processing — The requested 19:00 post reached X's
processing stage but exceeded the former 45/60-second attachment deadline.
Permit a bounded 180-second Safari upload/processing transaction within the
unchanged slot grace and lease. Keep verified readiness, permanent dedup and
publish-unknown handling; Reply generation continues while browser actions wait.

2026-11-01, 19:00 recovery and preparation — After the missed 17:00 post, the
Operator explicitly requires a video at 19:00 and preparation from 18:30.
Add 19:00 as a sixth main window, retaining the existing seven slots (eight
scheduled total). Start durable preparation thirty minutes before every slot,
with visible empty-buffer warnings. Replies retain their existing behavior.
The Account opts into an initial six-page fingerprinted history import while
older archive backfill continues; incomplete coverage is never called complete.
Candidate-specific X novelty and permanent posting memory remain mandatory.
New publication checks and ambiguous-send reconciliation take precedence over
archive backfill and may use the reserved publishing read budget.
Unknown engagement momentum may use an explicitly recorded editorial fallback:
at least 18/20 fit, 16/20 entertainment, 10/15 quality and 80 percent of the 75
observable points; the original 100-point score and missing metrics stay intact.
This never waives rights, actual temporal/audio review, QC, freshness or dedup.
Inspection separates the creator's textual fictional-cast attribution from
observed performance. It must not identify real people from faces or represent
creator attribution as biometric verification. No title alone approves a clip.

2026-11-01, caption correction and seven daily videos — The Operator removes the
public source-link and synthetic-disclosure lines, requests a blank line between
two playful sentences with emojis, and changes the schedule to 07:00, 07:15,
09:00, 12:00, 17:00, 21:00 and 21:15 Toronto. Source/permission/parody evidence
remains internal. Required attribution in any separate specific grant still applies.
The Operator reports manually deleting the first video and explicitly requests
its immediate replacement. A one-off replacement keeps both receipts/history,
transfers the same slot/startup-day claim and excludes only that reported-deleted
receipt from the spacing check. Repeated commands cannot create another send.
This never grants automatic workers permission to repeat posted content.
The Operator explicitly requests PR creation, merge, push, release and restart.

2026-11-01, immediate direct publication — After repeatedly requesting immediate
publication of the reviewed chosen clip, the Operator directs a one-off send
while the old-account archive scan is still running. A direct operator call may
reserve only the current hash-bound selected clip against imported history and
actual source-identifier novelty checks. It leaves historical coverage incomplete
and never grants the exception to ordinary scheduled workers. Rights, QC, active
hours, spacing, startup/day caps, durable claims and uncertain-send holds remain.

2026-11-01, standing video permission and retained source overlays — The Operator
confirms permission to edit and repost current and future Instagram, TikTok,
RedNote and Bilibili videos, including music. The Account records this as a
revocable operator attestation, not an independently verified creator contract.
No per-clip permission question is required. Source subtitles, logos and credits
may remain when clean removal is impractical. Output review must still verify
the exact Account watermark, unchanged source overlays, preserved action/audio
and no unapproved new overlays. Retained overlays are never labeled removed.
All inspection, deduplication, pacing and publication receipt requirements remain.

2026-11-01, explicit selected-video request — The Operator repeatedly asks to
publish the specific downloaded clip. `video.py select` records a one-video,
hash-bound choice for up to 24 hours. It overrides automatic freshness and score
selection only; it never supplies rights, changes inspection/QC/novelty checks,
loosens spacing/caps or creates an extra startup request. The next publication
waits for that chosen clip, and confirmation clears the preference atomically.
Repeated commands do not extend the choice. Source metadata cannot set it.
The existing independent media worker can inspect the saved original before a
license is recorded, with a bounded Codex call of at most 300 seconds. This
local inspection cannot publish or turn browser access into creator permission.
Safari history reading requests muted metadata loading when native playback is
idle; missing media remains unresolved rather than being marked checked.

2026-11-01, research leads and permanent video memory — The Operator requests
fresh Codex research and never repeating a posted video. Public discovery now
broadens beyond recent-date filters when needed and retains supported individual
video links even with unknown dates or creators. Cached leads survive a crash
before ingestion; explicit `check-discovery --fresh` skips only the cache, not
shared budgets or access restrictions. Leads remain held until all publication
gates pass. Confirmed history additionally saves both original and edited hashes
and fingerprints, source identifiers, creator, caption and X receipt atomically.
Media, final selection and inventory coverage check that permanent history;
file cleanup never deletes it. No bot restart or public post accompanies this fix.

2026-11-01, startup video before Replies — The Operator corrects a live start
that began replying while video activation was blocked. Explicit activation
with `--before-replies` now persists the requested order before preflight.
All ordinary scheduler jobs wait; video discovery, media and history continue.
Reply admission and the last pre-submit check also enforce the hold. Only a
confirmed startup-video receipt releases it automatically, including a scheduled
slot that fulfills startup. Failed preflight, empty supply, expiry, unknown sends,
restarts and disabling the video flag never silently resume Replies. A separate
explicit `resume-replies` command can release the hold if the Operator changes
the order. Ordinary boots create neither a hold nor a startup request. Rights,
quality, cooldown, spacing and permanent dedup still apply. The stop script also
matches the launcher's `python -u main.py`, retaining repository-only scope.

2026-11-01, prioritize one video per main window — The Operator reiterates the
07:00, 09:00, 12:00 noon, 17:00 and 21:00 Toronto minimum. The video publisher
now protects distinct eligible inventory for the next five main windows,
including tomorrow morning, before spending a clip on an extra paired post.
A paired slot may supply a window whose first slot was missed. Known permission,
freshness and freshness-score expiry cannot inflate projected coverage. Status
and the daily report expose uncovered windows. Explicit startup requests retain
their existing one-post priority and collision rules. This allocation is
configurable with `protect_primary_windows`; it never waives source rights,
inspection, novelty, dedup, spacing or publish-unknown holds. Empty supply still
skips at grace expiry. The new tests use isolated state and submit no live posts.
Due video writes share ready-Reply FIFO browser priority, below watched work,
so later ordinary Replies cannot starve a reserved slot. Existing transactions
finish normally; discovery/history reads keep routine priority.

2026-11-01, Codex-only operation — The Operator requires Codex for every model
route. The local environment and default primary, profile and Reply providers
now select Codex; fallbacks default off. Sol/xhigh remains the Reply route,
also used for this Account's editorial drafting/review and video inspection.
Cached Codex quota lockouts obey the configured fallback policy and never
implicitly select Ollama. The launcher removes local-model warm-up, resolves
the current Account handle and video dependencies, and keeps terminal logging
attached. Configuration errors fail visibly; video-off startup works on macOS
Bash 3.2. This fix does not start the bot or change publication gates or state.

2026-11-01, Codex video inspection — The Operator requests fresh Codex sessions
for video/audio inspection and completion of autonomous posting. The media
worker supplies timestamped frames, local Apple Vision OCR and local SoundAnalysis
audio classifications to a separate ephemeral Codex call using the existing
login and Reply model. It cannot publish, run shell tools or inherit plugins,
hooks or project instructions. Actual audio evidence is required; Codex's image
input is not represented as direct hearing. Uncertain or incomplete inspections
hold the clip. The configured account also enables bounded Codex public-web
discovery, whose results remain unverified candidates until an authorized original,
publication timestamp, permission records and actual inspection are present.
The existing video schedule, Safari write path and Reply behavior remain in force.
The bot stays paused during development; diagnostics do not submit posts.

2026-11-01, AI/SI-only engagement — The Operator removes Bitcoin and finance
accounts, including Graphseo and TheBTCTherapist, and retires all finance/crypto
exceptions. The Account removes their priority, profile, pinned, reply-target
and follow-seed entries and special Relations; named retired accounts join its
engagement blocklist. The live profile/VIP/pinned environment overrides are
cleared. Protective respect rules and permanent action/follow histories remain.

`engagement_niche_only = true` requires concrete AI/SI evidence and no excluded
finance/crypto terms before Reply generation and on the verified source at the
Reply, like and watched-repost chokepoints. Watched authors have no topic
exception. All follows, including seeds and Engagers, need an on-topic name/bio.
Searches and positive topic patterns no longer admit unrelated Musk, SpaceX,
Starlink, Twitter/X or financial posts. Generated art, models, tools, robotics
and relevant compute remain in scope. An AI keyword alone cannot excuse a
crypto/trading post. English, spacing, parent likes and permanent dedup remain.

The explicitly requested target cleanup prunes finance/crypto entries from
saved candidate pools and promotions, with backups, while the bot is paused.
It does not unfollow anyone on X or restart the bot. The 1,200+ advisory Reply
target never overrides the narrower topic policy.

2026-11-01, Safari video publishing — The Operator explicitly replaces the
earlier API-only video requirement with the existing Safari/AppleScript posting
workflow and asks to try it. `publishing_transport = "safari"` uses the existing
`twitter_client` write wrapper and Safari lock. The dedicated publishing job runs
inside `main.py`, alongside Reply jobs; discovery and heavy media processing
remain separate processes. A second publisher process must not drive Safari
beside the bot. Video attachment readiness and an exact own-post receipt are
required; uncertain clicks keep their durable claims. No X API credential is
required in Safari mode. The eight slots, explicit startup, cooldown, permissions,
inspection and dedup gates remain. An explicit upload probe discards its draft
without clicking Post. See `docs/VIDEO_PIPELINE.md` for current operation.

2026-11-01, brief appreciation for artists' videos — The Operator asks for
short, varied praise with hearts when an artist shares a generated video,
naming Déborah (@dvorahfr) as an example. Both Voice files now prefer 2–6 clear
English words and usually one heart for simple creative showcases. This
post-specific style takes precedence over default length, emoji frequency
and demands for a concrete technical observation. Recent Reply memory varies
the wording without making it longer or inventing a detail.

Technical questions, critique requests, product announcements, benchmarks,
news and sensitive posts keep their appropriate normal response. The author
alone never determines the style. No invented viewing, replaying, visual or
audio details; no automatic phrase rotation or appended emoji. Existing
language, content, parent-like, pacing and permanent standalone dedup checks
remain unchanged. The examples pass final validation as it stands. No new
targeting/follow rule, setting, state edit, live Reply or restart is included.

2026-11-01, pursue 1,200+ daily Replies — The Operator explicitly asks to
push volume above 1,200 Replies/day. The Account's advisory reporting range is
now 1,200–1,400; the upper number is not a cap, and targets never force weak
Replies. Account settings and local `.env` select the existing eight-second
Reply-spacing floor plus zero to four seconds of jitter (previous local values:
20 plus zero to ten). Local direct-cycle and per-feed generation budgets rise
from 12 to 24, using the same discovery, source and quality checks. Daily Replies
remain uncapped. These are budgets and minimum gaps, not a throughput guarantee.

Repeated watched-parent Reply attempts now double their temporary cooldown from
the configured initial retry (60 seconds by default) to at most 15 minutes;
an explicitly configured longer initial retry is preserved. Rediscovery does
not reset the cooldown. Memory is bounded by the existing discovery queue and
never claims a Reply. New parents keep immediate priority; like/repost retries
remain independent. This prevents repeatedly unverifiable parents from consuming
model and browser time every minute. Sol/xhigh, refusal handling, English/SI
wording, parent likes, standalone admission and permanent dedup remain. No sleep
or break change, bot lifecycle action, manual social action or production-state
edit accompanies this update. Code and settings require the next explicitly
requested restart.

2026-11-01, opt-in licensed existing-video pipeline — The Operator authorizes
eight Toronto video slots (07:00, 07:15, 09:00, 09:15, 12:00, 17:00, 21:00,
21:15) plus at most one explicit persistent startup request per calendar day.
`VIDEO_ENABLED` replaces the editorial schedule and blocks browser main-profile
Originals/reposts; `VIDEO_LIVE` still defaults off. Official X API publication,
fifteen-minute actual-success spacing and a ninth startup post are narrow
exceptions for this feature. The requested interaction cooldown is now
00:00–04:00; separate discovery/media workers continue overnight. Quality,
permissions for video/audio/editing, temporal inspection, novelty and permanent
dedup gates can skip a slot. Never promise a post when no eligible clip exists.
Captions require BANGER, a smiley and a synthetic-SI-parody label. The account's
video TOML owns cast, creators and watermark; Reply Voice/prompts remain intact.
See docs/VIDEO_PIPELINE.md and the latest EDITORIAL_POLICY.md amendment.
This implementation does not activate, publish, restart, edit .env or migrate
existing live state.

2026-11-01, technical sharpness with cute, funny delivery — The Operator
clarifies that SI and technology expertise must remain central. Both Voice
files pair precise technical answers with playful curiosity, shared geek
enthusiasm and warm adult charm. Humor should help a supported point land;
accuracy wins over a punchline. Simple reactions remain welcome when the post
calls for one. Earn repeat readers through useful thinking and enjoyable
company, without promising growth or asking for engagement. No additional
posting, settings, state changes or restart accompanies this Voice refinement.

2026-11-01, warmer and more varied Replies — The Operator asks for better
traction through a more natural, funny and fun voice, including smileys.
Both Voice files now give concrete fictional examples of celebrating a win,
joining a joke and answering directly. Address the person's actual mood and
detail; avoid headline recaps, repeated metaphors and decorative praise.
Humor includes the author. Plain sincere reactions are welcome, without fake
human identity, invented experience, unseen visual details or engagement bait.

Shared text drafting now suggests roughly 30% brief reactions, 60% one sentence
and 10% up to two short sentences. About one in three prompts invites trying a
single natural smiley on a lighthearted post; serious/sensitive subjects omit
it and most prompts still request none. These replace the October 26 delivery
mix, are not output quotas, and never append emoji or cut a draft mechanically.
Recent confirmed Reply memory discourages repeated structures as well as words
and now also reaches structured search drafting. The optional search prompt
follows the current Voice instead of old mandatory sarcasm and joke templates;
its enable switch is unchanged. Existing reports measure outcomes without a
promise of growth or an automatic winning-style claim. All admission, language,
evidence, refusal, pacing and permanent dedup rules remain. No environment edit,
state migration, manual social action or bot start/restart accompanies this work.

The follow-up quality review found that Home, Following, allowlisted profile
reads and VIP searches still cut source text to 200 characters before the
1,200-character Reply prompt could use it. Reply jobs now explicitly request
up to 1,200 visible source characters; VIP prompt limits match that bound.
VIP, early-bird and mega-watch candidates also preserve separately labeled
quoted context, with the outer original remaining the sole Reply target.
Other scraper callers keep their existing 200-character default. No extra
page visits, media inspection, scrolls or generations are added. The same
scan limits, profile allowlist, parent checks and publication rules remain.

2026-10-31, provider refusals are not Replies — Live verification caught a
provider's refusal boilerplate published as a Reply. Shared final validation now
rejects recognized self-referential refusal openings on Originals and Replies.
The Reply generator treats them as a decline before trimming or stripping
preambles, and checks again afterward. Refusals are skipped, never rewritten
into an opinion. Ordinary technical caveats, honest bot disclosures and source
text retain their existing checks. No bot restart or state edit accompanies this fix.

2026-10-31, faster watched-post response and one less sleeping hour — The
Operator requests immediate priority for newly seen watched originals and more
daytime Replies. Wake moves to 03:30 Toronto; midnight bedtime and the six daytime
breaks stay unchanged. This provides 19.5 scheduled active hours with ten-minute
breaks enabled. The previous 04:30 wake is superseded.

The watch now separates discovery, like/repost actions and Reply generation into
three dedicated scheduler workers. Latest polling defaults to 20 seconds and
reads the first viewport without extra scrolling; action and Reply dispatchers
check discovered work every two seconds. Every scraped viewport also offers
watched originals to a bounded in-memory handoff. The existing first-enable
boundary, root/author/age checks and permanent histories remain authoritative.
The queue keeps the newest 80 originals by default, never claims a Reply, and
needs no state migration. One Reply generation per dispatch selects the newest
eligible parent again after each call; a failed attempt backs off for a minute.
Action retries keep their existing backoffs and attempt four actions per dispatch.

Browser and send queues choose watched work first, other ready Replies second,
and routine reads/actions third, FIFO within each priority. They never interrupt
a browser transaction or an in-flight model call. An idle Reply-spacing wait can
yield its turn to an urgent sender, then re-read the ledger gap and keep its
finished draft. Sleep, required parent likes and final admission still apply.
Ordinary feed Reply batches finish both Home reads before generation; independent
watched-post work may begin while those reads continue. Full bounded feed scans
are preserved. Poll and dispatch intervals are not guaranteed publication latency.

Sol/xhigh and all language/content checks remain. Reposts still share the existing
profile ceiling, spacing and minimum-Original reservation; these can defer or
refuse a repost even when a like or Reply succeeds. No environment edit, live
bot start/restart, profile edit or production-state migration is included.

The Operator's later request for likability and good energy updates both Voice
files: warm enthusiasm, generous credit, playful observations that include the
author, and short lines that can stand alone. Match the person's mood; keep
facts honest and avoid forced agreement or requests for likes/follows.

The send queue rechecks parent admission before waiting, so a post another
worker already answered does not consume the next Reply gap.

English detection also recognizes sentence-final function words, common modals
and prepositions. English contractions and shared words such as on/me/son no
longer count as French on their own; French and mixed prose remain refused.

2026-10-26, engagement feedback and priority-watch repair — The Operator asks
for 700–1,400 daily Replies and better engagement, then explicitly asks to fix
the watched author's visits without likes, reposts or Replies. Targets are
advisory, never a requirement to fill weak Replies or a new cap. Daily Replies
remain uncapped. All Reply pipeline workers serialize their spacing wait and
submission through a separate send lock; Safari is free while they wait. The
write chokepoint still enforces admission, sleep, parent likes and permanent dedup.

The Account adds first-hour Latest searches without a popularity floor, covering
SI video, images, models, agents and builder workflows. Latest and Top share the
existing search-count budget; both Home feeds still finish discovery before
generation. Quoted text is labeled context and never replaces the target URL.
Feed author harvesting now requires niche relevance. Prompts carry the last 20
confirmed Replies to avoid repeated openings, with no invented video observations.

Watched sources use source validation rather than our Original-writing style
rules. A short English reaction or X's English language tag can resolve unknown
language; explicit French, content restrictions and respected-account checks
remain. This exemption never applies to our own outgoing text. Already-visible
reposts are remembered before source validation. The watch attempts at most eight
like/repost actions per pass and backs off refusals for five minutes; successful
actions for one hour. Its Reply budget remains two generations per pass.

The Account opts into `editorial.use_reply_route`: both Original drafting and
independent review use the configured Reply route (currently Codex Sol/xhigh),
without changing `.env`. Reposts leave room inside the existing profile ceiling
for the minimum Original target. The configured arXiv RSS host is trusted.

After confirmed Replies, passive receipt capture records an exact own status
URL when visible, never guesses. The CSV adds a tenth `published_url` column;
old headers are read positionally. A deterministic one-in-five sample keeps
three days of disposable outcome data. A read-only report every 20 minutes
visits at most 12 due own statuses, observes 1–3h and 24–36h counters with actual
ages, reports coverage, likes per 1,000 views, topic/source/freshness/hour/length
cohorts and separate follower change. Missing counters remain unknown; no causal
attribution or automatic winner claim. Analytics failure cannot hide a shipped
write or release its permanent claim. `profile_copy.txt` contains reviewable
profile copy only. No profile write, bot start/restart or state migration.

2026-10-26, natural Replies and generation reliability — The Operator asks for
more Replies, a more conversational voice, occasional smileys and sometimes
just a few words or one sentence. Both Voice files and Relation prompts allow
specific reactions and dry wit without a compulsory lesson or caveat. The
shared text generator varies delivery by parent: roughly 20% brief, 60% one
sentence and 20% up to two sentences; about one in six prompts permits a single
smiley when appropriate. These are drafting directions, never appended emoji
or mechanically shortened text. The main Reply routes see up to 1,200 source
characters. The Reply minimum is 8 characters instead of 25; generic applause,
emoji-only and unclear-language text still refuse. A narrow short-English
fallback recognizes clear reactions without weakening Original language checks.

Primary Codex calls receive at least `CODEX_MIN_TIMEOUT_SECONDS` (300 by
default), capped by the existing 360-second ceiling and next sleep/break.
Other providers and fallback deadlines keep their existing behavior. Drafting
calls explicitly disable built-in web search, shell tools and apps; the
research surface retains search. Structured CLI errors survive a timeout but
partial drafts never ship. Sol/xhigh, disabled fallback, uncapped daily Replies,
confirmed parent likes, spacing and permanent standalone dedup remain. No
environment edit, state migration or bot start accompanies this update.

2026-10-24, uncapped responses — The Operator requests unlimited Replies after
the shared 500-like threshold prevented most responses from 11:42 Toronto.
An admitted Reply's verified parent like is now exempt from that threshold.
The Reply chokepoint grants this permission only after admission, claim and
standalone-page verification, only for that parent and worker, and clears it
on success or error. All likes remain recorded. Background likes still stop
at the existing total-like threshold; no allowance is reset or increased for
them. Sleep, breaks, spacing, content checks and permanent one-Reply-per-original
dedup remain. A failed or unconfirmed parent like still stops the Reply.

The repost reader accepts legacy status-ID values of exactly `"confirmed"`
as permanent completed claims. It preserves them without inventing a URL or
timestamp; unknown strings or malformed structured records still refuse.
This repairs the compatibility error that halted the priority watch and
Originals. No production-state migration or environment edit is needed.

2026-10-24, fewer daytime breaks — The Operator requests less frequent breaks.
Keep `HOURLY_BREAK_MINUTES=10`, but schedule one break about every three waking
hours: six daily windows, in hours 07, 10, 13, 16, 19 and 22 Toronto time.
The start minute remains deterministic in 35–50 for the Account/date/hour,
shared by every worker and preserved across restarts. This supersedes the
plan with breaks in three of four hours. Midnight–04:30 sleep, publication limits, the
confirmed-like Reply prerequisite and all other admission checks remain.
No environment edit, restart or production-state migration accompanies this change.

2026-10-23, always like before replying — Every Reply must first confirm that
the verified parent's own like is visible on X. An existing like satisfies
the requirement without another click or like allowance. A new like uses
the shared write chokepoint (with the October 24 quota exception above); refusal, failure, uncertainty or
unreadable state stops the Reply before composition. The pre-submit Reply
claim is released so a later attempt remains possible. A historical cache
entry or a quoted post's like does not prove the parent is currently liked.
`REPLY_LIKE_PARENT_PROB` is accepted for old configuration compatibility but
has no effect. This supersedes probabilistic parent likes on every Reply
route, including the priority watch, without changing sleep, breaks, caps,
standalone admission or permanent dedup. No restart or environment edit.

2026-10-23, both feeds and the priority watch — Finish the configured For You
and Following reads before generating any Reply. A model quota failure on
the first feed must not skip discovery on the second. The Operator explicitly
authorizes likes, reposts and one Reply to new standalone originals by Elon
Musk. `auto_engage_handles = ["elonmusk"]` is the only repost exception;
the engine names no real account. A dedicated Latest search runs every minute
while active. First enable saves a boundary without replaying old posts;
subsequent passes inspect up to 20 posts from the past 24 hours, with at most
two Reply generations. Sleep, breaks, source/content checks and permanent
standalone Reply dedup still apply. Each action is attempted independently.

Reposts share the existing combined profile ceiling and spacing with Originals,
including pending editorial submissions. The browser verifies the exact
standalone author/status and uses only explicit repost controls, never undo.
`reposted_tweets.json` keeps process-locked permanent claims; uncertain writes
retain their claim and publication reservation across restarts. Only a proven
pre-submit failure releases one. `priority_watch_state.json` preserves the
first-enable boundaries. Unreadable guarded state refuses. Background likes
keep their daily threshold; required Reply-parent likes are exempt. No restart, environment
edit or production-state migration accompanies this change.

2026-10-23, The SI Maximalist — The Operator renames the Account to
`thesimaximalist`, retaining `TheAIShrink` in `previous_handles` and the
`theaishrink` folder/state namespace. Both Voice files describe a fictional
45-year-old SI expert: sharp, funny, warm, conversational, no therapist role.
She favors Elon Musk, X/Twitter, SpaceX and xAI, and calls Grok Imagine her
personal favorite. Taste never replaces supported facts or honest bot identity.
`publication_si_wording = true` extends SI / Super Intelligence to Originals,
before review and final publication checks; evidence and literal names remain.
Research keeps both vocabularies and explicitly includes the named Musk/X/
SpaceX ecosystem, without broadening to general politics, crypto or markets.

Both Home feeds are explicitly selected and verified. Collect each viewport
before scrolling; deduplicate by status ID and stop on a stalled feed. The
Account selects up to 20 scrolls and 160 collected posts per feed. Publication
counts and generation budgets stay bounded as before. `HOURLY_BREAK_MINUTES=10`
pauses new jobs, model requests and browser activity every three waking hours
under the October 24 amendment, starting at minute 35–50. The plan
is stable across workers and restarts and creates no state file. No restart,
profile edit or production-state migration accompanies the PR/merge/release.

2026-10-23, latest requests — Sleep from 00:00 through 04:29:59 Toronto time;
resume at 04:30. Midnight is the end of the preceding waking day for model
timeouts and Startup windows. Every Original and Reply is English, including
Replies to French parents and VIPs. The Account sets `english_only = true`:
generation always uses the English Voice, stale French language overrides
cannot win, and final content validation rejects French, mixed or unidentified
prose. Publication rules otherwise hold. The Operator requests a PR, merge,
push and release; this does not authorize a bot restart or state migration.

2026-10-23, Reply model switch — The Operator requests Codex Sol with xhigh
reasoning effort for responses. The local `.env` sets `AI_CLI` and
`REPLY_LLM_PROVIDER` to `codex`, both Reply model settings to `gpt-6.1-sol`,
and `CODEX_REASONING_EFFORT=xhigh`. The Account's Relation provider also uses
Codex. Originals keep their Ollama route. `LLM_DISABLE_FALLBACK=1` also
blocks the cached Codex quota lockout from silently using Ollama. Codex calls
pass the effort explicitly and allow the Reply routes' `/tmp` working directory
with a read-only sandbox. This setup requires a separately requested restart;
it does not start or restart the bot or migrate production state.

2026-10-23, later requests — The Operator requires one Reply per standalone
original permanently, no Replies to the Account's own originals or replies,
and no debate or follow-up exchanges. `standalone_replies_only = true` in the
Account disables debate, replyback and babysitter scheduling and their manual
entry points. Admission refuses known comments before generation, including
VIP sources; the browser verifies the actual parent, original status and own
author identities before the required parent like or Reply click. It clicks the
verified parent's button, never X's keyboard selection. Configured, runtime
and historical handles all count as our own. A visible earlier own Reply
also closes the thread and keeps its claim permanently. Replied IDs never expire or get evicted; claims and
updates use a process lock. Uncertain submissions stay claimed after restart;
only proven pre-submit failures release a claim. Unreadable history refuses.

The Operator also requests a sharper, emotionally engaging SI persona: a
fictional 45-year-old woman and mom of one with confident, playful adult
charm and deep technical perspective. Both Voice files and Relation prompts emphasize one useful
mechanism, implication, tradeoff or precise question, grounded in the supplied
evidence or stable knowledge. Kindness, factual support and honest bot identity
remain; no fabricated biography, tests, internals or claims of omniscience.
SI / Super Intelligence remains the publication vocabulary; research keeps both
AI and SI. No start, restart, environment edit or production-state migration.

2026-10-23 — On the hard-reset September 26 baseline, the Operator requests
SI wording in every Reply and both AI and SI vocabularies in research.
The Account enables `reply_si_wording`: standalone AI becomes SI, and
Artificial Intelligence becomes Super Intelligence in Reply prose. The shared
generator and pipeline apply it before length checks, and final Reply admission
enforces it again after formatting, before validating the text that ships.
Literal URLs, domains, email addresses, @handles, embedded names such as OpenAI
and French verb forms such as j'ai remain intact. Research retains AI and
Artificial Intelligence and adds SI, Super Intelligence, superintelligence and
ASI in queries and relevance filters. This terminology asserts no achieved
capability. Existing Account search counts, engagement filters, hours, pacing
and publication surfaces stay at the restored baseline. No start, restart,
environment edit or production-state migration accompanies this update.

[`docs/EDITORIAL_POLICY.md`](docs/EDITORIAL_POLICY.md) is the source of truth
(including the October 23–November 4 amendments) and supersedes older mandates. It encodes:

- Interactions active 04:30–23:30 America/Toronto (bedtime moved from midnight on 2026-11-24), with no daytime breaks for this Account; isolated video discovery/media may continue overnight.
- At least three sourced AI originals targeted a day, six planned, and eight
  combined profile publications at most, twenty minutes apart at least.
- Three trend slots (10:00, 13:00, 15:00) and a Startup post on every start
  in waking hours take their topic from rising AI posts on X, and their facts
  from a trusted article.
- Quotes, self-recycling and threads stay at zero. Reposts are limited to the
  explicitly watched author exception above, inside the same publication budget.
- Replies are uncapped in waking hours, paced and permanently deduplicated
  per standalone original. Self-replies and conversation follow-ups are disabled.
- Likes, follows, Reply spacing, Debate turns and the content checks carry
  the Operator's bounds (2026-09-25) in their `src/core/settings.py`
  declarations; `.env` and `account.toml` may only tighten them.
- Replies, likes and follows cover AI/SI only (2026-11-01). Research retains
  both vocabularies. Finance, crypto, general markets and unrelated space or
  social-platform topics are excluded, including posts by hand-picked authors.

A change that raises volume, restores a disabled surface or relaxes a check
needs an explicit operator request, and updates that policy file in the same
change. The same holds for the operator-owned guardrails: the Account's
Voice files (`accounts/<BOT_ACCOUNT>/voice_*.md`), which only the Operator
edits, `BLOCKLIST` in `src/core/config.py`, the restricted repost rule,
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
| Local Reply review: imported sources, question-first selection, guarded drafts and manual decisions, no-contact requests, local report; no publisher | `src/replies/review.py`, `src/guards/review_store.py`; `main.py --reply-review` |
| Account: handle, language, domain the prompts name, Slots and angles, feeds, Evergreen topics, trusted hosts, relevance filter, stricter limits; network handle lists, French-forced authors, added Blocked accounts, niche patterns, X searches (Trending posts' included); Relations (per-handle Reply prompt, provider or dossier) and the default VIP scan prompt | `accounts/<BOT_ACCOUNT>/account.toml`, loaded and checked at start by `src/core/account.py`; the Voice files and the Relations' prompts next to it |
| Originals: sources, evidence, draft, separate review, pending submissions in the ceiling and spacing | `src/editorial/editorial_bot.py` |
| Slot journal: the day's editorial state (day change, Attempts and feedback, Pending slot reserved, confirmed or released, closed Slots, used URLs, recent texts, the day's submissions and the latest); file and in-memory adapters | `src/editorial/slot_journal.py` |
| Draft and review limits, their JSON schemas and call profiles | `src/editorial/editorial_schemas.py` |
| Model calls: the Call surfaces, each with its model setting, provider setting and CLI options (`SURFACES`; callers name a surface, only a Relation's CLI overrides its provider), provider adapters, the one fallback ladder (no fallback unless `LLM_FALLBACK_CLI` names one; an unknown provider fails the call and runs nothing), the CLI model a model setting gives the provider called, timeouts, the answer read once in the profile's text or JSON mode, call profile (the label only names the call in logs), status (answered, failed, provider exhausted) and the provider and model that answered | `src/core/llm_client.py` |
| Trending posts for Trend slots and the Startup post: Top search, filters, ranking, prompt blocks | `src/editorial/trending.py` |
| Reply jobs: direct, feed sweep, early bird, mega watch, debate, replyback, babysit, notify, search | `src/replies/` |
| Reply prompts: Voice, recent confirmed text, hard rules, dossier, language, SKIP, failure and rate-limit outcomes (provider exhausted) | `src/replies/reply_generator.py` |
| Account's SI publication wording, applied before review and final validation; evidence and literal references preserved | `src/core/reply_wording.py` |
| Reply source: the candidates a job's declaration (oldest post, root posts only, expected author, niche, order) selects among its scraped posts, the niche filter, the fresh-and-rising order | `src/replies/reply_source.py` |
| Reply pipeline: admission before generation, set-aside posts, rate-limit stop, spacing wait, write, log after ship with the provider and model that wrote the Reply | `src/replies/reply_pipeline.py` |
| Account jobs: engage, follow engagers, followback, likes, pin, follower count, tracked accounts | `src/account/` |
| Follow run: one cycle's follows, Followed accounts skipped whatever the case, each handle tried once, no call past CAP_REACHED, bedtime and `StateUnreadable` raised, any other error one pick, counted and raised once the job saved its state; follow_engagers uses it | `src/account/follow_run.py` |
| Toronto clock, bedtime checks | `src/guards/active_hours.py` |
| Caps, pacing, anti-churn; the ledger facts the follow policy reads | `src/guards/action_guard.py` |
| Follow policy: handle, Blocked account, the account's relation it finds itself (Seed account, follower, Engager; a Stranger never), whitelist, caps, ceiling, quality gate, named Follow refusals, followed accounts and the other follow files | `src/guards/follow_policy.py` |
| Write ledger: today's counts, last write, last follow or unfollow; file and in-memory adapters | `src/guards/ledger.py` |
| Reply admission: Blocked account, own post, one Reply per post, Debate turn cap, spacing, final text, Respected account named | `src/guards/reply_admission.py` |
| Author, status ID and age read from a status URL; nested-reply filter for scraped tweets | `src/x/x_urls.py` |
| Replied store: permanent status-ID history with process-locked claims | `src/guards/replied_store.py` |
| Instagram leads for the video pipeline: creator Reels grids and keyword search read in the signed-in Safari session, audience floor and caption rule on the exact reel page | `src/video/instagram_browse.py`; capture in `src/video/native_source.py` |
| Priority watch: first-enable boundaries, Latest discovery and independent like/repost/Reply attempts | `src/replies/priority_watch.py` |
| Work priority: bounded viewport handoff and reentrant browser/send queues, watched work before ready Replies before routine work | `src/core/watch_discovery.py`, `src/core/work_priority.py` |
| Reply outcomes: exact own receipts, sampled public counters and advisory daily targets | `src/core/reply_feedback.py`, `src/x/reply_metrics.py` |
| Repost history: permanent claims and uncertain publication reservations; verified page controls | `src/guards/repost_store.py`, `src/x/repost_page.py` |
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

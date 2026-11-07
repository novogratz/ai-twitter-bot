# Verified SI news

The normal bot runs one hourly news job with `NEWS_ENABLED=1`, including public
discovery overnight. `NEWS_AUTO_PUBLISH=1` requires operator authorization. The
November 7 follow-up grants that authorization here: verified main picks publish
through the existing Safari session during active hours. The normal `bin/run.sh`
start picks up these settings; no separate service or manual draft copying is
needed. Code changes do not restart a running bot.

```dotenv
NEWS_ENABLED=1
NEWS_AUTO_PUBLISH=1
NEWS_MIN_SECONDS_BETWEEN_POSTS=7200
```

The Account [news.toml](../accounts/theaishrink/news.toml) is the configuration
example: RSS/HTML endpoints, public evidence hosts, queries, budgets, timeouts,
retries, thresholds and optional history paths. All 17 source endpoints were
fetched during implementation on November 7, 2026; feed endpoints returned
parseable RSS/Atom. Endpoint health is not a news-verification claim. Failures
remain visible in `status` and logs.

The single [news_prompt.md](../accounts/theaishrink/news_prompt.md) controls
discovery, verification, ranking, writing and independent review. Codex uses
the existing Reply model/login in isolated sessions; only discovery has public
search. Sources are untrusted data. Alternative model/source adapters implement
the small `call`, `discover` and `document` interfaces.

## Commands

```bash
uv run --with-requirements requirements-video.txt python bin/news.py --dry-run run
uv run --with-requirements requirements-video.txt python bin/news.py status
uv run --with-requirements requirements-video.txt python bin/news.py check-sources
uv run --with-requirements requirements-video.txt python bin/news.py import-history
# Prepare/review now while the bot runs; approved picks stay pending for its next hourly run:
uv run --with-requirements requirements-video.txt python bin/news.py --prepare-only run
# Manual draft-only run, with no X publication:
NEWS_AUTO_PUBLISH=0 uv run --with-requirements requirements-video.txt python bin/news.py run
uv run --with-requirements requirements-video.txt python bin/news.py ack DELIVERY_ID
```

`main.py --news ...` accepts the same commands. A manual real run respects
`NEWS_AUTO_PUBLISH` and cannot use Safari while another process owns the bot
lock. Normal starts register the hourly job; do not also run `serve`. For a
standalone draft-only installation, `NEWS_AUTO_PUBLISH=0 ... python bin/news.py
serve` runs one hourly scheduler. Intervals use `America/Toronto` with DST; UTC
search boundaries persist. Successful runs overlap the last 24 hours. Downtime
or partial coverage keeps the previous watermark to cover the missed interval.
Before the first complete new-worker run, the last dated, confirmed source post
in the legacy editorial journal also anchors catch-up. Pending submissions never
supply that date. This records a conservative migration boundary, not complete
historical search coverage; ordinary completed runs return to the overlapping
24-hour window. Preparation uses the same run lock, evidence checks and outbox;
it neither takes Safari from the running bot nor marks a pending draft delivered.

## Selection and delivery

Discover → fetch evidence → verify → deduplicate → rank → write → independently
check facts and weighted length → durable outbox → deliver/publish → receipt.
One exceptional story beats routine volume. Default thresholds are 85/100 for
the main pick and 90/100 for an optional different-story backup. No qualified
story means no destination message. There is no daily minimum or filler.

Verified main picks publish promptly when admission permits. Spacing, nighttime
and protected videos defer them; expired drafts never publish. The existing text
ceiling applies (seven locally, maximum eight), separately from video slots.
News defaults to a two-hour gap between news posts and protects thirty minutes
around video windows/successes. Active or uncertain video reservations defer
news. Video final admission also respects confirmed/uncertain news. Replies
retain existing pacing and priority. Backups are drafts, not automatic extra
public posts.

Each tweet has intentional blank lines and one fetched source link at the end.
Attribution and qualifiers are mandatory. Complete tweets use
`twitter-text-parser`, a Python port of the official conformance suite. X counts
URLs as 23 and weights Unicode/emoji; see
[X's character rules](https://docs.x.com/fundamentals/counting-characters).
Setuptools stays below 81 because the parser uses `pkg_resources` for its data.

SQLite permanently retains event/development IDs, canonical URLs, evidence,
decisions, deliveries and imported history. Semantic comparisons retrieve
relevant indexed records; this does not claim exhaustive knowledge of all past
posts. Existing tweet/editorial logs, news-watch JSON and configured JSON/JSONL
history/queues are imported where accessible. Missing files are marked missing;
corrupt accessible history stops the run. Video windows and available queue
reservations inform exact Toronto recommendations outside draft tweets.

Drafts/backups go to `state/<BOT_ACCOUNT>/news_inbox/<stable-id>.json`. `display`
contains the complete tweet and one date/recommendation line; `tweet` contains
only public text. `ack` records user acknowledgement. Optional draft webhooks
require `delivery_adapter="webhook"`, `NEWS_WEBHOOK_URL` and optionally
`NEWS_WEBHOOK_TOKEN` in the environment. Receivers must durably deduplicate
`Idempotency-Key` and return `{"id":"<same-id>","accepted":true}`. Retries
preserve ID and exact payload; exactly-once remote effects require that receiver
contract. There is no email adapter.

## Recovery and limits

`status` shows partial runs, missing history, usage, pending drafts and errors.
Requests have byte/time/retry limits and persistent cooldowns, including
Retry-After. Caching and per-run/day request/model budgets bound local work.
Actual observed tokens are retained, including a final-call overrun; unknown
dollar charges are never guessed. The next call stops at the token limit.

Before a Safari click, the outbox records `submitting`. Only a unique recent
own status with exact text and the observed source link yields `published`.
Ambiguous receipts become `publish_unknown`; crashes after claiming may leave
`submitting`. Neither retries automatically, and both block new news/video
sends. Inspect the actual account and reconcile the retained claim manually
using a verified receipt. Never reset/delete the database to retry a suspected
send. Local tests do not prove a live publication.

```bash
uv run --with-requirements requirements-video.txt python -m pytest tests/news -q
```

# Configuration

Every engine setting is declared once in `src/core/settings.py`, with its
type, default and bounds, and set in `.env`, which git does not track.
`.env.example` is the starting point for @thesimaximalist; its bounded settings
stay commented, at their default, so that an Account's `[limits]` holds.
What describes the Account rather than the engine (handle, language, Slots,
feeds, trusted hosts, relevance filter, network, niche and searches) lives in
`accounts/<BOT_ACCOUNT>/account.toml` ([Account](OPERATIONS.md#account)): its
`[limits]` may tighten an engine bound, never lift it, and `.env` wins over it.

The Account keeps `BOT_ACCOUNT=theaishrink` for its state namespace while its
handle is `thesimaximalist`; `previous_handles` includes `TheAIShrink`.
Its `[limits]` selects `FEED_SCROLL_PASSES=20`, `FEED_SWEEP_SCAN_LIMIT=160` and
`HOURLY_BREAK_MINUTES=0`: no daytime breaks, with sleep from midnight to 04:30
Toronto. The local `.env` also sets zero so its override cannot restore the old
ten-minute pauses. Other Accounts default to eight scrolls and no breaks.
Feed reads collect every viewport and stop after three with no new posts.
If explicitly enabled in another configuration, the legacy break setting controls
duration in six windows (hours 07, 10, 13, 16, 19 and 22); a repeatable account/day
plan starts each between minutes 35 and 50. Zero disables this entire plan.

The optional Account boolean `engagement_niche_only` defaults to false. The
live Account enables it: `niche.post` supplies AI/SI evidence and
`relevance.off_topic` rejects finance/crypto even alongside AI terms. Replies
check before generation and on the verified parent, likes read the actual
article before clicking, and watched reposts validate their source. Every
follow profile must match `niche.bio` without excluded terms, including seeds
and Engagers. Missing evidence refuses. The live profile, VIP-scan and pinned
lists and their `.env` overrides are empty; the Account's blocklist prevents
retired targets from being rediscovered or promoted.

The optional `auto_engage_handles` Account list defaults to empty. The live
Account sets only `elonmusk`, authorizing the priority watch's like, repost and
Reply attempts on new AI/SI standalone originals. Handles are validated, lowercased
and deduplicated. Polling defaults to 20 seconds (floor 20), a 24-hour
lookback (never longer), and 20 posts from the first viewport (maximum 40).
Separate action and Reply dispatchers check every two seconds (floor two), with
four like/repost attempts and one Reply generation per dispatch by default.
`PRIORITY_WATCH_QUEUE_LIMIT` bounds each disposable handoff/dispatch queue to 80
newest originals by default. A slow model call cannot block the polling worker.
First-enable timestamps survive restarts. Browser and send turns prioritize
watched work, then other ready Replies, then routine work; ongoing transactions
finish first. The existing activity, content and publication limits still apply.
Both Home reads finish before ordinary feed Reply generation; watched discoveries
can generate independently while feed discovery continues.


The optional `publication_si_wording` boolean defaults to false. The live
Account enables it for Originals as well as Replies: drafting, editorial
review and the final write use SI / Super Intelligence in publication prose.
Source evidence and literal references remain unchanged.

Every Reply now requires its verified parent to be visibly liked before
composition. Existing likes need no new click; failed or unconfirmed likes
stop the Reply. Required likes for verified, admitted Replies are exempt from
`LIKE_BOT_DAILY_CAP`, so it cannot become a daily Reply cap. All confirmed likes
remain counted in the ledger; background likes stop at the existing total-like
threshold. `REPLY_LIKE_PARENT_PROB` is retired:
old values are still accepted so existing `.env` files load, but cannot disable
this requirement. No environment change is needed to adopt the policy at restart.

The optional Account boolean `reply_si_wording` defaults to false. The live
Account sets it to true: Reply prose uses SI / Super Intelligence while research
retains AI and SI aliases in `[searches]`, `[niche]` and `[relevance]`. This
preference applies to Replies, including prepared replies and final admission.
It preserves literal references and source evidence; it is not a `.env` setting.

The live Account also sets `english_only = true` (default false for other
Accounts). All Originals and Replies use English, including those to French
parents. It overrides `CONTENT_LANG_PRIMARY`, `FR_FORCED_REPLY_HANDLES` and
per-job language selection, always uses `voice_en.md`, and checks the final
outgoing text on every publication surface. French, mixed or unidentified
prose is refused; literal URLs and @handles do not decide the language.
For Replies up to 80 characters, a narrow English-word fallback also recognizes
clear short reactions, including affectionate and technical vocabulary. Every
word must be recognized; this can also resolve the shared English/French `on`
marker, but never explicit French/mixed prose or unknown words. Generic applause
and emoji-only text remain refused.

The optional Account boolean `standalone_replies_only` defaults to false for
other Accounts; the live Account sets it to true. It disables debate, replyback
and babysitter jobs and refuses conversation continuations at admission and in
the browser. `.env`, including `ENABLE_DEBATES`, cannot override it. Changing
this operator-owned policy requires an explicit operator request.

`previous_handles` is an optional list of valid X handles without `@`. Together
with the Account handle and the runtime `BOT_HANDLE`, it protects all known own
identities from Replies. The former identity remains included so preserved URLs stay recognizable. This list does not rename the
profile or migrate state. Replied status IDs are retained permanently for all
Accounts, with no configurable eviction limit.

- `main.py` reads `.env` once at start. A variable already set in the
  process environment wins over `.env`.
- A key `settings.py` does not know, or a value its type rejects (a switch
  takes `0` or `1`, a number a number), stops the start with a message
  naming the key; `main.py --dry-run` stops on the same keys. Credentials
  the model CLIs read (`*_API_KEY`, `OLLAMA_HOST`, `OPENAI_*`,
  `ANTHROPIC_*`...) may sit in `.env` for those subprocesses.
- A value past its floor or ceiling is brought back to the bound and logged
  as a `[SETTINGS]` warning.
- **Any change to a setting takes effect at the next restart.** Nothing
  re-reads `.env` while the bot runs, `DRY_RUN` included.

The reference at the bottom of this page is generated from the declarations:
after adding or changing one, run
`uv run python bin/configuration_doc.py --write`. `tests/core/test_settings.py`
fails while it is stale, and on any key this page names that the engine does
not know.


The Account's optional `editorial.use_reply_route` selects REPLY rather than
ORIGINAL for both Original draft and review (default false). The live Account
sets it true. Optional `searches.latest` adds first-hour Latest discoveries to
the existing rotating search budget. `REPLY_DAILY_TARGET_MIN/MAX` are advisory
report values only; the live Account and local `.env` set 1500/1800. They change neither admission,
spacing, generation budgets nor the uncapped daily Reply policy.

The November 7 volume request retains
`MIN_SECONDS_BETWEEN_REPLIES=8` and `REPLY_JITTER_SECONDS=4` in the Account and
local `.env`, replacing the local 20/10 override. The engine floor stays eight.
Account and local `DIRECT_REPLY_MAX_PER_CYCLE=80` and
`FEED_SWEEP_MAX_REPLIES_PER_CYCLE=80` replace 40/40, and
`DIRECT_REPLY_QUERIES_PER_CYCLE=16` replaces twelve. These values persist every day.
`DIRECT_REPLY_PRIORITY_QUERIES_PER_CYCLE=4` reserves four grouped Latest searches
of `network.big_ai_hype` before ordinary buffered drafting. Returned authors must
match the queried group by status URL, be standalone AI/SI originals and be at
most 24 hours old (or the tighter configured source limit). These groups name
operator-designated major accounts, not observed follower counts.
`DIRECT_REPLY_LATEST_QUERIES_PER_CYCLE=4` reserves four ordinary first-hour Latest
searches; the remaining eight go to Top. Each pool rotates separately, missing
pool capacity can backfill from another pool, and the total stays bounded. A
cycle may finish its Reply budget before every ordinary query runs.
`REPLY_PRIORITIZE_LARGE_ACCOUNTS=1` places the configured group first in ordinary
buffered Reply ordering. Like preference then applies within each group, with
author variety and observed parent views ordering comparable candidates.
At the existing buffer limit, configured major authors are retained first, then
the newest source IDs within each group; the disabled default retains newest
sources alone. Rediscovery can tighten an earlier source expiry, never extend it.
Unknown views are not zero; only the exact parent's analytics can provide them.
Other Accounts default to no major-author searches or ordering preference.
`REPLY_PREFERRED_MIN_LIKES=3` prefers strictly more than two observed likes,
without excluding otherwise eligible lower-liked or unknown-count sources.
Routine Top queries and first-hour Latest queries have no popularity floors;
the separate high-traction Top queries retain their floors.
Discovery budgets and admission checks still apply. Browser and
model work add time beyond the required gap, so settings cannot promise volume.
Repeated watched-parent Reply attempts double `PRIORITY_WATCH_REPLY_RETRY_SECONDS`
up to `PRIORITY_WATCH_REPLY_RETRY_MAX_SECONDS` (default and ceiling 900 seconds,
floor 20), or the configured initial delay if longer. Rediscovery does
not reset this process-local backoff; pruning the parent removes it. New watched
parents and independent like/repost retries are unaffected.

`REPLY_VOLUME_BOOST_DATE` optionally doubles those three discovery/generation
budgets on one Toronto date, written as `YYYY-MM-DD`; blank disables it and an
invalid date refuses startup. The local setting is blank now that 16/80/80 is
the persistent Account baseline, avoiding a second doubling.
An explicitly configured date still expires at midnight without reloading
settings or changing the file.
Explicit manual `max_replies` arguments remain exact. This changes neither
spacing, admission, scheduler concurrency nor the advisory daily targets.
`main.py --dry-run` and the startup log expose the effective budgets. Loading
a newly selected date still requires the Operator's next explicit restart.

Video configuration lives in `accounts/<BOT_ACCOUNT>/video.toml`. The live
Account uses thirteen 90-minute slots from 05:00 through 23:00 Toronto,
`scheduled_daily_cap=13`, `startup_on_boot=true`, `preferred_age_hours=72` and
`max_age_hours=17520` (730 days). X is an enabled source alongside Instagram,
TikTok, RedNote and Bilibili, with observed source views limited to 50,000.
The startup request creates no Reply hold; publication still uses durable claims,
inspection, dedup and existing spacing. The [README](../README.md) links the
video pipeline guide and operating commands.

The live video configuration enables `auto_edit`, `bangers_only`,
`one_line_caption` and `adaptive_discovery`. It reads the account-local
`discovery_prompt_file`, `query_bank_file` and `discovery_memory_file` on research
passes; paths must resolve inside the Account folder. Source duration is bounded
by `source_max_duration_seconds=300`, the selected excerpt by `edit_max_seconds=120`.
`banger_min_score=88` controls the separate editorial rubric. The original raw
ranking retains its unknown components. `discovery_calls_per_hour=3` is shared
across sources and still subject to daily Codex/request budgets. Platform weights
are 40/30/10/4/5/7/4 for Instagram/Bilibili/TikTok/RedNote/X/YouTube/Douyin;
unavailable/cooling providers are skipped. `ready_reserve_min=3` warns below the
existing `buffer_target=16`; it never waives eligibility. Matching X copies use
`x_max_views=50000` and `x_reach_max_age_seconds=21600`. Exact X source metrics
retain the tighter one-hour check. These settings create no extra publisher.

## Policy ceilings

The current rules are in [EDITORIAL_POLICY.md](EDITORIAL_POLICY.md). These
hold whatever `.env` says:

| Rule | Where |
|---|---|
| Working hours 04:30–00:00 America/Toronto, DST aware | `active_hours.WAKE`, `BEDTIME`; `BOT_TIMEZONE` in `src/core/config.py` |
| `MIN_TARGET_POSTS_PER_DAY` 3, `TARGET_POSTS_PER_DAY` 6 | Constants in `src/core/config.py`; `config.post_targets()` caps both at the day's ceiling |
| `MAX_PROFILE_POSTS_PER_DAY` 8, combined ceiling of profile publications | Constant in `src/core/config.py`; the day's ceiling, `config.posts_ceiling()`, is the lower of it and `MAX_ORIGINALS_PER_DAY` |
| `MAX_ORIGINALS_PER_DAY` | Ceiling 8: the Account's `[limits]` or `.env` may lower it only |
| `MIN_SECONDS_BETWEEN_POSTS` | Floor 1200 (20 minutes): `.env` may lengthen it only |
| `POST_JITTER_SECONDS` | Floor 0: a negative jitter cannot shorten the spacing |
| Quotes | 0: `action_guard.can_post` refuses them |
| Reposts | Only exact standalone originals by `auto_engage_handles`; share the Originals' combined ceiling and spacing, including pending submissions |
| Replies per day | Unlimited: no setting caps them; `MIN_SECONDS_BETWEEN_REPLIES` (floor 8) plus `REPLY_JITTER_SECONDS` (floor 0) space them |
| `BLOCKLIST` | Constant in `src/core/config.py`, operator-managed |

The Debate turn, Reply spacing, like, follow, price-target and duplicate
settings, and `REPLY_MIN_CHARS`, carry the Operator's bounds of 2026-09-25
(issue #201), listed in
[EDITORIAL_POLICY.md](EDITORIAL_POLICY.md#bounds-on-volume-and-check-settings)
and in the Bounds column below. `BAN_SHORT_TERM_PRICE_TARGETS` has floor `1`:
`0` reads as `1`. `main.py --dry-run` prints each bounded setting's effective
value under `bounded_settings`, and the warnings under `settings_warnings`.

## Models and providers

The live operator configuration and `.env.example` (2026-11-01) set `AI_CLI=codex`,
`PROFILE_LLM_PROVIDER=codex`, `REPLY_LLM_PROVIDER=codex`, `REPLY_MODEL=gpt-6.1-sol`,
`PRIORITY_REPLY_MODEL=gpt-6.1-sol`, and `CODEX_REASONING_EFFORT=xhigh`.
`LLM_DISABLE_FALLBACK=1` keeps every route on Codex even during cached usage
lockouts: those calls return a rate-limit outcome without calling a different model. The engine defaults
below still apply to settings that the operator has not set.

- `AI_CLI` picks the primary provider, `codex` by default (also when blank);
  `PROFILE_LLM_PROVIDER` and `REPLY_LLM_PROVIDER` route the profile surfaces
  and the Replies, `codex` both; blank inherits `AI_CLI`. An unknown provider
  name fails every call it routes without running anything; the start logs it and `--dry-run`
  lists it under `unknown_llm_providers`.
- `LLM_DISABLE_FALLBACK` defaults to `1`. Enabling a fallback requires both
  `LLM_DISABLE_FALLBACK=0` and an explicit `LLM_FALLBACK_CLI` (`codex`, `gemini`
  or `ollama`). Unset means a failed call fails, Originals and Replies alike. Ignored,
  logged at start and listed by `--dry-run` under `ignored_llm_fallbacks`:
  `claude`, a CLI not installed, Ollama behind Ollama, or the primary itself
  without `LLM_FALLBACK_MODEL`. A fallback runs `LLM_FALLBACK_MODEL`, else
  `CODEX_FALLBACK_MODEL` or `GEMINI_FALLBACK_MODEL`.
- A Relation may override the provider with its installed CLI; the live
  Account has no Relation-specific providers. A codex primary
  under a cached usage lockout (`codex_lockout.json`) obeys the same explicit
  fallback settings as a newly failed call; it never selects Ollama implicitly.
- `CODEX_REASONING_EFFORT` sets `model_reasoning_effort` on every Codex
  invocation; blank keeps the CLI's own configured default. It does not
  change another provider or the operator's global Codex configuration.
- `CODEX_MIN_TIMEOUT_SECONDS` gives primary Codex calls a minimum of 300
  seconds by default, including Relations that requested 60 seconds. Set 0
  to keep caller/general deadlines. The primary ceiling remains 360 seconds;
  bedtime and breaks can shorten every call. Fallback budgets are unchanged.
  Codex emits JSON events; text drafting explicitly disables built-in web
  search, shell tools and apps, while the research route retains search.
- `NEWS_MODEL`, `REPLY_MODEL` and `PRIORITY_REPLY_MODEL` name the model of a
  CLI (codex, claude, gemini). Unset or blank, the call takes the default of
  the CLI it runs, from `MODEL_DEFAULTS` below. Ollama never reads them: it
  runs `EDITORIAL_OLLAMA_MODEL` for Originals and `OLLAMA_MODEL` for the
  rest, only when explicitly selected. `bin/run.sh` performs no model warm-up.
  Nor does OpenCode read these CLI model settings, nor a fallback.

## Retired keys

A key no code reads any more is not declared: a `.env` that still sets one
stops the start and names it. Delete the line. The few declared settings
that no longer have an effect are listed under
[No effect](#no-effect-remove-from-env) below. The lists of
keys retired by issues #107, #168 and #170, and the earlier configuration
tables, are in [HISTORY.md](HISTORY.md).

<!-- BEGIN settings reference: generated by bin/configuration_doc.py --write, do not edit -->

## Settings reference

Every setting `src/core/settings.py` declares, in declaration order. A value
past a bound is brought back to it and logged as a `[SETTINGS]` warning.

| Setting | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `BOT_ACCOUNT` | str | `theaishrink` |  | Account the bot runs: the folder accounts/<name>/ holding its account.toml. |
| `BOT_HANDLE` | str | blank |  | X handle the bot runs, without @; the Account's handle unless set. |
| `MAX_REPLIES_PER_CYCLE` | int | `5` |  | Replies one reply cycle may ship. |
| `AI_CLI` | str | `codex` |  | Primary LLM provider: codex by default; other providers require explicit configuration. |
| `NEWS_MODEL` | str | unset: `MODEL_DEFAULTS` |  | CLI model for Originals; unset or blank, the default of the CLI called (MODEL_DEFAULTS). |
| `REPLY_MODEL` | str | unset: `MODEL_DEFAULTS` |  | CLI model for Replies; unset or blank, the default of the CLI called (MODEL_DEFAULTS). |
| `PRIORITY_REPLY_MODEL` | str | unset: `MODEL_DEFAULTS` |  | CLI model for priority Replies; unset or blank, the default of the CLI called (MODEL_DEFAULTS). |
| `PROFILE_LLM_PROVIDER` | str | `codex` |  | Provider for profile surfaces; blank inherits AI_CLI. |
| `REPLY_LLM_PROVIDER` | str | `codex` |  | Provider for Replies; blank inherits AI_CLI. |
| `DRY_RUN` | 0 or 1 | `0` |  | 1 logs every write instead of doing it; config.dry_run() reads it at call time. |
| `VIDEO_ENABLED` | 0 or 1 | `0` |  | Opt into isolated licensed-video workers and replace the main editorial schedule; defaults off. |
| `VIDEO_LIVE` | 0 or 1 | `0` |  | Permit video API uploads/posts after explicit activation; DRY_RUN still overrides. Defaults off. |
| `VIDEO_CONFIG_FILE` | str | blank |  | Operator video TOML path; blank uses accounts/<BOT_ACCOUNT>/video.toml. |
| `VIDEO_CREDENTIALS_FILE` | str | blank |  | Private (mode 600) JSON credentials path for official X API user access; never a token value. |
| `NEWS_CONFIG_FILE` | str | blank |  | News worker TOML; blank uses the Account news.toml. NEWS_ENABLED adds it to normal bot startup. |
| `NEWS_WEBHOOK_URL` | str | blank |  | Optional HTTPS draft destination, used only when news delivery_adapter is webhook. |
| `NEWS_WEBHOOK_TOKEN` | str | blank |  | Optional bearer credential for the configured news draft webhook; never an X/email credential. |
| `NEWS_ENABLED` | 0 or 1 | `0` |  | Run hourly verified news discovery with the normal bot; independent of video mode. |
| `NEWS_AUTO_PUBLISH` | 0 or 1 | `0` |  | Explicit operator opt-in to publish verified main news picks through Safari. Backups remain drafts. |
| `NEWS_MIN_SECONDS_BETWEEN_POSTS` | int | `7200` | floor `1200` | Minimum gap between news publications, including uncertain attempts. |
| `MAX_ORIGINALS_PER_DAY` | int | `8` | floor `0`, ceiling `8` | Originals per Toronto day. |
| `MIN_SECONDS_BETWEEN_POSTS` | int | `1200` | floor `1200` | Minimum gap between two Profile publications. |
| `POST_JITTER_SECONDS` | int | `0` | floor `0` | Random delay added to the post spacing. |
| `MIN_SECONDS_BETWEEN_REPLIES` | int | `8` | floor `8` | Minimum gap between two Replies. |
| `REPLY_JITTER_SECONDS` | int | `7` | floor `0` | Random delay added to the Reply spacing. |
| `FOLLOW_WHITELIST_ONLY` | 0 or 1 | `1` |  | Follow only whitelisted accounts. |
| `FOLLOWBACK_BYPASS_WHITELIST` | 0 or 1 | `1` |  | Let Follow-backs past the whitelist. |
| `FOLLOW_ENFORCE_RATIO` | 0 or 1 | `0` |  | Keep following under FOLLOW_RATIO_CEILING x followers. |
| `FOLLOW_RATIO_CEILING` | finite float | `0.8` |  | Following-to-followers ratio when the ratio is enforced. |
| `FOLLOW_TOTAL_CAP` | int | `300` | floor `0`, ceiling `3500` | Accounts followed in total. |
| `FOLLOW_GROWTH_MODE` | 0 or 1 | `0` |  | Untie the following ceiling from the followers count. |
| `FOLLOW_LOW_PHASE_CEILING` | int | `150` |  | Following ceiling while followers are under FOLLOW_LOW_PHASE_FOLLOWERS. |
| `FOLLOW_LOW_PHASE_FOLLOWERS` | int | `300` |  | Followers count that ends the low phase. |
| `MIN_SECONDS_BETWEEN_FOLLOWS` | int | `600` |  | Minimum gap between two follows. |
| `FOLLOW_SPACING_JITTER_SECONDS` | int | `300` |  | Random delay added to the follow spacing. |
| `MAX_FOLLOWS_PER_DAY` | int | `20` | floor `0`, ceiling `20` | Follows per day. |
| `CHURN_COOLDOWN_DAYS` | int | `30` |  | Days before an account followed or unfollowed may be touched again. |
| `FOLLOW_ACTION_JITTER_SECONDS` | int | `45` |  | Random pause around a follow action. |
| `BAN_SHORT_TERM_PRICE_TARGETS` | 0 or 1 | `1` | floor `1` | Refuse text carrying a short-term price target; always on. |
| `ENABLE_REPLY_SEARCH` | 0 or 1 | `0` |  | Schedule the search reply job (main.py, src/replies/reply_bot.py). |
| `CONTENT_LANG_PRIMARY` | str | `en` |  | Primary content language, en or fr (content_guard, editorial_bot); the Account's language unless set. |
| `DEBATE_MAX_TURNS_PER_AUTHOR_PER_DAY` | int | `4` | floor `0`, ceiling `4` | Debate turns per Engager per Toronto day. |
| `DUP_JACCARD_THRESHOLD` | finite float | `0.45` | ceiling `0.45` | Content-word Jaccard that makes an Original a duplicate. |
| `DUP_CONTAINMENT_THRESHOLD` | finite float | `0.6` | ceiling `0.6` | Content-word containment that makes an Original a duplicate. |
| `DUP_SHARED_BIGRAMS` | int | `3` | floor `1`, ceiling `3` | Shared content bigrams that make an Original a duplicate. |
| `DUP_TOPIC_WINDOW_HOURS` | finite float | `24.0` | floor `24.0` | Hours a post counts for the same-story check. |
| `DUP_TOPIC_SHARED_WORDS` | int | `3` | floor `0`, ceiling `3` | Content words shared with a same-entity post that make a same story. |
| `DUP_TEXT_WINDOW_HOURS` | finite float | `48.0` | floor `48.0` | Hours a post counts for the text-similarity checks. |
| `REPLY_MIN_CHARS` | int | `8` | floor `8` | Shortest Reply content_guard accepts; generic applause is still refused. |
| `RATIONED_SHAPE_WINDOW_HOURS` | int | `6` |  | Hours a rationed opener shape blocks its reuse. |
| `FOLLOWING_COUNT_OVERRIDE` | str | unset |  | Following count the ceiling uses instead of following_count.json; digits only. |
| `FOLLOW_MIN_FOLLOWERS` | int | `2000` |  | Followers a non-Engager needs to pass the follow quality gate. |
| `FOLLOW_REQUIRE_ENGLISH` | 0 or 1 | `1` |  | Refuse to follow a profile that does not read English. |
| `FOLLOW_REQUIRE_NICHE` | 0 or 1 | `1` |  | Refuse to follow a non-Engager whose bio is off-niche. |
| `HUMAN_TYPO_HANDLES` | str | blank |  | Comma-separated handles whose Replies get a human typo. |
| `BLANK_GRACE_AFTER_RESTART_SECONDS` | int | `120` |  | Seconds after a Safari restart when blank pages do not count. |
| `PROFILE_VISIT_ALLOWLIST` | str | blank |  | Comma-separated profiles the scraper may visit, besides our own; the Account's network.profile_visits unless set. |
| `NOTIFY_LIKE_REPLIES_COUNT` | int | `3` |  | Replies under our latest post the notify job likes. |
| `OLLAMA_MODEL` | str | `qwen3.6:35b-a3b` |  | Model used only when Ollama is explicitly selected and a call profile names none. |
| `OLLAMA_BASE_URL` | str | `http://localhost:11434` |  | HTTP endpoint used only when Ollama is explicitly selected. |
| `OLLAMA_NUM_CTX` | int | `32768` |  | Ollama context window, in tokens. |
| `OLLAMA_NUM_PREDICT` | int | `1800` |  | Tokens Ollama may generate per call. |
| `LLM_TIMEOUT_SECONDS` | int | `180` |  | Default model-call timeout, and Ollama's floor. |
| `LLM_FALLBACK_CLI` | str | blank |  | Fallback provider: codex, gemini or ollama; blank means none. |
| `LLM_DISABLE_FALLBACK` | 0 or 1 | `1` |  | 1 turns the fallback off whatever LLM_FALLBACK_CLI says; disabled by default. |
| `CODEX_REASONING_EFFORT` | str | blank |  | Codex reasoning effort (for example xhigh); blank keeps the CLI's configured default. |
| `CODEX_MIN_TIMEOUT_SECONDS` | int | `300` | floor `0`, ceiling `360` | Minimum primary Codex call budget, still cut short by sleep or breaks; 0 keeps the caller's timeout. |
| `LLM_FALLBACK_MODEL` | str | blank |  | Model of every fallback call; blank, the fallback CLI's own below. |
| `CODEX_FALLBACK_MODEL` | str | `gpt-5.4-mini` |  | Codex model as the fallback; blank means this default. |
| `GEMINI_FALLBACK_MODEL` | str | `gemini-2.0-flash` |  | Gemini model as the fallback; blank means this default. |
| `FR_FORCED_REPLY_HANDLES` | str | blank |  | Comma-separated handles whose posts always get French Replies; the Account's network.fr_forced_reply unless set. |
| `EDITORIAL_OLLAMA_MODEL` | str | `gemma4:31b` |  | Ollama model that drafts and reviews Originals. |
| `EDITORIAL_LLM_TIMEOUT_SECONDS` | int | `300` |  | Minimum timeout of an editorial model call. |
| `DIRECT_REPLY_MAX_AGE_MINUTES` | int | `7200` |  | Oldest post the search and feed-sweep Replies answer. |
| `VIP_SCAN_HANDLES` | str | blank |  | Comma-separated accounts the direct_reply VIP scan answers; the Account's network.vip_scan unless set. |
| `DIRECT_REPLY_MAX_PER_CYCLE` | int | `3` | floor `0` | Replies one direct_reply cycle may ship; zero disables its scheduled generation. |
| `DIRECT_REPLY_QUERIES_PER_CYCLE` | int | `8` | floor `1` | Search queries one direct_reply cycle scrapes. |
| `DIRECT_REPLY_PRIORITY_QUERIES_PER_CYCLE` | int | `0` | floor `0`, ceiling `16` | Rotating Latest searches of the Account's big_ai_hype authors within the total search budget; zero disables this lane. |
| `DIRECT_REPLY_LATEST_QUERIES_PER_CYCLE` | int | `4` | floor `0` | First-hour Latest searches reserved within the total search budget after priority-author searches; remaining capacity goes to Top, with bounded backfill. |
| `REPLY_PRIORITIZE_LARGE_ACCOUNTS` | 0 or 1 | `0` | floor `0` | Prefer the Account's configured big_ai_hype authors in ordinary buffered Replies, then like tiers, author variety and observed post views; no follower-count or eligibility claim. |
| `REPLY_VOLUME_BOOST_DATE` | YYYY-MM-DD date or blank | blank |  | Toronto date (YYYY-MM-DD) on which search, direct-cycle and per-feed Reply budgets double; blank disables it. Automatically expires at midnight; never changes pacing or admission. |
| `REPLY_DAILY_TARGET_MIN` | int | `0` | floor `0` | Advisory daily Reply target; never changes admission or pacing. |
| `REPLY_DAILY_TARGET_MAX` | int | `0` | floor `0` | Upper advisory daily Reply target; neither a cap nor a quota to fill. |
| `REPLY_CANDIDATE_BUFFER_LIMIT` | int | `400` | floor `1`, ceiling `1000` | Unprocessed source posts retained per search/feed lane in memory; no posting claims. |
| `REPLY_CANDIDATE_BUFFER_TTL_SECONDS` | int | `1800` | floor `60`, ceiling `3600` | Maximum time an unused source stays buffered; source freshness may expire sooner. |
| `REPLY_RECENT_MEMORY_COUNT` | int | `100` | floor `20`, ceiling `200` | Confirmed Replies checked for repeated wording; prompt includes a compact older-pattern summary. |
| `REPLY_PREFERRED_MIN_LIKES` | int | `2` | floor `0`, ceiling `1000` | Prefer candidates with at least this many observed likes; never an eligibility floor. Zero disables the preference. |
| `ENABLE_DEBATES` | 0 or 1 | `1` |  | Let the debate job answer mentions; read at each cycle. |
| `DEBATE_MAX_PER_CYCLE` | int | `3` |  | Debate Replies one debate cycle may ship. |
| `DEBATE_MAX_AGE_HOURS` | finite float | `24.0` |  | Oldest mention the debate job answers. |
| `BABYSIT_WINDOW_MINUTES` | finite float | `60.0` |  | Age of the latest post under which the babysitter sweeps replybacks. |
| `FEED_SWEEP_SCAN_LIMIT` | int | `80` | floor `1` | Posts the feed sweep scrapes per feed. |
| `FEED_SCROLL_PASSES` | int | `8` | floor `1`, ceiling `40` | Maximum scrolls per verified Home feed; collect each viewport before scrolling. |
| `HOURLY_BREAK_MINUTES` | int | `0` | floor `0`, ceiling `10` | Scheduled break length every three waking hours; 0 disables breaks. |
| `PRIORITY_WATCH_INTERVAL_SECONDS` | int | `20` | floor `20` | Poll watched authors independently of generation; running browser transactions may delay a poll. |
| `PRIORITY_WATCH_DISPATCH_SECONDS` | int | `2` | floor `2` | Check discovered watched posts for independent action and Reply work. |
| `PRIORITY_WATCH_QUEUE_LIMIT` | int | `80` | floor `1`, ceiling `200` | Maximum discovered watched originals retained in process memory, newest first. |
| `PRIORITY_WATCH_ACTIONS_PER_CYCLE` | int | `4` | floor `1`, ceiling `8` | Maximum independent like/repost attempts per watch action dispatch. |
| `PRIORITY_WATCH_REPLY_RETRY_SECONDS` | int | `60` | floor `20` | Initial watched Reply retry delay; repeated attempts double to the configured maximum or this value if longer. Permanent claims still govern admission. |
| `PRIORITY_WATCH_REPLY_RETRY_MAX_SECONDS` | int | `900` | floor `20`, ceiling `900` | Maximum repeated watched Reply cooldown; never shortens the initial retry delay. |
| `PRIORITY_WATCH_MAX_AGE_HOURS` | int | `24` | floor `1`, ceiling `24` | Maximum age of new watched originals; never before the watch was first enabled. |
| `PRIORITY_WATCH_SCAN_LIMIT` | int | `20` | floor `1`, ceiling `40` | Recent standalone originals collected per watched handle. |
| `PRIORITY_WATCH_MAX_REPLIES` | int | `1` | floor `1`, ceiling `2` | Maximum Reply generations per dispatch; one selects the newest parent again after each generation. |
| `FEED_SWEEP_MAX_REPLIES_PER_CYCLE` | int | `8` | floor `0` | Reply generations one feed sweep may run per feed; zero disables generation. |
| `FEED_SWEEP_HARVEST_MIN_LIKES` | int | `100` |  | Likes that add a feed post's author to dynamic_accounts.json. |
| `PINNED_TRACKED_HANDLES` | str | blank |  | Comma-separated handles the curator always tracks first (account_curator); the Account's network.pinned_tracked unless set. |
| `CURATOR_WINDOW_DAYS` | int | `14` |  | Days of engagement log the curator scores. |
| `CURATOR_TRACKED_MAX` | int | `40` |  | Earned accounts the curator tracks, pinned ones aside. |
| `CURATOR_MIN_ENGAGEMENTS` | int | `3` |  | On-lane engagements an author needs to be tracked. |
| `CURATOR_DISCOVERED_PER_DAY` | int | `3` |  | Accounts the curator may add to the whitelist discovered tier per day. |
| `CURATOR_DISCOVERED_MAX` | int | `50` |  | Accounts the whitelist discovered tier holds at most. |
| `CURATOR_PROMOTE_MIN_ENGAGEMENTS` | int | `5` |  | On-lane engagements an author needs to be promoted to the whitelist. |
| `PIN_MIN_LIKES` | int | `2` |  | Likes an own post needs before pin_job may pin it. |
| `PIN_MAX_AGE_DAYS` | int | `7` |  | Days after which a pin no longer defends its slot with the 1.3x rule. |
| `LIKE_TOP_TAB_PROBABILITY` | finite float | `0.55` |  | Probability like_job searches the Top tab instead of Live. |
| `LIKE_BOT_PER_CYCLE` | int | `10` | floor `0`, ceiling `10` | Search posts like_job hands to like_tweet per cycle. |
| `LIKE_BOT_DAILY_CAP` | int | `500` | floor `0`, ceiling `500` | Daily background-like threshold; required Reply-parent likes are exempt. like_job also counts UNCONFIRMED clicks. |
| `LIKE_BOT_CYCLE_SECONDS` | finite float | `30.0` |  | Seconds after taking the Safari lock past which like_job starts no like. |
| `FOLLOWBACK_CAP` | int | `8` | floor `0`, ceiling `8` | Follow-back attempts per followback_job cycle. |
| `ENABLE_FOLLOW_ENGAGERS` | 0 or 1 | `1` |  | Run follow_engagers_job. |
| `FOLLOW_ENGAGERS_PER_DAY` | int | `10` | floor `0`, ceiling `10` | Engagers follow_engagers_job follows per Toronto day. |
| `FOLLOW_ENGAGERS_PER_CYCLE` | int | `2` | floor `0`, ceiling `2` | Engagers follow_engagers_job follows per cycle. |

### `MODEL_DEFAULTS`: the model of a CLI when its setting is unset

| Setting | claude | codex | gemini |
|---|---|---|---|
| `NEWS_MODEL` | `claude-opus-4-8` | `gpt-5.4-mini` | `gemini-2.0-flash` |
| `REPLY_MODEL` | `claude-haiku-4-5-20251001` | `gpt-5.4-mini` | `gemini-1.5-flash` |
| `PRIORITY_REPLY_MODEL` | `claude-haiku-4-5-20251001` | `gpt-5.4-mini` | `gemini-2.0-flash` |

### No effect: remove from `.env`

No code reads these any more. They stay declared so a `.env` that still
sets them starts; delete them from it.

| Setting | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `REPLY_LIKE_PARENT_PROB` | finite float | `0.12` |  | No effect: remove it from .env. |
| `OPENCODE_FALLBACK_MODEL` | str | `opencode/big-pickle` |  | No effect: remove it from .env. |
| `BESTIE_HANDLE` | str | blank |  | No effect: remove it from .env. |
| `DIRECT_REPLY_MAX_EN_PER_CYCLE` | int | `9999` |  | No effect: remove it from .env. |
| `DIRECT_REPLY_FEED_SCAN_LIMIT` | int | `150` |  | No effect: remove it from .env. |
| `DIRECT_REPLY_PROFILE_SCAN_LIMIT` | int | `25` |  | No effect: remove it from .env. |
| `DIRECT_REPLY_HOT_QUERY_LIMIT` | int | `20` |  | No effect: remove it from .env. |
| `DIRECT_REPLY_LIVE_QUERY_LIMIT` | int | `20` |  | No effect: remove it from .env. |

### Keys the shell scripts read

Not read by the engine: these scripts read them after sourcing `.env`.

| Key | Read by |
|---|---|
| `CODEX_BIN` | `operator_cycle.sh` |
| `ENABLE_AI_MAINTENANCE` | `operator_cycle.sh` |
| `ENABLE_CODEX_OPERATOR` | `operator_cycle.sh` |
| `LLM_MAX_CALLS_PER_DAY` | `operator_cycle.sh`, `bot_watchdog.sh` |
| `LLM_MAX_CALLS_PER_HOUR` | `operator_cycle.sh`, `bot_watchdog.sh` |
| `LLM_MIN_SECONDS_BETWEEN_CALLS` | `operator_cycle.sh`, `bot_watchdog.sh` |
| `OPERATOR_MODEL` | `operator_cycle.sh` |
| `QUOTE_MODEL` | `operator_cycle.sh`, `bot_watchdog.sh` |
| `ROAST_MODEL` | `operator_cycle.sh`, `bot_watchdog.sh` |

<!-- END settings reference -->

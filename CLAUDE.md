# CLAUDE.md

Project context for **Claude Code** sessions. Mirror of [`CODEX.md`](CODEX.md). Use whichever CLI you have authenticated.

> **You'll hate me until I'm right.**

> **Mandate 2026-06-05 PM (CURRENT — MONETIZATION SPEC, supersedes 2026-06-04):**
> Goal: grow @TheAIShrink into a focused, SPONSORABLE persona account
> (subscriptions + sponsorships; ad revenue is a bonus). Baseline: ~1.3K
> followers / ~4.7K following (bad ratio), repost-heavy timeline, links in
> posts — all three suppress reach and kill sponsor appeal.
>
> **Persona (do not drift):** the deadpan AI therapist for traders/investors —
> market trauma, portfolio anxiety, crypto fear, AI hype. Wry, calm, slightly
> clinical. 100% finance/markets/AI lane. NO space content, NO off-topic.
>
> **Hard don'ts (ENFORCED IN CODE at the chokepoints):**
> - ❌ external links in posts/quotes → `_strip_post_urls` strips them
>   (link-in-first-reply is the sanctioned pattern)
> - ❌ hashtags anywhere → stripped in `_scrub_metadata_leaks`
> - ❌ off-topic quotes/reposts → space keywords REMOVED from `_is_on_niche`
> - ❌ mass-follow → `ENABLE_FOLLOW_BLAST=0`, `MAX_FOLLOWS_PER_DAY=10`
>
> **Content strategy:** original-first (≥80%): 3–6 originals/day across US
> market hours, 80-min+jitter spacing, no bursts (`MAX_ORIGINALS_PER_DAY=6`).
> Quotes ≤6/day, ALWAYS with a therapeutic-angle take. Bare retweets OFF
> (`MAX_RETWEETS_PER_DAY=0`). Replies genuine not spam: ≤100/day, 90s+jitter
> spacing, mid-size finance/AI accounts in-voice.
>
> **Account hygiene:** ratio repair via gradual unfollows — `MAX_UNFOLLOWS_PER_DAY=300`,
> 20/cycle ≈ ≤50/hr randomized, tier1/tier2 + 30d-churn protected. Target:
> following < followers.
>
> **Human-in-the-loop:** `REVIEW_MODE=1` routes every post/quote into
> `review_queue.json` instead of publishing; the `/approve` skill ships them.
> Default OFF (operator judged the voice dialed in 2026-06-05).
>
> **Monetization roadmap:** 3–5K followers → media kit + sponsor outreach
> (trading apps, brokers, AI tools); 5–10K → X Subscriptions ("exclusive
> therapy sessions"); ongoing → newsletter funnel. Engagement rate >2–3%
> matters more than raw counts.
>
> **ARCHITECTURE MAPPING (spec → this codebase):** the spec's tweepy/X-API
> modules map onto the EXISTING Safari+AppleScript stack — no paid X API tier,
> no API keys. `content_gen`→generation bots + Claude Code CLI (NOT the
> Anthropic SDK — operator: "we use Claude Code CLI as before", `AI_CLI=claude`,
> no rate limits so Claude is now PRIMARY with ollama fallback);
> `poster`→`twitter_client` chokepoints; `scheduler`→APScheduler in `main.py`;
> `hygiene`→`smart_unfollow_bot`; `analytics`→`performance.py` +
> `engine_health_bot` + `analyzer_bot`; `review_queue`→REVIEW_MODE +
> `/approve`; SQLite→the existing JSON state files.

> **Mandate 2026-06-04 (superseded by 2026-06-05 PM above — rebrand → "The AI Therapist" @TheAIShrink):**
> Persona modeled on **@TheBTCTherapist** (supportive coach), adapted to AI. Bio:
> "Treating market trauma. AI-powered portfolio therapy. Follow the signal. Heal
> the fear." **Warm, reassuring, POSITIVE** — name the fear (layoffs, AI trauma,
> failed AI bets, drawdowns, crypto crashes), validate it, then HEAL it (reassure
> + signal + hope; calm > clever, hope not hype). Scope: AI + the human side
> (jobs/fear) / markets-portfolios-AI-stocks / Bitcoin-crypto (supportive HODL
> coach). Formats: JUST IN, therapist one-liner, validation+reassurance, quote
> reaction. **Repost ALL of @TheBTCTherapist** (`MUST_REPOST_HANDLES` in
> retweet_bot, no scoring gate, ≤48h). English standalone; replies match parent.
> Voice/identity in `core_identity.md` + `lang_mode`. BOT_HANDLE=TheAIShrink.
>
> **Mandate 2026-06-03 (superseded — "The AI Decoder"):** AI-ONLY, English.
> The account is now a pure AI account. ALL content is about AI: labs/models/agents,
> compute/GPU/datacenters/AI-power, embodied AI (humanoid robots), and the MONEY angle on AI
> (Nvidia/Palantir/AI-capex, winners/losers, the bubble debate). NO standalone space, NO generic
> markets/crypto except through the AI lens. Standalone content in ENGLISH; replies match the
> parent's language. Lead with the take (opinion/contrarian angle), bury the news inside. Go hard
> on replies + retweets/quotes of viral AI posts ≤48h old. Growth mode on (`ENABLE_FOLLOW_BLAST=1`,
> `FOLLOW_ENFORCE_RATIO=0`). Discovery (replies/retweets/quotes/follows) is AI-only. The 48h
> repost-freshness rule + no-near-term-price-target validator stay. Goal: 10k followers fast.
>
> **Mandate 2026-06-02 (superseded by the line above):** Full revert to **French**.
> Brand = 🚀 The AI & Space Decoder ⚡, 3 pillars (AI / Space / Investment) unchanged.
> **All standalone content + all quote-repost commentary generate in FRENCH** (native, not
> translated). **Replies match the parent post's language** — English replies to English
> accounts/text, French otherwise (model detect-and-match; default FR only on low-confidence
> + FR-leaning). Theses are **multi-year** — short-term price targets (price + near-term
> timeframe) are banned and rejected pre-publish. Specialty = **Bourse (broad — indices,
> macro, earnings, dividends, crypto-as-asset, not just AI/space stocks) + IA + Spatial**;
> every post/quote/reply must land a precise, factual, non-consensus point ("sharpest in
> the room"). Follow policy is **hybrid** (operator choice 2026-06-02): we DO follow new
> French accounts for growth, but while following is over the ceiling
> (**following < 0.8×followers**) a follow is allowed only on a **net-negative day**
> (today's follows < today's unfollows), so the ratio heals daily; `follow_blast` mass-follow
> stays off (`ENABLE_FOLLOW_BLAST=0`). Quote-reposts are the **highest-ROI surface** — run hot
> (`MAX_QUOTE_REPOSTS_PER_DAY=18`, 12-min spacing). News/articles are de-duped on disk with
> canonical URLs (`posted_news_urls.json`); the bot carries a recent-posts **memory**
> (`src/bot_memory.py`, injected via `lang_mode`) to call back to past theses when it adds
> value. Replies are the primary growth lever. Branding/visual identity, the
> AI+Space+Stocks theme, and the Safari+APScheduler architecture are OUT OF SCOPE — unchanged.
>
> NOTE: this bot is **Safari + AppleScript driven (no X API)** — "API rate-limit / 429 backoff"
> from the revision spec maps to Safari **write-pacing** (per-action daily caps + jittered
> spacing + no bursts), same intent, different mechanism.

> **Mandate 2026-05-29 (superseded by 2026-06-02 above, kept for context):** Brand = 🚀 The AI & Space Decoder ⚡. 3 pillars: **AI** (labs, models, GPU infra, robotics, agentic), **Space** (SpaceX, Rocket Lab, NASA, satellites, space stocks), **Investment** (AI stocks, space stocks, Bitcoin/crypto as asset class, tech earnings). Goal = 20k followers. Be the best quant analyst AND funniest account on X.

### 2026-06-06 PM — engine-health clamps baseline by current cap

PR #6 silenced the false `retweet` "collapse" alerts when `MAX_RETWEETS_PER_DAY=0`.
But the SAME class of false positive kept firing for surfaces that were
**capped but not zeroed**: `hotake` ran at 2/day (its full quota under the
monetization mandate) and the watchdog compared it to a ~19/by-this-hour 7-day
baseline built from pre-mandate days when the cap was 8 → `2/19 = 11%`, under
the 40% floor → "hotake collapsed" alert every cycle, burning self-heal
cooldowns on a surface that was doing exactly what it was told.

Fix: `_daily_cap_for(kind)` returns the smallest positive cap that governs the
surface (or `None` if no cap is set); `run_engine_health_cycle` clamps
`baseline = min(baseline, cap)` before the ratio check. A surface running at
or above its current cap can never trip the alert against an unreachable
historical baseline. New guard test `test_engine_health_clamps_baseline_by_cap`
pins the contract (cap=2, baseline=20 → no alert when today=2).

Lesson: the watchdog's baseline is only meaningful relative to today's cap.
When operator policy moves the ceiling, the baseline has to move with it —
otherwise every cap reduction looks like a regression.

### 2026-06-06 — engine-health ignores deliberately disabled surfaces

The 2026-06-05 PM monetization mandate set `MAX_RETWEETS_PER_DAY=0` (bare
retweets off). But `engine_health_bot` still compared today's forced-zero
against a 7-day baseline that included pre-mandate retweet activity
(e.g. 152 on 2026-06-05) → it fired "retweet collapsed: 0 today vs ~20 by
this hour over the last 7 days (0%)" every cycle, which kept tripping the
self-heal launcher and burning headless-Claude emergency runs on a surface
that was *intentionally* turned off. Fix: `_is_surface_disabled(kind)` skips
any watched type whose governing env-var cap(s) are all explicitly 0
(`_CAP_ENVS` maps each surface to its cap names — `quote` has two and is
only "disabled" when BOTH are zero). Read at call time so a live cap edit
takes effect without restart. Three new guard tests pin the contract: alert
suppressed when off, alert still fires for on-but-flatlined, and `quote`
stays watched if either of its two caps is positive.

Lesson: a real collapse and a deliberately-disabled surface both bottom out
at 0. The watchdog has to know which one is which — operator intent lives
in the cap, not the count.

### 2026-06-05 engine-collapse fixes (post-mortem)

Engagement log showed retweets 140/day→0 (Jun 3) and replies 397→42/day (Jun 4).
Two one-line root causes, both fixed:

1. **Dropped scrape timestamps** — `_scrape_tweets_from_page` extracted
   `<time datetime>` in JS but the Python mapping dropped the field → every
   candidate had unknown age → the hard 48h gate skipped 100% of feed/search
   candidates. The mapping now carries `timestamp`; the 48h rule is untouched.
2. **Eaten reply JSON** — `unwrap_text`: a single-line ollama JSON array hit
   `_unwrap_ndjson`, which returned `""` for non-dict events → every
   REPLY_SEARCH cycle died holding valid replies. `structured_output=True`
   callers now get the verbatim array before the NDJSON unwrapper runs.

Lesson: when a surface flatlines, check `engagement_log.csv` daily counts per
action type FIRST — the collapse was invisible in bot.log noise.

### 2026-06-05 PM — learning loop + throughput (PR #5)

- **Per-post metrics scraper rebuilt** — `performance.scrape_own_metrics` had
  returned 0 tweets since ~May 11 (DOM drift + no Safari lock): the pattern-ROI
  bandit and analyzer flew blind for 3+ weeks. Now rides the shared
  `scrape_profile_tweets` pipeline; the shared scraper JS also extracts VIEWS
  (analytics-link aria-label). Live-verified same day.
- **GIF A/B tagging** — GIF posts/quotes log to engagement_log with
  `source=GIF/<query>` (and `action_type=quote_gif`) so the analyzer can
  compare GIF vs text-only and rank memes by performance.
- **Off-mandate scan targets pruned** — ~30 space/legacy handles (esa, CNES,
  ArianeGroup, RocketLab, ChrisHadfield, nextspaceflight…) removed from
  early_bird/direct_reply/reply_agent/retweet_bot scan lists; one Safari
  serializes everything, so each pruned scan converts to quote/reply
  throughput. SpaceX kept (markets megastory + Musk-AI overlap).
- **Therapist anchor in self_evolution_agent** — the 4h persona-evolution
  prompt now hard-anchors inside the therapist persona (the "cynical trader
  at 3 AM" drift can't recur).
- **`src/first_hour_babysitter.py`** — every 10 min, if the latest post is
  <60 min old, fires an extra replyback sweep (first-hour replies carry ~15x
  algo weight). Near-zero cost outside the window.

### 2026-06-05 PM — native GIF attachments (tested live, "you nailed it")

Funny posts/quotes now carry GIFs from X's NATIVE composer picker (no
downloads/re-uploads — brittle + repost-flag risk):
- `twitter_client._attach_native_gif(query)` — clicks `gifSearchButton`,
  pastes the query, clicks the first `gifSearchGifImage`. Best-effort: on any
  failure the post ships text-only.
- `post_tweet_with_gif(text, q)` / `quote_tweet_with_gif(url, comment, q)` —
  full chokepoint gates, composer flow (intent URL can't open the picker).
- Generators emit `[GIF: <2-4 word search>]`: stunt bot ALWAYS, quote bot ~1
  in 3 (restraint reads human). `humanizer.extract_gif_query` strips the tag;
  `_scrub_metadata_leaks` also strips GIF tags as backstop.
- Curated query bank in prompts: "this is fine", "michael jordan crying"
  (market down), "wolf of wall street"/"leonardo dicaprio cheers" (boss),
  "pablo escobar waiting", "kermit panic", "futurama fry suspicious".
- Live-validated 2026-06-05 18:00: "this is fine" GIF post composed,
  attached, and published end-to-end.

### 2026-06-05 PM — human-typo injection for @Graphseo

Operator mandate: every reply to @Graphseo (and ONLY him — he tweeted that
spelling mistakes are the only proof of humanity) carries exactly ONE
keyboard-adjacent typo ("xonfigurer" for "configurer").
`humanizer.inject_human_typo` picks one lowercase ASCII word ≥6 chars (never
@mentions/#tags/URLs/$tickers/accented words) and swaps one letter for an
adjacent key. Enforced in `twitter_client.reply_to_tweet` via
`HUMAN_TYPO_HANDLES` (default `Graphseo`) so every reply path obeys.

### 2026-06-05 PM — one reply per tweet, EVER (chokepoint dedup)

The account replied TWICE to the same @Graphseo tweet 7 min apart: two reply
bots each load `replied_tweets.json` at cycle start, so both saw the tweet as
fresh (stale in-memory copies = race). Fix: `twitter_client.reply_to_tweet`
re-checks the on-disk canonical replied set (status-ID keyed, URL-form
agnostic) right before the write and marks it before posting — covers ALL
reply paths incl. `reply_to_tweet_in_thread`. Operator rule: "never send 2
replies on same tweet." Regression test: two bots + a `?s=20` URL variant →
exactly one write.

### 2026-06-05 PM — truncation guard (the "ChatGPT paste" callout)

A blind `text[:220]` slice in the Graphseo reply path published a reply cut
mid-sentence ("…la vraie question n") and a follower publicly called the
account a botched ChatGPT paste. Fixes:
- **`humanizer.smart_trim(text, limit)`** — sentence-boundary trim (terminal
  punctuation preferred, else word boundary with dangling-fragment cleanup).
  All outgoing blind slices replaced (direct_reply graphseo, roast, promo bots).
- **Chokepoint backstop** — `content_guard.validate` rejects replies/quotes
  >278 chars (composer would cut them) or that LOOK truncated
  (`looks_truncated`: connector-punctuation ending, dangling 1-2 letter
  fragment). Applies to every reply bot via the chokepoint.
- NEVER use a bare `[:N]` slice on outgoing tweet text — use `smart_trim`.

### 2026-06-05 PM — FULL AGENTIC stack

Operator: "I want this bot and repo to be full agentic — goal is to
self-improve over time and push code on github."

- **`tests/test_guards.py`** — 19 deterministic guard tests (<1s, stdlib-only):
  dedup v2, price gate, language, lazy replies, pattern scrub, unwrap, scrape
  timestamps, history idempotency. THE gate for agentic pushes. Run with
  `.venv/bin/python -m pytest tests/ -q`.
- **`.github/workflows/ci.yml`** — guard suite on every push to main; a red X
  means an autonomous run shipped a regression (next run fixes it first).
- **`bin/auto_improve.sh` + `~/Library/LaunchAgents/com.kzer.ai-twitter-bot-improve.plist`**
  — DAILY 07:17 headless Claude Code session: diagnose (engagement_log +
  engine_health_alerts + bot.log) → ONE tested improvement → **ship via PR**
  (branch → `gh pr create` → wait for green CI → squash-merge; validated
  end-to-end on PR #3) → record memory. Single-flight lock, 2h stale-lock
  recovery, never starts the bot. Manual: `./bin/auto_improve.sh`.
  NOTE: no required-checks branch protection on main — it would block the
  running bot's direct state pushes; the PR flow + CI-watch gives the same
  guarantee for code changes.
- **Self-healing** — `engine_health_bot` collapse alerts now spawn
  `bin/auto_improve.sh --emergency "<alert>"` (rate-limited
  `SELF_HEAL_COOLDOWN_HOURS=6`, kill-switch `ENABLE_SELF_HEAL=0`) so a dead
  surface gets root-caused within the hour instead of days.
- Already on: `ENABLE_AI_MAINTENANCE=1` + `ENABLE_AI_DISCOVERY=1` (strategy /
  evolution / reflection / scout state-tuning loops).
- Dedup hardening from test findings: exact normalized-text rehash is always
  blocked, even for short stopword-heavy one-liners under the 4-word floor.

### 2026-06-05 PM — quote-RT surge + persona files

- **Quote-RT surge (operator: "abuse a bit of it for the next few weeks"):**
  first therapist-voice quote earned 4 likes in 2h → cap 100→**150/day**,
  spacing 90s+jitter45, feed-sweeper quote bar 300→200 likes and 4/cycle.
  Revisit ~2026-06-26 (or earlier if suppression_watch trips).
- **`bot_self_en.json` / `bot_self_fr.json` rewritten** to the bio spirit
  ("Treating market trauma. AI-powered portfolio therapy. Follow the signal.
  Heal the fear. ⚡") — the old "fierce / cynical trader at 3 AM" state was
  injected into every prompt and fought the therapist identity.
  self_evolution_agent may drift these; `core_identity.md` stays the anchor.
- **Launch release `launch-v1.0`** tagged + published on GitHub — rollback
  point for the whole 2026-06-05 stack (`git checkout launch-v1.0`).
- Autonomous mandate: ≥1 improvement/day, push main daily, record memory.

### 2026-06-05 round 2 — reliability + therapist voice alignment

- **`src/engine_health_bot.py`** — hourly per-action pace vs 7-day same-hour
  baseline; alerts (`engine_health_alerts.json` + ERROR log) when a surface
  drops below 40% of baseline. Born from the silent 2-day retweet collapse.
- **`src/conversion_attribution_bot.py`** — hourly: new followers diffed against
  authors we replied to in the last 48h; conversions bump per-author weight in
  `engagement_targets_log.json` (+0.5, cap 3.0) used by engagement_targeting.
- **Follow button fixed** — temp-file JS, 3 selector strategies
  (`data-testid$="-follow"`, aria-label Follow/Suivre @, placementTracking text),
  REAL click status; only `CLICKED` records a follow. Anti-churn loop guard
  confirmed: any handle touched within 30d is blocked from BOTH follow and
  unfollow at the chokepoint (operator 2026-06-05: "just follow once").
- **Replyback handle fix** — scraper returns display names; the reply's status
  URL now provides the @handle fallback so engagers actually get replies.
- **Reply language** — reply_agent's stale "FRENCH = ABSOLUTE PRIORITY" block
  replaced with strict match-the-parent (default EN on doubt).
- **Therapist voice alignment** — quote prompt (was "sharp/sarcastic/meme"),
  direct_reply header+tone (was "sharpest analyst/roast"), spicy instructions,
  replyback docstring all rewritten to the 2026-06-04 AI-Therapist persona:
  name the emotion → validate → calm reframe with the precise fact. Hope not
  hype, calm beats clever; the sharp numbers stay, the snark goes.

### 2026-06-05 growth push (operator: "push it harder")

Analytics 2026-06-05: impressions +26% but engagement rate −11%, replies −30%.
Operator levers, all shipped:

- **`src/feed_sweeper_bot.py`** — sweeps For You / Following (alternating, every
  8 min): on-niche post ≥`FEED_SWEEP_QUOTE_MIN_LIKES` (300) → QUOTE with a clever
  take; below → REPLY. ("reply or quote-retweet every single post you see").
- **Quote engine fixes**: `quote_tweet()` now returns bool; the quote bot marks a
  candidate consumed only AFTER a confirmed post (before, every spacing-skip cycle
  silently burned its best viral pick — the 28/day-actual vs cap gap). Spacing
  120s+jitter60 (was 180+120), cap 80→100/day. Viral high-min_faves queries added
  + `PRIORITY_QUOTE_HANDLES` (default TheBTCTherapist) jump the candidate queue.
  **2026-06-05 PM-3 follow-up:** the SAME bug lived on in `hot_quote_bot.py` (the
  4x/day hot-signal slots). It pre-marked the URL via `_mark_quoted()` and then
  unconditionally set `state["last_slot"] = slot_key` regardless of the bool
  `quote_tweet` returned. Result: every dedup near-miss or spacing skip burned
  the slot — both hot-quote slots on 2026-06-05 (06:13 spacing, 08:07 dup) were
  silently lost. Fixed: capture the bool, `continue` to next topic on `False`
  (slot + URL preserved), only mark consumed + advance `last_slot` after a
  confirmed `True`. Guard tests `test_hot_quote_preserves_slot_on_chokepoint_skip`
  + `test_hot_quote_consumes_slot_on_successful_post` pin the contract.
- **Reply discovery widened**: 72h window (`DIRECT_REPLY_MAX_AGE_MINUTES=4320`),
  feed scans 100 deep with proportional scrolling (feed scrapers now scroll
  `max_tweets//12` times instead of always 2), space + viral search terms added,
  per-cycle reply budgets raised in `.env`.
- **`src/viral_stunt_bot.py`** — occasional superviral-format first-person AI-stunt
  comedy ("I tested X's AI support…"). Max 2/day, 35% fire prob per 90-min check,
  SKIP-by-default 9/10 bar, must read as an obvious bit (never fake literal news).
- **Stock promo: REMOVED (operator 2026-06-05 PM).** The $MNTS/$SPCX/$SPCE
  campaign was cancelled the same day it launched. `stock_promo_config.json` is
  disabled + empty (kills space_promo_bot AND the reply/quote soft-injection
  blocks), the 9:40/15:40 cron jobs are unscheduled, and `operator_locked`
  prevents the WSB rotation bot from picking a new ticker. `space_promo_bot.py`
  stays in the tree, dormant — do NOT re-enable without explicit operator
  instruction. (GIF clipboard support in `_post_tweet_with_image` remains.)

### 2026-06-02 policy modules (single write chokepoints)

All write actions funnel through the lowest-level functions in `twitter_client`
(`post_tweet` / `quote_tweet` / `reply_to_tweet` / `follow_account` /
`unfollow_account` / `like_tweet` / `retweet_post`) so every one of the ~30 bots
obeys the same rules without per-bot rewrites:

- **`src/content_guard.py`** — pre-publish validation. Rejects any draft pairing a
  price/multiplier with a near-term timeframe (FR+EN regexes), and requires FRENCH for
  originals + quotes (replies are language-matched upstream, so only the price gate applies
  to them). `generate_validated()` regenerates up to `CONTENT_VALIDATION_RETRIES` then
  skip+logs — a flagged draft is NEVER published.
  **Dedup v2 (2026-06-05):** `is_duplicate()` now fires on ANY of: stemmed-word Jaccard
  ≥ `DUP_JACCARD_THRESHOLD` (0.45), containment ≥ `DUP_CONTAINMENT_THRESHOLD` (0.6),
  ≥ `DUP_SHARED_BIGRAMS` (3) shared distinctive bigrams ("power bill", "real bottleneck"),
  or same-story window (shared named entity + ≥ `DUP_TOPIC_SHARED_WORDS` (3) content words
  vs any post in the last `DUP_TOPIC_WINDOW_HOURS` (24)). Tuned live 2026-06-05:
  text-similarity signals only apply within `DUP_TEXT_WINDOW_HOURS` (48) — older
  overlap is topic continuity, not duplication; EN "The Decode…" headers are
  stripped like the FR ones; header words + niche-universal "ai"/"ia" are
  stopworded (never entities). Added after the bot posted the
  "GPU supply / power bill" take twice and the Anthropic raise 3× in one morning.
  Enforced at BOTH chokepoints now (`post_tweet` AND `quote_tweet`), and every published
  original/quote is recorded into `tweet_history.json` from the chokepoint
  (`_record_posted`, idempotent `history.save_tweet`) so the dedup corpus covers ALL ~30
  surfaces and survives restarts. `_scrub_metadata_leaks` also strips bare bracketed
  pattern IDs (`[RENAME]`) that the `[PATTERN: …]` rules missed and leaked live 2026-06-05.
  **spicy_bot is news-anchored (2026-06-05):** both SPICY and QUESTION modes must react to a
  fresh item from `external_signal.json` (≤`SPICY_SIGNAL_MAX_AGE_HOURS`=6h, top items by
  score injected into the prompt); no fresh signal → SKIP. Free-form "what's on my mind"
  musings are banned — the model had parroted its own prompt example into live posts.
- **`src/action_guard.py`** — write ledger + caps + pacing + follow policy. Persistent
  timestamped ledger (`action_ledger.json`) for the 30-day anti-churn check + audit.
  Per-action daily caps (`MAX_ORIGINALS_PER_DAY=3`, `MAX_QUOTE_REPOSTS_PER_DAY=3`,
  `MAX_REPLIES_PER_DAY=30`, `MAX_FOLLOWS_PER_DAY=5`, `MAX_UNFOLLOWS_PER_DAY=25`) with
  jittered min-spacing (45 min posts, 90 s replies). `can_follow` enforces whitelist-only +
  ratio ceiling (`following < FOLLOW_RATIO_CEILING×followers`) + 30-day cooldown; `can_unfollow`
  protects tier1/tier2 + caps the daily prune. `DRY_RUN=1` logs intended writes without
  executing (kill switch — run this first to verify, then set `DRY_RUN=0`).
- **`whitelist.json`** — tiered curated accounts (tier1 sources/targets, tier2 FR peers,
  tier3 watch-only). The ONLY accounts the bot may follow, plus the source list for
  quote-reposts/engagement targeting. The bot may SUGGEST additions (`suggestions[]`) for
  human approval but **never auto-adds**. Seeded from operator-curated lists, `review_required:true`.
- **`following_count.json`** — live following counter (seeded at the real ~4.2K baseline since
  `followed_accounts.json` under-reports), kept in sync by `action_guard.adjust_following()`
  on each follow/unfollow so the ratio invariant blocks new follows until the prune lands.
- Reciprocity mass-following (`follow_blast_bot`) is disabled whenever `FOLLOW_WHITELIST_ONLY=1`.

- **`src/engagement_targeting.py`** (BUILT 2026-06-02) — growth engine. Ranks tier1/2
  whitelist posts by velocity `(likes+reposts)/hour` × learned per-author weight, replies to
  the hottest few with a language-matched substantive take through the reply chokepoint
  (shares the 30/day cap + spacing + validators). Logs targets/tallies to
  `engagement_targets_log.json`. Scheduled every 20 min in `main.py`.
- **`src/bot_memory.py`** — recent-posts digest injected via `lang_mode` so the bot can call
  back to past theses (with dates) when it adds value. `content_guard` also rejects lazy
  replies ("bien vu", too short) so replies stay substantive.
- Autonomous strategy loop runs under `ENABLE_AI_MAINTENANCE=1` (analyzer 4h, meta_strategy 4h,
  strategy 3h, evolution 3h, reflection 6h) — periodic Claude/Ollama assess-and-improve.

> **Remaining (optional next):** conversion attribution for `engagement_targeting` (re-scrape
> targets to learn who liked/replied/followed back and adjust per-author weights), and folding
> likes/retweets into one explicit queue object. Caps/pacing/dedup already run through `action_guard`.

---

## Quick context

Autonomous Twitter/X influencer bot. ~30 concurrent micro-bots managed by APScheduler in `main.py`. Browser-driven via Safari + AppleScript — no Twitter API key.

**Default AI provider: Ollama** (`AI_CLI=ollama`). Codex is the default backup when the local model fails.

To switch providers:

```bash
AI_CLI=codex ./bin/run.sh
echo "AI_CLI=codex" >> .env
```

The `src/llm_client.py` adapter handles each provider transparently. If the
primary returns a hard failure (non-zero exit, empty stdout) **or a soft
refusal** (exit 0 but body like `[no need to search for external sources…]`),
the same fallback ladder fires: `LLM_FALLBACK_CLI` / `LLM_FALLBACK_MODEL`,
then `OPENCODE_FALLBACK2_MODEL`. Refusal patterns live in
`_REFUSAL_PATTERNS` in `src/llm_client.py`.

News bursts are tuned via `NEWS_POSTS_PER_CYCLE` (default `3`); set to `1`
when the LLM is flaky so each cycle skips fast instead of grinding for 6+ min
on bad output.
Repost / quote volume is tuned high but bounded: `MAX_RETWEETS_PER_DAY=150`,
`RETWEETS_PER_CYCLE=15`, retweet job every 2 min, and the quote bot every
4 min (cycles were taking >2 min, causing 80% of fires to be blocked by
`max_instances=1`; bumped to 4 min 2026-05-31).
Quote and repost discovery is English-first (2026-05-27 pivot): they scan
global high-signal EN AI / crypto / markets / space queries and EN trusted
handles first, with a short FR tail only for major French stories. Every
generated quote is in English.
Retweet and quote candidates still pass source, niche, age, min-like, respect
list, and dedup filters before posting.

**Catchup burst (2026-05-29):** On every startup, after the normal weekly/daily
Decode burst, the bot fires 3 extra rounds of RT → quote → spicy → breakout →
direct-reply back-to-back before the scheduler begins. Fills downtime gaps fast.

Impact tuning: top historical posts were concrete, numeric, named-actor
updates (Capital B funding/BTC buys, Saylor/Strategy BTC buys, ex-OpenAI
startup valuation). Prompts now explicitly prefer actor +
exact number + consequence, and avoid abstract standalone one-liners
that do not carry a verifiable fact.

Daily Decode schedule: cron at 07:00 `America/New_York` (`daily_news_job`).
Weekly fires at startup AND cron Fridays at 07:00 EST.
`MAX_NEWS_PER_DAY` caps the daily total; per-`(topic, format)` dedup
(`daily_topic_state.json`) prevents topic repetition across restarts.

**Scheduler hardening (2026-05-26):** `BlockingScheduler` runs with
`misfire_grace_time=3600`, `coalesce=True`, `max_instances=2`, and a
30-thread pool. APScheduler's defaults (`misfire_grace_time=1s`, 10 threads)
silently DROPPED once-a-day crons whenever a 600s LLM call saturated the
pool at the scheduled tick — so the daily news could skip the whole day.

Monthly recaps: `python main.py --monthly-recap-now` forces three Monthly
Décode Top 10 posts (IA, Crypto, Investissement). Scheduled monthly on the
1st at 8 AM New York. Big-post discovery is enabled for reposts/replies, but
freshness gates remain strict: reposts stay under `RETWEET_MAX_AGE_HOURS`,
direct replies under `DIRECT_REPLY_MAX_AGE_MINUTES`.

**Hard post-flight guard** (`contains_post_unsafe_leak` in `src/llm_client.py`,
wired into `twitter_client.post_tweet`): refuses to post anything containing
tool-call XML (`<function=…>`), NDJSON envelope keys (`"sessionID":`,
`"step_start"`, etc.), or text that opens with `{` / `[{`. Added after a
163k-char `{"type":"step_start",…}` blob got pushed to Safari on 2026-05-14
because the previous guard only caught XML, not JSON streams.

**`structured_output=True` flag (2026-05-28):** `run_llm()` and `unwrap_text()`
accept `structured_output=True` to bypass the `[{` safety guard when the caller
expects a JSON array (not a tweet). `reply_agent.py` uses this for `REPLY_SEARCH`
— without it, every Ollama JSON-array response was silently swallowed, causing
zero replies from search cycles.

**Safari black-screen recovery (2026-05-29):** `safari_hygiene._launch_safari()`
now calls `_warm_up_xcom()` after every relaunch: navigates to x.com, unregisters
all service workers, clears all caches, and hard-reloads. Prevents the stale-SW
blank app shell that made every scrape return `NO_ARTICLES`. Reactive path:
`twitter_client._record_blank_page()` counts consecutive blank-page responses;
after 5 in a row triggers `restart_safari("black_screen_recovery")` with a 5-min
cooldown (vs 30-min for preventive).

**Codex usage-limit lockout cache** (`codex_lockout.json` at repo root):
when codex returns "hit your usage limit, try again at …", `run_llm` parses
the date and caches it. Until that timestamp passes, codex is bypassed
entirely and calls go straight to the local Ollama fallback (`LLM_FALLBACK_CLI` /
`LLM_FALLBACK_MODEL`). Self-cleaning — the cache file is deleted when the
lockout window expires. Avoids the 6+ min per-cycle ladder cost while codex
is unavailable for days.

LLM budgets are soft by default: `LLM_ENFORCE_BUDGET=0` means usage is logged
but production content is not blocked by local hourly/daily counters. Set it to
`1` only when you explicitly want hard caps. News/replies should use the LLM;
research, scoring, RSS/HN/X signal collection, and maintenance should stay
deterministic or feature-gated.

---

## Setup

```bash
git clone <repo>
cd ai-twitter-bot
pip install -r requirements.txt
cp .env.example .env       # edit caps + handle
opencode auth              # or claude login / gemini login
./bin/run.sh               # foreground start, Ctrl-C to stop
```

For full operations playbook see [`docs/OPERATIONS.md`](docs/OPERATIONS.md).

---

## Skills

User-invokable slash commands live under `.claude/skills/` (mirrored at `.codex/skills/`). 25 skills, each is a directory with a `SKILL.md` file:

- **Lifecycle**: `start`, `stop`, `restart`, `status`, `run-agent`
- **Manual triggers**: `post`, `reply`, `engage`, `boost`, `hotake`, `news`, `tweet`, `thread`, `dryrun`
- **Account ops**: `follow`, `like`, `accounts`, `history`
- **Telemetry**: `logs`, `stats`, `config`, `reset`, `improve`
- **Weekly strategy**: `strategy` — Claude-powered weekly review (style evolution + prompt tuning)

Skill format (frontmatter YAML):

```markdown
---
name: post
description: Trigger one post cycle
allowed-tools: Bash Read
---

Trigger one post cycle:
1. ...
2. ...
```

---

## Project conventions

### Hard rules — stamped into every prompt

1. No illegal content of any kind.
2. No trolling US government / federal agencies (Fed, SEC, IRS, etc.).
3. No criticism by name of anyone in `respect_list.json`.

These three are baked into `personality_store.HARD_RULES_BLOCK` and injected into every generation prompt. Cannot be overridden by autonomous agents.

### Safety lattice

- **`BLOCKLIST`** in `src/config.py` — hard list (never engage at all).
- **`respect_list.py`** — soft list (engage but never criticize by name). Output scrubs at every content bot's post path. Default-seeded with 30 high-traction handles.
- **`suppression_watch_bot`** — hourly health check; pauses aggressive bots (`spicy`, `breakout`, `follow_blast`) if avg likes drop below the floor.
- **`health.py`** — Safari watchdog auto-restarts after 3 consecutive cycle failures.
- **`safari_hygiene.py`** — preventive Safari quit+relaunch every 2h. Stops Safari from wedging after hours of `webbrowser.open()` + AppleScript JS. Cookies / localStorage / IndexedDB are file-based so login survives the restart.

### Voice — `core_identity.md`

Stable. Never auto-rewritten. Loaded into every prompt as the ideological spine. Four pillars:

1. **Before anyone else** — ship first or SKIP.
2. **In-depth analysis** — sharp angle, exact figure, named causality.
3. **Zero bullshit, zero fluff** — every word earns its slot.
4. **You'll hate me until I'm right** — confident-arrogant, signs the take.

### Comedy patterns — `pattern_tags.py`

Every generated tweet carries `[PATTERN: <ID>]` metadata. Six patterns:
- `REPETITION` / `DIALOGUE` / `METAPHOR` / `RENAME` / `EN_ANCHOR` / `UNDERSTATEMENT`

Plus `FR_ANCHOR` for FR-mode runs, `OTHER` as fallback. The metadata line is stripped before posting and logged into `engagement_log.csv` column 6 for bandit attribution. `evolution_agent` reads this to compute per-pattern ROI and rewrite the style guide.

### Language — `lang_mode.py`

`CONTENT_LANG_PRIMARY=en` (default since the 2026-05-27 pivot) → all standalone content (news, hot takes, breakouts, spicy, threads, quotes, reposts) in English. The quote bot's prompt is hardcoded English; repost/quote discovery is English-first (see `quote_tweet_bot.py` / `retweet_bot.py`).

Reply paths (`direct_reply`, `reply_bot`, `replyback_agent`, `viral_followup`, `spike`, `mega_watch`, `early_bird`) **always match parent tweet language** regardless of `CONTENT_LANG_PRIMARY` — so French replies still happen on French threads.

### Self-modification boundary

Agentic maintenance is disabled by default. These agents auto-rewrite project
state only when the matching feature flags are enabled (`ENABLE_AI_MAINTENANCE`
for strategy/evolution/reflection/meta/self-evolution, `ENABLE_AI_DISCOVERY`
for discovery/scout):

| Agent | Cadence | What it modifies |
|---|---|---|
| `meta_strategy_agent` | 4h | `live_strategy.json` (daily caps, cadence factor, topic focus) — min bounds prevent zeroing hot takes |
| `strategy_agent` | 3h | `dynamic_queries.json` + `dynamic_accounts.json` (additions only) |
| `evolution_agent` | 3h | `directives.md` + `pruned_accounts.json` + `reinforced_accounts.json` |
| `reflection_agent` | 6h | `personality.json` (per-account dossiers + topic positions) |
| `self_evolution_agent` | 4h | `bot_self_fr.json` + `bot_self_en.json` (mood, obsession, character_traits, en_voice, drift, self_narrative) |
| `scout_agent` | 4h | `dynamic_accounts.json` + auto-follows |
| `analyzer_bot` | 4h | `performance_insights.json` (top patterns, best hours, rising topics, viral examples) |
| `style_evolution_bot` | 168h (weekly) | `directives.md` — scrapes viral X formats, rewrites style guide with Claude Sonnet |
| `performance.py` | 2h | `performance_log.json` + `learnings.json` |
| `daily_digest` | 1h (idempotent) | `daily_digest.md` |

Agents CANNOT touch:
- `core_identity.md` (ideological spine)
- `BLOCKLIST` in `config.py`
- `respect_list.py` defaults (operator-managed)
- `personality_store.HARD_RULES_BLOCK`
- `REPOST_MAX_AGE_HOURS` in `config.py` — ⛔ HARD operator rule: NEVER reshare
  (retweet) or quote-repost content older than **48h**. Clamped to 48 (env or
  agent cannot raise it); unknown age = stale = skip. Enforced in `retweet_bot`
  (feed `_feed_candidate_ok` + trusted-handle paths), `quote_tweet_bot`
  (`_too_old_to_quote`), `hot_quote_bot`, `wsb_signal_bot`. DO NOT CHANGE EVER.
- Any source code (only state files)

---

## Files of note

| File | Purpose |
|---|---|
| `main.py` | Scheduler entry point — boots all bots |
| `src/config.py` | Central config + live-cap reader (`get_live_cap`, `get_live_cadence_factor`) |
| `src/llm_client.py` | CLI adapter (OpenCode / Claude / Codex / Gemini) |
| `src/twitter_client.py` | Safari + AppleScript browser automation |
| `src/agent.py` etc. | Generation modules (one per content surface) |
| `core_identity.md` | Stable voice anchor |
| `personality.json` | Per-account dossiers (rewritten by reflection_agent when maintenance is enabled) |
| `bot_self.json` | Bot's evolving mood (rewritten by self_evolution_agent when maintenance is enabled) |
| `live_strategy.json` | Daily caps + cadence (rewritten by meta_strategy_agent when maintenance is enabled) |
| `directives.md` | Style guide (rewritten by evolution_agent when maintenance is enabled) |
| `engagement_log.csv` | Append-only action log (source of truth for ROI math) |

For the full module catalog see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## Adding a new bot

See [`docs/ARCHITECTURE.md#6-adding-a-new-bot`](docs/ARCHITECTURE.md#6-adding-a-new-bot).

Mandatory invariants:

1. Wrap the cycle body in `try/except` inside `safe_run_*` so a single-cycle exception cannot crash the scheduler.
2. Call `health.record_success/failure` at the end.
3. If interacting with Safari, take `_safari_lock` before opening URLs and `close_front_tab` at the end.
4. If writing state files that should be in git, call `git_ops.auto_push([...], "message")` after success.
5. If you have a daily cap, key state by `date.today().isoformat()` and short-circuit when reached.

---

## Memory model

This file is read by Claude Code agentic sessions when working on the bot's source. It exists to give the AI context about the project so first-time edits don't break invariants. The same content lives in [`CODEX.md`](CODEX.md) for Codex CLI sessions. **Keep them in sync** when you edit either.

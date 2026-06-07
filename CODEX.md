# CODEX.md

Project context for **Claude Code** sessions. Mirror of [`CLAUDE.md`](CLAUDE.md). Use whichever CLI you have authenticated.

> **You'll hate me until I'm right.**

> **Mandate 2026-06-07 PM (CURRENT — VIRAL FOCUS: QRT + REPLIES, QUALITY
> BARBELL; refines the morning AGENT SPEC below):**
>
> **Identity (anchored in `core_identity.md`, operator-stated):** The AI
> Therapist @TheAIShrink — *"Treating market trauma. AI-powered portfolio
> therapy. Follow the signal. Heal the fear. ⚡"* — AND the **sharpest in
> the room on AI**: the therapist voice is HOW, the exact number/mechanism
> nobody else in the thread has is WHAT.
>
> **Focus (operator: "focus should be Quote Retweet AND replies"):**
> - **QRTs = the QUALITY lane** — 100/day cap @5min+jitter (operator raised
>   three times, final: "we should do more quote retweet"), 50-like floor
>   (mid-size analytical finance/AI posts, NOT mega-virals — they engage
>   back). The measured formula (operator's two best posts, 3.5-7K views
>   each): **re-denominate their number + one mechanism metaphor + closing
>   question**; cashtags/@mentions welcome. Screenshot-worthy or SKIP —
>   SKIP is free, mediocre is expensive.
> - **Replies = the QUANTITY lane** — unlimited, freshest-fast-rising
>   first, investor-psychology expertise, hook in 6-8 words, 100-180 chars.
> - Originals 3-4/day in jittered US-market slot crons (9:30/12:30/16:30/
>   20:00 NY; 12:30 leads with the GIF stunt) — they exist to CONVERT the
>   profile visits QRTs+replies generate. Plain RTs 0-2/day.
>
> **The running bits:** @TheBTCTherapist bestie blitz (reply to EVERY ≤48h
> post of his; QRT his best with the AI-side INVERSION + GIF — big-brother
> warmth, he should quote back). AI-vs-BTC feud steering on all BTC parents.
>
> **Self-reinforcing loops (all live):** winners (≥1 external like in 1h)
> get self-RT then un-RT→re-RT recycling (4h gaps, max 4, ≤48h);
> `account_curator` earns the tracked/scan list from on-lane engagement ×
> conversion evidence (NO static lists — pins: TheBTCTherapist, Graphseo;
> may promote ≤3/day to the whitelist `discovered` tier); `self_winners`
> bank + pillar attribution feed every generation prompt.
>
> **WHAT WORKS (measured, 2026-06-07):**
> - **market_trauma therapist one-liners: 29.8 avg likes vs 13.1 for plain
>   AI news takes (2.3x)** — therapize, don't report.
> - **QRTs of mid-size analytical finance posts**: thousands of views +
>   5-10 likes each from a 1.3K-follower account; the number-reframe +
>   metaphor + question structure specifically.
> - **Reply volume converts**: 941 replies on Jun 6 → +37 followers/day;
>   +298 followers that week.
> - Self-RT of a winner ≈ +200 views historically.
> - **Following/unfollowing is operator-manual** (bot unfollows OFF; seed
>   follows resume automatically once the purge passes the ceiling).

> **Mandate 2026-06-07 AM (AGENT SPEC: FOLLOW + CONTENT — volume settings
> for QRTs superseded by the PM block above; follow rules + slots + format
> rules still in force):**
> Operating spec for @TheAIShrink — "The AI Therapist". Lane: **AI × markets ×
> psychology**, English only. Golden rule: **don't report the news — therapize
> it.** Voice: witty, deadpan, irreverent, emotionally intelligent but savage —
> a calm shrink diagnosing the market's (and the investor's) neuroses.
>
> **PART 1 — FOLLOWING (rebuild from near-zero after the full purge).**
> Following is a tool for exactly two things: curating reply targets +
> signaling the lane. Hard constraints, ENFORCED IN `action_guard.can_follow`:
> - Total following cap **300** (`FOLLOW_TOTAL_CAP`); steady-state ~120–150.
>   While followers < 300, stay under **150** (`FOLLOW_LOW_PHASE_CEILING`);
>   once followers exceed 300, keep following ≤ followers.
> - Max **20 follows/day** (`MAX_FOLLOWS_PER_DAY`), randomized gaps **≥10 min**
>   (`MIN_SECONDS_BETWEEN_FOLLOWS=600` + jitter). Never burst-follow.
> - **No churn**: 30-day anti-churn + `can_unfollow` protects ALL whitelist
>   tiers. Whitelist-only (`FOLLOW_WHITELIST_ONLY=1`); follow_blast +
>   followback OFF.
> - Seed list in `whitelist.json`, followed IN PRIORITY ORDER by
>   `marquee_follow_bot` (seed-follow job, 1 attempt/15 min, chokepoint-paced):
>   tier1 foils (TheBTCTherapist — the AI-vs-Bitcoin feud), tier2 niche reply
>   targets (Housel, ParikPatelCFA, Litquidity, greg, ReformedBroker, Zweig),
>   tier3 AI signal (karpathy, sama, steipete, mattwolfe, gregisenberg,
>   AndrewYNg, lexfridman, kaifulee), tier4 crypto/markets foils (saylor,
>   APompliano, balajis). Handles are HINTS — resolve via display name +
>   keywords in `seeds[]`; skip + log unresolved/suspended/off-niche.
> - Phase 2 discovery (peers of tier1-2, 1k–200k followers, active ≤14d,
>   on-niche, no spam/airdrop/shill) goes to `suggestions[]` for human
>   approval — the bot NEVER auto-adds. Expand to ~120–150 then hold.
>
> **PART 2 — CONTENT (output mix per day, enforced via chokepoint caps +
> meta_strategy/strategy_lab bounds clamped to the spec):**
> - **Originals 3–4/day** (`MAX_ORIGINALS_PER_DAY=4`, 2.5h+jitter spacing ≈ US
>   market slots ~9:30a/12:30p/4-5p/8p ET; never two within 10-15 min). The
>   conversion layer. ≥1 daily original carries native media (stunt bot GIF).
> - **QRTs 1–2/day** (`MAX_QUOTE_REPOSTS_PER_DAY=2`) — ride the day's biggest
>   AI/markets headline with a persona take, ideally within 1-2h of trending.
> - **Plain RTs 0–2/day** (`MAX_RETWEETS_PER_DAY=2`) — reciprocity/on-brand
>   amplification only; prefer QRT (carries our voice, earns distribution).
> - **Replies UNLIMITED** — the core engine, max throughput
>   (`MAX_REPLIES_PER_DAY=999999`; 8s+jitter spacing stays as the ban-safety
>   floor — Safari serializes anyway). Front-load fresh fast-rising posts
>   (<30-60 min) from whitelist tier1-2 first, then on-niche trending. Every
>   reply adds a sharp/funny/therapist-framed take; never generic, never
>   duplicate text (dedup chokepoint stays). Only a hard rate-limit pauses
>   replies — then resume at full throttle.
> - **Reply-bait question 3–4/week** (`REPLY_BAIT_PER_WEEK=4`, spicy QUESTION
>   mode, weekly-capped in `spicy_bot`).
> - Format rules (already code-enforced): no links in post bodies
>   (link-in-first-reply), no hashtags, one idea per post, hook first line.
> - Guardrails: not financial advice — observational/humorous only, never
>   actionable buy/sell calls, price targets, or pump language. No
>   impersonation; clearly a fictional AI-therapist persona.
> - Content pillars (rotate): market-trauma therapy (primary) /
>   AI-vs-everything hot takes (AI-vs-Bitcoin running bit) / meme-reaction
>   with native GIF / reply-bait questions.
> - Weekly metrics review → shift mix toward winners (followers Δ, following
>   ≤300, impressions/post, reply→profile-visit→follow conversion, top pillar).

> **Mandate 2026-06-05 PM (superseded by 2026-06-07 above — MONETIZATION SPEC, supersedes 2026-06-04):**
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
> **2026-06-06 UNLIMITED MODE (operator: "remove limits on bots period go
> unlimited", "be more active"):** all volume caps effectively removed —
> originals 999/day (news 15, hotakes 40, breakouts 30, spicy 30), quotes
> 500/day @60s, retweets BACK ON 600/day, replies 2000/day @15s, likes 1800.
> Scheduler cranked: reply scan 2-3 min, direct-reply 2-4, quote + retweet
> jobs 2 min, sweeper 5 min, engagement targeting 10 min. Only jittered
> min-spacing remains (ban protection). Quality gates stay absolute (dedup,
> 48h rule, one-reply-per-tweet, no links/hashtags, niche, voice).
> follow_blast stays OFF. Auto-pin: pin_bot rotates the pinned slot to the
> best-performing post every 3h (already live).
>
> **2026-06-06 adjustments:** replies back to ~400/day @30s+jitter (operator:
> "you are doing less replies than a few weeks ago" — replies stay the #1
> growth lever; the 100/day cap was over-correction). "🔎 The Decode Daily"
> series branding REMOVED from the news prompt — posts now open with the hook,
> therapist-framed, no header, no URL (operator: "I don't want to see the
> decode daily").
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

### 2026-06-07 PM-12 — French-to-the-bestie incident + the Safari test wall

Two live failures within an hour of the PM-11 relaunch, both mine:

1. **VIP lane shipped the Graphseo treatment to @TheBTCTherapist** (operator:
   "why did it reply in french to the bitcoin therapist? and with m dash").
   PM-11 added him to `VIP_SCAN_HANDLES`, but the lane had ONE generator —
   the Graphseo FR prompt (French + the deliberate-typo style). ~5 of his
   posts got French replies 13:52-13:57. Fix: per-handle persona in
   `_run_graphseo_scan` (bestie EN prompt for TheBTCTherapist, buddy prompt
   for other VIPs, Graphseo keeps his FR generator) + `humanize()` on VIP
   output (the lane skipped it — that's how the em dash survived).
   Em/en-dash strip is now ALSO a chokepoint backstop in `reply_to_tweet`
   for every path. Guard: `test_vip_scan_uses_bestie_prompt_for_btctherapist`,
   `test_reply_chokepoint_strips_em_dashes`.

2. **A guard test drove the LIVE Safari and posted real replies** to
   @TheBTCTherapist mid-test (incl. duplicate replies on one status — the
   test used a tmp replied-store, so the chokepoint saw everything fresh).
   Root cause: the test mocked `direct_reply.reply_to_tweet`, but the VIP
   scan imports it FUNCTION-LOCALLY from twitter_client — the mock was
   bypassed. `tests/conftest.py` now has an autouse `_no_safari` wall:
   `webbrowser.open`, `_run_applescript`, `_paste_text` raise in every
   test unless explicitly re-patched. Same family as the logger-isolation
   fix (a1077a0): tests must not be able to touch production surfaces.

Lesson: a function-local `from .twitter_client import X` resolves at call
time from twitter_client — mocking the caller module does nothing. Mock at
the chokepoint module, and let the conftest wall catch the ones you miss.
### 2026-06-07 PM-11 — THE PHANTOM REPLY BUG (the real "bot doesn't do much")

Operator: "bot is not fast and doesn't do much, it's disappointing." He was
right, and the engine's own numbers were lying. Since the one-reply-ever
chokepoint landed (2026-06-05 17:46), FIVE bots that "locked the URL in
BEFORE posting" (`save_replied` premark) — `direct_reply._reply_to_tweets`
(= direct_reply search/feed AND feed_sweeper), `early_bird`, `mega_watch`,
`reply_bot`, `roast` — had 100% of their replies silently refused: the
chokepoint loads the on-disk store, sees the caller's own premark, and
skips. Their unconditional `log_reply()` then recorded a PHANTOM row, so
engagement_log said "941 replies on Jun 6" while bot.log's `Reply posted!`
said 140 (Jun 7: 81 real vs 513 self-refusals). Repro was deterministic:
premark → `load_replied()` → refuse.

Fix (chokepoint-honest contract, pinned by
`test_reply_callers_never_premark_store` +
`test_reply_chokepoint_returns_bool`):
- `twitter_client.reply_to_tweet` returns **True only when the reply
  actually shipped** (DRY_RUN counts), False on policy/content/dedup skips.
- Callers NEVER write the replied store before the call — crash-safety is
  the chokepoint's job (it marks right before the Safari write). In-memory
  `replied.add(url)` stays (no same-cycle retry).
- `log_reply` fires ONLY on True — no more phantom rows poisoning the ROI
  loop, the watchdog baselines, and the operator's own measurements.
- Same gating applied to VIP scan, engagement_targeting, btc_blitz,
  retweet_bot replyback.

Also: VIP scan lane trimmed to `Graphseo,TheBTCTherapist` (env
`VIP_SCAN_HANDLES`) — the 2026-06-06 four-handle FR list burned ~3 min of
serialized Safari per cycle converting to zero on the EN persona.

Lesson (the dedup-chokepoint family grows again): when a chokepoint both
CHECKS and MARKS a store, callers must not touch that store at all —
"defensive" caller-side marking turns the guard against its own caller.
And NEVER log an action as done unless the chokepoint said it shipped:
every measurement downstream (pillar ROI, watchdog baselines, operator
trust) inherits the lie.

### 2026-06-07 PM-10 — profile visits OFF (operator launch config: "don't visit any profiles anymore")

Discovery surfaces are now EXACTLY three: **@TheBTCTherapist's profile**
(the main account), **Home** (For You + the Following tab), and **search
terms**. `twitter_client._profile_visit_allowed` gates BOTH profile-visit
primitives — `scrape_profile_tweets` and `visit_profile_and_like` — at the
chokepoint: only our own profile (boost/pin/metrics/with_replies) and
`PROFILE_VISIT_ALLOWLIST` (env, default `TheBTCTherapist,Graphseo`, read
at CALL time per the side-effect-env rule) may be visited; anything else returns
`[]`/no-ops BEFORE any Safari work. Bots that scanned other profiles
(early_bird, mega_watch, engagement_targeting, quote priority/trusted-handle
passes, retweet trusted-handle passes, engage/notify reciprocity likes) now
skip those handles instantly — their Safari time flows to home/search/reply
lanes. Follow/unfollow profile visits are untouched (mechanically required
to click the button; follows are chokepoint-dormant under the ceiling,
unfollows operator-only). Guard test:
`test_profile_visits_blocked_outside_allowlist`.

**Buddy blitz (same mandate, operator: "reply to everything graphseo and
thebtctherapist post"):** `btc_blitz` now runs a buddy pass after the
bestie pass — every `BLITZ_BUDDY_HANDLES` (default `Graphseo`) fresh ≤48h
post gets exactly one reply (language-matched, warm + sharp, no QRT bit —
the inversion stays BTCTherapist-only; Graphseo's one-typo rule is already
chokepoint-enforced). Same idempotency: replied-set check pre-LLM +
chokepoint dedup. Guard test: `test_buddy_blitz_replies_to_every_fresh_post`.

### 2026-06-07 PM-9 — viral push round 3 (operator: "DO IT … push it")

Two new levers, both measured-data-driven:

1. **market_trauma is now the DEFAULT original format**, not one option
   among six. `pillar_tags.market_trauma_priority_block()` (the 29.8-vs-13.1
   likes measurement, 2.3x) is injected into the hotake AND spicy prompts —
   the two text surfaces the post slots try. Plain news takes only ship
   when the story is big enough that the number alone carries it.
2. **`src/breaking_qrt_bot.py`** — breaking-news instant QRT, every 10 min.
   The 4x/day hot_quote slots can lag a mega story by 4h; QRTs only 100x
   inside the first 1-2h. Spike detector (`pick_breaking_item`, pure +
   guard-tested): top niche signal item fires only when score ≥15
   (`BREAKING_QRT_MIN_SCORE`) AND ≥3x the runner-up
   (`BREAKING_QRT_SPIKE_RATIO`) — a flat pool is not breaking. Max 6/day
   (`BREAKING_QRT_MAX_PER_DAY`). Reuses the ENTIRE hot_quote pipeline
   (niche filter, viral-tweet hunt, QUOTED_FILE dedup, persona quote) and
   the quote_tweet chokepoint — zero new write paths. Story dedup by
   order-insensitive title key; chokepoint skip keeps the story ARMED
   (slot-burn lesson); `can_post(QUOTE)` precheck before any Safari/LLM.

### 2026-06-07 PM-8 — reply volume push (operator: "we use to do 400 a day now you are at like 100… push it")

Diagnosis first: the engine was NOT throttled — Jun 6 did 941 replies, and
Jun 7 had 509 by 06:30. The "100/day" feel was downtime (bot stopped
06:25-11:10 for the purge) + the restart spending its first ~20 min of
serialized Safari on RT/quote/hot-quote/hotake/breakout bursts before the
reply loop warmed up (killed at 11:31 with ~8 post-restart replies). Two
structural fixes so every running minute favors replies:

1. **Startup order: replies first.** main.py warmup is now feed sweep →
   direct_reply → notify/replyback → THEN the post-surface bursts. The
   volume lane owns the first Safari minutes after every restart.
2. **hot_quote spacing busy-loop killed.** A spacing-blocked slot used to
   lap scrape → LLM → chokepoint-refuse every ~40s until the gap elapsed
   (3 laps witnessed 11:22-11:24), burning Safari searches + ollama calls.
   `can_post(QUOTE)` precheck now runs BEFORE the scrape; spacing block →
   `_wait_for_quote_spacing` (cheap sleep, Safari stays free); cap block →
   end cycle, slot preserved. Guard test pins it:
   `test_hot_quote_spacing_block_never_touches_safari_or_llm`.

Lesson: when the operator says a surface dropped, read engagement_log
per-hour FIRST — pace-by-hour separates "engine throttled" from "engine
was off". Replies/hr while running: 54-111 (healthy). The fix is uptime +
Safari-time allocation, not caps.

### 2026-06-07 PM-7 — boost blind-toggle bug (the banger kept getting UN-retweeted)

Operator: "bot is not good at retweeting his banger tweet of the day."
Morning log showed why: once every recent post was in boost_history,
`run_boost_cycle` fell back to `retweet_own_latest()` every 20 min — a
blind 't'+Enter on the latest post. That keystroke TOGGLES: on an
already-retweeted post it UN-retweets. The banger's self-RT was switched
off/on all morning. Fix: the all-boosted case now resurfaces the
HIGHEST-engagement own post via `reboost_tweet` (un-RT→re-RT, always ends
retweeted); scrape failures skip instead of toggling. Guard test pins it.
Lesson: every keystroke-shortcut Safari primitive is a TOGGLE — never fire
one without knowing the current state (same family as reboost_tweet's
two-press design).

**Deeper root cause found same hour:** the scraper's `author` field is the
DISPLAY NAME ("The AI Therapist"), not the @handle — FIVE bots compared it
to BOT_HANDLE and silently saw zero own posts (boost never picked a banger,
recycler would find no winners, spike/viral_followup blind,
suppression_watch measured nothing). `twitter_client.is_own_post()` (URL =
ground truth: /BOT_HANDLE/status/) now used at all five sites. THIRD
occurrence of the display-name-vs-handle family (BLOCKLIST 2026-04-26,
replyback 2026-06-05) — never compare scraper `author` to a handle.
LIVE-VERIFIED: real self-RT shipped post-fix.

### 2026-06-07 PM-6 — engine-health boot-warmup grace (downtime ≠ collapse)

Witnessed live: minutes after a boot (bot had been stopped for the
operator's manual purge), the watchdog fired "reply collapsed: 0 today vs
~50 by this hour" and spawned an emergency self-heal Claude run on a
perfectly healthy engine. Cumulative-by-hour comparisons are meaningless
right after process start — every surface reads 0 after downtime.
`run_engine_health_cycle` now no-ops for `ENGINE_HEALTH_WARMUP_MINUTES`
(default 90) after boot. Fourth member of the intent-vs-collapse family:
cap=0 (PR #6), today≥cap (PR #7), fired-within-the-hour (PR #22), and now
just-booted.

### 2026-06-07 PM-5 — focus mandate + identity anchor

Operator: "focus of the bot should be Quote Retweet AND replies — and the
bot needs to be the sharpest in the room in AI with the motto [the bio]."
`core_identity.md` (operator-managed, loaded into every prompt) now anchors
all three: the motto (was already the positioning line), the
sharpest-in-the-room analyst edge (was only in reply/quote prompts — now
spine-level: voice is HOW, the number is WHAT), and a PRIMARY SURFACES
section (QRT quality lane + reply quantity lane; originals convert the
visits). Hashtag line fixed to NO hashtags. Folded into the CURRENT
mandate block at the top of this file.

### 2026-06-07 PM-4 — QUALITY BARBELL (operator: "goal is big viral posts… you decide")

Operator asked if 100 QRT/day was too much, then delegated. Decision:
**quantity on replies, quality on everything on the profile.** QRTs
100→40/day @10min+jitter (raised to 60 same day — operator: "totally
cool if we do more than 40"); agent bounds 20-80 (meta_strategy /
strategy_lab); quote prompt got the explicit gate "screenshot-worthy for
the group chat or SKIP — SKIP is free, mediocre is expensive". Rationale:
per-post engagement rate is what the algo and a profile visitor read;
the marginal 80th QRT of a firehose is mediocre and average is invisible.
Replies stay unlimited (941/day → +37 followers, measured). Note: ~288
quotes shipped on Jun 6 without platform trouble — 40 is a quality
choice, not a safety ceiling.

### 2026-06-07 PM-3 — self-RT recycler (operator: "abuse the retweet of your own posts")

Operator: when a post works, self-RT it after ~1h, then keep cycling
unretweet → re-retweet (like the pin rotation) so it resurfaces in
followers' feeds repeatedly. **`src/boost_recycler_bot.py`** (every 45 min,
ONE action/cycle): own posts with ≥1 like from someone else within the
first hour (scraped likes ≥2 — the bot self-likes at publish, so 2 = 1
external; `BOOST_RECYCLE_MIN_LIKES`) and 1h-48h old → first self-RT
(organic algo push owns the first hour), then
un-RT→re-RT via the existing `twitter_client.reboost_tweet` (one Safari
session, ends retweeted) every ≥4h (`BOOST_RECYCLE_GAP_HOURS`), max 4
cycles/post (`BOOST_RECYCLE_MAX_CYCLES`). Hard 48h ceiling — stale
resurfacing reads desperate. State invariant shared with notify_bot's
boost engine: URL in boost_history.json ⇔ currently retweeted (decides
retweet_post vs reboost_tweet). `pick_action` is pure + guard-tested
(fresh-winner-first, gap, cap, age window). Complements (not replaces)
boost_job's fresh-post self-RT and the disabled pin rotation.

### 2026-06-07 PM-3 — self-heal kill switch was read at import time (phantom emergency)

bot.log at 09:44/09:55/10:04 reported `[ENGINE_HEALTH] ⚠️ ALERT: reply
collapsed: 0 today vs ~50 by this hour over the last 7 days (0%)` while
engagement_log.csv showed 501 replies for the same day (00h-06h, before the
bot stopped at 06:25 today under .bot_disabled). The 10:04 cycle also
launched `bin/auto_improve.sh --emergency` against the phantom alert —
which spawned a real headless Claude run.

Root cause: `tests/test_guards.py::test_engine_health_still_alerts_active_surface`
(and four siblings) call `run_engine_health_cycle()` against tmp CSVs with
synthetic "today=0 vs baseline=50" data, expecting an alert to fire. They
set `monkeypatch.setenv("ENABLE_SELF_HEAL", "0")` to suppress the
subprocess — but `ENABLE_SELF_HEAL = os.environ.get(...) == "1"` was a
**module-level constant** evaluated at first import, so the env patch had
no effect. Every such test logged `log.error("⚠️ ALERT: reply collapsed: 0
today vs ~50...")` into the real bot.log (shared logger writes to the same
RotatingFileHandler) AND spawned `auto_improve.sh --emergency` in the
production repo. The "reply collapsed" alert this very session diagnosed
was the test's own synthetic line.

Fix: `_maybe_trigger_self_heal` reads `ENABLE_SELF_HEAL` and
`SELF_HEAL_COOLDOWN_HOURS` at call time (same pattern as `_is_surface_disabled`
which is documented to "Read at call time so live edits ... take effect
without restart"). Module-level constants for these two env vars are
removed. Two guard tests pin the contract:
`test_self_heal_env_kill_switch_is_read_at_call_time` (ENABLE_SELF_HEAL=0
must suppress Popen even when the cooldown stamp is missing) and
`test_self_heal_cooldown_env_is_read_at_call_time` (a 24h cooldown env
must hold an hour-old stamp).

Lesson — re-stating the chokepoint-dedup lesson in a new register: any
env var that gates a SIDE EFFECT (subprocess spawn, network write,
posting) must be read at call time, not import time. The cost of `os.environ.get`
on every call is microseconds; the cost of a phantom Claude emergency run
is dollars and operator confusion.

### 2026-06-07 PM-2 — QRT SURGE (operator: "abuse those bro", measured)

Operator data: QRTs of relative large accounts = thousands of views +
5-10 likes each; his two best posts of the day were BOTH QRTs of mid-size
analytical finance accounts (~3.5-7K views, 6 likes each), built the same
way: **re-denominate their number ($145B → $37.5B quarterly burn) + one
mechanism metaphor ("collecting rent on silicon that doesn't exist yet" /
"$50k interns into $500k employees") + closing question that forces a
side.** That structure is now in the quote prompt as the default for
ticker/markets/AI-capex parents; cashtags + @company mentions welcome.

SUPERSEDES the spec's 1-2 QRT/day: `MAX_QUOTE_REPOSTS_PER_DAY=100`,
`MAX_QUOTES_PER_DAY=100`, spacing 5min+jitter3, `QUOTE_MIN_LIKES=50`
(300 was excluding exactly the mid-size lane that works),
`FEED_SWEEP_QUOTE_MIN_LIKES=100`, sweeper 6 quotes/cycle. meta_strategy /
strategy_lab quote bounds opened to 20-150; autonomous_growth prompt
updated (volume levers = replies AND quotes). live_strategy.json reset.
Startup burst fires sweep→quote→reply again (RTs stay out — 2/day).
Originals (4/day slots), plain RTs (2/day), follows: unchanged.

### 2026-06-07 PM — bestie blitz + self-curated tracking (operator mandate)

Operator: comment EVERY ≤48h @TheBTCTherapist post at startup (never twice
on one post), QRT his most impactful with the AI-side inversion bit ("he
works the weekend because Bitcoin — we're boarding the jet to the
afterparty" + GIF), be his best friend / big brother. AND: stop ALL static
account lists — the bot develops its own tracked list; only TheBTCTherapist
and Graphseo stay operator-pinned.

- **`src/btc_blitz.py`** — startup + every 6h: scrapes his profile, QRTs the
  most-liked not-yet-quoted ≤48h posts (bestie inversion prompt, GIF bank:
  private jet / leo cheers / wolf of wall street), then replies to every
  fresh post not yet replied. Fully idempotent: replied/quoted dedup stores
  + chokepoints make re-runs free. Runs BEFORE the startup reply burst so
  the day's 2 QRT slots go to the bit first.
- **`src/account_curator.py`** — every 4h, rebuilds `tracked_accounts.json`:
  score = on-lane engagements (last `CURATOR_WINDOW_DAYS`=4d) × conversion
  weight (engagement_targets_log). **Lane gate**: engagements whose text
  classifies pillar="other" (where FR-era replies land) DON'T count — this
  is what lets the curator survive a persona pivot. PINNED first:
  TheBTCTherapist, Graphseo.
- **`EARLY_BIRD_ACCOUNTS` / `MEGA_ACCOUNTS` static lists are GONE** (empty
  lists pinned by guard test) — both bots scan `tracked_handles()` (early
  bird top-30, mega watcher top-12).
- **Whitelist "discovered" tier** (operator grant: "develop yourself the
  list of accounts you want to follow"): curator promotes its strongest
  finds — promotion bar ABOVE tracking bar (≥5 engagements, no digit-run
  spam handles), ≤3 adds/day, ≤50 total, logged; operator tiers untouched;
  follows still go through every chokepoint rule (20/day, 10-min gaps,
  300/150 ceiling, churn). Discovered handles queue AFTER operator seeds
  in the seed-follow bot.
- Live-verified: curator on real data tracks unusual_whales, cointelegraph,
  polymarket, coinbureau…; FR-era authors correctly excluded by the lane
  gate; spam-pattern handles correctly blocked from promotion.

### 2026-06-07 PM — viral push round 2: the learning loops were broken

First live read of `pillar_engagement_30d` (scraped own-metrics joined to
pillars): **market_trauma posts average 29.8 likes vs 13.1 for ai_news_take
and 9.1 for "other" — the therapist one-liner is the proven winner by 2.3x.**
The mix should keep tilting toward it.

Loop fixes that made that reading possible:
- **`self_winners` was imported in main.py but NEVER SCHEDULED** (same
  dead-import bug as the old marquee job) — now every 2h. Floor 10→3 likes
  (`SELF_WINNERS_MIN_LIKES` — 10 left the bank EMPTY at this account size).
- **`_is_own` rejected 100% of rows**: the 2026-06-05 scraper rebuild
  writes {text,likes,views,timestamp} with no author/url, so the own-check
  failed on every row. Rows are own-by-construction now.
- **Provenance guards**: the profile scrape catches retweeted ads (a 2M-view
  Seedance promo was about to be injected as "our best post") and FR-era
  posts — views ceiling (`SELF_WINNERS_MAX_VIEWS`=100K) + French-marker
  filter + 4-day window (`SELF_WINNERS_WINDOW_DAYS`, therapist-era only).
- **Empty bank now CLEARS the file** — "skip write on empty" kept stale
  junk being injected into prompts forever.
- self_winners block now also injected into **spicy** (hotake already had
  it); render header EN (was French, fought the voice).
- **`analyzer_bot.pillar_engagement_30d`** — avg likes/views per pillar
  from scraped metrics; counts say what we POSTED, this says what the
  audience REWARDED.
- **Slot crons jittered** (±15 min posts, ±10 min hot-quote) — a bot that
  posts at 09:30:00 sharp daily fingerprints itself as a cron job.

### 2026-06-07 PM — viral push (operator: "make the account/posts more viral")

At 1.3K followers virality is mechanical, not magical: the only surfaces
that can 100x are (1) sharp replies inside a mega-post's first minutes and
(2) QRTs on the day's biggest story. Changes, all reply-side:

- **`mega_watch_bot.MEGA_ACCOUNTS` re-laned** (≤4-min watcher = the single
  highest-leverage surface): space + GPU-miner tail OUT; foils
  (saylor, TheBTCTherapist), market-news megas (WatcherGuru, zerohedge,
  DocumentingBTC, unusual_whales, KobeissiLetter) and fin-meme seeds
  (morganhousel, litcapital, ParikPatelCFA, greg) IN. List kept tight —
  every watched handle costs scan time inside the freshness window.
- **`early_bird_bot.EARLY_BIRD_ACCOUNTS` 95→~45**: the old list was a
  museum of dead mandates — FR crypto/bourse/media tails, space, VC tail,
  and THREE BLOCKLISTED handles (MathieuL1, NCheron_bourse, Capetlevrai)
  burning serialized-Safari scan cycles. Halving the list doubles rotation
  frequency on the handles that matter. Guard test pins blocklist/space
  out + foils in.
- **REPLY_PROMPT**: SPACE expertise block + space examples replaced with
  INVESTOR PSYCHOLOGY expertise (loss aversion, behavior gap, disposition
  effect, drawdown math) + two psychology sharpness examples; new
  VIRALITY MECHANICS section — hook in the first 6-8 words, no
  throat-clearing openers, 100-180 char target, screenshot-quotable.

### 2026-06-07 PM — spec round 3 (operator: "DO IT PUSH IT HARD", pre-launch)

- **Reply queries re-laned** — space queries REMOVED from
  `direct_reply.SEARCH_QUERIES`/`HOT_TAB_QUERIES` (persona: no space), FR
  tail slimmed to 1; added investor-psychology queries (panic-sold / bought
  the top / FOMO / trading psychology — the market-trauma home turf) and
  `from:` scans of the tier1-2 seeds + foils so their fresh posts are always
  in the reply pool (spec: whitelist targets first). Guard test pins the lane.
- **Quote engine** — scope line fixed (AI x markets x psychology, NO space);
  new AI-vs-Bitcoin feud instruction fires on BTC parents (the ai_vs_btc
  pillar was 1% of actions — the running bit barely existed);
  `QUOTE_MIN_LIKES` 5→300 + `FEED_SWEEP_QUOTE_MIN_LIKES`=300 so the 2 QRT
  slots/day ride genuinely trending posts (priority handles bypass via
  their own queue, not the floor).
- **Seed handle resolution** — `marquee_follow_bot` now verifies display
  name/keywords (from whitelist `seeds[]`) against the scraped profile
  before following; confident mismatch → `seed_unresolved.json`, retried
  weekly, never followed blind. Scrape failure proceeds (follow_account
  fails safe). Guard pre-check skips the Safari visit when the chokepoint
  would refuse anyway.
- **Startup firehose → replies only** — the boot burst no longer fires
  sweep/quote/RT rounds: with 2 QRT + 2 RT slots/day it would burn the
  whole quota on stale feed content at launch. Replies (unlimited) keep
  the 3-round burst.
- **autonomous_growth_agent prompt** re-bounded to the spec mix (it said
  "keep retweets/quotes high" — anti-spec; volume lever is replies).
- **Weekly review** now includes top posts by likes/views with engagement
  rate + pillar tag (from the rebuilt own-metrics scraper).

### 2026-06-07 PM — spec round 2 (operator: "implement everything")

- **Unfollowing OFF in the bot** (operator: "don't unfollow in this bot, I'll
  be the one doing unfollow myself"): `MAX_UNFOLLOWS_PER_DAY=0` +
  `UNFOLLOW_CAP_PER_CYCLE=0`; `smart_unfollow_bot` bails before any Safari
  work at cap 0. `bin/mass_unfollow.py` (the operator's `/unfollow` skill)
  records straight to the ledger and is NOT blocked by the cap.
- **Freshness-first reply ordering** — `direct_reply._freshness_sort_key`
  orders every reply candidate list: <60-min bucket first, then ≤6h, then
  older, unknown-age last; likes-per-hour velocity breaks ties. Applied
  inside `_reply_to_tweets` so direct_reply AND feed_sweeper inherit it
  (sweeper's `random.shuffle` removed).
- **Pillar attribution** — `src/pillar_tags.py` classifies every outgoing
  text into the spec pillars (market_trauma / ai_vs_btc / meme_reaction /
  reply_bait / ai_news_take / other), logged as engagement_log column 7 at
  the `engagement_log` chokepoint. Analyzer emits `pillar_mix_7d/24h`
  (classify-on-the-fly for old rows). spicy/breakout/text-stunt posts now
  log to engagement_log at all (they were invisible to the ROI loop).
- **smart_trim at the reply chokepoint** — >278-char replies get a
  sentence-boundary trim then re-validate instead of being discarded with
  their paid LLM call (several/day in the log).
- **Cron-anchored posting slots** — originals fire at 09:30 / 12:30 / 16:30
  / 20:00 New York via `run_post_slot` (tries news/hotake → breakout →
  spicy → stunt, stops on the first landed post; 12:30 leads with the GIF
  stunt for the daily native-media original). hotake/spicy/breakout/stunt
  interval jobs removed; thread/digest/recap bots DISABLED (threads aren't
  in the spec mix and were eating the 4/day cap ahead of slots).
- **Weekly review** — `src/weekly_review_bot.py` writes `weekly_review.md`
  Sundays ≥17:00 NY (idempotent per ISO week): follower Δ, following vs the
  300 cap, action + pillar mix, spec targets. Deterministic, no LLM.

### 2026-06-07 PM — pre-LLM dedup re-check on the reply hot paths

Audit of bot.log on 06-07 06:30 turned up 422 `[REPLY] already replied to this
tweet (chokepoint dedup) — skipping` entries from the day, and 352 the day
before. Each one is a tweet that the chokepoint in
`twitter_client.reply_to_tweet` correctly refused — but only AFTER the ollama
DIRECT_REPLY call burned ~17s generating the reply. Pattern in the log was
unambiguous: `[LLM] DIRECT_REPLY:` at T, `[REPLY] already replied … skipping`
at T+17s. At 774 hits / 48h that is ~3.6h of wasted compute per day, on
ollama time we want spent on actually-fresh candidates.

Root cause: each reply bot (`direct_reply`, `feed_sweeper_bot`,
`retweet_bot._reply_after_repost`) loads `replied_tweets.json` once at cycle
start. While the cycle is iterating, OTHER reply bots are writing new URLs
to the same file. The cycle's in-memory snapshot drifts stale. The
in-memory `if url in replied: continue` check passes, the LLM runs, and the
chokepoint (which loads fresh from disk) is the first guard that sees the
race.

Fix: `_reply_to_tweets` and `retweet_bot._reply_after_repost` now call
`load_replied()` **just before** `_generate_single_reply` and skip if the URL
landed on disk meanwhile. The fresh load is ~5ms against the 10k-URL store —
cheap relative to a saved ~17s LLM call. The chokepoint stays as the final
guard. Guard test `test_reply_skips_llm_when_concurrent_bot_already_replied`
pins the contract: a URL another bot wrote between snapshot and LLM call must
be skipped before generation runs.

Lesson: a chokepoint that loads-from-disk is the right last line of defense,
but it is NOT a free correctness gate — every check that runs after an
expensive call costs the wasted call. When you see a chokepoint dedup firing
in volume, walk the call chain backward and re-do the same disk check at the
earliest cheap point.

### 2026-06-07 — engine-health suppresses alert when surface fired within last hour

The clamp-by-cap fix (PR #7) silenced the cap-policy false positives but a
third class of false positive kept firing. 2026-06-07 04:01:30 logged
`hotake collapsed: 2 today vs ~10 by this hour over the last 7 days (20%)`
while the hotake bot was firing at MAX cadence (every 20 min: 03:23, 03:43,
04:02). The baseline of ~10 averages days where the cycle was faster (e.g.
06-04 hour 02 had 6 fires alone); today's 2 just means today started slower
or had skips. Bot was alive and pacing exactly as designed — but the alert
fired anyway, and the same noise had repeated 5x on 06-06 morning, each time
burning the self-heal cooldown on a healthy engine.

Fix: `_counts_by_day_hour` now also returns `latest_hour_today` (`{kind:
max_hour}`). In `run_engine_health_cycle`, before appending an alert,
`if latest_hour_today.get(kind, -1) >= hour_now - 1: continue` — a surface
that fired in the current or previous clock hour is alive, just slow.
Sustained silence (≥2 hours since the last fire) still alerts. Two new
guard tests pin the contract: recent-fire suppresses, 2h-stale fire alerts.

Lesson: a slower cadence and a dead surface look identical in a
cumulative-by-hour comparison. The cheap signal that disambiguates them is
"did anything from this kind happen in the last hour?" — the same kind of
intent-aware guard as PR #6 (cap=0) and PR #7 (today≥cap).

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

**Default AI provider: Claude Code CLI** (`AI_CLI=claude`, since 2026-06-07 — operator: "claude code cli as main one"). **Ollama is the fallback** (`LLM_FALLBACK_CLI=ollama` → local HTTP path with `OLLAMA_MODEL`) when claude fails.

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

User-invokable slash commands live under `.claude/skills/` (mirrored at `.codex/skills/`). 27 skills, each is a directory with a `SKILL.md` file:

- **Lifecycle**: `start`, `stop`, `restart`, `status`, `run-agent`
- **Manual triggers**: `post`, `reply`, `engage`, `boost`, `hotake`, `news`, `tweet`, `thread`, `dryrun`
- **Account ops**: `follow`, `unfollow` (mass-unfollow on /following via `bin/mass_unfollow.py` — keep-set protected, ledger-recorded), `like`, `accounts`, `history`
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

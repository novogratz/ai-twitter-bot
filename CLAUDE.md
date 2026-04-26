# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup

```bash
pip install -r requirements.txt
```

No API keys needed. The bot posts via browser + AppleScript (macOS only) and uses the Claude Code CLI subscription for AI generation.

The only requirement is that the `claude` CLI is installed and authenticated:
```bash
claude login
```

## Running

Use skills (slash commands) to control the bot:

```
/start              # Start full bot in background (all systems)
/stop               # Stop the bot gracefully
/restart            # Stop then start
/status             # Quick health check - running?, counters, errors
/run-agent          # Run as Claude Code agent (replaces python main.py)
```

### Manual triggers
```
/post               # Trigger one post cycle (news or hot take)
/reply              # Trigger one reply cycle
/engage             # Trigger one engage cycle (follow + like)
/boost              # Self-retweet latest tweet
/hotake             # Generate a hot take, preview, then post
/news               # Generate a news tweet preview
/tweet              # Post a specific tweet right now
/thread             # Post a multi-tweet thread
/follow             # Follow a specific account
/like               # Visit a profile and like their tweets
/dryrun             # Preview what the bot would do without posting
```

### Monitoring & config
```
/stats              # Full engagement dashboard
/logs               # Recent bot logs
/history            # Recent tweet history
/accounts           # View/manage target accounts
/config             # View/edit bot configuration
/reset              # Reset daily counters
/improve            # Self-improvement cycle from performance data
```

The bot runs 4 systems: reply bot first (scan for tweets), then post bot, then schedules all jobs (posts, replies, engagement, notification farming). Each cycle is wrapped in error handling so the scheduler stays alive. Graceful shutdown via Ctrl+C or SIGTERM.

## Architecture

AI, crypto and bourse news. Sharp takes. Zero bullshit. Tu vas me détester jusqu'à ce que j'aie raison. Follow @kzer_ai.

Autonomous bot covering AI + crypto + bourse with smart, philosophical, meme-style commentary. The sharpest critic in the room — but always trolls IDEAS, never PEOPLE.

### HARD RULES (only two — everything else is mutable strategy the bot can evolve)

1. **Aucun contenu illegal.** Sous aucune forme.
2. **Aucun troll / mocking / attaque du gouvernement americain** (US gov, administrations, presidents passes ou actuels, agences federales: Fed, SEC, CFTC, IRS, FBI, DOJ). Commenter les FAITS de leurs decisions OK, troller / mocker / attaquer NON. En cas de doute -> SKIP.

These two rules are stamped into every generation prompt via `personality_store.HARD_RULES_BLOCK` and into the reflection agent's dossier-writing prompt. Everything else below (BLOCKLIST, troll-ideas-not-people, no em dashes, FR priority, niches, cadences, etc.) is **defaultstrategy that the bot is authorized to evolve** via the operator layer / strategy agent / evolution agent / reflection agent.

### Strategy
- **French-near-exclusive**: Audience is 100% francophone. Aim **90%+ French replies** (was 60-70%). EN tweets only when the news is huge AND the FR commentary adds a unique franco-french angle. Hot takes mostly French.
- **Comedy DNA — 6 patterns + FR cultural anchors**: Every news/reply must use ≥1 of: (1) répétition qui tue, (2) mini-dialogue FR, (3) métaphore tueuse, (4) renaming, (5) callback culturel FR (RER B, Bercy, syndicat, BFM, "et les charges?", Macron, tonton à Noël, café-clope, coach Tesla, formations à 2k€), (6) understatement brutal. Validated by user feedback ("Getafe. Getafe.", "S&P 7", "syndicat: oui mais qui tamponne le bon de sortie?").
- **AI + crypto + bourse**: Three niches. Engage list and reply targets cover all three.
- **Troll ideas, never people**: Roast trends, hype, concepts, systems. NEVER mock the influencer's coaching, training, business, audience. Influencer should be able to like our reply.
- **Replies are the growth engine**: 3-4 replies every 20 min, French priority.
- **Hot takes are memes**: 4/day - smart, sharp, philosophical, laugh-out-loud, screenshot-worthy.
- **News**: 10/day cap (configurable). 3 niches (AI + crypto + bourse) so volume is shared across them. News-first policy: first 3 posts of the day MUST be news. Every news post needs a PUNCH — sourced article without a joke = failure. SETUP → PUNCH format, troll the idea/trend/market.
- **Humanizer on everything**: Every post goes through a human-pass.
- **Self-improving**: Scrapes own metrics every 2h and adapts prompts.
- **Autonomous discovery**: Every 6h, finds new crypto/AI/bourse influencers and adds them to monitoring. Approved FR ai/crypto/bourse accounts get auto-followed.
- **Blocklist**: `BLOCKLIST` in `src/config.py` — `@pgm_pm` (La Pique). Skipped in reply/replyback paths so we never get sucked into a bot-vs-bot loop.
- **Roast bot**: Dedicated path for `@pgm_pm` — visits his profile every 10 min and posts ONE sarcastic reply per ORIGINAL tweet (URL dedup hard-caps to 1 per tweet). Roasts the *phenomenon* (auto-replies, scripted prises), never the person.
- **Anti-spam**: Slower cadences + jitter + quiet hours (1am-7am Paris). Engagement cycles (replies, engage, direct-reply, early-bird, roast, notify, replyback) are SKIPPED during quiet hours so the account looks human. News still flows but at slowest cadence (info doesn't sleep). Target: ~80-100 actions/day total (was 250+).
- **Impact filter**: News + reply prompts force the agent to SCORE 3-5 candidates 1-10 (surprise + angle + stakes + division) and SKIP unless best ≥ 7. Mid > silence on the timeline.
- **Skip dead tweets**: Scraper extracts likes + replies counts via aria-label parsing; tweets with 0 likes AND 0 replies are skipped everywhere (direct_reply, roast_pgm_bot). No point replying where no one's looking.
- **Hot-tweet sources**: Search queries use `min_faves:N` to surface already-engaged tweets. New `scrape_x_search(tab="top")` hits X's algorithmic Top tab. HOT_TAB_QUERIES list adds a guaranteed-hot pass per cycle (every query carries a `min_faves:` floor — "Top" alone returns 0-like tweets so the filter is mandatory). Claude / Claude Code surfaced as the hot topic.
- **Quote cards on hot takes**: Hot takes ship with a generated PNG quote-card (clean dark background, @kzer_ai branded, random palette). Pasted via clipboard into /compose/post. Requires Pillow — falls back to text-only if missing.
- **Autonomous strategy agent**: Every 6h, an agentic Claude run reads the engagement log + uses tools (WebSearch, Read, Bash) to investigate what's actually working AND what's trending in FR AI/crypto/bourse RIGHT NOW. Proposes JSON; the Python wrapper APPLIES additions only (queries → `dynamic_queries.json`, accounts → `dynamic_accounts.json`). Direct_reply merges these with its static lists at runtime. Removals stay manual (safety boundary). Audit trail in `strategy_log.json`.
- **Source attribution**: Every reply written to `engagement_log.csv` carries a `source` tag (e.g. `PROFILE-FR/MathieuL1`, `SEARCH-FR-HOT/Bitcoin lang:fr`). The strategy agent uses this to compute per-source ROI.
- **Quote tweets**: Cap 2/day. Picks the most-liked viral FR tweet in our niches and posts a sharp meme observation as a quote-tweet (lands in followers' feed AND notifies the original author). Different distribution surface than replies.
- **Boost (validated lever)**: Self-retweet of latest tweet every 4h (was 6h/8h). Confirmed: one boost pulled 200 views + 6 likes. Free distribution multiplier — cheapest action we have.
- **Fast feedback kill-switch**: `src/fast_feedback.py` runs every 2h via the perf cycle. Strategy-agent-added handles with ≥5 outbound attempts in 8h that aren't reinforced get fast-demoted with a 7d TTL (vs the 30d evolution-agent prune). Closes the gap between strategy_agent (6h additions) and evolution_agent (12h audits).
- **Autonomous operator mode**: when the user is away, a remote cron may run higher-level meta-improvements every few hours. Audit trail in `autonomous_log.md` (committed). Operator can push code + restart the bot autonomously. Never touches BLOCKLIST or quiet-hours boundaries.

### Bots

**Post bot** - 24 news + 24 hot takes/day (2x bump 2026-04-26 PM — user wants 1k followers in 2 weeks, "post 2 times more"). ~45% hot take roll on each cycle. **News format = MEME HOT TAKE + URL** (mandate 2026-04-26 PM): a screenshot-worthy punchline, then `\n\n` + raw article URL on its own line so X renders the link card. No "Selon X..." / "Breaking:" / news-report style. If the news doesn't lend itself to a meme → SKIP. News prompt also keeps FIRST-DERIVATIVE rule (reject angles BFM/Bloomberg would post as-is) + IMPACT FILTER (4×NO → SKIP). Humanizer on all output.

**Reply bot** - Cap 7 replies/cycle (3→5→7), every ~22 min jittered. French priority, bilingual. Impact-ranked (agent picks best of 6-8 candidates). Pre-filter dedup + blocklist + **source-aware engagement floor**: `REPLY_MIN_LIKES` (default 5) applies to random-discovery sources (SEARCH-FR-LIVE, SEARCH-FR-HOT) but is **bypassed for curated paths** (PROFILE-FR, FEED, FOLLOWING) per user directive 2026-04-26 PM ("GO CRAZY, comment everything from 1k+ FR accounts"). Content blocklist (e.g. "se poser") still active. Persisted memory of 2000 replied URLs. Quiet 1am-7am Paris.

**Engage bot** - 3-5 accounts/cycle, every ~45 min jittered. Targets merge static list + autonomously discovered handles. Quiet 1am-7am Paris.

**Notify + Boost bot** - Like replies on own tweets every 45 min (quiet 1am-7am Paris). When an INFLUENCER replies under our tweet, reply IN-THREAD (lands under their reply) — otherwise standalone @mention. Self-retweet every 6 hours.

**Discover bot** - Every 6h: searches X, scores candidates with Claude, appends approved handles to `discovered_accounts.json`. Also auto-follows the best new FR ai/crypto/bourse handles (persisted in `followed_accounts.json`).

**Roast bot** - Every ~20 min jittered: visits @pgm_pm's profile, posts up to 3 sarcastic replies on his original tweets (1 per URL via existing dedup). Quiet 1am-7am Paris. His replies on our tweets stay blocked via BLOCKLIST so no loop.

**Performance bot** - Scrapes likes/views every 2h. Identifies top/worst performers. Injects learnings into prompts.

**Reflection agent (personality / autobiographical brain)** - Every 6h: agentic Claude run reads engagement_log + replied_back + history + learnings, builds and updates `personality.json` — per-account dossiers (category: builder/predator/retail/media/influencer/institution/unknown; stance: respect/skeptical/hostile/neutral/pity/curious/fond; feelings; notes; predictions track-record; do; dont) + per-topic positions (stance, frame, accumulated evidence). Replies/quotes become PERSONAL because the bot remembers each account it interacts with. Read at prompt-time by `direct_reply` (per-author dossier) and by `agent`/`hotake_agent`/`reply_agent` (global mood). `engagement_log.log_reply` auto-bumps `interaction_count` per author so dossiers grow organically. Hard rules (no illegal / no US-gov troll) are baked in.

**Strategy agent (INPUT side)** - Every 6h: agentic Claude run with Read + WebSearch + Bash tools. Reads engagement_log.csv (per-source ROI), looks up live FR AI/crypto/bourse trends, proposes new search queries + accounts. Python wrapper APPLIES additions only — never removes. Outputs land in `dynamic_queries.json` / `dynamic_accounts.json` and are merged at runtime by direct_reply. Audit trail in `strategy_log.json`. Fully autonomous, no human in the loop.

**Evolution agent (OUTPUT side)** - Every 12h: agentic Claude run that reads engagement_log + performance_log, identifies what content patterns WIN and what dies, then ADAPTS:
  - Writes `directives.md` (overwritten each cycle) — short actionable rules ("toujours finir sur une chute", "drop 🚀, garde 🔥", "format mini-dialogue cartonne — refais"). Loaded by ALL generation agents (news/reply/hot take) at runtime.
  - Adds to `pruned_accounts.json` — handles that produced 0 engagement after ≥5 sollicitations get filtered from selectors. TTL 30 days (auto-expires so a slow week isn't a death sentence). Hard cap 3 prunes/cycle.
  - Adds to `reinforced_accounts.json` — handles whose tweets converted into our top posts get 2x weight in selectors. No TTL. Hard cap 5 reinforcements/cycle.
  Audit trail in `evolution_log.json`. The bot literally rewrites its own style guide twice a day.

**Quote-tweet bot** - Every 90 min, cap 12/day (was 2h/8): scrapes HOT FR tweets (min_faves:30), picks the single most-liked candidate, generates a sharp meme observation, posts it as a quote-tweet. New distribution surface (followers' feed + author notification). Pure additive growth — different surface than replies.

**Early-bird bot** - Every ~7 min jittered (12-min freshness window). Scrapes 3 random accounts from a 75-account roster (FR media + crypto/bourse FR + AI mega EN), replies to any tweet < 12 min old. Hard cap 1 reply/cycle. Quiet 1am-7am Paris. Top-5 reply on a viral tweet = 10-100x impressions multiplier. Source-tagged `EARLYBIRD/<handle>`.

**Reciprocity loop** - Inside notify_bot replyback: after handling influencer/standalone replies, picks up to 3 non-influencer engagers at random (60% probability per candidate so the pattern isn't mechanical) and visits their profile to LIKE one tweet AND FOLLOW BACK if not already following. Reply = strongest follow-back signal there is.

### Files

- **`src/config.py`** - Central config: handle, paths, limits (10 news, 4 hot takes), models, retry settings, BLOCKLIST, DISCOVERED_ACCOUNTS_FILE.
- **`src/agent.py`** - News agent. Opus + WebSearch.
- **`src/hotake_agent.py`** - Hot take agent. Sonnet. Smart/sharp/philosophical memes. Trolls ideas, never people.
- **`src/reply_agent.py`** - Reply agent. Sonnet + WebSearch. Bilingual (FR priority). Pulls discovered handles into prompt.
- **`src/replyback_agent.py`** - Reply-back agent. Sonnet, no web search. Matches reply's language.
- **`src/humanizer.py`** - Humanizer. Sonnet pass to make AI-generated text sound human.
- **`src/bot.py`** - Post orchestration. ~30% hot takes. Persistent daily limits.
- **`src/reply_bot.py`** - Reply orchestration. Pre-filter dedup + blocklist + intra-batch dedup. Cap 2000.
- **`src/engage_bot.py`** - Growth engine. Static list + discovered handles merged at load.
- **`src/notify_bot.py`** - Reply-back + boost. Influencer replies get nested in-thread responses.
- **`src/discover_bot.py`** - Autonomous influencer discovery (search X -> score with Claude -> persist). Auto-follows approved FR ai/crypto/bourse handles.
- **`src/roast_pgm_bot.py`** - Dedicated 1-roast-per-tweet bot for @pgm_pm. URL dedup hard-cap.
- **`src/performance.py`** - Self-improving. Scrapes metrics every 2h.
- **`src/engagement_log.py`** - CSV engagement logging.
- **`src/twitter_client.py`** - Browser automation with Safari lock + retry. `reply_to_tweet_in_thread()` for nested replies. `scrape_following_feed()` for the chronological Following tab. `scrape_x_search(tab="top")` for X's algorithmic Top results. `post_tweet(text, image_path=...)` attaches PNG via clipboard paste on /compose/post. Scraper returns likes/replies counts.
- **`src/image_gen.py`** - Generates PNG quote cards for hot takes (dark bg, accent bar, branded handle, random palette). Pillow-based; no-op if PIL missing.
- **`src/strategy_agent.py`** - **Autonomous self-improvement INPUT side (agentic).** Every 3h: spawns a Claude agent with Read+WebSearch+Bash tools, reads engagement log, investigates trends, proposes JSON. Python applies additions only.
- **`src/evolution_agent.py`** - **Autonomous self-improvement OUTPUT side (agentic).** Every 6h: spawns a Claude agent with Read tools, analyzes engagement_log + performance_log, identifies winning/losing patterns + dead/hot accounts. Outputs directives + prune list + reinforce list. Python applies with hard caps + TTL.

- **`src/topic_dedup.py`** - **Cross-format topic banlist (shared by news + hot take).** `extract_recent_topics()` returns a set of entities (Claude/Bitcoin/OpenAI/etc.) recurring in the last 24-48h. Both `agent.py` and `hotake_agent.py` import this so a topic can't appear once as a news post AND once as a hot take in the same 30 min window — would otherwise look like recycling.
- **`src/evolution_store.py`** - Append-only/TTL stores for the evolution agent: `directives.md` (overwritten each cycle), `pruned_accounts.json` (TTL 30d), `reinforced_accounts.json`. Helper `filter_and_weight(accounts)` used by all selectors.
- **`src/personality_store.py`** - Personality / autobiographical brain. Per-account + per-topic dossiers in `personality.json`. Helpers: `upsert_account`, `record_interaction`, `render_account_block(handle)` (per-author prompt block), `render_global_mood()` (aggregate state of mind), `HARD_RULES_BLOCK` (the two hard rules — stamped into every generation prompt).
- **`src/reflection_agent.py`** - Agentic Claude run every 6h that reads engagement / history / learnings and writes JSON patches applied via personality_store. The bot grows a relationship with each account in its orbit. Hard caps: 30 account updates / 10 topic updates per cycle.
- **`personality.json`** - Per-account dossiers + per-topic positions. Grows over time. Read at prompt-time.
- **`reflection_log.json`** - Audit trail of every reflection cycle.
- **`src/dynamic_strategy.py`** - Append-only stores: `dynamic_queries.json` (live + hot tabs) and `dynamic_accounts.json` (FR + EN). Read by direct_reply at runtime.
- **`src/quote_tweet_bot.py`** - Quote-tweet path. Cap 2/day. Picks the single most-liked viral FR tweet and amplifies it with a sharp observation.
- **`src/early_bird_bot.py`** - Early-bird reply path. ~7 min jittered, scans 3 of ~92 mega accounts (FR/QC/EN AI+crypto+bourse) for tweets < 12 min old. Cap 2 replies per cycle. Top-5-reply is 10-100x impressions vs. late-reply.
- **`src/health.py`** - Safari watchdog. Each safe_run_*_cycle calls `record_success(label)` / `record_failure(label)`. After 3 consecutive failures (10-min cooldown), force-restart Safari via osascript. Audit trail in `autonomous_log.md`, state in `safari_health.json`.
- **`src/pattern_tags.py`** - 6-pattern bandit attribution: REPETITION / DIALOGUE / METAPHOR / RENAME / FR_ANCHOR / UNDERSTATEMENT / OTHER. Generation prompts emit `[PATTERN: <id>]` line, extracted server-side and logged into `engagement_log.csv` 6th column. Evolution agent computes per-pattern ROI from this.
- **`src/roast_pgm_bot.py`** - 1-roast-per-tweet bot for @pgm_pm. URL dedup. **Circuit breaker**: 8 consecutive empty scrapes → 24h pause (auto-resets). Stops burning cycles when target suspends/blocks/private. State in `roast_state.json`.
- **`src/history.py`** - Tweet history persistence.
- **`main.py`** - CLI entry point. APScheduler. Signal handlers. Graceful shutdown.
- **`discovered_accounts.json`** - Persisted autonomously-discovered handles.
- **`dynamic_queries.json`** - Strategy-agent-added search queries (live + hot). Append-only.
- **`dynamic_accounts.json`** - Strategy-agent-added monitor handles (FR + EN). Append-only.
- **`strategy_log.json`** - Audit trail of every strategy-agent cycle.
- **`replied_tweets.json`** - Persisted reply dedup (cap 2000).
- **`replied_back.json`** - Persisted reply-back dedup (by URL).
- **`quoted_tweets.json`** - Persisted quote-tweet dedup.
- **`directives.md`** - Evolution-agent's current style guide (overwritten every 12h). Auto-injected into all generation prompts.
- **`pruned_accounts.json`** - Accounts the evolution agent has demoted (TTL 30d, max 3 added per cycle). Filtered from selectors.
- **`reinforced_accounts.json`** - Accounts the evolution agent has confirmed work (no TTL). Get 2x weight in selectors.
- **`evolution_log.json`** - Audit trail of every evolution cycle.

## Schedule (EST + Paris quiet hours)

| Time (EST)   | Post interval | Reply interval (Paris awake)         |
|--------------|---------------|--------------------------------------|
| 11pm - 8am   | 150-240 min   | SKIP between 1am-7am Paris (~7pm-1am EST) |
| 8am - 12pm   | 90-150 min    | ~25-38 min jittered                  |
| 12pm - 6pm   | 90-150 min    | ~25-38 min jittered                  |
| 6pm - 11pm   | 140-220 min   | ~25-38 min jittered                  |

Engage: ~45 min jittered (3-5 accounts/cycle, expanded list w/ FR media), quiet 1am-7am Paris. Notify: 45 min, quiet hours. Replyback: 60 min, cap 4, quiet hours. Reciprocity loop now FOLLOWS BACK engagers (not just likes). **Boost: every 3h (was 6h→4h→3h, validated lever, kept earning lift). Discover: every 3h (was 6h). Roast (@pgm_pm): ~20 min jittered, quiet hours. Performance: every 2h. Strategy agent: every 3h (was 6h — bot self-adjusts INPUT side multiple times/day). Evolution agent: every 6h (was 12h — auto-rewrites style guide more often). Quote-tweet bot: every 90 min (cap 12/day). Early-bird bot: ~7 min jittered (75-account roster), cap 2/cycle, quiet hours.**

**Graceful quiet-hour fade (FR + QC dual targeting)** — replaced the hard cliff with `should_skip_engagement()`:
- 04-07 Paris: 95% skip (deepest quiet — 4 of 6 hours dark, light pulse OK)
- 00-04 Paris (= QC primetime 18-22 ET): 25% skip (light-active, captures Quebec audience)
- weekend Sat/Sun 8-11 Paris: 30% skip (slow weekend mornings)
- else: 0% skip
- Cadences also accelerated for 16h-active profile: post 45-80min peak, reply 12-20min, direct-reply 13-19min, engage 26-38min, roast 12-17min, early-bird 5-7min.

## Key design notes

- No API keys needed (no Twitter API, no Anthropic API).
- French priority, bilingual (replies match tweet language). Scope: AI + crypto + bourse. 280 chars max.
- Troll IDEAS / TRENDS / CONCEPTS, never the person. Influencer should be able to like our reply.
- 10 news + 4 hot takes per day (defaults, configurable via env). News must troll hard — SETUP→PUNCH format.
- Hot takes = smart, sharp, philosophical memes. Screenshot-worthy.
- Replies are the #1 growth engine: French priority, then EN influencers.
- BLOCKLIST in `src/config.py` (currently `@pgm_pm`). Enforced everywhere.
- Reply dedup: persisted last 2000 URLs in `replied_tweets.json`. Pre-filter + intra-batch dedup.
- Replyback: influencer replies get NESTED in-thread responses (lands under their reply).
- Autonomous discovery: every 6h, populates `discovered_accounts.json`.
- Humanizer pass on ALL output.
- News agent: Opus. Reply + hot take + replyback + discovery: Sonnet.
- Browser automation via `webbrowser.open` + AppleScript. macOS only. Safari lock.
- No em dashes anywhere.
- Self-improving: scrapes own metrics every 2h **AND runs an autonomous agentic strategy cycle every 6h** that adds new queries/accounts based on per-source ROI + live trend research.
- Source attribution on every reply (`engagement_log.csv` source column) feeds the strategy agent's analysis.
- Append-only safety boundary on the strategy agent: it can ADD queries/accounts but never REMOVE — bad runs degrade gracefully.
- Persistent daily state survives process restarts.
- All limits configurable via environment variables.

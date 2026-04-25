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

### Strategy
- **French priority, bilingual**: Replies match the tweet's language (FR -> FR, EN -> EN). Aim ~60-70% French replies. Hot takes mostly French.
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
- **Anti-spam**: Moderate frequencies to avoid shadow bans.
- **Skip dead tweets**: Scraper extracts likes + replies counts via aria-label parsing; tweets with 0 likes AND 0 replies are skipped everywhere (direct_reply, roast_pgm_bot). No point replying where no one's looking.
- **Hot-tweet sources**: Search queries use `min_faves:N` to surface already-engaged tweets. New `scrape_x_search(tab="top")` hits X's algorithmic Top tab. HOT_TAB_QUERIES list adds a guaranteed-hot pass per cycle. Claude / Claude Code surfaced as the hot topic.
- **Quote cards on hot takes**: Hot takes ship with a generated PNG quote-card (clean dark background, @kzer_ai branded, random palette). Pasted via clipboard into /compose/post. Requires Pillow — falls back to text-only if missing.
- **Autonomous strategy agent**: Every 6h, an agentic Claude run reads the engagement log + uses tools (WebSearch, Read, Bash) to investigate what's actually working AND what's trending in FR AI/crypto/bourse RIGHT NOW. Proposes JSON; the Python wrapper APPLIES additions only (queries → `dynamic_queries.json`, accounts → `dynamic_accounts.json`). Direct_reply merges these with its static lists at runtime. Removals stay manual (safety boundary). Audit trail in `strategy_log.json`.
- **Source attribution**: Every reply written to `engagement_log.csv` carries a `source` tag (e.g. `PROFILE-FR/MathieuL1`, `SEARCH-FR-HOT/Bitcoin lang:fr`). The strategy agent uses this to compute per-source ROI.
- **Quote tweets**: Cap 2/day. Picks the most-liked viral FR tweet in our niches and posts a sharp meme observation as a quote-tweet (lands in followers' feed AND notifies the original author). Different distribution surface than replies.
- **Boost (validated lever)**: Self-retweet of latest tweet every 8h. Confirmed: one boost pulled 200 views + 6 likes. Free distribution multiplier — keep the cadence.

### Bots

**Post bot** - up to 10 news + 4 hot takes/day. ~30% hot take ratio. News must FOLLOW the SETUP→PUNCH format and make people laugh — sourced article without a joke = failure. Humanizer on all output.

**Reply bot** - 3-4 replies per cycle, every 20 min. French priority, bilingual. Pre-filter dedup + blocklist. Persisted memory of 2000 replied URLs.

**Engage bot** - 3-5 accounts per cycle, every 30 min. Targets merge static list + autonomously discovered handles.

**Notify + Boost bot** - Like replies on own tweets every 45 min. When an INFLUENCER replies under our tweet, reply IN-THREAD (lands under their reply) — otherwise standalone @mention. Self-retweet every 8 hours.

**Discover bot** - Every 6h: searches X, scores candidates with Claude, appends approved handles to `discovered_accounts.json`. Also auto-follows the best new FR ai/crypto/bourse handles (persisted in `followed_accounts.json`).

**Roast bot** - Every 10 min: visits @pgm_pm's profile, posts up to 3 sarcastic replies on his original tweets (1 per URL via existing dedup). Jittered between posts. His replies on our tweets stay blocked via BLOCKLIST so no loop.

**Performance bot** - Scrapes likes/views every 2h. Identifies top/worst performers. Injects learnings into prompts.

**Strategy agent** - Every 6h: agentic Claude run with Read + WebSearch + Bash tools. Reads engagement_log.csv (per-source ROI), looks up live FR AI/crypto/bourse trends, proposes new search queries + accounts. Python wrapper APPLIES additions only — never removes. Outputs land in `dynamic_queries.json` / `dynamic_accounts.json` and are merged at runtime by direct_reply. Audit trail in `strategy_log.json`. Fully autonomous, no human in the loop.

**Quote-tweet bot** - Every 4h, cap 2/day: scrapes HOT FR tweets (min_faves:30), picks the single most-liked candidate, generates a sharp meme observation, posts it as a quote-tweet. New distribution surface (followers' feed + author notification).

**Early-bird bot** - Every 5 min: scrapes 3 random mega accounts (sama, OpenAI, AnthropicAI, elonmusk, MathieuL1, etc.), replies within minutes to any tweet < 12 min old. Hard cap 1 reply per cycle. Being a top-5 reply on a viral tweet is a 10-100x impressions multiplier vs. landing #50 an hour later. Source-tagged `EARLYBIRD/<handle>`.

**Reciprocity loop** - Inside notify_bot replyback: after handling influencer/standalone replies, picks up to 2 non-influencer engagers at random (50% probability per candidate so the pattern isn't mechanical) and visits their profile to like 1 tweet. Triggers a notification on their side; often converts to follow-back.

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
- **`src/strategy_agent.py`** - **Autonomous self-improvement (agentic).** Every 6h: spawns a Claude agent with Read+WebSearch+Bash tools, reads engagement log, investigates trends, proposes JSON. Python applies additions only.
- **`src/dynamic_strategy.py`** - Append-only stores: `dynamic_queries.json` (live + hot tabs) and `dynamic_accounts.json` (FR + EN). Read by direct_reply at runtime.
- **`src/quote_tweet_bot.py`** - Quote-tweet path. Cap 2/day. Picks the single most-liked viral FR tweet and amplifies it with a sharp observation.
- **`src/early_bird_bot.py`** - Early-bird reply path. Every 5 min, scans 3 mega accounts for tweets < 12 min old. Cap 1 reply per cycle. Top-5-reply is 10-100x impressions vs. late-reply.
- **`src/history.py`** - Tweet history persistence.
- **`main.py`** - CLI entry point. APScheduler. Signal handlers. Graceful shutdown.
- **`discovered_accounts.json`** - Persisted autonomously-discovered handles.
- **`dynamic_queries.json`** - Strategy-agent-added search queries (live + hot). Append-only.
- **`dynamic_accounts.json`** - Strategy-agent-added monitor handles (FR + EN). Append-only.
- **`strategy_log.json`** - Audit trail of every strategy-agent cycle.
- **`replied_tweets.json`** - Persisted reply dedup (cap 2000).
- **`replied_back.json`** - Persisted reply-back dedup (by URL).
- **`quoted_tweets.json`** - Persisted quote-tweet dedup.

## Schedule (EST)

| Time (EST)   | Post interval | Reply interval |
|--------------|---------------|----------------|
| 11pm - 8am   | 240-420 min   | 20 min         |
| 8am - 12pm   | 120-200 min   | 20 min         |
| 12pm - 6pm   | 90-160 min    | 20 min         |
| 6pm - 11pm   | 150-240 min   | 20 min         |

Engage bot: every 30 min (3-5 accounts, 3 likes each). Notify bot: every 45 min. Replyback: every 60 min (includes reciprocity loop). Boost: every 6h (validated). Discover: every 6h. Roast (@pgm_pm): every 10 min. Performance: every 2h. **Strategy agent: every 6h (autonomous self-improvement). Quote-tweet bot: every 4h. Early-bird bot: every 5 min.**

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

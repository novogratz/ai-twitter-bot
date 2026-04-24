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
- **News**: 18/day cap (configurable), only real stories.
- **Humanizer on everything**: Every post goes through a human-pass.
- **Self-improving**: Scrapes own metrics every 2h and adapts prompts.
- **Autonomous discovery**: Every 6h, finds new crypto/AI/bourse influencers and adds them to monitoring.
- **Blocklist**: `BLOCKLIST` in `src/config.py` — currently `@pgm_pm` (La Pique). Never reply.
- **Anti-spam**: Moderate frequencies to avoid shadow bans.

### Bots

**Post bot** - up to 18 news + 4 hot takes/day. ~30% hot take ratio. Humanizer on all output.

**Reply bot** - 3-4 replies per cycle, every 20 min. French priority, bilingual. Pre-filter dedup + blocklist. Persisted memory of 2000 replied URLs.

**Engage bot** - 3-5 accounts per cycle, every 30 min. Targets merge static list + autonomously discovered handles.

**Notify + Boost bot** - Like replies on own tweets every 45 min. When an INFLUENCER replies under our tweet, reply IN-THREAD (lands under their reply) — otherwise standalone @mention. Self-retweet every 8 hours.

**Discover bot** - Every 6h: searches X, scores candidates with Claude, appends approved handles to `discovered_accounts.json`.

**Performance bot** - Scrapes likes/views every 2h. Identifies top/worst performers. Injects learnings into prompts.

### Files

- **`src/config.py`** - Central config: handle, paths, limits (18 news, 4 hot takes), models, retry settings, BLOCKLIST, DISCOVERED_ACCOUNTS_FILE.
- **`src/agent.py`** - News agent. Opus + WebSearch.
- **`src/hotake_agent.py`** - Hot take agent. Sonnet. Smart/sharp/philosophical memes. Trolls ideas, never people.
- **`src/reply_agent.py`** - Reply agent. Sonnet + WebSearch. Bilingual (FR priority). Pulls discovered handles into prompt.
- **`src/replyback_agent.py`** - Reply-back agent. Sonnet, no web search. Matches reply's language.
- **`src/humanizer.py`** - Humanizer. Sonnet pass to make AI-generated text sound human.
- **`src/bot.py`** - Post orchestration. ~30% hot takes. Persistent daily limits.
- **`src/reply_bot.py`** - Reply orchestration. Pre-filter dedup + blocklist + intra-batch dedup. Cap 2000.
- **`src/engage_bot.py`** - Growth engine. Static list + discovered handles merged at load.
- **`src/notify_bot.py`** - Reply-back + boost. Influencer replies get nested in-thread responses.
- **`src/discover_bot.py`** - Autonomous influencer discovery (search X -> score with Claude -> persist).
- **`src/performance.py`** - Self-improving. Scrapes metrics every 2h.
- **`src/engagement_log.py`** - CSV engagement logging.
- **`src/twitter_client.py`** - Browser automation with Safari lock + retry. `reply_to_tweet_in_thread()` for nested replies.
- **`src/history.py`** - Tweet history persistence.
- **`main.py`** - CLI entry point. APScheduler. Signal handlers. Graceful shutdown.
- **`discovered_accounts.json`** - Persisted autonomously-discovered handles.
- **`replied_tweets.json`** - Persisted reply dedup (cap 2000).
- **`replied_back.json`** - Persisted reply-back dedup (by URL).

## Schedule (EST)

| Time (EST)   | Post interval | Reply interval |
|--------------|---------------|----------------|
| 11pm - 8am   | 240-420 min   | 20 min         |
| 8am - 12pm   | 120-200 min   | 20 min         |
| 12pm - 6pm   | 90-160 min    | 20 min         |
| 6pm - 11pm   | 150-240 min   | 20 min         |

Engage bot: every 30 min (3-5 accounts, 3 likes each). Notify bot: every 45 min. Replyback: every 60 min. Boost: every 8h. Discover: every 6h. Performance: every 2h.

## Key design notes

- No API keys needed (no Twitter API, no Anthropic API).
- French priority, bilingual (replies match tweet language). Scope: AI + crypto + bourse. 280 chars max.
- Troll IDEAS / TRENDS / CONCEPTS, never the person. Influencer should be able to like our reply.
- 18 news + 4 hot takes per day (defaults, configurable via env).
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
- Self-improving: scrapes own metrics every 2h.
- Persistent daily state survives process restarts.
- All limits configurable via environment variables.

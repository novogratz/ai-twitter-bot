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

```bash
python main.py              # Run all bots
python main.py --post-only  # Run only the post bot
python main.py --reply-only # Run only the reply bot
python main.py --dry-run    # Print actions without posting
```

The bot runs 4 systems: reply bot first (scan for tweets), then post bot, then schedules all jobs (posts, replies, engagement, notification farming). Each cycle is wrapped in error handling so the scheduler stays alive. Graceful shutdown via Ctrl+C or SIGTERM.

## Architecture

Le compte IA/Crypto/Finance le plus tranchant sur X. Le plus rapide sur les news. Le plus gros troll de la salle. 0% bullshit. Follow @kzer_ai.

Bot autonome qui couvre l'actu IA, crypto et marchés/investissements. Balance des réponses troll hilarantes, poste des hot takes philosophiques. Tout en FRANÇAIS. Audience francophone. Qualité élite, pas de spam.

### Smart Features
- **Tout en français**: Posts, réponses, hot takes - tout en français avec accents obligatoires
- **3 domaines**: IA + Crypto + Investissements/Marchés
- **Rythme humain**: ~5 news + ~3 hot takes par jour. Comme un vrai mec qui tweete entre deux trucs
- **TROLL MODE**: Le plus tranchant, le plus drôle, le plus provocateur
- **Self-improving**: Scrape ses propres métriques (likes/vues) et adapte son style automatiquement
- **Auto-follow**: Suit les top comptes IA/crypto/finance, priorité aux comptes francophones
- **Safari lock**: Un seul bot utilise le navigateur à la fois (pas de texte garbled)
- **Structured logging**: Logs rotatifs (bot.log), CSV engagement tracking
- **Persistent state**: Compteurs journaliers survivent aux restarts
- **22 slash commands**: Contrôle total depuis Claude Code

### 5 Bots

**Post bot** - News IA/crypto/finance en français (Opus, avec web search) + hot takes (Sonnet, sans web search). ~5 news + ~3 hot takes par jour (rythme humain). Threads pour les grosses stories.

**Reply bot** - 5-7 réponses de haute qualité par cycle. Tourne toutes les 5 min. TROLL MODE MAXIMUM. Cherche des tweets francophones en priorité, répond toujours en français. Cible les gros posts IA/crypto/finance. Quote tweets sur ~15%.

**Engage bot** - 8-12 comptes par cycle toutes les 10 min. Auto-follow + 3 likes par visite. Comptes IA + crypto + finance, priorité aux comptes francophones.

**Notify + Boost bot** - Like les réponses sur nos tweets toutes les 8 min. Self-retweet toutes les 45 min.

**Performance bot** - Scrape likes/vues toutes les 2h. Identifie top/worst performers. Injecte les learnings dans les prompts.

### Files

- **`src/config.py`** - Central configuration: bot handle, file paths, daily limits, models, retry settings. All configurable via environment variables.
- **`src/logger.py`** - Structured logging with rotating file handler (5MB, 3 backups). Used by all modules.
- **`src/agent.py`** - News tweet agent. Opus + WebSearch. French prompt. IA + Crypto + Investissements. Returns `SKIP` if no fresh news.
- **`src/hotake_agent.py`** - Hot take agent. Sonnet, no web search. French. IA + Crypto + Investissements trolling.
- **`src/reply_agent.py`** - Reply agent. Single Sonnet + WebSearch. 5-7 tweets per cycle. French only. IA + Crypto + Investissements. Targets big francophone posts. This week only.
- **`src/replyback_agent.py`** - Reply-back agent. Sonnet, no web search. Generates witty replies to people who reply to our tweets.
- **`src/bot.py`** - Post orchestration. ~60% news, ~40% hot takes. Persistent daily limits (5 news, 3 hot takes). Falls back to hot take when no news. Handles threads. Engagement logging.
- **`src/reply_bot.py`** - Reply orchestration. Refreshes feed, generates replies with cross-dedup, auto-likes, posts replies. Engagement logging.
- **`src/engage_bot.py`** - Growth engine. Auto-follows AI/crypto/finance accounts, priorité francophones. Likes their latest 3 tweets.
- **`src/notify_bot.py`** - Notification farmer. Visits own latest tweet, likes up to 8 replies. Self-retweet every 45 min.
- **`src/performance.py`** - Self-improving system. Scrapes own metrics, identifies top/worst tweets, generates learnings for prompts.
- **`src/engagement_log.py`** - CSV engagement logging. Tracks all posts, replies, hot takes with timestamps.
- **`src/twitter_client.py`** - Browser automation with Safari lock and retry logic: `post_tweet()`, `post_thread()`, `reply_to_tweet()`, `quote_tweet()`, `follow_account()`, `visit_profile_and_like()`, `like_own_tweet_replies()`, `refresh_feed()`, `like_tweet()`, `close_front_tab()`.
- **`src/history.py`** - Tweet history persistence, dedup, capped at 500 entries.
- **`main.py`** - CLI entry point. APScheduler with 6 jobs. Argument parser. Signal handlers. Graceful shutdown.

## Schedule (EST)

| Time (EST)   | Post interval | Reply interval |
|--------------|---------------|----------------|
| 11pm - 7am   | 180-300 min   | 5 min          |
| 7am - 10am   | 80-140 min    | 5 min          |
| 10am - 1pm   | 60-100 min    | 5 min          |
| 1pm - 5pm    | 70-120 min    | 5 min          |
| 5pm - 9pm    | 80-140 min    | 5 min          |
| 9pm - 11pm   | 120-180 min   | 5 min          |

Engage bot: every 10 min (follow + like 3 tweets). Notify bot: every 8 min (like 8 replies). Boost bot: every 45 min (self-retweet). Performance: every 2h. All 24/7.

## Key design notes

- No API keys needed (no Twitter API, no Anthropic API).
- Tout en FRANÇAIS, 280 chars max. Audience francophone.
- IA + CRYPTO + INVESTISSEMENTS. Les 3 domaines qui bougent le plus.
- ~5 news + ~3 hot takes par jour. Rythme humain, pas de spam.
- TROLL MODE: le plus tranchant, le plus drôle, le plus provocateur.
- News agent: Opus (deep analysis, better research). Reply + hot take agents: Sonnet.
- Browser automation via `webbrowser.open` + AppleScript with retry logic. macOS only.
- Safari lock (threading.Lock) prevents multiple bots from using Safari simultaneously.
- Safari tabs auto-close after every action.
- Auto-follows top IA/crypto/finance accounts, priorité francophones.
- Likes 3 tweets per profile visit.
- Auto-likes tweets before replying (double notification).
- Notification farming: likes 8 replies on own tweets every 8 min.
- Self-retweet every 45 min.
- Cross-dedup between reply bot and post bot.
- No em dashes anywhere.
- Accents obligatoires: é, è, ê, à, â, ô, î, ç. Toujours.
- Commence toujours par une majuscule.
- Reply recency: this week only. News recency: today only.
- Reply volume: 5-7 per cycle, runs every 5 min. Single agent for speed.
- Target big posts with high engagement for maximum visibility on replies.
- Priorité tweets francophones pour les réponses.
- Structured logging to bot.log with rotation (5MB, 3 backups).
- Persistent daily state survives process restarts.
- Self-improving: scrapes own metrics every 2h, adapts prompts based on performance.
- All limits configurable via environment variables.
- Engagement tracking: all actions logged to engagement_log.csv.

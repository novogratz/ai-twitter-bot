# @kzer_ai - The Sharpest AI Account on X

The fastest AI news. The hardest takes. 0% bullshit. Powered by Claude Code.

## What It Does

4 autonomous bots running 24/7:

**Post Bot** - Finds breaking AI news via web search (Opus) and writes sharp English tweets. ~70 news posts + ~20 hot takes per day. Hot takes mix: AI philosophy, industry trolling, and personal AI tool reviews ("Just tested Claude Code and..."). Threads for big stories.

**Reply Bot** - Finds 10-14 AI tweets every 2 minutes and drops devastating one-liner replies. Matches tweet language (English or French). Targets big posts with high engagement + replies to top comments on viral threads. Auto-likes before replying.

**Engage Bot** - Auto-follows top AI accounts. Visits 5-8 profiles every 15 minutes, likes their latest 2 tweets. ~45 accounts: OpenAI, Anthropic, Google DeepMind, Sam Altman, Yann LeCun, Karpathy, and more. Tracks who's been followed.

**Notify Bot** - Likes up to 8 replies on own tweets every 10 minutes. People feel seen, come back, become regulars.

## Schedule (EST)

| Time         | Post interval | Reply interval | Engage     | Notify     |
|--------------|---------------|----------------|------------|------------|
| 11pm - 6am   | 30-45 min     | 2 min          | 15 min     | 10 min     |
| 6am - 7pm    | 15-20 min     | 2 min          | 15 min     | 10 min     |
| 7pm - 11pm   | 20-30 min     | 2 min          | 15 min     | 10 min     |

## Growth Features

- **AI-only focus** - Pure AI authority. No dilution.
- **High volume** - ~90 posts/day + ~400 replies/day
- **Auto-follow** - Follows top AI accounts automatically
- **Double-like** - Likes 2 tweets per profile visit
- **Personal experience tweets** - "Just tested [tool] and..." feels authentic, drives engagement
- **Big post targeting** - Replies to high-engagement tweets for max visibility
- **Auto-like before reply** - Double notification for tweet authors
- **Notification farming** - Likes 8 replies every 10 min, builds loyalty
- **Thread posting** - 2-3 tweet threads for big stories (algorithm boost)
- **Follow CTA** - ~25% of posts include "Follow @kzer_ai"
- **Cross-dedup** - Reply bot avoids topics the post bot just covered
- **Structured logging** - Rotating file logs + engagement CSV

## Setup

```bash
pip install -r requirements.txt
```

Install and authenticate the Claude Code CLI:

```bash
npm install -g @anthropic-ai/claude-code
claude login
```

No Twitter API keys. No Anthropic API key. Nothing else.

## Usage

```bash
python main.py              # Run all 4 bots
python main.py --post-only  # Only post news + hot takes
python main.py --reply-only # Only reply to tweets
python main.py --dry-run    # Print without posting
```

Stop with `Ctrl+C` (graceful shutdown).

## Configuration

Environment variables (all optional):

| Variable | Default | Description |
|----------|---------|-------------|
| `MAX_NEWS_PER_DAY` | 70 | Max news posts per day |
| `MAX_HOTAKES_PER_DAY` | 20 | Max hot takes per day |
| `NEWS_MODEL` | claude-opus-4-6 | Model for news tweets |
| `REPLY_MODEL` | claude-sonnet-4-6 | Model for replies |
| `HOTAKE_MODEL` | claude-sonnet-4-6 | Model for hot takes |

## Requirements

- macOS (posting uses AppleScript to automate Safari)
- Claude Code CLI installed and authenticated
- X/Twitter logged in on Safari

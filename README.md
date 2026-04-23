# ai-twitter-bot

The sharpest AI account on X/Twitter. Fastest news. Hardest takes. 0% bullshit. Powered by Claude Code.

## How it works

The bot runs 4 autonomous systems:

**Post bot** - Finds the freshest AI news via web search (Opus) and writes sharp English tweets (280 chars max). ~20% of posts are hot takes (Sonnet, no web search) for engagement. Posts threads for big stories. Falls back to hot takes when news is slow.

**Reply bot** - Drops 10-12 hilarious troll replies per cycle (Sonnet). French Twitter is #1 priority, any topic (tech, startups, dev life, AI, whatever is trending). Then English. Any account size. Full comedy mode. Auto-likes before replying. 20-30% are quote tweets. Replies match the language of the original tweet. Today only, last 30 min preferred.

**Engage bot** - Visits 3-5 target AI accounts every 25 minutes and likes their latest tweet. ~25 accounts including AI companies, leaders, influencers, and French tech. Builds reciprocity.

**Notify bot** - Every 20 minutes, visits own latest tweet and likes up to 5 replies. People feel seen, come back, become regulars. Signals active engagement to the algorithm.

## Schedule (EST)

Posts:
- Night (11pm-6am): every 45-75 min
- Morning rush (6am-10am): every 15-20 min
- Midday (10am-5pm): every 40 min
- Evening rush (5pm-7pm): every 15 min
- Wind down (7pm-11pm): every 40 min

Replies adapt to peak hours:
- Peak (6-9am, 2-5pm EST, 2-4am for France): every 3-5 min
- Default: every 8 min
- Late night: every 15-20 min

Engage bot: every 25 min. Notify bot: every 20 min.

## Growth features

- **Hot takes** - Engagement bait posts (unpopular opinions, rankings, predictions) with zero web search latency
- **French priority** - French Twitter is #1 priority, any topic. Searches "IA", "tech", "startup", "dev" first
- **High volume replies** - 10-12 replies per cycle in full troll/comedy mode
- **Strict recency** - All content must be from today, last 30 min preferred
- **Rising tweet targeting** - Replies to tweets posted 10-30 min ago for top-of-thread placement
- **Big account filter** - Prioritizes 10k+ follower accounts for replies
- **Quote tweets** - 20-30% of replies visible on own timeline
- **Like + reply combo** - Double notification for tweet authors
- **Thread posting** - 2-3 tweet threads for big stories (algorithm boost)
- **Engagement pods** - Auto-likes target AI accounts for reciprocity
- **Notification farming** - Likes replies on own tweets to build loyalty
- **Cross-dedup** - Reply bot avoids topics the post bot just covered
- **Follow CTA** - ~25% of posts include "Follow @kzer_ai"
- **Safari cleanup** - Auto-closes tabs after every action

## Setup

```bash
pip install -r requirements.txt
```

Install and authenticate the Claude Code CLI:

```bash
npm install -g @anthropic-ai/claude-code
claude login
```

No Twitter API keys, no Anthropic API key, nothing else.

## Usage

```bash
# Run the bot (all 4 systems)
python main.py

# Post a single tweet manually
python test_tweet.py
```

Stop with `Ctrl+C`.

## Requirements

- macOS (posting uses AppleScript to automate browser clicks)
- Claude Code CLI installed and authenticated
- X/Twitter logged in on your default browser (Safari)

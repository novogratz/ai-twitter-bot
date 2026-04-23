# ai-twitter-bot

L'actu IA, Crypto et Bourse avant tout le monde. Des prises de position tranchees. Zero bullshit. Tu me detesteras jusqu'a ce que j'aie raison. Powered by Claude Code. Tout en francais.

## How it works

The bot runs 4 autonomous systems:

**Post bot** - Finds the freshest IA/Crypto/Bourse news via web search (Opus) and writes sharp French tweets (280 chars max). ~20% of posts are hot takes (Sonnet, no web search) covering all 3 topics. Posts threads for big stories. All posts in French.

**Reply bot** - Drops 30-36 hilarious troll replies per cycle (Sonnet). 3x volume across IA + Crypto + Investissement. French Twitter is #1 priority. FULL TROLL MODE. Any account size. Auto-likes before replying. 20-30% are quote tweets (always in French). STRICT recency: last 30 min preferred, today only, NEVER older.

**Engage bot** - Visits 3-5 target accounts every 25 minutes and likes their latest tweet. ~40 accounts across AI, crypto, finance, and French tech. Builds reciprocity.

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

- **3 topics** - IA, Crypto, Investissement/Bourse. All covered in news, replies, and hot takes
- **Full French mode** - All posts, hot takes, and quote tweets in French. Replies match original tweet language
- **3x reply volume** - 30-36 replies per cycle (~10-12 per topic) in FULL TROLL MODE
- **Hot takes** - Engagement bait in French across all 3 topics with zero web search latency
- **French priority** - French Twitter is #1 priority, any topic. Searches "IA", "tech", "startup", "dev" first
- **High volume replies** - 10-12 replies per cycle in full troll/comedy mode
- **Strict recency** - All content must be from today, last 30 min preferred. NEVER yesterday or older. Date injected into prompts
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

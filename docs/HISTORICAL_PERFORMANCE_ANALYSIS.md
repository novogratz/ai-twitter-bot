# Historical Performance Analysis

Local data sources:

- `performance_log.json`: scraped recent main-post metrics
- `engagement_log.csv`: action ledger for posts, replies, quotes, retweets
- `self_winners.md`: recent main-post winners
- `reply_winners.md`: reply winner bank when available

## Main Posts

90-day local sample from `performance_log.json`:

- sample count: 200
- median impressions: 46.5
- average impressions: 589.89
- 75th percentile: 73
- 90th percentile: 96
- heuristic hits: 14
- heuristic breakouts: 1

The average is much higher than the median, which means a few outliers are carrying the account while the normal post is weak. This is the core main-post problem.

Top observed winner examples in `self_winners.md` are concise, human, and reactive:

- “Alphabet and ARM? Sounds less like ‘what next?’ and more like ‘please stop, my portfolio needs a nap.’”
- “Qwen beating Opus. me watching Opus finally lose its halo like: ‘well, there goes the ego tax.’”

These are not article summaries. They are short observations with voice.

## Replies

90-day local action sample:

- reply rows: 48,613
- top reply topics: markets, general AI, models, AI infrastructure, crypto
- top reply hook styles: surprising number, result-first, contradiction

The available local data does not include reliable per-reply impressions/likes for every reply, but the volume and winner-bank design show the account already treats replies as the discovery layer.

## Why Replies Outperform Main Posts

Supported hypotheses from repository evidence:

- replies inherit distribution from large or mid-size conversations
- replies are naturally shorter and more reactive
- reply prompts target concrete parent tweets, so they avoid abstract summary mode
- replies often start with the punchline or direct disagreement
- main posts are split across many surfaces and can drift into source compression
- quote posts can depend on someone else’s content for the interesting part

Transferable traits:

- directness
- brevity
- concrete named actors
- unexpected observation
- human/psychological frame
- no generic “AI news” summary voice

Non-transfer:

- do not repost replies as main posts
- do not copy reply text into a longer post
- do not turn every successful reply topic into a post without a standalone insight

## First Experiments

1. AI/human psychology standalone versus quote reaction.
   Hypothesis: standalone human-behavior observations outperform source-dependent quote reactions.

2. Contradiction hook versus summary hook.
   Hypothesis: “what people are missing” with one fact beats launch-summary openings.

3. Short personal observation versus medium explainer.
   Hypothesis: the “me watching...” energy from winners transfers reply naturalness into Home posts.

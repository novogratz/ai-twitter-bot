# Content Strategy

## Two Engines

Replies are the discovery and acquisition engine.

Main posts are the Home Timeline and account-identity engine.

The system should not optimize for more tweets. It should optimize for expected value per main post: quality, novelty, timeliness, credibility, audience fit, and AI Therapist fit.

## Reply Strategy

The reply system remains intact. It exists to:

- get noticed under relevant accounts
- create conversations
- generate profile visits
- detect audience interests
- seed future main-post opportunities

Reply lessons can inform main posts, but successful replies are not copied into main posts.

## Main-Post Workflow

The target editorial workflow is:

```text
Signal
Research packet
Insight candidates
Hook variants
Critic / scoring
Originality and fact checks
Format selection
Publish or human review
Measure
Learn
```

Sources provide facts. The AI Therapist provides the insight.

The current Phase 1 implementation lives in `src/original_content_engine.py`.
Every scheduled standalone slot now tries this engine first:

```text
editorial brief + opportunity queue
        |
        v
15-30 candidate posts
        |
        v
semantic deduplication
        |
        v
quality / originality / genericness / clickbait / repetition / factuality scoring
        |
        v
publish one winner, queue for review, or skip the slot
        |
        v
best-effort first comment to create an early reply surface
```

The engine is intentionally allowed to skip. A blank slot is better than a
generic post that trains the audience to ignore the profile.

Standalone posts should be written for discussion, not applause. The best
version leaves a specific human tension open enough that readers can answer
with a story, disagreement, or example.

## Impact Mode

Standalone originals now run in hot-AI impact mode:

- One startup impact-original attempt after the source/opportunity queue is refreshed.
- 10 original slot attempts per day across US waking hours, with quality gates expected to publish roughly 7-10 strong posts.
- 80-minute minimum spacing between standalone posts.
- 30 candidates per slot with stricter 84/82 quality and originality floors.
- AI relevance is mandatory for original-engine candidates.
- Fresh source material is preferred from primary AI sources and high-quality AI reporting.
- Legacy hot-take, breakout, spicy, and stunt surfaces no longer fill standalone post slots; the original engine owns that inventory.
- Replies are not reduced; they remain the discovery engine.

The source registry scores stories by AI relevance, source reliability, human
impact, novelty, urgency, and saturation. Crypto/market stories without a clear
AI-human angle are filtered out of the original-engine opportunity feed.

## Reply-To-Post Flywheel

```text
High-performing reply
        |
        v
Identify resonant idea
        |
        v
Research deeper
        |
        v
Generate a new original insight
        |
        v
Standalone main post
```

The new growth layer uses reply analytics as an audience sensor. It increases the prior for topics that repeatedly show up in reply activity, while still requiring a strong standalone opportunity.

## Voice

The account should sound like a sharp, curious, very online observer of AI who is fascinated by what AI reveals about humans.

Prefer:

- specific facts
- second-order effects
- human behavior implications
- concise observations
- defensible opinions
- uncertainty when warranted

Avoid:

- generic launch summaries
- “game changer” language
- fake certainty
- repetitive hooks
- source-dependent quote reactions
- empty engagement bait

## Content Types

Supported main-post formats:

- breaking insight
- hot take
- second-order effect
- explainer
- prediction
- contrarian analysis
- data observation
- AI/human observation
- thesis update
- original synthesis
- open question

Standalone should generally be the default. Quote posts remain useful when the source context is essential and the commentary adds substantial new value.

## Phase Roadmap

Phase 1 is implemented: preserve replies, strengthen standalone generation,
rank many candidates, add genericness/repetition checks, and separate original
analytics from reply analytics.

Phase 2 should deepen the existing external-signal layer into a formal source
registry, primary-source resolver, news scorer, breaking-news scheduler, and AI
Therapist news-angle generator.

Phase 3 should mine successful replies into trend models, expand experiments,
and produce weekly strategy recommendations without automatically rewriting the
account strategy from tiny samples.

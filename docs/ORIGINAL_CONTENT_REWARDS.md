# Original Content Rewards

## Goal

Primary objective:

500,000 qualifying Home Timeline impressions over a rolling 90-day period.

## Official Versus Estimated Metrics

The local repository can estimate supporting metrics from scraped post views, but it does not currently have the official X qualified Home Timeline metric.

Do not treat ordinary scraped impressions as the official rewards metric.

The growth dashboard reads optional manual input from:

```text
official_rewards_metric.json
```

Suggested schema:

```json
{
  "official_qualified_home_impressions_90d": 123456,
  "recorded_at": "2026-08-18T19:00:00"
}
```

If this file is absent, `growth/home_timeline_500k_dashboard.json` clearly labels progress as supporting/estimated only.

## Supporting Metrics

The dashboard tracks:

- rolling 90-day main-post impressions estimate
- main-post count
- median impressions per post
- average impressions per post
- hit count
- breakout count
- remaining gap to 500k
- required daily and weekly average
- scenario analysis for 2k, 5k, 10k, 20k, and 50k average impressions/post

## Original Engine

The standalone posting path is intentionally separate from replies.

Replies remain the discovery engine. Original standalone posts are the rewards and brand engine because the Home Timeline eligibility target depends on original posts, not reply volume.

Each original slot now runs this sequence before any legacy fallback:

1. Generate 15-30 AI Therapist concepts.
2. Remove semantic duplicates.
3. Score candidates for hook strength, originality, insight density, resonance, reply/repost/bookmark potential, clarity, brand fit, and timeliness.
4. Apply genericness, clickbait, engagement-bait, factuality, and repetition penalties.
5. Publish or queue only the best candidate when it clears the configured quality and originality floors.

Decision and provenance logs:

```text
growth/original_post_decisions.json
growth/original_post_provenance.json
```

Important knobs:

```text
ORIGINAL_CONTENT_ENGINE_ENABLED=1
ORIGINAL_CONTENT_CANDIDATES_PER_SLOT=20
ORIGINAL_CONTENT_TOP_CONCEPTS=8
MAIN_POST_MINIMUM_QUALITY_SCORE=75
MAIN_POST_MINIMUM_ORIGINALITY_SCORE=75
```

## Operating Modes

`MAIN_POST_OPERATING_MODE=growth_automation`

Preserves current automated main-post publishing behavior. The growth layer provides analytics, memory, opportunity ranking, and prompt context.

`MAIN_POST_OPERATING_MODE=rewards_eligible`

Queues generated main-post drafts for human review instead of posting automatically. Replies are not redesigned by this mode.

Optional override:

```text
MAIN_POST_REQUIRE_HUMAN_APPROVAL=1
```

Approval queue:

```text
growth/main_post_approval_queue.json
```

Each draft stores:

- generated draft
- quality score
- metadata
- final human version field
- review actions: approve, edit, regenerate, reject, save for later

## Eligibility Note

Automated content may not qualify under current X Original Content Rewards rules. The rewards-oriented mode is designed to keep AI useful for discovery, research, ideation, critique, and ranking while preserving meaningful human review before main-post publication.

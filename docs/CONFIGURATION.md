# Active editorial settings (September 20, 2026)

The current policy is [documented here](EDITORIAL_POLICY.md). These settings
supersede the historical surfaces listed below:

| Setting | Effective value |
|---|---|
| Working hours | 04:30–22:00 America/Toronto, DST aware |
| `TARGET_POSTS_PER_DAY` | 6 |
| `MAX_PROFILE_POSTS_PER_DAY` | 7, hard combined ceiling |
| `MAX_ORIGINALS_PER_DAY` | 7 maximum; environment may lower it |
| `MAX_QUOTES_PER_DAY`, `MAX_QUOTE_REPOSTS_PER_DAY`, `MAX_RETWEETS_PER_DAY` | 0, hard disabled |
| `MAX_REPLIES_PER_DAY` | 0 means unlimited |
| `MIN_SECONDS_BETWEEN_POSTS` | At least 3600 |
| `MIN_SECONDS_BETWEEN_REPLIES`, `REPLY_JITTER_SECONDS` | Existing environment settings |
| `DEBATE_MAX_TURNS_PER_AUTHOR_PER_DAY` | 4 debate turns per author per Toronto day, shared by `debate_job`, `replyback_job` and `babysit_job`; read at call time |
| `PROFILE_LLM_PROVIDER`, `REPLY_LLM_PROVIDER` | Existing configured providers |

Legacy profile job caps do not add posting slots. `get_live_cap` cannot lift the
hard ceiling, restore quotes/reposts, or impose a daily reply limit.

---

## Historical module configuration reference

# Configuration reference

Every knob is an environment variable, settable in `.env` (loaded by `src/config.py:_load_dotenv`). Defaults are tuned for an English-content / global-audience build with conservative caps.

---

## Identity

| Variable | Default | Purpose |
|---|---|---|
| `BOT_HANDLE` | `TheAIShrink` | Your X handle, without `@`. Used in profile URLs + log filtering. |

---

## AI provider

| Variable | Default | Purpose |
|---|---|---|
| `AI_CLI` | `ollama` | `ollama` / `codex` / `opencode` / `gemini`. `ollama` uses the direct local HTTP path. |
| `LLM_FALLBACK_CLI` | `codex` | Fallback provider used when the primary LLM fails, times out, is missing, or returns empty output. |
| `LLM_FALLBACK_MODEL` | (unset) | Optional universal model for fallback calls. Overrides provider-specific fallback defaults. |
| `OPENCODE_FALLBACK_MODEL` | `opencode/big-pickle` | Legacy model label for the direct Ollama fallback path when `LLM_FALLBACK_MODEL` is unset. |
| `LLM_DISABLE_FALLBACK` | `0` | Set to `1` to disable automatic LLM fallback. |
| `NEWS_MODEL` | `gpt-5.4-mini` | Model for real sourced news posts. Override to `gpt-5.4` only for high-quality manual cycles. |
| `HOTAKE_MODEL` | `gpt-5.4-mini` | Model for hot takes + breakouts + spicy. |
| `REPLY_MODEL` | `gpt-5.4-mini` | Model for replies. Mini keeps the volume surface cheaper. |
| `PRIORITY_REPLY_MODEL` | `gpt-5.4-mini` | Model for VIP-account replies. |
| `QUOTE_MODEL` | `gpt-5.4-mini` | Model for FR quote-post commentary on external tweets. |
| `ROAST_MODEL` | `gpt-5.4-mini` | Model for the @pgm_pm roast bot. |
| `NEWS_POSTS_PER_CYCLE` | `3` | Number of separate news posts to publish per post cycle. |
| `NEWS_POST_SPACING_SECONDS` | `120` | Delay between burst news posts. |
| `ENABLE_CODEX_OPERATOR` | `0` | Allow the 4-hour `operator_cycle.sh` to spend a Codex CLI agent run when `ENABLE_AI_MAINTENANCE` is off. |

---

## Daily caps — original content

Original content uses LLM cycles + appears on the profile feed; the cap balances freshness with profile-noise.

| Variable | Default | Purpose |
|---|---|---|
| `MAX_NEWS_PER_DAY` | `5` | Real sourced Décode insight posts. |
| `MAX_HOTAKES_PER_DAY` | `3` | Quick takes on AI / crypto / macro stories. |
| `MAX_BREAKOUTS_PER_DAY` | `4` | Breakout reactions to viral stories. |
| `MAX_SPICY_PER_DAY` | `4` | Polarizing takes / questions. |

Threads are 1/day each (`thread_bot` and `digest_thread_bot`) — non-overridable, idempotent state file.

---

## Daily caps — reshare + engagement

Reshare paths don't burn LLM cycles (deterministic scoring) so caps can be much higher.

| Variable | Default | Purpose |
|---|---|---|
| `MAX_QUOTES_PER_DAY` | `300` | Bot-level cap for the quote bot (the chokepoint cap `MAX_QUOTE_REPOSTS_PER_DAY`=150 is the binding one). |
| `MAX_RETWEETS_PER_DAY` | `30` | Selective crypto / AI / bourse reposts. |
| `RETWEETS_PER_CYCLE` | `3` | Max external retweets shipped after each deterministic candidate scrape. |
| `MAX_REPLIES_PER_CYCLE` | `3` | Broad reply-bot cap per cycle. |
| `DIRECT_REPLY_MAX_PER_CYCLE` | `2` | High-value profile/feed reply cap per cycle; cadence targets 20-50/day. |
| `DIRECT_REPLY_MAX_EN_PER_CYCLE` | `5` | English reply cap inside one direct-reply cycle. |
| `MAX_PROMOTES_PER_DAY` | `3` | Promote-best-reply (plain-repost own top reply). |
| `MAX_BOOSTS_PER_DAY` | (no cap) | Self-RT scheduled by cadence only. |

---

## Cycle volumes

Per-cycle quotas (not daily caps):

| Variable | Default | Purpose |
|---|---|---|
| `FOLLOW_BLAST_PER_CYCLE` | `30` | Bulk Follow-button clicks per cycle. |
| `FOLLOW_BLAST_DAILY_CAP` | `650` | Daily circuit breaker for bulk Follow-button clicks. |
| `LIKE_BOT_PER_CYCLE` | `22` | Bulk Like-button clicks per cycle. |
| `LIKE_BOT_DAILY_CAP` | `1800` | Daily circuit breaker for bulk Like-button clicks. |
| `FOLLOWBACK_CAP` | `8` | Follow-back attempts per cycle. |
| `UNFOLLOW_CAP_PER_CYCLE` | `15` | Smart-unfollow targets per cycle. |
| `EARLY_BIRD_MAX_REPLIES_PER_CYCLE` | `4` | Early-bird replies per cycle. |
| `VIRAL_FOLLOWUP_CAP` | `3` | Viral follow-up replies per cycle. |
| `VIRAL_THRESHOLD` | `8` | Likes threshold to trigger viral follow-up. |
| `SPIKE_LIKES` | `25` | Likes threshold to trigger spike orchestration. |

---

## Quality + safety gates

| Variable | Default | Purpose |
|---|---|---|
| `RETWEET_MIN_LIKES` | `25` | Skip retweet candidates below this floor; niche/source/age gates carry quality. |
| `RETWEET_MAX_AGE_HOURS` | `18` | Skip candidates older than this. |
| `FEED_REPOST_MIN_ENGAGEMENT` | `5` | Minimum likes + 2×replies for feed-native reposts from For You / Following / search. |
| `FAVORITE_REPOSTS_PER_CYCLE` | `3` | Best recent posts to repost while visiting favorite/VIP profiles. |
| `FAVORITE_REPOST_MIN_ENGAGEMENT` | `3` | Minimum likes + 2×replies for favorite-profile reposts. |
| `FAVORITE_REPOST_MAX_AGE_MINUTES` | `2880` | Max age for favorite-profile reposts. |
| `RETWEET_FEED_SEARCHES_PER_CYCLE` | `12` | Targeted crypto / AI / bourse searches scraped by the retweet cycle, with extra FR searches before EN fallback. |
| `DIRECT_REPLY_MAX_AGE_MINUTES` | `1440` | Max age for direct replies. Keeps big-post search from commenting on old viral tweets. |
| `X_FEED_SEARCHES_PER_CYCLE` | `2` | Targeted searches merged into `external_signal.json` for news generation. |
| `LIKE_TOP_TAB_PROBABILITY` | `0.55` | Probability the like bot uses X Top search instead of Live to train For You toward the niche. |
| `QUOTE_MAX_AGE_HOURS` | `18` | Max age for quote-post candidates. |
| `BREAKOUT_MIN_LIKES` | `30` | Min likes to consider a tweet a "breakout candidate". |
| `BREAKOUT_VELOCITY_LIKES` | `100` | Likes threshold for "this is breaking". |
| `MAX_BREAKOUTS_PER_DAY` | `4` | Daily cap on breakout posts. |
| `PROMOTE_MIN_LIKES` | `5` | Min likes on a reply before it's promotable. |
| `PIN_MIN_LIKES` | `5` | Min likes on a post before it's pinnable. |
| `SUPPRESSION_AVG_LIKES_FLOOR` | `1.0` | Trigger shadowban-pause if avg drops below. |
| `SUPPRESSION_COOLDOWN_H` | `4` | Hours to pause aggressive bots after a flag. |
| `AUTO_TUNE_LOOKBACK_MIN` | `90` | Window for real-time velocity gauge. |

---

## Language

| Variable | Default | Purpose |
|---|---|---|
| `CONTENT_LANG_PRIMARY` | `en` | `en` / `fr` / `mixed` (70% EN / 30% FR). Reply paths always match parent tweet language regardless. |

---

## Self-modification toggles

| Variable | Default | Purpose |
|---|---|---|
| `ENABLE_AI_MAINTENANCE` | `0` | Strategy + evolution + reflection + meta-strategy + self-evolution agents. Disabled by default so calls go to news/replies. |
| `ENABLE_AI_DISCOVERY` | `0` | Discover + scout agents. Disabled by default to skip account-discovery LLM calls. |

---

## Authoring

`config.py` exposes runtime helpers that read JSON state files written by autonomous agents:

```python
from src.config import (
    get_live_cap,                # cap from meta_strategy_agent (env fallback)
    get_live_cadence_factor,     # cadence multiplier (default 1.0)
    get_live_topic_focus,        # current topic focus list
)

# Example: bot reads its dynamic cap, falls back to env constant.
cap = get_live_cap("MAX_NEWS_PER_DAY", MAX_NEWS_PER_DAY)
```

These are best-effort: the file may not exist on first boot or after a fresh clone. The fallback default ensures the bot always has a sane number.

---

## .env.example template

```env
BOT_HANDLE=TheAIShrink
AI_CLI=ollama
LLM_FALLBACK_CLI=codex
NEWS_MODEL=gpt-5.4-mini
HOTAKE_MODEL=gpt-5.4-mini
REPLY_MODEL=gpt-5.4-mini
PRIORITY_REPLY_MODEL=gpt-5.4-mini
QUOTE_MODEL=gpt-5.4-mini
ROAST_MODEL=gpt-5.4-mini
NEWS_POSTS_PER_CYCLE=3
NEWS_POST_SPACING_SECONDS=120

MAX_NEWS_PER_DAY=10
MAX_HOTAKES_PER_DAY=0
MAX_BREAKOUTS_PER_DAY=4
MAX_SPICY_PER_DAY=4
MAX_QUOTES_PER_DAY=80
MAX_RETWEETS_PER_DAY=30
RETWEETS_PER_CYCLE=3
MAX_REPLIES_PER_CYCLE=8
DIRECT_REPLY_MAX_PER_CYCLE=32
DIRECT_REPLY_MAX_EN_PER_CYCLE=5

FOLLOW_BLAST_PER_CYCLE=30
FOLLOW_BLAST_DAILY_CAP=650
LIKE_BOT_PER_CYCLE=22
LIKE_BOT_DAILY_CAP=1800
RETWEET_MIN_LIKES=25
RETWEET_MAX_AGE_HOURS=18
QUOTE_MAX_AGE_HOURS=18

ENABLE_AI_MAINTENANCE=0
ENABLE_AI_DISCOVERY=0
ENABLE_CODEX_OPERATOR=0

CONTENT_LANG_PRIMARY=en
```

---

## 2026-06-07 additions (viral focus / quality barbell — see HISTORY.md)

The live values are in `.env` (which overrides everything above; treat the
older tables on this page as historical defaults).

| Variable | Live value | Purpose |
|---|---|---|
| `MAX_QUOTE_REPOSTS_PER_DAY` / `MAX_QUOTES_PER_DAY` | `100` | QRT quality lane — the focus surface. 50-like floor, screenshot-or-SKIP gate. |
| `MIN_SECONDS_BETWEEN_QUOTES` / `QUOTE_JITTER_SECONDS` | `300` / `180` | ~5-min jittered QRT spacing, never bursts. |
| `QUOTE_MIN_LIKES` / `FEED_SWEEP_QUOTE_MIN_LIKES` | `50` / `100` | Mid-size analytical posts are the measured winners (not mega-virals). |
| `MAX_REPLIES_PER_DAY` | `999999` | Replies = quantity lane, unlimited; 8s+jitter ban floor stays. |
| `MAX_ORIGINALS_PER_DAY` | `4` | One per US-market slot cron (9:30/12:30/16:30/20:00 NY ±15min). |
| `MAX_RETWEETS_PER_DAY` | `2` | Plain RTs: reciprocity / MUST_REPOST only. |
| `FOLLOW_TOTAL_CAP` / `FOLLOW_LOW_PHASE_CEILING` | `300` / `150` | Hard following ceilings (spec Part 1). |
| `MAX_FOLLOWS_PER_DAY` / `MIN_SECONDS_BETWEEN_FOLLOWS` | `20` / `600` | Follow pacing, whitelist-only. |
| `MAX_UNFOLLOWS_PER_DAY` | `0` | Bot never unfollows — operator-manual (`bin/mass_unfollow.py`). |
| `REPLY_BAIT_PER_WEEK` | `4` | spicy QUESTION mode weekly cap. |
| `BOOST_RECYCLE_MIN_LIKES` | `2` | Winner bar: ≥1 external like (bot self-likes at publish). |
| `BOOST_RECYCLE_GAP_HOURS` / `BOOST_RECYCLE_MAX_CYCLES` | `4` / `4` | un-RT→re-RT recycling pace per winner (≤48h). |
| `CURATOR_WINDOW_DAYS` / `CURATOR_DISCOVERED_PER_DAY` / `CURATOR_DISCOVERED_MAX` | `4` / `3` / `50` | Self-curated tracked list + whitelist `discovered`-tier promotion caps. |
| `PINNED_TRACKED_HANDLES` | `TheBTCTherapist,Graphseo` | The only operator-pinned scan targets — everything else is earned. |
| `SELF_WINNERS_MIN_LIKES` / `SELF_WINNERS_WINDOW_DAYS` / `SELF_WINNERS_MAX_VIEWS` | `3` / `4` / `100000` | Own-wins prompt bank: floor, therapist-era window, foreign-content guard. |
| `BESTIE_HANDLE` / `BLITZ_MAX_QUOTES_PER_CYCLE` | `TheBTCTherapist` / `2` | Bestie blitz target + per-cycle QRT offer. |

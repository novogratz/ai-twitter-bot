# Configuration reference

Every knob is an environment variable, settable in `.env` (loaded by `src/config.py:_load_dotenv`). Defaults are tuned for an English-content / global-audience build with conservative caps.

---

## Identity

| Variable | Default | Purpose |
|---|---|---|
| `BOT_HANDLE` | `kzer_ai` | Your X handle, without `@`. Used in profile URLs + log filtering. |

---

## AI provider

| Variable | Default | Purpose |
|---|---|---|
| `AI_CLI` | `claude` | `claude` / `codex` / `gemini`. The CLI must be authenticated. |
| `NEWS_MODEL` | `claude-opus-4-7` | Model for news + threads. Opus recommended for instruction-following. |
| `HOTAKE_MODEL` | `claude-opus-4-7` | Model for hot takes + breakouts + spicy. |
| `REPLY_MODEL` | `claude-sonnet-4-6` | Model for replies. Sonnet sufficient for the volume surface. |
| `PRIORITY_REPLY_MODEL` | `claude-opus-4-7` | Model for VIP-account replies (curated `ALWAYS_PROFILES`). |
| `QUOTE_MODEL` | `claude-haiku-4-5-20251001` | Model for quote-tweet commentary. Haiku is fine — it's a one-liner. |
| `ROAST_MODEL` | `claude-haiku-4-5-20251001` | Model for the @pgm_pm roast bot. |
| `LLM_MIN_SECONDS_BETWEEN_CALLS` | `45` | Local rate-limit guardrail. |
| `LLM_MAX_CALLS_PER_HOUR` | `60` | Local hourly model-call budget. |

---

## Daily caps — original content

Original content uses LLM cycles + appears on the profile feed; the cap balances freshness with profile-noise.

| Variable | Default | Purpose |
|---|---|---|
| `MAX_NEWS_PER_DAY` | `12` | News posts. |
| `MAX_HOTAKES_PER_DAY` | `6` | Hot takes (sharper, less news-y). |
| `MAX_BREAKOUTS_PER_DAY` | `4` | Breakout reactions to viral stories. |
| `MAX_SPICY_PER_DAY` | `4` | Polarizing takes / questions. |

Threads are 1/day each (`thread_bot` and `digest_thread_bot`) — non-overridable, idempotent state file.

---

## Daily caps — reshare + engagement

Reshare paths don't burn LLM cycles (deterministic scoring) so caps can be much higher.

| Variable | Default | Purpose |
|---|---|---|
| `MAX_QUOTES_PER_DAY` | `30` | Quote-tweets (LLM commentary on viral content). |
| `MAX_RETWEETS_PER_DAY` | `60` | Selective retweets of trusted-handle content. |
| `MAX_REPLIES_PER_CYCLE` | `25` | Replies per `reply_bot` / `direct_reply` cycle. |
| `MAX_PROMOTES_PER_DAY` | `3` | Promote-best-reply (quote-RT own top reply). |
| `MAX_BOOSTS_PER_DAY` | (no cap) | Self-RT scheduled by cadence only. |

---

## Cycle volumes

Per-cycle quotas (not daily caps):

| Variable | Default | Purpose |
|---|---|---|
| `FOLLOW_BLAST_PER_CYCLE` | `30` | Bulk Follow-button clicks per cycle. |
| `LIKE_BOT_PER_CYCLE` | `22` | Bulk Like-button clicks per cycle. |
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
| `RETWEET_MIN_LIKES` | `10` | Skip retweet candidates below this floor. |
| `RETWEET_MAX_AGE_HOURS` | `18` | Skip candidates older than this. |
| `QUOTE_MAX_AGE_HOURS` | `18` | Same for quote-tweets. |
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
| `ENABLE_AI_MAINTENANCE` | `1` | Strategy + evolution + reflection + meta-strategy + self-evolution agents. Disable to run "no-LLM-background" mode. |
| `ENABLE_AI_DISCOVERY` | `1` | Discover + scout agents. Disable to skip account-discovery LLM calls. |

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
BOT_HANDLE=kzer_ai
AI_CLI=claude
NEWS_MODEL=claude-opus-4-7
HOTAKE_MODEL=claude-opus-4-7
REPLY_MODEL=claude-sonnet-4-6
PRIORITY_REPLY_MODEL=claude-opus-4-7
QUOTE_MODEL=claude-haiku-4-5-20251001
ROAST_MODEL=claude-haiku-4-5-20251001

MAX_NEWS_PER_DAY=12
MAX_HOTAKES_PER_DAY=6
MAX_BREAKOUTS_PER_DAY=4
MAX_SPICY_PER_DAY=4
MAX_QUOTES_PER_DAY=30
MAX_RETWEETS_PER_DAY=60
MAX_REPLIES_PER_CYCLE=25

FOLLOW_BLAST_PER_CYCLE=30
LIKE_BOT_PER_CYCLE=22
RETWEET_MIN_LIKES=10
RETWEET_MAX_AGE_HOURS=18
QUOTE_MAX_AGE_HOURS=18

LLM_MIN_SECONDS_BETWEEN_CALLS=45
LLM_MAX_CALLS_PER_HOUR=60

ENABLE_AI_MAINTENANCE=1
ENABLE_AI_DISCOVERY=1

CONTENT_LANG_PRIMARY=en
```

# Active editorial settings (September 23, 2026)

The current policy is [documented here](EDITORIAL_POLICY.md). These settings
supersede the historical surfaces listed below:

| Setting | Effective value |
|---|---|
| Working hours | 04:30–23:30 America/Toronto, DST aware (`active_hours.WAKE`, `BEDTIME`) |
| `MIN_TARGET_POSTS_PER_DAY` | 3 |
| `TARGET_POSTS_PER_DAY` | 6 |
| `MAX_PROFILE_POSTS_PER_DAY` | 8, hard combined ceiling |
| `MAX_ORIGINALS_PER_DAY` | 8 maximum; environment may lower it |
| Quotes and reposts | 0: `action_guard.can_post` refuses them, and no setting restores them |
| Replies per day | Unlimited: no setting caps them |
| `MIN_SECONDS_BETWEEN_POSTS` | At least 1200 (20 minutes); the environment may lengthen it |
| `POST_JITTER_SECONDS` | 0; a random extra gap after each original, drawn once per post; a negative value reads as 0 |
| `MIN_SECONDS_BETWEEN_REPLIES`, `REPLY_JITTER_SECONDS` | Existing environment settings |
| `DEBATE_MAX_TURNS_PER_AUTHOR_PER_DAY` | 4 debate turns per author per Toronto day, shared by `debate_job`, `replyback_job` and `babysit_job`; read at call time |
| `PROFILE_LLM_PROVIDER`, `REPLY_LLM_PROVIDER` | Existing configured providers, `ollama` by default. An unknown name fails every call it routes without running anything; the start logs it and `--dry-run` lists it under `unknown_llm_providers` |
| `LLM_FALLBACK_CLI` | Unset: no fallback, a failed call fails, Originals and Replies alike. `codex` (or `gemini`, `ollama`) opts into one; an unknown name fails the fallback without running anything. Ignored, and logged at start and listed by `--dry-run` under `ignored_llm_fallbacks`: `claude`, a CLI not installed, Ollama behind Ollama, or the primary itself without `LLM_FALLBACK_MODEL`. Two calls leave the configured provider without it: the Replies to @Graphseo run on the Claude CLI whenever it is installed, and a codex primary under a cached usage lockout (`codex_lockout.json`) goes to local Ollama |
| `FR_FORCED_REPLY_HANDLES` | `Graphseo`: parents always answered in French by the search and feed-sweep Replies; `judge_reply` refuses an English-looking reply to them; read at call time |
| `LIKE_BOT_PER_CYCLE`, `LIKE_BOT_DAILY_CAP`, `LIKE_BOT_CYCLE_SECONDS` | 10 posts per cycle, 500 likes a day, 30 s per cycle; declared in `src/core/settings.py`, read at each like cycle |
| `DRY_RUN` | `1` logs every write instead of sending it; read at each call through `config.dry_run()` |

Legacy profile job caps do not add posting slots.

The quote, repost and boost branches left the live jobs (issue #107), and no
code reads the variables that gated them any more: `FAVORITE_REPOSTS_PER_CYCLE`, `FAVORITE_REPOST_MIN_ENGAGEMENT`,
`FAVORITE_REPOST_MAX_AGE_MINUTES`, `FEED_SWEEP_QUOTE_MIN_LIKES`,
`FEED_SWEEP_MAX_QUOTES_PER_CYCLE`, `FEED_SWEEP_BANGER_LIKES`,
`BLITZ_MAX_QUOTES_PER_CYCLE`.

The bot never unfollows: the unfollow chokepoint left `src/` with its cap
(issue #168), and no code reads `MAX_UNFOLLOWS_PER_DAY` any more.
`bin/mass_unfollow.py`, run by hand, is bounded by its own `--max`.

`config.py` stopped parsing the variables no Python code read (issue #170):
`MAX_NEWS_PER_DAY`, `MAX_HOTAKES_PER_DAY`, `MAX_QUOTES_PER_DAY`,
`MAX_QUOTE_REPOSTS_PER_DAY`, `MAX_RETWEETS_PER_DAY`, `MAX_REPLIES_PER_DAY`,
`HOTAKE_MODEL`, `GROWTH_ENHANCEMENT`, `FOLLOW_BACK_RATIO`,
`RETWEET_ENGAGEMENT_THRESHOLD`, `BOOST_ENGAGEMENT_POSTS`,
`FOLLOWING_STEADY_STATE`, `REPLY_LANGUAGE_MATCH`, `ENABLE_AI_DISCOVERY`. The
legacy tables below still list some of them. `ENABLE_AI_MAINTENANCE` and
`ENABLE_CODEX_OPERATOR` are read by `operator_cycle.sh` only.

---

## Historical module configuration reference

# Configuration reference

Every knob is an environment variable, settable in `.env`. `main.py` reads `.env` once at start through `src/core/settings.py`, which declares every key the engine reads; a key it does not know, or a badly typed value, stops the start, and `main.py --dry-run` names the key. Defaults are tuned for an English-content / global-audience build with conservative caps.

---

## Identity

| Variable | Default | Purpose |
|---|---|---|
| `BOT_HANDLE` | `TheAIShrink` | Your X handle, without `@`. Used in profile URLs + log filtering. |

---

## AI provider

| Variable | Default | Purpose |
|---|---|---|
| `AI_CLI` | `ollama` | `ollama` / `codex` / `opencode` / `gemini`. `ollama` uses the direct local HTTP path. An unknown name fails the call; a CLI not installed fails it too, and no other CLI stands in. |
| `LLM_FALLBACK_CLI` | (unset) | Fallback provider used when the primary LLM fails, times out, is missing, or returns empty output. Unset or empty: no fallback. Naming the primary gives no fallback unless `LLM_FALLBACK_MODEL` is set. A codex primary under a cached usage lockout goes to local Ollama even when unset. |
| `LLM_FALLBACK_MODEL` | (unset) | Optional universal model for fallback calls. Overrides provider-specific fallback defaults. |
| `CODEX_FALLBACK_MODEL` | `gpt-5.4-mini` | Codex model as the fallback when `LLM_FALLBACK_MODEL` is unset; blank means the default. |
| `GEMINI_FALLBACK_MODEL` | `gemini-2.0-flash` | Gemini model as the fallback when `LLM_FALLBACK_MODEL` is unset; blank means the default. |
| `OPENCODE_FALLBACK_MODEL` | `opencode/big-pickle` | No effect; kept so an old `.env` still starts. An Ollama fallback runs the call profile's model. |
| `LLM_DISABLE_FALLBACK` | `0` | Set to `1` to disable automatic LLM fallback. |
| `OLLAMA_MODEL` | `qwen3.6:35b-a3b` | Ollama model of every call whose profile names none, the Replies. `bin/run.sh` pre-warms it. |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama HTTP endpoint, for the bot and the `bin/run.sh` pre-warm. |
| `OLLAMA_NUM_CTX`, `OLLAMA_NUM_PREDICT` | `32768`, `1800` | Ollama context window and generation cap, in tokens. |
| `LLM_TIMEOUT_SECONDS` | `180` | Default model-call timeout, and Ollama's floor. |
| `NEWS_MODEL` | (unset) | CLI model for Originals, on the primary CLI. Unset or blank, each call takes the default of the CLI it runs (`settings.MODEL_DEFAULTS`): `gpt-5.4-mini` on codex, `claude-opus-4-8` on claude, `gemini-2.0-flash` on gemini. Ollama, OpenCode and a fallback never read it. |
| `REPLY_MODEL` | (unset) | CLI model for Replies. Unset or blank: `gpt-5.4-mini` on codex, `claude-haiku-4-5-20251001` on claude, `gemini-1.5-flash` on gemini. |
| `PRIORITY_REPLY_MODEL` | (unset) | CLI model for VIP and @Graphseo Replies. Unset or blank: `gpt-5.4-mini` on codex, `claude-haiku-4-5-20251001` on claude, `gemini-2.0-flash` on gemini. |
| `HOTAKE_MODEL` | `gpt-5.4-mini` | Model for hot takes + breakouts + spicy. |
| `ENABLE_CODEX_OPERATOR` | `0` | Allow the 4-hour `operator_cycle.sh` to spend a Codex CLI agent run when `ENABLE_AI_MAINTENANCE` is off. |

---

## Daily caps — original content

Original content uses LLM cycles + appears on the profile feed; the cap balances freshness with profile-noise.

| Variable | Default | Purpose |
|---|---|---|
| `MAX_NEWS_PER_DAY` | `5` | Real sourced Décode insight posts. |
| `MAX_HOTAKES_PER_DAY` | `3` | Quick takes on AI / crypto / macro stories. |

---

## Daily caps — reshare + engagement

Reshare paths don't burn LLM cycles (deterministic scoring) so caps can be much higher.

| Variable | Default | Purpose |
|---|---|---|
| `MAX_QUOTES_PER_DAY` | `300` | Bot-level cap for the quote bot (the chokepoint cap `MAX_QUOTE_REPOSTS_PER_DAY`=150 is the binding one). |
| `MAX_RETWEETS_PER_DAY` | `30` | Selective crypto / AI / bourse reposts. |
| `MAX_REPLIES_PER_CYCLE` | `3` | Broad reply-bot cap per cycle. |
| `DIRECT_REPLY_MAX_PER_CYCLE` | `3` | Direct search/VIP reply cap per cycle; keeps the 2-minute job from overlapping itself. |
| `DIRECT_REPLY_MAX_EN_PER_CYCLE` | `5` | English reply cap inside one direct-reply cycle. |

---

## Cycle volumes

Per-cycle quotas (not daily caps):

| Variable | Default | Purpose |
|---|---|---|
| `LIKE_BOT_PER_CYCLE` | `10` | Search posts `like_job` hands to `like_tweet` per cycle; at most that many likes. |
| `LIKE_BOT_DAILY_CAP` | `500` | Daily circuit breaker on the likes `like_job` clicked: `LIKED` plus `UNCONFIRMED`, a click the page did not confirm. |
| `LIKE_BOT_CYCLE_SECONDS` | `30` | Seconds after `like_job` takes the Safari lock past which it starts no like; bounds how long it holds the browser. |
| `FOLLOWBACK_CAP` | `8` | Follow-back attempts per cycle. |
| `EARLY_BIRD_MAX_REPLIES_PER_CYCLE` | `4` | Early-bird replies per cycle. |

---

## Quality + safety gates

| Variable | Default | Purpose |
|---|---|---|
| `DIRECT_REPLY_MAX_AGE_MINUTES` | `1440` | Max age for direct replies. Keeps big-post search from commenting on old viral tweets. |
| `LIKE_TOP_TAB_PROBABILITY` | `0.55` | Probability the like bot uses X Top search instead of Live to train For You toward the niche. |
| `PIN_MIN_LIKES` | `5` | Min likes on a post before it's pinnable. |

---

## Language

| Variable | Default | Purpose |
|---|---|---|
| `CONTENT_LANG_PRIMARY` | `en` | `en` / `fr` / `mixed` (70% EN / 30% FR). Reply paths always match parent tweet language regardless. |

---

## Self-modification toggles

| Variable | Default | Purpose |
|---|---|---|
| `ENABLE_AI_MAINTENANCE` | `0` | Lets the 4-hour `operator_cycle.sh` spend a Codex CLI run. The in-process agents it once enabled were removed. |
| `ENABLE_AI_DISCOVERY` | `0` | No code reads it; the discover and scout agents it gated were removed. |

---

## .env.example template

```env
BOT_HANDLE=TheAIShrink
AI_CLI=ollama
LLM_FALLBACK_CLI=
NEWS_MODEL=gpt-5.4-mini
HOTAKE_MODEL=gpt-5.4-mini
REPLY_MODEL=gpt-5.4-mini
PRIORITY_REPLY_MODEL=gpt-5.4-mini

MAX_NEWS_PER_DAY=10
MAX_HOTAKES_PER_DAY=0
MAX_QUOTES_PER_DAY=80
MAX_RETWEETS_PER_DAY=30
MAX_REPLIES_PER_CYCLE=8
DIRECT_REPLY_MAX_PER_CYCLE=32
DIRECT_REPLY_MAX_EN_PER_CYCLE=5

LIKE_BOT_PER_CYCLE=10
LIKE_BOT_DAILY_CAP=500

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
| `MAX_REPLIES_PER_DAY` | `999999` | Replies = quantity lane, unlimited; 8s+jitter ban floor stays. |
| `MAX_ORIGINALS_PER_DAY` | `4` | One per US-market slot cron (9:30/12:30/16:30/20:00 NY ±15min). |
| `MAX_RETWEETS_PER_DAY` | `2` | Plain RTs: reciprocity / MUST_REPOST only. |
| `FOLLOW_TOTAL_CAP` / `FOLLOW_LOW_PHASE_CEILING` | `300` / `150` | Hard following ceilings (spec Part 1). |
| `MAX_FOLLOWS_PER_DAY` / `MIN_SECONDS_BETWEEN_FOLLOWS` | `20` / `600` | Follow pacing, whitelist-only. |
| `CURATOR_WINDOW_DAYS` / `CURATOR_DISCOVERED_PER_DAY` / `CURATOR_DISCOVERED_MAX` | `4` / `3` / `50` | Self-curated tracked list + whitelist `discovered`-tier promotion caps. |
| `PINNED_TRACKED_HANDLES` | `TheBTCTherapist,Graphseo` | The only operator-pinned scan targets — everything else is earned. |
| `BESTIE_HANDLE` | `TheBTCTherapist` | Account whose posts get the bestie prompt in the `direct_reply` VIP scan. |

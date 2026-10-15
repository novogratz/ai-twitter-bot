---
name: config
description: View and edit bot configuration - pacing, follows, models, settings
allowed-tools: Read Edit Bash(uv run python bin/configuration_doc.py*)
---

Show and edit config:

1. Read `docs/CONFIGURATION.md` (its reference is generated from
   `src/core/settings.py`) and `src/core/config.py` - display the settings
2. Show which settings `.env` sets
3. If the operator wants changes, edit `.env`; a new or changed declaration
   goes in `src/core/settings.py`, then
   `uv run python bin/configuration_doc.py --write`
4. Remind that any change takes effect at restart only

Hard ceilings cannot be lifted from `.env`, and are
not edited without an explicit operator request that also updates
`docs/EDITORIAL_POLICY.md` in the same change: the eight-post ceiling
(`MAX_ORIGINALS_PER_DAY` can only go lower), the twenty-minute spacing
between originals (`MIN_SECONDS_BETWEEN_POSTS` can only go higher), quotes
and reposts at zero, waking hours and `BLOCKLIST`.

The live Account has `publish_originals = false`; `.env` cannot enable Originals.
Keep its no-contact protection in `network.blocked_accounts` as well as
`replies.protected_handles`. Outgoing SI wording is in `text_replacements`.

Reply pacing defaults to 30 seconds plus up to 15 seconds of jitter within
05:00–24:00 Toronto every day, subject to approved
drafts and model/browser time. The minimum cannot be lowered below 30; jitter
may range from 0 to 180. The live Account requires ranked selection;
changing pacing does not bypass review, clear a saved deadline or authorize a restart.
Reply volume has no daily or hourly count cap. Every Reply target needs at least
two likes, rechecked on the opened post; reposts and views cannot substitute.
New ranked drafts independently choose no smiley with 50% probability or
exactly one friendly smiley with 50%, enforced within the assigned length limit
through publication.
The selector checks every ten seconds after its 60-second startup delay, with
15 seconds for a new pool to collect choices before independent comparison.
Every Account discovery query includes SI, "super intelligence", superintelligence
and ASI, retaining AI and "artificial intelligence" as search aliases.

Direct discovery runs every minute with three rotating Latest/Top queries and
four draft attempts per cycle by default. Feed sweeps run every minute, with
For You first in three of four cycles, reading 40 posts and attempting four
drafts per feed. Collectors stop new reads
when the eight-draft queue is full. These are preparation bounds, not daily quotas.
Each feed scan selects and verifies its native tab before reading posts.

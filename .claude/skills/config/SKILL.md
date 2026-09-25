---
name: config
description: View and edit bot configuration - pacing, follows, models, settings
allowed-tools: Read Edit
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

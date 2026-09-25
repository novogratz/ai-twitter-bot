---
name: config
description: View and edit bot configuration - pacing, follows, models, settings
allowed-tools: Read Edit
---

Show and edit config:

1. Read `src/core/config.py` and `docs/CONFIGURATION.md` (its top table is
   current; the rest documents legacy env vars) - display the settings
2. Show which env vars can override them (`.env`)
3. If the operator wants changes, edit `.env` or `src/core/config.py`
4. Remind that changes take effect at restart

Hard ceilings cannot be lifted from `.env`, and are
not edited without an explicit operator request that also updates
`docs/EDITORIAL_POLICY.md` in the same change: the eight-post ceiling
(`MAX_ORIGINALS_PER_DAY` can only go lower), the twenty-minute spacing
between originals (`MIN_SECONDS_BETWEEN_POSTS` can only go higher), quotes
and reposts at zero, waking hours, `BLOCKLIST` and the 48-hour
`REPOST_MAX_AGE_HOURS` clamp.

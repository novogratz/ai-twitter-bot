---
name: like
description: Visit an allowlisted profile and like its latest posts, skipping the ones already liked
arguments: [username]
disable-model-invocation: true
allowed-tools: Bash Read
---

Like @$username's latest posts. Only on an explicit operator request.

1. Strip @ if present. The handle must be in `PROFILE_VISIT_ALLOWLIST`
   (`.env`, else the Account's `network.profile_visits`:
   `TheBTCTherapist,Graphseo`); any other is refused before Safari opens.
2. Preconditions in `docs/OPERATIONS.md#manual-writes`. Check:
   `pgrep -if "python.*main\.py"` prints nothing and
   `uv run python -c "from src.guards.active_hours import is_active; print(is_active())"`
   prints `True`.
3. Run `uv run python -c "from src.core import config; from src.x.twitter_client import visit_profile_and_like; print([o.value for o in visit_profile_and_like('$username', like_count=2)], 'dry_run' if config.dry_run() else 'live')"`
   - It prints one outcome per post of theirs shown on the profile
     (reposts of others skipped): `liked`, `already_liked` (nothing
     clicked), `blocked` (a Blocked account; nothing clicked or recorded) or
     `failed` (the post or its like button could not be found, or the page
     did not show the like after the click; nothing recorded). The walk
     stops at the first `failed`.
   - `[]` means the profile was refused, `like_count` was 0, or `DRY_RUN=1`
     (it then prints `dry_run` and opens nothing).
4. Report the outcomes and the `[LIKE]` lines of `bot.log`, which name each
   post's status URL.

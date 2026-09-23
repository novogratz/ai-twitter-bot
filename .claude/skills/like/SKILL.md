---
name: like
description: Visit an allowlisted profile and like its latest posts
arguments: [username]
disable-model-invocation: true
allowed-tools: Bash Read
---

Like @$username's latest posts. Only on an explicit operator request.

1. Strip @ if present
2. The handle must be in `PROFILE_VISIT_ALLOWLIST` (`.env`, default
   `TheBTCTherapist,Graphseo`); otherwise the call logs
   `[LIKE] profile visit blocked` and does nothing.
3. The bot must be stopped (`pgrep -if "python.*main\.py"` returns nothing):
   it shares Safari. Only during active hours (04:30–22:00 Toronto).
4. The like is the `l` shortcut, which toggles: an already-liked post gets
   unliked. Check the profile first and lower `like_count` accordingly.
5. Run `uv run python -c "from src.twitter_client import visit_profile_and_like; visit_profile_and_like('$username', like_count=2)"`
6. Confirm from the `bot.log` lines ("Tweet liked!" or "Failed to like").

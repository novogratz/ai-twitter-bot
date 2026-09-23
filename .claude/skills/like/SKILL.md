---
name: like
description: Visit an allowlisted profile and like its latest posts - do not run until issue 121 ships
arguments: [username]
disable-model-invocation: true
allowed-tools: Bash Read
---

Like @$username's latest posts. Only on an explicit operator request.

1. Do not run this until issue #121 ships; tell the operator so and stop.
   `visit_profile_and_like` presses the toggling `l` shortcut on the latest
   post before its loop, even with `like_count=0`, without reading the liked
   state, so it un-likes an already-liked post and still logs "Tweet liked!".

Once #121 ships, the call is
`uv run python -c "from src.twitter_client import visit_profile_and_like; visit_profile_and_like('$username', like_count=2)"`,
with the preconditions in `docs/OPERATIONS.md#manual-writes`, for a handle
in `PROFILE_VISIT_ALLOWLIST` (`.env`, default `TheBTCTherapist,Graphseo`).

---
name: like
description: Visit a profile and like their latest tweets
arguments: [username]
allowed-tools: Bash
---

Like @$username's latest tweets:

1. Strip @ if present
2. Run `python3 -c "from src.twitter_client import visit_profile_and_like; visit_profile_and_like('$username', like_count=2)"`
3. Confirm

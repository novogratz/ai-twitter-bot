---
name: follow
description: Follow a specific Twitter account
disable-model-invocation: true
arguments: [username]
allowed-tools: Bash Read Write
---

Follow @$username:

1. Strip @ if present
2. Run `python3 -c "from src.twitter_client import follow_account; follow_account('$username')"`
3. Add to followed_accounts.json if not already there
4. Confirm

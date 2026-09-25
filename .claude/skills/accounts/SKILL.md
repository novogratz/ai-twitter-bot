---
name: accounts
description: View and manage the accounts the bot engages with and may follow
allowed-tools: Read Write Bash Edit
---

Manage target accounts:

1. Engage pool (`engage_job`), built at each cycle, not a static list:
   `network.engage_vip` in `accounts/<BOT_ACCOUNT>/account.toml`, plus the
   handles the feed sweeper harvested in `dynamic_accounts.json` (`en`/`fr`
   buckets) and `discovered_accounts.json`. Show counts per source.
2. Follow whitelist: `accounts/theaishrink/whitelist.json` (`tiers`,
   `seeds`), plus the handles the curator promoted in
   `whitelist_discovered.json`. `follow_account`
   never follows a Stranger. With `FOLLOW_WHITELIST_ONLY` on, it follows
   outside the whitelist only a follower or an Engager, and only while
   `FOLLOWBACK_BYPASS_WHITELIST` is on.
3. Profile visits: `PROFILE_VISIT_ALLOWLIST` in `.env`, else the Account's
   `network.profile_visits` (`TheBTCTherapist,Graphseo`), gates the profile
   likes.
4. Read `followed_accounts.json` - show which are already followed.
5. Ask if the operator wants to add or remove accounts; edit
   the Account's `[network]` lists or `accounts/theaishrink/whitelist.json`
   accordingly. Changes to code, `account.toml` or `.env` take effect at
   restart; the whitelist is read at each follow.

To block an account everywhere, the base `BLOCKLIST` in `src/core/config.py`,
the Account's `network.blocked_accounts` (it adds to the base, never removes
from it) and `accounts/theaishrink/respect_list.json` are operator-managed:
change them only on an explicit operator request.

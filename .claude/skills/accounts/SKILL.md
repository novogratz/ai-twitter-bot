---
name: accounts
description: View and manage the accounts the bot engages with and may follow
allowed-tools: Read Write Bash Edit
---

Manage target accounts:

1. Engage pool (`engage_job`), built at each cycle, not a static list:
   `VIP_ACCOUNTS` in `src/account/engage_bot.py`, plus the handles the feed
   sweeper harvested in `dynamic_accounts.json` (`en`/`fr` buckets) and
   `discovered_accounts.json`. `TARGET_ACCOUNTS` is an import shim, not the
   pool. Show counts per source.
2. Follow whitelist: `whitelist.json` (`tiers`, `seeds`). `follow_account`
   never follows a Stranger. With `FOLLOW_WHITELIST_ONLY` on, it follows
   outside the whitelist only a follower or an Engager, and only while
   `FOLLOWBACK_BYPASS_WHITELIST` is on.
3. Profile visits: `PROFILE_VISIT_ALLOWLIST` in `.env` (default
   `TheBTCTherapist,Graphseo`) gates the profile likes.
4. Read `followed_accounts.json` - show which are already followed.
5. Ask if the operator wants to add or remove accounts; edit
   `VIP_ACCOUNTS` or `whitelist.json` accordingly. Changes to code or
   `.env` take effect at restart.

To block an account everywhere, `BLOCKLIST` in `src/core/config.py` and
`respect_list.json` are operator-managed: change them only on an explicit
operator request.

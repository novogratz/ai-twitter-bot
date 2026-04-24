Follow a specific Twitter account right now.

Usage: /follow username

1. Take the username argument (strip @ if included)
2. Run `python -c "from src.twitter_client import follow_account; follow_account('USERNAME')"` to follow them
3. Add them to followed_accounts.json if not already there
4. Confirm the follow

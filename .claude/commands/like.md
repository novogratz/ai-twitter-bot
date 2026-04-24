Visit a profile and like their latest tweets.

Usage: /like username [count]

1. Take the username argument (strip @ if included)
2. Default like count is 2, or use the number provided
3. Run `python -c "from src.twitter_client import visit_profile_and_like; visit_profile_and_like('USERNAME', like_count=N)"` to like their tweets
4. Confirm which account was engaged with

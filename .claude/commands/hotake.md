Generate and post a hot take right now:

1. Run `python -c "from src.hotake_agent import generate_hotake; print(generate_hotake())"` to generate a hot take
2. Show the generated hot take to the user
3. Ask if they want to post it, edit it, or generate a new one
4. If approved, run `python -c "from src.twitter_client import post_tweet; post_tweet('TEXT')"` to post it

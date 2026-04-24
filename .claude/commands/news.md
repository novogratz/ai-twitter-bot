Generate a news tweet without posting it. Preview mode for reviewing what the AI would write:

1. Run `python -c "from src.agent import generate_tweet; tweet = generate_tweet(); print(tweet if tweet else 'SKIP - no fresh news found')"` to generate
2. Show the generated tweet to the user
3. Show character count
4. Ask if they want to: post it, edit it, regenerate, or discard
5. If posting, use `python -c "from src.twitter_client import post_tweet; post_tweet('TEXT')"`

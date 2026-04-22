import traceback
from .news_fetcher import fetch_ai_news
from .tweet_generator import generate_tweet
from .twitter_client import post_tweet


def run_bot_cycle():
    """Fetch news, generate a tweet, and post it."""
    print("Fetching AI news...")
    articles = fetch_ai_news()
    if not articles:
        print("No articles found, skipping cycle.")
        return

    print(f"Found {len(articles)} articles. Generating tweet...")
    tweet = generate_tweet(articles)
    print(f"Generated tweet: {tweet}")

    post_tweet(tweet)


def safe_run_bot_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    try:
        run_bot_cycle()
    except Exception:
        print("Error during bot cycle:")
        traceback.print_exc()

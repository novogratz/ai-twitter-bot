import os
import tweepy


def get_twitter_client() -> tweepy.Client:
    return tweepy.Client(
        bearer_token=os.environ["TWITTER_BEARER_TOKEN"],
        consumer_key=os.environ["TWITTER_API_KEY"],
        consumer_secret=os.environ["TWITTER_API_SECRET"],
        access_token=os.environ["TWITTER_ACCESS_TOKEN"],
        access_token_secret=os.environ["TWITTER_ACCESS_TOKEN_SECRET"],
    )


def post_tweet(text: str) -> str:
    client = get_twitter_client()
    response = client.create_tweet(text=text)
    tweet_id = response.data["id"]
    print(f"Tweet posted (id={tweet_id}): {text}")
    return tweet_id

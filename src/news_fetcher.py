import os
import requests


def fetch_ai_news() -> list[dict]:
    """Fetch recent AI news headlines from NewsAPI."""
    api_key = os.environ["NEWS_API_KEY"]
    url = "https://newsapi.org/v2/everything"
    params = {
        "q": "artificial intelligence OR AI OR machine learning OR LLM",
        "language": "en",
        "sortBy": "publishedAt",
        "pageSize": 10,
        "apiKey": api_key,
    }
    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status()
    articles = response.json().get("articles", [])
    return [
        {"title": a["title"], "description": a.get("description", ""), "url": a["url"]}
        for a in articles
        if a.get("title") and "[Removed]" not in a["title"]
    ]

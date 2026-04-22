import anthropic


def generate_tweet(news_articles: list[dict]) -> str:
    """Use Claude to generate a French tweet about AI news."""
    client = anthropic.Anthropic()

    news_text = "\n".join(
        f"- {a['title']}: {a['description']}" for a in news_articles[:5]
    )

    prompt = f"""Tu es un expert en intelligence artificielle qui gère un compte Twitter francophone.
Voici les dernières actualités IA du moment :

{news_text}

Rédige un tweet en français (280 caractères max) qui :
- Commente une de ces actualités ou synthétise une tendance
- Est engageant et informatif
- Utilise 2-3 hashtags pertinents (#IA #IntelligenceArtificielle #MachineLearning etc.)
- A un ton professionnel mais accessible
- Ne commence pas par "Tweet :" ou des guillemets

Réponds uniquement avec le texte du tweet, rien d'autre."""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text.strip()

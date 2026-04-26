"""Cross-agent topic dedup — extract recently-covered entities from history
so news + hot-take prompts can hard-ban the same subjects across BOTH paths.

Before this module: news agent and hot-take agent each ran their own dedup,
so a topic could appear once as news and again as a hot take within an hour
without either side noticing. This unifies the entity ban so the audience
doesn't see "Claude Code" twice in two different formats.
"""
import re
from collections import Counter

# Known AI/crypto/bourse entities — single hit in history is enough to ban.
_KNOWN_ENTITIES = {
    "Anthropic", "Claude", "Claude Code", "OpenAI", "GPT", "ChatGPT",
    "Mistral", "xAI", "Grok", "Gemini", "Google", "DeepMind", "Meta",
    "Llama", "Microsoft", "Copilot", "Nvidia", "AMD", "Intel", "TSMC",
    "Bitcoin", "BTC", "Ethereum", "ETH", "Solana", "Tether", "USDC",
    "Binance", "Coinbase", "Kraken", "FTX", "MicroStrategy",
    "S&P", "S&P 500", "CAC 40", "NASDAQ", "Bercy", "BCE", "Fed",
    "Mistral AI", "Hugging Face", "ServiceNow", "Salesforce",
    "Macron", "Lagarde", "Powell", "Musk", "Altman", "Zuckerberg",
    "PSG", "RER B", "BFM", "Pôle Emploi", "URSSAF",
    # Recent additions (2026-04-26 PM): trending names that kept showing up
    "DeepSeek", "Tesla", "Apple", "Amazon", "Palantir", "Karp",
}

# Sentence-initial / pronoun caps that aren't real entities — must NOT be
# treated as topics or every tweet's first word would get banned.
_STOPWORD_CAPS = {
    "Le", "La", "Les", "Un", "Une", "Des", "Du", "De", "Et", "Ou", "Mais",
    "On", "Tu", "Vous", "Nous", "Ils", "Elles", "Je", "Il", "Elle", "Ce",
    "Cette", "Ces", "Mon", "Ma", "Mes", "Ton", "Ta", "Tes", "Son", "Sa",
    "Ses", "Quand", "Si", "Comme", "Pour", "Sans", "Avec", "Dans", "Sur",
    "Sous", "Par", "Vers", "Chez", "Tout", "Tous", "Toute", "Toutes",
    "Plus", "Moins", "Bien", "Mal", "Très", "Encore", "Déjà", "Toujours",
    "Jamais", "Aussi", "Donc", "Alors", "Puis", "Voilà", "Voici", "Oui",
    "Non", "Bon", "OK", "Bref", "Magnifique", "Sublime", "Bonjour",
    "The", "A", "An", "This", "That", "I", "You", "He", "She", "It", "We",
    "They", "Just", "Now", "When", "Where", "What", "Who", "Why", "How",
}


def extract_recent_topics(recent: list) -> set:
    """Return the set of topics that recur strongly enough in `recent` to
    warrant banning from the next generation. A known entity hit OR two
    capitalized-phrase hits both qualify."""
    if not recent:
        return set()
    counter = Counter()
    for tweet in recent:
        for ent in _KNOWN_ENTITIES:
            if re.search(rf"\b{re.escape(ent)}\b", tweet, flags=re.IGNORECASE):
                counter[ent] += 2  # weighted so a single hit is enough
        for cap in re.findall(
            r"\b[A-ZÉÈÊÀ][a-zéèêà]+(?:\s+[A-ZÉÈÊÀ][a-zéèêà]+)?\b", tweet
        ):
            if cap not in _STOPWORD_CAPS and len(cap) >= 3:
                counter[cap] += 1
    return {ent for ent, c in counter.items() if c >= 2}

import subprocess
from typing import Optional
from .history import get_recent_tweets

PROMPT_TEMPLATE = """Tu es un influenceur IA ultra-connecté avec un style percutant et provocateur. Tu gères un compte Twitter viral en français.

ÉTAPE 1 — RECHERCHE : Fais PLUSIEURS recherches web pour trouver les news IA des 15 DERNIÈRES MINUTES.
Cherche en anglais ET en français pour couvrir plus large :
- "AI news today" / "actualités IA aujourd'hui"
- "AI breaking news" / "IA dernière heure"
- "AI announcement today"
- Noms spécifiques : OpenAI, Anthropic, Google DeepMind, Meta AI, Mistral, xAI, Stability AI
- Cherche aussi sur Twitter/X : "AI just announced", "breaking AI"

ÉTAPE 2 — SÉLECTION : Choisis l'info la PLUS FRAÎCHE et SURPRENANTE. Privilégie :
- Les scoops, fuites, annonces de dernière minute
- Les chiffres choquants (levées de fonds, benchmarks, utilisateurs)
- Les controverses et dramas dans la communauté IA
- Les retournements de situation inattendus
- ÉVITE les news génériques que tout le monde connaît déjà

{dedup_section}

ÉTAPE 3 — RÉDACTION : Écris UN tweet viral en français (280 chars max).
Style obligatoire :
- Commence par un HOOK percutant (chiffre choc, question provocante, affirmation bold)
- Donne une opinion tranchée ou un angle que personne d'autre n'a
- Utilise un ton direct, presque journalistique mais avec du caractère
- AÈRE le tweet : utilise des sauts de ligne pour séparer le hook, le contenu, et les hashtags
- Mets les hashtags sur une ligne séparée à la fin
- 2-3 hashtags max, bien choisis
- PAS de emojis excessifs, PAS de ton corporate, PAS de "c'est fascinant"

Format exemple :
[Hook percutant]

[Détail / opinion]

🔗 [URL source]

#Hashtag1 #Hashtag2

IMPORTANT : Inclus TOUJOURS le lien URL de ta source principale dans le tweet.

Si AUCUNE actualité vraiment nouvelle et différente n'existe, réponds UNIQUEMENT avec le mot : SKIP

Sinon, réponds UNIQUEMENT avec le texte final du tweet, sans guillemets ni explication."""


def generate_tweet() -> Optional[str]:
    """Invoke the Claude Code CLI to search the web for AI news and write a French tweet.
    Returns None if no fresh news is found."""
    recent = get_recent_tweets(hours=24)

    if recent:
        tweets_list = "\n".join(f"- {t}" for t in recent)
        dedup_section = f"""⚠️ ANTI-DOUBLON : Voici les tweets déjà publiés ces dernières 24h. Tu ne dois PAS tweeter sur le même sujet ou la même news :
{tweets_list}

Choisis une actualité DIFFÉRENTE de celles ci-dessus."""
    else:
        dedup_section = ""

    prompt = PROMPT_TEMPLATE.format(dedup_section=dedup_section)

    result = subprocess.run(
        [
            "claude",
            "-p", prompt,
            "--allowedTools", "WebSearch",
            "--model", "claude-sonnet-4-6",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"Claude CLI stderr: {result.stderr}")
        raise RuntimeError(f"Claude CLI failed (exit {result.returncode}): {result.stderr}")
    tweet = result.stdout.strip()
    if not tweet:
        raise RuntimeError("Claude CLI returned empty output.")
    if tweet.upper() == "SKIP":
        return None
    return tweet

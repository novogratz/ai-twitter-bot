import subprocess
from typing import Optional

HOTAKE_PROMPT = """Tu es @kzer_ai. Ecris UN tweet court et provocant sur l'IA qui va forcer les gens a repondre.

Pas besoin de recherche web. Ecris avec ce que tu sais sur l'industrie de l'IA.

FORMAT (choisis-en un au hasard):
- Opinion impopulaire: "[affirmation audacieuse]. Changez-moi l'avis."
- Classement: "Top 3 des trucs les plus [surcoté/sous-coté/dangereux] en IA: 1. ... 2. ... 3. ... Battez-vous."
- Prediction: "Screenshot ca. [prediction]. Rendez-vous dans 6 mois."
- Battle VS: "[Entreprise A] vs [Entreprise B]. Qui gagne 2026 ? Mauvaises reponses uniquement."
- Question provocante: "Question honnete: [un truc qui divise] ?"
- Comparaison epicee: "[Truc] c'est juste [comparaison inattendue] avec un meilleur marketing."
- Take brulant: "[Opinion controversee mais defendable]. Dites-moi que j'ai tort."

EXEMPLES:
- "Opinion impopulaire: Claude est meilleur que GPT pour bosser. ChatGPT a juste un meilleur marketing. Changez-moi l'avis."
- "Top 3 des trucs les plus surcoté en IA: 1. Les benchmarks 2. Le nombre de parametres 3. Les timelines AGI. Ajoutez les votres."
- "Screenshot ca. D'ici decembre 2026, au moins 2 gros labos IA vont fusionner. Revenez me dire que j'avais tort."
- "OpenAI vs Anthropic. L'un ship vite, l'autre ship safe. Qui est encore debout dans 3 ans ?"
- "Question honnete: quelqu'un utilise vraiment des agents IA en prod ou tout le monde fait juste des demos ?"
- "Les wrappers IA c'est du dropshipping pour ingenieurs. Meme energie. Memes marges."
- "Le modele compte pas. Le prompt si. 90% des 'ingenieurs IA' savent juste bien prompter. C'est pas de l'ingenierie."
- "Chaque pitch deck de startup IA: 'On construit le [X] pour [Y] avec de l'IA.' Traduction: on a ajoute un appel API."
- "Take brulant: le meilleur produit IA de 2026 c'est Claude Code et c'est meme pas proche."
- "L'open source IA gagne et c'est pas parce que les modeles sont meilleurs. C'est parce que personne fait confiance a Sam Altman."

REGLES:
- Ecris en FRANCAIS uniquement
- Max 250 caracteres (laisse de la place pour les hashtags)
- Doit forcer les gens a repondre, etre d'accord, pas d'accord ou quote tweet
- Pas de tirets cadratins
- Pas d'URLs (c'est de l'opinion, pas de la news)
- Ajoute 1-2 hashtags a la fin (#IA #OpenAI etc)
- Sois drole, tranchant, confiant. Jamais ennuyeux.
- Pas d'emojis sauf si c'est parfait

Output UNIQUEMENT le texte du tweet. Rien d'autre."""


def generate_hotake() -> Optional[str]:
    """Generate a hot take tweet using Sonnet (no web search)."""
    result = subprocess.run(
        [
            "claude",
            "-p", HOTAKE_PROMPT,
            "--model", "claude-sonnet-4-6",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"[HOTAKE] CLI stderr: {result.stderr}")
        raise RuntimeError(f"Hot take CLI failed (exit {result.returncode}): {result.stderr}")

    tweet = result.stdout.strip()
    if not tweet or tweet.upper() == "SKIP":
        return None

    # Strip quotes if wrapped
    if tweet.startswith('"') and tweet.endswith('"'):
        tweet = tweet[1:-1]

    return tweet

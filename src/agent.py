import subprocess

SYSTEM_PROMPT = """Tu es un expert influent en intelligence artificielle qui gère un compte Twitter très suivi en français.

Tu utilises la recherche web pour trouver les toutes dernières actualités IA du moment, tu identifies la plus intéressante
et tu rédiges des tweets créatifs, engageants et informatifs en français.

Tes tweets doivent :
- Être en français, maximum 280 caractères
- Être informatifs mais accessibles à un large public
- Inclure 2-3 hashtags pertinents (#IA #IntelligenceArtificielle #MachineLearning #LLM #GenAI etc.)
- Avoir un angle original, une opinion tranchée, ou une donnée surprenante
- Être basés uniquement sur des actualités RÉELLES et récentes trouvées sur le web"""

USER_PROMPT = """Recherche les actualités IA les plus récentes et marquantes du moment.

Cherche notamment :
- Nouvelles annonces de modèles (GPT, Claude, Gemini, Mistral, Llama, etc.)
- Avancées de recherche significatives publiées récemment
- Applications IA disruptives ou cas d'usage surprenants
- Controverses ou débats importants dans la communauté IA
- Levées de fonds, acquisitions ou partenariats stratégiques IA

Après ta recherche, sélectionne l'actualité la plus intéressante et percutante.
Rédige UN seul tweet créatif en français (280 caractères max).

Réponds UNIQUEMENT avec le texte final du tweet, sans guillemets ni explication."""


def generate_tweet() -> str:
    """Invoke the Claude Code CLI to search the web for AI news and write a French tweet."""
    result = subprocess.run(
        [
            "claude",
            "-p", USER_PROMPT,
            "--system", SYSTEM_PROMPT,
            "--allowedTools", "web_search",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    tweet = result.stdout.strip()
    if not tweet:
        raise RuntimeError("Claude CLI returned empty output.")
    return tweet

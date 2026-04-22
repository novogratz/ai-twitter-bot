import anthropic

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
    """Run the Claude agent: autonomously search the web for AI news, then write a French tweet."""
    client = anthropic.Anthropic()

    tools = [{"type": "web_search_20260209", "name": "web_search"}]
    messages = [{"role": "user", "content": USER_PROMPT}]

    max_continuations = 5
    for _ in range(max_continuations):
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=4096,
            thinking={"type": "adaptive"},
            system=SYSTEM_PROMPT,
            tools=tools,
            messages=messages,
        )

        if response.stop_reason == "end_turn":
            for block in response.content:
                if block.type == "text":
                    return block.text.strip()

        elif response.stop_reason == "pause_turn":
            # Server-side search loop hit its iteration limit — resume
            messages.append({"role": "assistant", "content": response.content})
            continue

        # Any other stop reason — extract whatever text we have
        for block in response.content:
            if block.type == "text":
                return block.text.strip()
        break

    raise RuntimeError("Agent did not produce a tweet after max continuations.")

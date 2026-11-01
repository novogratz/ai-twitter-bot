"""Fictitious per-author instructions for engine tests, never live targets."""

PROMPTS = {
    "special": "Reply to @{author} about {tweet_text}. Keep a playful, precise SI observation.",
    "friendly": "Reply warmly to @{author}: {tweet_text}. A short reaction is welcome.",
}

DOSSIER = {
    "first_seen": "2026-05-02", "last_interaction": "2026-05-02",
    "interaction_count": 0, "category": "builder", "stance": "fond",
    "notes": ["Shares useful SI projects."], "predictions": [],
    "feelings": "Warm respect.", "do": "Be curious and specific.",
    "dont": "Do not invent results.",
}

RELATIONS_TOML = '''
[relations.handles.FriendlyVip]
prompt = "relations/friendly.md"

[relations.handles.SpecialVip]
prompt = "relations/special.md"
provider = "codex"

[relations.handles.FixedDossier.dossier]
first_seen = "2026-05-02"
last_interaction = "2026-05-02"
category = "builder"
stance = "fond"
notes = [
    "Shares useful SI projects.",
]
feelings = "Warm respect."
do = "Be curious and specific."
dont = "Do not invent results."
'''

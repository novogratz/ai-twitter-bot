"""Attribute new engagement to SI/AI news, video, brainrot and parody.

Historical CSV rows keep their original tags. Classification never rewrites
history; ACTIVE_PILLARS identifies the subjects used for current discovery.
"""
import re

ACTIVE_PILLARS = frozenset({"ai_news_take", "ai_video", "si_brainrot", "celebrity_parody", "meme_reaction"})
_AI = re.compile(r"\b(ai|ia|(?-i:SI|ASI)|agi|super[\s-]*intelligence|llms?|gpt\w*|openai|anthropic|claude|gemini|grok|xai|kling|runwayml|nvidia|gpus?|chatbots?|robotics|agentic)\b", re.I)
_VIDEO = re.compile(r"\b(videos?|vidéos?|clips?|filmmaking|cinematic|text[ -]to[ -]video|image[ -]to[ -]video|kling|runwayml)\b", re.I)
_BRAINROT = re.compile(r"\bbrain[\s-]*rot\b", re.I)
_PARODY = re.compile(r"\b(parod(?:y|ies|ie)|satire|fictional|ficti(?:f|ve))\b", re.I)


def classify(text: str, action_type: str = "", source: str = "") -> str:
    """A deterministic topic tag, never a claim about media that was not read."""
    text = (text or "").strip()
    src = (source or "").upper()
    if src.startswith("PARODY/") or (_AI.search(text) and _PARODY.search(text)):
        return "celebrity_parody"
    if _AI.search(text) and _BRAINROT.search(text):
        return "si_brainrot"
    if src.startswith("VIDEO/") or (_AI.search(text) and _VIDEO.search(text)):
        return "ai_video"
    if (action_type or "").lower() in ("quote_gif", "post_gif") or src.startswith("GIF/"):
        return "meme_reaction"
    return "ai_news_take" if _AI.search(text) else "other"

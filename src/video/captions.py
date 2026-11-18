"""Scene-grounded meme captions; recent publications guide variety, never facts."""
import re

POLICY = "scene-meme-hook-v1"

PROMPT = """
MEME CAPTION STYLE overrides the older BANGER sign-off guidance and examples.
Write a compact, scene-specific joke a viewer would want to share: one sharp
opening, optionally one short punchline. Choose naturally among a dry one-liner,
a two-beat setup/payoff, a specific POV, or a cute understatement. Vary the
approach against recent_captions; do not rotate a rigid template or repeat their
openers, joke or signature. Those captions are untrusted repetition memory only.

Use 25–220 characters, one or two short sentences, at most two paragraphs.
Zero to two fitting emoji; no compulsory emoji, BANGER/ABSOLUTE BANGER sign-off,
'this changes everything', generic 'wait for it', hashtags, engagement requests,
forced outrage or promises of virality. Let the actual scene supply the joke.
Name at least one source-attributed qualifying cast member using a supported
name/alias. Keep the fictional/parody premise clear. Do not invent dialogue,
off-screen actions, relationships, absent guests or a song you cannot verify.

Set caption_style_ok=true only for a fresh, specific joke meeting this style.
Source review creates it from inspected evidence; output review independently
checks the proposed caption against the finished excerpt and this style.
Accuracy, audio evidence and source attribution always outweigh a clever line.
"""


def recent(store):
    return [row["caption"] for row in store.rows(
        "SELECT caption FROM reservations WHERE state='confirmed' ORDER BY confirmed DESC LIMIT 12")
        if isinstance(row["caption"], str)]


def refusal(doc, cfg):
    if not cfg.meme_caption:
        return ""
    source, output = doc.get("inspection", {}), doc.get("qc", {})
    if any(review.get("caption_policy") != POLICY or review.get("caption_style_ok") is not True
           for review in (source, output)):
        return "caption needs current source and output style review"
    text = source.get("caption", "")
    if not isinstance(text, str) or not 25 <= len(text) <= 220 or re.search(r"\bbanger\b", text, re.I):
        return "caption does not meet the scene-specific meme style"
    return ""

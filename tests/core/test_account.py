"""src/core/account: the Account BOT_ACCOUNT picks, its account.toml checked
at start, and its layer in the settings (#202)."""
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from src.core import account, config, settings
from src.editorial import editorial_bot as editorial

ROOT = Path(__file__).resolve().parents[2]
THEAISHRINK = (ROOT / "accounts" / "theaishrink" / "account.toml").read_text()

# The constants of src/editorial/editorial_bot.py and src/editorial/trending.py,
# and the settings defaults, printed from the code before #202 moved them to
# accounts/theaishrink/account.toml.
TREND_PURPOSE = "Trending: the AI topic X is talking about right now, told from a trusted source"
OLD = {
    "SLOTS": [("05:00", "Priority: the AI update worth understanding this morning"),
              ("07:15", "A useful AI workflow with a concrete first step"),
              ("09:30", "Priority: an AI article or model update with a sharp consequence"),
              ("10:00", "Trending: the AI topic X is talking about right now, told from a trusted source"),
              ("11:45", "An AI concept explained through a clear example"),
              ("13:00", "Trending: the AI topic X is talking about right now, told from a trusted source"),
              ("14:00", "A model or tool update and what changes for its users"),
              ("15:00", "Trending: the AI topic X is talking about right now, told from a trusted source"),
              ("16:15", "Priority: an evidence-backed take on an AI tradeoff"),
              ("18:30", "A practical AI idea worth saving or sharing"),
              ("20:45", "Optional: an exceptional fresh AI update or unusually useful source")],
    "TREND_SLOTS": ["10:00", "13:00", "15:00"],
    "TREND_PURPOSE": TREND_PURPOSE,
    "EXCEPTIONAL_SLOT": "20:45",
    "FEEDS": [("OpenAI", "https://openai.com/news/rss.xml"),
              ("Google AI", "https://blog.google/technology/ai/rss/"),
              ("DeepMind", "https://deepmind.google/blog/rss.xml"),
              ("Hugging Face", "https://huggingface.co/blog/feed.xml"),
              ("NVIDIA", "https://blogs.nvidia.com/feed/"),
              ("Microsoft Research", "https://www.microsoft.com/en-us/research/feed/"),
              ("Mistral AI", "https://mistral.ai/rss.xml"),
              ("Replicate", "https://replicate.com/blog/rss"),
              ("The Decoder", "https://the-decoder.com/feed/"),
              ("arXiv cs.AI", "https://rss.arxiv.org/rss/cs.AI")],
    "KNOWLEDGE": [("chat_templates", "Why a chat template changes model behavior",
                   "https://huggingface.co/docs/transformers/chat_templating"),
                  ("evaluation", "How to evaluate an AI model on your own examples",
                   "https://huggingface.co/docs/evaluate/index"),
                  ("quantization", "What quantization trades for smaller AI models",
                   "https://huggingface.co/docs/transformers/quantization/overview"),
                  ("retrieval", "When retrieval can improve a language model's answers",
                   "https://huggingface.co/learn/cookbook/en/advanced_rag"),
                  ("structured_output", "Why structured output still needs factual checks",
                   "https://huggingface.co/docs/inference-providers/guides/structured-output"),
                  ("agents", "When an agent loop is useful and when it adds complexity",
                   "https://huggingface.co/docs/smolagents/conceptual/tutorial"),
                  ("tool_use", "What changes when a model can call tools",
                   "https://huggingface.co/docs/transformers/chat_extras"),
                  ("generation", "What temperature actually changes in generated text",
                   "https://huggingface.co/docs/transformers/main_classes/text_generation"),
                  ("lora", "What a small adapter changes during model fine tuning",
                   "https://huggingface.co/docs/peft/conceptual_guides/lora"),
                  ("tokenization", "Why tokenization matters for context budgets",
                   "https://huggingface.co/docs/transformers/tokenizer_summary"),
                  ("model_cards", "What to check in a model card before using a model",
                   "https://huggingface.co/docs/hub/model-cards"),
                  ("datasets", "Why the evaluation dataset matters as much as the score",
                   "https://huggingface.co/docs/datasets/about_dataset_features")],
    "KNOWLEDGE_PUBLISHER": "Hugging Face docs",
    "HOSTS": ["arxiv.org", "blog.google", "blogs.nvidia.com", "deepmind.google", "huggingface.co",
              "mistral.ai", "openai.com", "replicate.com", "the-decoder.com", "www.microsoft.com"],
    "AI_TOPIC": ("\\b(ai|artificial intelligence|model|llm|agent|machine "
                 "learning|openai|anthropic|claude|chatgpt|gpt|gemini|deepmind|deepseek|mistral|qwen|llama|"
                 "robotics|transformer|inference|training|neural|diffusion|gpu)\\b", 34),
    "OFF_TOPIC": ("\\$[A-Za-z]{2,6}\\b|\\b(crypto|bitcoin|btc|ethereum|memecoin|airdrop|giveaway|presale)\\b", 34),
    "BOT_HANDLE": "TheAIShrink",
    "CONTENT_LANG_PRIMARY": "en",
}


def test_theaishrink_loads_the_old_constants():
    loaded = account.load("theaishrink")
    ed = loaded.editorial
    assert list(ed.slots) == OLD["SLOTS"]
    assert sorted(ed.trend_clocks) == OLD["TREND_SLOTS"]
    assert ed.trend_angle == OLD["TREND_PURPOSE"]
    assert ed.exceptional_clocks == {OLD["EXCEPTIONAL_SLOT"]}
    assert list(ed.feeds) == OLD["FEEDS"]
    assert [(t.topic, t.title, t.url) for t in ed.evergreen] == OLD["KNOWLEDGE"]
    assert {t.publisher for t in ed.evergreen} == {OLD["KNOWLEDGE_PUBLISHER"]}
    assert sorted(ed.trusted_hosts) == OLD["HOSTS"]
    assert (loaded.relevance.topic.pattern, loaded.relevance.topic.flags) == OLD["AI_TOPIC"]
    assert (loaded.relevance.off_topic.pattern, loaded.relevance.off_topic.flags) == OLD["OFF_TOPIC"]
    assert (loaded.handle, loaded.language) == (OLD["BOT_HANDLE"], OLD["CONTENT_LANG_PRIMARY"])
    assert loaded.limits == {}


def test_the_editorial_reads_the_loaded_account():
    assert settings.get("BOT_ACCOUNT") == "theaishrink"
    assert [tuple(slot) for slot in editorial.slots()] == OLD["SLOTS"]
    assert sorted(editorial.trend_slots()) == OLD["TREND_SLOTS"]
    assert [slot.clock for slot in editorial.slots() if slot.exceptional] == [OLD["EXCEPTIONAL_SLOT"]]
    assert config.BOT_HANDLE == OLD["BOT_HANDLE"]


# --- Loading: BOT_ACCOUNT, and the settings layers ------------------------------


@pytest.fixture
def accounts(monkeypatch, tmp_path):
    """`write(name, text)` puts an account.toml under a temporary accounts/."""
    folder = tmp_path / "accounts"
    monkeypatch.setattr(account, "ACCOUNTS_DIR", str(folder))
    monkeypatch.setattr(account, "_loaded", {})

    def write(name, text=THEAISHRINK):
        (folder / name).mkdir(parents=True, exist_ok=True)
        (folder / name / "account.toml").write_text(text)
    return write


@pytest.fixture
def fresh(monkeypatch, tmp_path):
    """Settings that have not loaded yet: `load(env_text, environ)`."""
    monkeypatch.setattr(settings, "_values", None)
    monkeypatch.setattr(settings, "_warnings", [])
    env_file = tmp_path / ".env"

    def load(text="", environ=None):
        env_file.write_text(text)
        environ = {} if environ is None else environ
        settings.load(env_file=str(env_file), environ=environ)
        return environ
    return load


def test_bot_account_picks_the_folder(accounts, fresh):
    accounts("other", THEAISHRINK.replace('handle = "TheAIShrink"', 'handle = "OtherBot"')
             .replace('language = "en"', 'language = "fr"'))
    environ = fresh("BOT_ACCOUNT=other\n")
    assert account.current().name == "other"
    assert settings.get("BOT_HANDLE") == "OtherBot"
    assert config.BOT_PROFILE_URL == "https://x.com/OtherBot"
    assert settings.get("CONTENT_LANG_PRIMARY") == "fr"
    # content_guard and editorial_bot still read the language from the environment.
    assert environ["CONTENT_LANG_PRIMARY"] == "fr"


def test_env_wins_over_the_account(accounts, fresh):
    accounts("theaishrink")
    environ = fresh("BOT_HANDLE=FromEnv\nCONTENT_LANG_PRIMARY=fr\n")
    assert settings.get("BOT_HANDLE") == "FromEnv"
    assert environ["CONTENT_LANG_PRIMARY"] == "fr"


@pytest.mark.parametrize("value", ["missing", "../theaishrink", "", "TheAIShrink"])
def test_an_unknown_bot_account_stops_the_start(accounts, fresh, value):
    accounts("theaishrink")
    with pytest.raises(settings.SettingsError, match="BOT_ACCOUNT"):
        fresh(f"BOT_ACCOUNT={value}\n")


def test_main_stops_on_an_unknown_bot_account():
    env = {**os.environ, "BOT_ACCOUNT": "no-such-account"}
    out = subprocess.run([sys.executable, "main.py", "--dry-run"], env=env, cwd=ROOT,
                         capture_output=True, text=True)
    assert out.returncode != 0
    assert "BOT_ACCOUNT=no-such-account" in out.stderr
    assert out.stdout == ""


# --- account.toml: unknown keys and badly typed values stop the start -----------


@pytest.mark.parametrize("old, new, named", [
    ('handle = "TheAIShrink"', 'handle = "TheAIShrink"\nnickname = "shrink"', "nickname"),
    ('trend_angle =', 'trend_hours = 3\ntrend_angle =', "editorial.trend_hours"),
    ('{ clock = "10:00", trend = true }', '{ clock = "10:00", trend = true, weight = 2 }',
     "editorial.slots[3].weight"),
    ('publisher = "OpenAI", url', 'publisher = "OpenAI", lang = "en", url', "editorial.feeds[0].lang"),
    ('[relevance]', '[relevance]\nniche = "ai"', "relevance.niche"),
    ('[limits]', '[limits]\nMAX_ORIGINALS_PER_DA = 6', "limits.MAX_ORIGINALS_PER_DA"),
    # A setting without a bound is the engine's, not the Account's.
    ('[limits]', '[limits]\nMAX_FOLLOWS_PER_DAY = 5', "limits.MAX_FOLLOWS_PER_DAY"),
])
def test_an_unknown_key_stops_the_start(accounts, fresh, old, new, named):
    assert THEAISHRINK.count(old) == 1
    accounts("theaishrink", THEAISHRINK.replace(old, new))
    with pytest.raises(settings.SettingsError, match=re.escape(named)):
        fresh()


@pytest.mark.parametrize("old, new, named", [
    ('handle = "TheAIShrink"', "handle = 3", "handle"),
    ('language = "en"', 'language = "de"', "language"),
    ('{ clock = "10:00", trend = true }', '{ clock = "10:00", trend = "yes" }', "editorial.slots[3].trend"),
    ('{ clock = "10:00", trend = true }', '{ clock = "10h00", trend = true }', "editorial.slots[3].clock"),
    ('{ clock = "10:00", trend = true }', '{ clock = "09:00", trend = true }', "editorial.slots[3].clock"),
    ('{ clock = "10:00", trend = true }', '{ clock = "10:00" }', "editorial.slots[3].angle"),
    ('{ clock = "10:00", trend = true }', '{ clock = "10:00", trend = true, angle = "x" }',
     "editorial.slots[3].angle"),
    ('"openai.com", "blog.google"', '"openai.com", 7', "editorial.trusted_hosts[1]"),
    ('chat_templating"\npublisher = "Hugging Face docs"', 'chat_templating"\npublisher = true',
     "editorial.evergreen[0].publisher"),
    ("off_topic = '", "off_topic = '(", "relevance.off_topic"),
    ('[limits]', '[limits]\nMAX_ORIGINALS_PER_DAY = "6"', "limits.MAX_ORIGINALS_PER_DAY"),
    ('handle = "TheAIShrink"\n', "", "handle"),
    ('handle = "TheAIShrink"', 'handle = "TheAIShrink', "not valid TOML"),
])
def test_a_badly_typed_value_stops_the_start(accounts, fresh, old, new, named):
    assert THEAISHRINK.count(old) == 1
    accounts("theaishrink", THEAISHRINK.replace(old, new))
    with pytest.raises(settings.SettingsError, match=re.escape(named)):
        fresh()


# --- Limits: an Account may only tighten an engine bound ------------------------


@pytest.mark.parametrize("limit, name, bound", [
    ("MAX_ORIGINALS_PER_DAY = 12", "MAX_ORIGINALS_PER_DAY", 8),
    ("MIN_SECONDS_BETWEEN_POSTS = 60", "MIN_SECONDS_BETWEEN_POSTS", 1200),
    ("POST_JITTER_SECONDS = -30", "POST_JITTER_SECONDS", 0),
])
def test_an_account_value_past_an_engine_bound_is_brought_back_to_it(accounts, fresh, limit, name, bound):
    accounts("theaishrink", THEAISHRINK.replace("[limits]", f"[limits]\n{limit}"))
    fresh()
    assert settings.get(name) == bound
    assert [w for w in settings.startup_warnings()
            if w.startswith(os.path.join(account.ACCOUNTS_DIR, "theaishrink", "account.toml")) and name in w]


def test_a_stricter_account_value_holds_under_the_defaults_and_env_wins_over_it(accounts, fresh):
    accounts("theaishrink", THEAISHRINK.replace(
        "[limits]", "[limits]\nMAX_ORIGINALS_PER_DAY = 5\nMIN_SECONDS_BETWEEN_POSTS = 3600"))
    fresh("MIN_SECONDS_BETWEEN_POSTS=2400\n")
    assert settings.get("MAX_ORIGINALS_PER_DAY") == 5
    assert settings.get("MIN_SECONDS_BETWEEN_POSTS") == 2400
    assert settings.startup_warnings() == []

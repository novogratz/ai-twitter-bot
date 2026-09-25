"""src/core/account: the Account BOT_ACCOUNT picks, its account.toml checked
at start, and its layer in the settings (#202)."""
import os
import re
import shutil
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
    """`write(name, text)` puts an account.toml under a temporary accounts/,
    next to a copy of theaishrink's other files (Voice, Relation prompts)."""
    folder = tmp_path / "accounts"
    monkeypatch.setattr(account, "ACCOUNTS_DIR", str(folder))
    monkeypatch.setattr(account, "_loaded", {})

    def write(name, text=THEAISHRINK):
        shutil.copytree(ROOT / "accounts" / "theaishrink", folder / name, dirs_exist_ok=True)
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
    fresh("BOT_ACCOUNT=other\n")
    assert account.current().name == "other"
    assert settings.get("BOT_HANDLE") == "OtherBot"
    assert config.BOT_PROFILE_URL == "https://x.com/OtherBot"
    assert settings.get("CONTENT_LANG_PRIMARY") == "fr"


def test_the_account_folder_is_absolute_and_follows_accounts_dir(accounts, fresh, tmp_path):
    accounts("other")
    fresh("BOT_ACCOUNT=other\n")
    assert account.current().folder == str(tmp_path / "accounts" / "other")


def test_the_real_account_folder_holds_its_account_toml(monkeypatch, unwalled):
    monkeypatch.setattr(account, "ACCOUNTS_DIR", unwalled["accounts_dir"])
    folder = account.load("theaishrink").folder
    assert os.path.isabs(folder)
    assert Path(folder).resolve() == ROOT / "accounts" / "theaishrink"


def test_env_wins_over_the_account(accounts, fresh):
    accounts("theaishrink")
    fresh("BOT_HANDLE=FromEnv\nCONTENT_LANG_PRIMARY=fr\n")
    assert settings.get("BOT_HANDLE") == "FromEnv"
    assert settings.get("CONTENT_LANG_PRIMARY") == "fr"


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
    ('[limits]', '[limits]\nMIN_SECONDS_BETWEEN_FOLLOWS = 900', "limits.MIN_SECONDS_BETWEEN_FOLLOWS"),
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


@pytest.mark.parametrize("new, problem", [
    ('{ clock = "10:00" }', "editorial.slots[3].angle is required unless trend = true."),
    ('{ clock = "10:00", trend = true, angle = "x" }',
     "editorial.slots[3].angle must be absent when trend = true, which takes trend_angle instead."),
])
def test_a_slot_angle_is_required_or_forbidden_by_trend(accounts, fresh, new, problem):
    old = '{ clock = "10:00", trend = true }'
    assert THEAISHRINK.count(old) == 1
    accounts("theaishrink", THEAISHRINK.replace(old, new))
    with pytest.raises(settings.SettingsError) as raised:
        fresh()
    assert str(raised.value).endswith(problem)


# --- Limits: an Account may only tighten an engine bound ------------------------


@pytest.mark.parametrize("limit, name, bound", [
    ("MAX_ORIGINALS_PER_DAY = 12", "MAX_ORIGINALS_PER_DAY", 8),
    ("MIN_SECONDS_BETWEEN_POSTS = 60", "MIN_SECONDS_BETWEEN_POSTS", 1200),
    ("POST_JITTER_SECONDS = -30", "POST_JITTER_SECONDS", 0),
    # The Operator's bounds of #201.
    ("FOLLOW_TOTAL_CAP = 5000", "FOLLOW_TOTAL_CAP", 3500),
    ("LIKE_BOT_DAILY_CAP = 1800", "LIKE_BOT_DAILY_CAP", 500),
    ("MIN_SECONDS_BETWEEN_REPLIES = 0", "MIN_SECONDS_BETWEEN_REPLIES", 8),
    ("DUP_TEXT_WINDOW_HOURS = 12", "DUP_TEXT_WINDOW_HOURS", 48.0),
    ("BAN_SHORT_TERM_PRICE_TARGETS = false", "BAN_SHORT_TERM_PRICE_TARGETS", True),
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


def test_a_stricter_account_value_holds_for_the_operator_bounds(accounts, fresh):
    accounts("theaishrink", THEAISHRINK.replace(
        "[limits]", "[limits]\nLIKE_BOT_DAILY_CAP = 200\nDUP_JACCARD_THRESHOLD = 0.3\nREPLY_MIN_CHARS = 40"))
    fresh()
    assert settings.get("LIKE_BOT_DAILY_CAP") == 200
    assert settings.get("DUP_JACCARD_THRESHOLD") == 0.3
    assert settings.get("REPLY_MIN_CHARS") == 40
    assert settings.startup_warnings() == []


# --- Network and niche (#204) ------------------------------------------------------

# The constants of src/replies/direct_reply.py, reply_agent.py (its
# TARGET_ACCOUNTS as REPLY_TARGET_ACCOUNTS), src/account/engage_bot.py (its
# TARGET_ACCOUNTS and VIP_ACCOUNTS as ENGAGE_*), like_bot.py,
# follow_engagers_bot.py (its _SKIP_HANDLES set, sorted here) and
# src/guards/follow_policy.py, and three settings defaults, printed from the
# code before #204 moved them to accounts/theaishrink/account.toml. A pattern
# is (source, flags).
OLD_NETWORK = {
    "PROFILE_VISIT_ALLOWLIST": "TheBTCTherapist,Graphseo",
    "VIP_SCAN_HANDLES": "Graphseo,TheBTCTherapist",
    "PINNED_TRACKED_HANDLES": "TheBTCTherapist,Graphseo,Mindset4Money_X",
    "VIP_REPLY_ACCOUNTS": [
        "TheBTCTherapist", "Graphseo", "RodolpheSteffan", "vision_ia", "FinTales_", "novogratz",
        "jbelizaireCEO", "FlasheurInvest", "ylecun", "arthurmensch", "GuillaumeLample", "fchollet",
        "karpathy", "demishassabis", "sama", "VitalikButerin", "saylor", "brian_armstrong",
        "cz_binance", "SpaceX",
    ],
    "BIG_AI_HYPE_ACCOUNTS": [
        "sama", "elonmusk", "DarioAmodei", "demishassabis", "satyanadella", "sundarpichai",
        "JensenHuang", "gdb", "miramurati", "AravSrinivas", "karpathy", "ylecun", "AndrewYNg",
        "drfeifei", "lexfridman", "ID_AA_Carmack", "fchollet", "EMostaque", "clementdelangue",
        "OpenAI", "AnthropicAI", "GoogleDeepMind", "GoogleAI", "xai", "MistralAI", "perplexity_ai",
        "nvidia", "Microsoft", "Meta", "OpenAIDevs", "huggingface", "cursor_ai", "rowancheung",
        "TheRundownAI", "minchoi", "kimmonismus", "slow_developer", "mreflow", "bentossell",
        "venturetwins", "heybarsee", "alexandr_wang", "emollick", "swyx", "_akhaliq", "GaryMarcus",
        "testingcatalog", "btibor91", "AISafetyMemes", "amasad", "OfficialLoganK", "DrJimFan",
        "sytelus",
    ],
    "MID_SIZE_AI_ACCOUNTS": [
        "hwchase17", "jerryjliu0", "yoheinakajima", "mckaywrigley", "rasbt", "Teknium1", "abacaj",
        "corbtt", "Yuchenj_UW", "nutlope", "skirano", "steph_palazzolo", "saranormous", "packyM",
        "nearcyan", "giffmana", "vikhyatk", "mattshumer_", "alexalbert__", "goodside", "simonw",
        "karinanguyen_", "charliebholtz", "amanrsanger", "mathemagic1an",
    ],
    "HIGH_TRACTION_REPLY_ACCOUNTS": [
        "PowerHasheur", "LeJournalDuCoin", "CryptoastMedia", "coinacademy_fr", "CryptoPicsou",
        "crypto_futur", "TheCrypt0Matrix", "TagadoBTC", "Crypto__Goku", "MiningTk", "MoneyRadar_FR",
        "Capetlevrai", "Dark_Emi_", "Divs_King", "MathieuL1", "NCheron_bourse", "ABaradez",
        "Phil_RX", "arthurmensch", "GuillaumeLample", "GaelVaroquaux", "fchollet", "MistralAI",
    ],
    "BIG_FR_ACCOUNTS": [
        "Korben", "micode", "Underscore_", "presse_citron", "numerama", "siecledigital", "BFMTech",
        "frandroid", "journaldugeek", "FlavienChervet", "MistralAI", "arthurmensch",
        "GuillaumeLample", "Heu7reka", "Yoann_Lopez_", "Finary", "ZonebourseFR", "BFMBourse",
        "latribune", "Capital", "LesEchos", "boursorama", "GoodValYou", "Zonebourse", "Investir",
        "SnowballEcho", "Hasheur", "cryptodiffusion", "Cointribune", "BFMcrypto", "PowerHasheur",
        "LeJournalDuCoin", "CryptoastMedia", "coinacademy_fr", "CryptoPicsou",
    ],
    "ALWAYS_REPLY_ACCOUNTS": [
        "TheBTCTherapist", "Graphseo", "RodolpheSteffan", "vision_ia", "FinTales_", "novogratz",
        "jbelizaireCEO", "FlasheurInvest", "ylecun", "arthurmensch", "GuillaumeLample", "fchollet",
        "karpathy", "demishassabis", "sama", "VitalikButerin", "saylor", "brian_armstrong",
        "cz_binance", "SpaceX", "elonmusk", "DarioAmodei", "satyanadella", "sundarpichai",
        "JensenHuang", "gdb", "miramurati", "AravSrinivas", "AndrewYNg", "drfeifei", "lexfridman",
        "ID_AA_Carmack", "EMostaque", "clementdelangue", "OpenAI", "AnthropicAI", "GoogleDeepMind",
        "GoogleAI", "xai", "MistralAI", "perplexity_ai", "nvidia", "Microsoft", "Meta",
        "OpenAIDevs", "huggingface", "cursor_ai", "rowancheung", "TheRundownAI", "minchoi",
        "kimmonismus", "slow_developer", "mreflow", "bentossell", "venturetwins", "heybarsee",
        "alexandr_wang", "emollick", "swyx", "_akhaliq", "GaryMarcus", "testingcatalog", "btibor91",
        "AISafetyMemes", "amasad", "OfficialLoganK", "DrJimFan", "sytelus", "hwchase17",
        "jerryjliu0", "yoheinakajima", "mckaywrigley", "rasbt", "Teknium1", "abacaj", "corbtt",
        "Yuchenj_UW", "nutlope", "skirano", "steph_palazzolo", "saranormous", "packyM", "nearcyan",
        "giffmana", "vikhyatk", "mattshumer_", "alexalbert__", "goodside", "simonw",
        "karinanguyen_", "charliebholtz", "amanrsanger", "mathemagic1an", "PowerHasheur",
        "LeJournalDuCoin", "CryptoastMedia", "coinacademy_fr", "CryptoPicsou", "crypto_futur",
        "TheCrypt0Matrix", "TagadoBTC", "Crypto__Goku", "MiningTk", "MoneyRadar_FR", "Capetlevrai",
        "Dark_Emi_", "Divs_King", "MathieuL1", "NCheron_bourse", "ABaradez", "Phil_RX",
        "GaelVaroquaux", "Korben", "micode", "Underscore_", "presse_citron", "numerama",
        "siecledigital", "BFMTech", "frandroid", "journaldugeek", "FlavienChervet", "Heu7reka",
        "Yoann_Lopez_", "Finary", "ZonebourseFR", "BFMBourse", "latribune", "Capital", "LesEchos",
        "boursorama", "GoodValYou", "Zonebourse", "Investir", "SnowballEcho", "Hasheur",
        "cryptodiffusion", "Cointribune", "BFMcrypto",
    ],
    "ENGAGE_VIP_ACCOUNTS": [
        "Graphseo",
    ],
    "ENGAGE_TARGET_ACCOUNTS": [
        "Graphseo", "XFenaux", "RodolpheSteffan", "FinTales_",
    ],
    "REPLY_TARGET_ACCOUNTS": [
        "Graphseo", "RodolpheSteffan", "vision_ia", "FinTales_", "novogratz", "jbelizaireCEO",
        "FlasheurInvest", "McnallieM", "sama", "OpenAI", "AnthropicAI", "GoogleDeepMind",
        "elonmusk", "xAI", "karpathy", "ylecun", "fchollet", "demishassabis", "MistralAI",
        "arthurmensch", "GuillaumeLample", "GaelVaroquaux", "nvidia", "AMD", "intel", "CoreWeave",
        "IREN_Ltd", "LambdaAPI", "applied_dc", "KobeissiLetter", "unusual_whales", "SpaceX",
        "Tesla", "BostonDynamics", "Figure_robot", "ID_AA_Carmack", "drfeifei", "NCheron_bourse",
        "ABaradez", "IVTrading", "Yoann_Lopez_", "SnowballEcho", "GoodValYou", "Finary", "LesEchos",
        "BFMBusiness", "BFMBourse", "Capital_fr", "latribune", "CafeDelaBourse", "ZoneBourse",
        "FlasheurInvest", "DereeperVivre", "Phil_RX", "Korben", "underscore_", "MichaelBenabou",
        "presse_citron", "siecledigital", "usine_digitale", "numerama", "01net", "frandroid",
        "LesNumeriques", "FrenchWeb", "MaddyNess", "arthurmensch", "GuillaumeLample",
        "GaelVaroquaux", "vision_ia", "PowerHasheur", "Capetlevrai", "CoinAcademy_FR", "saylor",
        "MicroStrategy", "VitalikButerin", "CoinDesk", "blockworks_", "Palantir",
    ],
    "SKIP_HANDLES": [
        "bloomberg", "business", "cnbc", "cointelegraph", "ft", "reuters", "unusual_whales",
        "watcherguru", "wsj", "zerohedge",
    ],
    "NICHE_PATTERN": (
        r"\b(ai|i\.a|ia|agi|llm|gpt|chatgpt|claude|openai|anthropic|mistral|gemini|grok|xai|"
        r"deepseek|huggingface|nvidia|cuda|gpu|tpu|agent|agents|robot|robots|humanoide|"
        r"humanoïde|altman|musk|ml|deep\s*learning|neural|saas|software|cloud|datacenter|codex|"
        r"copilot|cursor|windsurf|replit|programmeur|coding|coder|développeur|ide|api|sdk|"
        r"crypto|btc|bitcoin|eth|ethereum|sol|solana|xrp|blockchain|defi|stablecoin|token|"
        r"altcoin|memecoin|nft|wallet|binance|coinbase|kraken|satoshi|web3|dao|staking|yield|"
        r"dex|cex|space|espace|spatial|spacex|starship|starlink|rocket|fusée|fusee|satellite|"
        r"nasa|esa|ariane|arianegroup|blue\s*origin|orbite|orbit|astéroïde|exploration|mars|"
        r"lune|moon|cosmos|bourse|action|actions|stock|stocks|marché|trading|trader|invest|"
        r"investir|portefeuille|etf|pea|cto|cac|cac40|nasdaq|fed|bce|taux|powell|lagarde|"
        r"rendement|dividendes|ipo|valuation|per|fcf|roe|roic|livret|assurance|levée|fund|"
        r"funding|vc|venture|startup|banque|fintech|néobanque|paiement|virement|swift|sepa|immo|"
        r"immobilier|inflation|récession|earnings|acquisition|merger|m&a|finance|cotation|"
        r"pétrole|xau|commodity|semi.?conducteur|bullish|bearish|oversold|resistance|support|"
        r"volatility|krach|goldman|jpmorgan|morgan\s*stanley|dette|deficit|fiscal|impot|budget|"
        r"deflation|monetaire|souverain|oat|spread|notation|moody|tesla|meta|microsoft|google|"
        r"amazon|apple|netflix|alphabet|spotify|uber|airbnb|palantir|shopify|stripe|databricks|"
        r"snowflake|datadog|cloudflare)\b", 34),
    "TICKER_RE": (r"\$[A-Z]{1,5}\b", 32),
    "NICHE_BIO_RE": (
        r"\b(ai|a\.i\.|artificial intelligence|machine learning|\bml\b|llm|gpt|agent|crypto|"
        r"bitcoin|btc|eth|web3|defi|blockchain|token|invest|investor|investing|trader|trading|"
        r"markets?|stocks?|equit|finance|financial|fintech|macro|quant|hedge|portfolio|capital|"
        r"wealth|analyst|founder|builder|startup|venture|\bvc\b|tech|software|engineer|nvidia|"
        r"bourse|économie|economy)\b", 34),
    "SEARCH_QUERIES": [
        "from:TheBTCTherapist OR from:morganhousel OR from:ParikPatelCFA OR from:litcapital min_faves:5",
        "from:greg16676935420 OR from:ReformedBroker OR from:jasonzweigwsj OR from:saylor min_faves:5",
        "from:Mindset4Money_X min_faves:2",
        '"why would" OR "why is" OR "what am I missing" (fed OR gold OR rates OR Nvidia OR AI OR Bitcoin OR market) lang:en min_faves:30',
        '"would you buy" OR "would you rather" OR "do you own" (stock OR $NVDA OR AI OR Bitcoin OR ETF) lang:en min_faves:30',
        'OpenAI OR Anthropic OR xAI OR "GPT-5" lang:en min_faves:50',
        "ChatGPT OR Claude OR Gemini OR Grok OR Llama lang:en min_faves:50",
        '"AI agents" OR "agentic AI" OR "reasoning model" OR AGI lang:en min_faves:30',
        '"Claude Code" OR Cursor OR Copilot OR "AI coding" lang:en min_faves:30',
        'Meta AI OR "Apple Intelligence" OR Microsoft Copilot OR "Amazon AI" OR Tesla AI lang:en min_faves:50',
        'Nvidia OR NVDA OR GPU OR "AI datacenter" OR "AI capex" lang:en min_faves:50',
        'TSMC OR AMD OR Broadcom OR "AI chips" OR "AI power" OR "AI energy" lang:en min_faves:30',
        'CoreWeave OR Nebius OR "Applied Digital" OR "data center" OR "AI electricity" lang:en min_faves:30',
        'Palantir OR "AI stock" OR "AI bubble" OR "AI valuation" lang:en min_faves:50',
        '"AI startup" OR "AI funding" OR "AI layoffs" OR "AI jobs" OR "open source AI" OR DeepSeek lang:en min_faves:30',
        '"panic sold" OR "bought the top" OR "portfolio is down" OR drawdown lang:en min_faves:30',
        'Bitcoin OR BTC OR "crypto crash" OR "BTC ETF" lang:en min_faves:100',
        'Nvidia OR Palantir OR "AI trade" OR "AI capex" OR "AI datacenter" earnings lang:en min_faves:100',
        '"AI crypto" OR "AI token" OR "decentralized AI" OR "AI agents" crypto lang:en min_faves:50',
    ],
    "HOT_TAB_QUERIES": [
        'OpenAI OR Anthropic OR xAI OR "GPT-5" lang:en min_faves:500',
        'Nvidia OR "AI datacenter" OR "AI capex" lang:en min_faves:300',
        '"AI agents" OR "reasoning model" OR AGI lang:en min_faves:300',
        'Palantir OR "AI stock" OR "AI bubble" lang:en min_faves:300',
        'ChatGPT OR Claude OR Gemini OR "humanoid robot" lang:en min_faves:500',
        '"market crash" OR "sell off" OR "sell-off" OR VIX lang:en min_faves:500',
        'Bitcoin OR "BTC ETF" OR crypto lang:en min_faves:300',
    ],
    "LIKE_QUERIES": [
        "AI datacenter OR power demand lang:en min_faves:50",
        "megawatt OR gigawatt OR nuclear AI lang:en min_faves:50",
        "CoreWeave OR CRWV OR APLD lang:en min_faves:50",
        "IREN OR HIVE OR TeraWulf OR WULF lang:en min_faves:50",
        "TAO OR Bittensor OR decentralized compute lang:en min_faves:50",
        "Nvidia OR GPU OR compute cluster lang:en min_faves:50",
        "robotics OR humanoid robots OR frontier tech lang:en min_faves:50",
        "SpaceX OR Starlink OR space infrastructure lang:en min_faves:50",
    ],
}


def test_theaishrink_loads_the_old_network_niche_and_searches():
    loaded = account.load("theaishrink")
    net, niche, searches = loaded.network, loaded.niche, loaded.searches
    assert ",".join(net.profile_visits) == OLD_NETWORK["PROFILE_VISIT_ALLOWLIST"]
    assert ",".join(net.vip_scan) == OLD_NETWORK["VIP_SCAN_HANDLES"]
    assert ",".join(net.pinned_tracked) == OLD_NETWORK["PINNED_TRACKED_HANDLES"]
    assert list(net.vip_reply) == OLD_NETWORK["VIP_REPLY_ACCOUNTS"]
    assert list(net.big_ai_hype) == OLD_NETWORK["BIG_AI_HYPE_ACCOUNTS"]
    assert list(net.mid_size_ai) == OLD_NETWORK["MID_SIZE_AI_ACCOUNTS"]
    assert list(net.high_traction_reply) == OLD_NETWORK["HIGH_TRACTION_REPLY_ACCOUNTS"]
    assert list(net.big_fr) == OLD_NETWORK["BIG_FR_ACCOUNTS"]
    assert list(net.always_reply) == OLD_NETWORK["ALWAYS_REPLY_ACCOUNTS"]
    assert list(net.engage_vip) == OLD_NETWORK["ENGAGE_VIP_ACCOUNTS"]
    assert list(net.engage_targets) == OLD_NETWORK["ENGAGE_TARGET_ACCOUNTS"]
    assert list(net.reply_targets) == OLD_NETWORK["REPLY_TARGET_ACCOUNTS"]
    assert sorted(net.follow_engagers_skip) == OLD_NETWORK["SKIP_HANDLES"]
    assert len(set(net.follow_engagers_skip)) == len(net.follow_engagers_skip)
    assert (niche.post.pattern, niche.post.flags) == OLD_NETWORK["NICHE_PATTERN"]
    assert (niche.ticker.pattern, niche.ticker.flags) == OLD_NETWORK["TICKER_RE"]
    assert (niche.bio.pattern, niche.bio.flags) == OLD_NETWORK["NICHE_BIO_RE"]
    assert list(searches.replies) == OLD_NETWORK["SEARCH_QUERIES"]
    assert list(searches.hot_tab) == OLD_NETWORK["HOT_TAB_QUERIES"]
    assert list(searches.likes) == OLD_NETWORK["LIKE_QUERIES"]
    assert net.blocked_accounts == ()


def test_the_account_network_fills_three_settings_and_env_wins(accounts, fresh):
    accounts("theaishrink")
    fresh("VIP_SCAN_HANDLES=FromEnv\n")
    assert settings.get("PROFILE_VISIT_ALLOWLIST") == OLD_NETWORK["PROFILE_VISIT_ALLOWLIST"]
    assert settings.get("PINNED_TRACKED_HANDLES") == OLD_NETWORK["PINNED_TRACKED_HANDLES"]
    assert settings.get("VIP_SCAN_HANDLES") == "FromEnv"


def test_the_jobs_read_the_loaded_account(accounts, fresh):
    from src.account import engage_bot
    from src.guards import follow_policy
    from src.replies import direct_reply, notify_bot
    other = (THEAISHRINK
             .replace('engage_vip = ["Graphseo"]', 'engage_vip = ["OtherVip"]')
             .replace('vip_reply = [', 'vip_reply = ["OtherVip", ')
             .replace('engage_targets = [', 'engage_targets = ["OtherTarget", ')
             .replace("post = '", "post = '\\bzebra\\b|")
             .replace("bio = '", "bio = '\\bgiraffe\\b|"))
    accounts("other", other)
    fresh("BOT_ACCOUNT=other\n")
    assert engage_bot._vip_accounts() == ("OtherVip",)
    assert direct_reply.always_reply_accounts()[0] == "OtherVip"
    assert direct_reply.reply_call("othervip").label == "DIRECT_REPLY_VIP"
    assert direct_reply.reply_call("nobody").label == "DIRECT_REPLY"
    assert "othertarget" in notify_bot._influencer_handles()
    assert direct_reply.is_on_niche("a Zebra crossing")
    assert follow_policy._quality_decision(5000, "giraffe keeper", "Someone", False) == (True, "")


@pytest.mark.parametrize("old, new, named", [
    ('vip_scan = ["Graphseo", "TheBTCTherapist"]', 'vip_scan = ["@Graphseo"]', "network.vip_scan[0]"),
    ('engage_vip = ["Graphseo"]', 'engage_vip = "Graphseo"', "network.engage_vip"),
    ("blocked_accounts = []", 'blocked_accounts = [" _ "]', "network.blocked_accounts[0]"),
    ("blocked_accounts = []", "blocked_accounts = [3]", "network.blocked_accounts[0]"),
    ("ticker = '", "ticker = '(", "niche.ticker"),
    ("likes = [", "likes = [\n    ' ',", "searches.likes[0]"),
    ("[searches]", "[searches]\nquotes = []", "searches.quotes"),
    ('vip_scan = ["Graphseo", "TheBTCTherapist"]\n', "", "network.vip_scan"),
    # No key removes a Blocked account of the engine's BLOCKLIST.
    ("blocked_accounts = []", 'blocked_accounts = []\nunblocked_accounts = ["pgm_pm"]',
     "network.unblocked_accounts"),
])
def test_a_bad_network_niche_or_search_stops_the_start(accounts, fresh, old, new, named):
    assert THEAISHRINK.count(old) == 1
    accounts("theaishrink", THEAISHRINK.replace(old, new))
    with pytest.raises(settings.SettingsError, match=re.escape(named)):
        fresh()


# --- Relations: the per-handle Reply instructions (#203) -------------------------

# sha256 of GRAPHSEO_PROMPT, BESTIE_REPLY_PROMPT and BUDDY_REPLY_PROMPT in
# src/replies/direct_reply.py before #203 moved them to relations/. An
# Operator edit of these files updates the hash here.
OLD_RELATION_PROMPTS = {
    "graphseo": (3173, "ce0bff9b595f5e7a74d7e941b9ad078cf2aacef94efa32a567bdd8bb024d3cbe"),
    "bestie": (1225, "a71626b227d107ef059b8357bb84e21469d23c53f36937fc9dcc55ac05d5421e"),
    "buddy": (641, "cbfc14614b789f68107917006c20a6948341ff95e209a965e7475922badfc3fb"),
}
# personality_store.get_account("mcnalliem") before #203, a dossier in the code.
OLD_MCNALLIEM = {
    "first_seen": "2026-05-02",
    "last_interaction": "2026-05-02",
    "interaction_count": 0,
    "category": "builder",
    "stance": "fond",
    "notes": [
        "User loves this account: McNallie Money shows results on AI, crypto, data centers, and companies.",
        "Priority VIP: reply often, make him laugh, and avoid anything that could feel like a dunk on him.",
    ],
    "predictions": [],
    "feelings": "Warm respect. Treat him as a useful operator sharing real results.",
    "do": "Be playful, impressed, specific, and funny about the AI/data-center/crypto market absurdity.",
    "dont": "Do not mock him, his work, his results, or his credibility. Never make him upset.",
}


def _digest(text):
    import hashlib
    return len(text), hashlib.sha256(text.encode()).hexdigest()


def test_theaishrink_relations_hold_the_old_prompts():
    relations = account.load("theaishrink").relations
    graphseo, bestie = relations.get("Graphseo"), relations.get("TheBTCTherapist")
    assert {"graphseo": _digest(graphseo.prompt), "bestie": _digest(bestie.prompt),
            "buddy": _digest(relations.default)} == OLD_RELATION_PROMPTS
    assert (graphseo.handle, graphseo.provider, graphseo.dossier) == ("Graphseo", "claude", None)
    assert (bestie.handle, bestie.provider, bestie.dossier) == ("TheBTCTherapist", None, None)
    assert relations.get("@GRAPHSEO") is graphseo, "handles ignore case and a leading @"
    mcnallie = relations.get("mcnalliem")
    assert (mcnallie.prompt, mcnallie.provider) == (None, None)
    assert sorted(relations.handles) == ["graphseo", "mcnalliem", "thebtctherapist"]
    assert relations.vip_prompt("thebtctherapist") == bestie.prompt
    assert relations.vip_prompt("McnallieM") == relations.vip_prompt("vision_ia") == relations.default


def test_a_fixed_dossier_reads_as_the_old_one():
    from src.core import personality_store
    assert personality_store.get_account("McnallieM") == OLD_MCNALLIEM
    assert personality_store.get_account("@mcnalliem") == OLD_MCNALLIEM


def test_the_relation_providers_are_llm_client_clis():
    from src.core import llm_client
    assert set(account.CLI_PROVIDERS) == set(llm_client.ADAPTERS) - {"ollama"}


@pytest.mark.parametrize("old, new, named", [
    ('provider = "claude"', 'provider = "claude"\nlabel = "X"', "relations.handles.Graphseo.label"),
    ('stance = "fond"', 'stance = "fond"\nmood = "x"', "relations.handles.McnallieM.dossier.mood"),
    ('default = "relations/buddy.md"', 'default = "relations/buddy.md"\nbuddy = "x.md"', "relations.buddy"),
    ("[relations.handles.Graphseo]", '[relations.handles."Graph-seo"]', "relations.handles.Graph-seo"),
    ("[relations.handles.Graphseo]", "[relations.handles.ThisHandleIsTooLong]",
     "relations.handles.ThisHandleIsTooLong"),
    ("[relations.handles.McnallieM.dossier]", "[relations.handles.graphseo.dossier]",
     "relations.handles.graphseo repeats Graphseo"),
])
def test_an_unknown_relation_key_or_handle_stops_the_start(accounts, fresh, old, new, named):
    assert THEAISHRINK.count(old) == 1
    accounts("theaishrink", THEAISHRINK.replace(old, new))
    with pytest.raises(settings.SettingsError, match=re.escape(named)):
        fresh()


@pytest.mark.parametrize("old, new, named", [
    ('provider = "claude"', 'provider = "claud"', "relations.handles.Graphseo.provider takes one of"),
    ('prompt = "relations/graphseo.md"\n', "", "relations.handles.Graphseo.provider needs a prompt"),
    ('stance = "fond"', "stance = 3", "relations.handles.McnallieM.dossier.stance"),
    ('notes = [\n', 'notes = [\n    7,\n', "relations.handles.McnallieM.dossier.notes[0]"),
    ('prompt = "relations/graphseo.md"', 'prompt = "relations/nope.md"', "relations.handles.Graphseo.prompt"),
    ('prompt = "relations/bestie.md"', 'prompt = "../voice_en.md"', "outside the Account's folder"),
])
def test_a_bad_relation_value_stops_the_start(accounts, fresh, old, new, named):
    assert THEAISHRINK.count(old) == 1
    accounts("theaishrink", THEAISHRINK.replace(old, new))
    with pytest.raises(settings.SettingsError, match=re.escape(named)):
        fresh()


def test_an_empty_fixed_dossier_stops_the_start(accounts, fresh):
    start = THEAISHRINK.index("[relations.handles.McnallieM.dossier]")
    end = THEAISHRINK.index("\n\n", THEAISHRINK.index("dont = ", start))
    accounts("theaishrink", THEAISHRINK[:start] + "[relations.handles.McnallieM.dossier]" + THEAISHRINK[end:])
    with pytest.raises(settings.SettingsError, match=re.escape("relations.handles.McnallieM.dossier is empty")):
        fresh()


def test_the_default_prompt_is_needed_only_for_a_scanned_handle_without_its_own(accounts, fresh):
    # Graphseo and TheBTCTherapist, the vip_scan handles, each have their own prompt.
    accounts("theaishrink", THEAISHRINK.replace('default = "relations/buddy.md"\n', ""))
    fresh()
    assert account.current().relations.default is None
    assert account.current().relations.vip_prompt("vision_ia") is None
    scan = 'vip_scan = ["Graphseo", "TheBTCTherapist"]'
    accounts("other", THEAISHRINK.replace('default = "relations/buddy.md"\n', "")
             .replace(scan, 'vip_scan = ["Graphseo", "TheBTCTherapist", "McnallieM"]'))
    with pytest.raises(settings.SettingsError, match=re.escape(
            "relations.default is missing: network.vip_scan lists McnallieM, which has no Relation "
            "with its own prompt")):
        account.load("other")


def test_an_account_without_relations_starts_when_it_scans_no_vip(accounts, fresh):
    start = THEAISHRINK.index("[relations]")
    bare = THEAISHRINK[:start] + THEAISHRINK[THEAISHRINK.index("[limits]"):]
    accounts("theaishrink", bare)
    with pytest.raises(settings.SettingsError, match=re.escape(
            "relations.default is missing: network.vip_scan lists Graphseo")):
        fresh()
    old = 'vip_scan = ["Graphseo", "TheBTCTherapist"]'
    assert bare.count(old) == 1
    accounts("other", bare.replace(old, "vip_scan = []"))
    fresh("BOT_ACCOUNT=other\n")
    relations = account.current().relations
    assert (relations.default, relations.handles) == (None, {})


@pytest.mark.parametrize("text, problem", [
    ("Reply to {author} about {topic}.", "{topic} is no Reply prompt field"),
    ("Reply to {author now.", "braces do not parse"),
    ("  \n", "which is empty"),
])
def test_a_relation_prompt_with_bad_fields_stops_the_start(accounts, fresh, tmp_path, text, problem):
    accounts("theaishrink")
    (tmp_path / "accounts" / "theaishrink" / "relations" / "buddy.md").write_text(text)
    with pytest.raises(settings.SettingsError, match=re.escape(problem)) as raised:
        fresh()
    assert "relations.default" in str(raised.value)


def test_a_prompt_file_linked_outside_the_folder_stops_the_start(accounts, fresh, tmp_path):
    accounts("theaishrink")
    outside = tmp_path / "outside.md"
    outside.write_text("Reply to {author}.")
    link = tmp_path / "accounts" / "theaishrink" / "relations" / "buddy.md"
    link.unlink()
    link.symlink_to(outside)
    with pytest.raises(settings.SettingsError, match=re.escape(
            "relations.default names 'relations/buddy.md', outside the Account's folder")):
        fresh()


def test_a_relations_folder_linked_outside_stops_the_start(accounts, fresh, tmp_path):
    accounts("theaishrink")
    relations = tmp_path / "accounts" / "theaishrink" / "relations"
    outside = tmp_path / "outside"
    shutil.move(relations, outside)
    relations.symlink_to(outside, target_is_directory=True)
    with pytest.raises(settings.SettingsError, match=re.escape("outside the Account's folder")):
        fresh()


def test_a_link_inside_the_folder_is_followed(accounts, fresh, tmp_path):
    accounts("theaishrink")
    folder = tmp_path / "accounts" / "theaishrink"
    (folder / "relations" / "buddy.md").rename(folder / "buddy_real.md")
    (folder / "relations" / "buddy.md").symlink_to(folder / "buddy_real.md")
    fresh()
    assert _digest(account.current().relations.default) == OLD_RELATION_PROMPTS["buddy"]


@pytest.mark.parametrize("name", account.VOICE_FILES)
@pytest.mark.parametrize("break_it, problem", [
    (lambda path, outside: path.unlink(), "cannot be read"),
    (lambda path, outside: path.write_text(" \n"), "is empty"),
    (lambda path, outside: (outside.write_text("A voice."), path.unlink(), path.symlink_to(outside)),
     "links outside the Account's folder"),
])
def test_a_missing_empty_or_outside_voice_file_stops_the_start(accounts, fresh, tmp_path, name,
                                                              break_it, problem):
    accounts("theaishrink")
    break_it(tmp_path / "accounts" / "theaishrink" / name, tmp_path / "outside.md")
    with pytest.raises(settings.SettingsError,
                       match=re.escape(f"theaishrink/{name}: the Voice file {problem}")):
        fresh()

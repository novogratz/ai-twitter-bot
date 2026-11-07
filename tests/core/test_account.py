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
# accounts/theaishrink/account.toml; the Operator renamed the account and
# changed publication wording to SI on 2026-10-23.
TREND_PURPOSE = "Trending: the SI topic X is talking about right now, told from a trusted source"
OLD = {
    "SLOTS": [("05:00", "Priority: the SI update worth understanding this morning"),
              ("07:15", "A useful SI video or image workflow: concrete first step, output and limitation"),
              ("09:30", "Priority: an SI article or model update with a sharp consequence"),
              ("10:00", "Trending: the SI topic X is talking about right now, told from a trusted source"),
              ("11:45", "An SI concept explained through a clear example"),
              ("13:00", "Trending: the SI topic X is talking about right now, told from a trusted source"),
              ("14:00", "An SI video, image or model tool update and what changes for creators"),
              ("15:00", "Trending: the SI topic X is talking about right now, told from a trusted source"),
              ("16:15", "Priority: an evidence-backed take on an SI tradeoff"),
              ("18:30", "A practical SI idea worth saving or sharing"),
              ("20:45", "Optional: an exceptional fresh SI update or unusually useful source")],
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
                  ("evaluation", "How to evaluate an SI model on your own examples",
                   "https://huggingface.co/docs/evaluate/index"),
                  ("quantization", "What quantization trades for smaller SI models",
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
              "mistral.ai", "openai.com", "replicate.com", "rss.arxiv.org", "the-decoder.com", "www.microsoft.com"],
    "AI_TOPIC": ("\\b(ai|artificial intelligence|model|llm|agent|machine "
                 "learning|openai|anthropic|claude|chatgpt|gpt|gemini|deepmind|deepseek|mistral|qwen|llama|"
                 "robotics|transformer|inference|training|neural|diffusion|gpu)\\b", 34),
    "OFF_TOPIC": ("\\$[A-Za-z]{2,6}\\b|\\b(crypto|bitcoin|btc|ethereum|memecoin|airdrop|giveaway|presale)\\b", 34),
    "BOT_HANDLE": "thesimaximalist",
    "CONTENT_LANG_PRIMARY": "en",
}
# trending.TREND_QUERIES before #208 moved them to [searches] trending.
OLD_TREND_QUERIES = [
    '"artificial intelligence" lang:en min_faves:50 -filter:replies',
    'AI lang:en min_faves:200 -filter:replies',
]
NEWS_ANGLE = "A consequential new SI capability, model, research result or creative tool: the concrete change and why it matters"
NEWS_SLOTS = [(f"{hour:02}:30", NEWS_ANGLE) for hour in range(5, 24, 2)]
NEWS_FEEDS = [(name, {"Google AI": "https://blog.google/innovation-and-ai/technology/ai/rss/",
                       "Mistral AI": "https://mistral.ai/news/rss"}.get(name, url))
              for name, url in OLD["FEEDS"] if name != "The Decoder"]
FOURTH_SLOT = '{ clock = "11:30", angle = "' + NEWS_ANGLE + '" }'


def test_the_account_has_two_hour_primary_source_news_and_preserves_reply_policy():
    loaded = account.load("theaishrink")
    ed = loaded.editorial
    assert list(ed.slots) == NEWS_SLOTS
    assert not ed.trend_clocks
    assert ed.trend_angle == OLD["TREND_PURPOSE"]
    assert not ed.exceptional_clocks
    assert ed.news_only and ed.bangers_only and ed.max_news_age_hours == 48
    assert list(ed.feeds) == NEWS_FEEDS
    assert [(t.topic, t.title, t.url) for t in ed.evergreen] == OLD["KNOWLEDGE"]
    assert {t.publisher for t in ed.evergreen} == {OLD["KNOWLEDGE_PUBLISHER"]}
    assert sorted(ed.trusted_hosts) == OLD["HOSTS"]
    assert loaded.relevance.off_topic.search("AI crypto trading")
    assert loaded.engagement_niche_only
    assert (loaded.handle, loaded.language) == (OLD["BOT_HANDLE"], OLD["CONTENT_LANG_PRIMARY"])
    assert loaded.limits == {"FEED_SWEEP_SCAN_LIMIT": 160, "FEED_SCROLL_PASSES": 20,
                             "HOURLY_BREAK_MINUTES": 0, "MIN_SECONDS_BETWEEN_REPLIES": 8,
                             "REPLY_JITTER_SECONDS": 4, "REPLY_DAILY_TARGET_MIN": 1500,
                             "REPLY_DAILY_TARGET_MAX": 1800, "REPLY_PREFERRED_MIN_LIKES": 3,
                             "DIRECT_REPLY_QUERIES_PER_CYCLE": 16,
                             "DIRECT_REPLY_PRIORITY_QUERIES_PER_CYCLE": 4,
                             "DIRECT_REPLY_LATEST_QUERIES_PER_CYCLE": 4,
                             "REPLY_PRIORITIZE_LARGE_ACCOUNTS": True,
                             "DIRECT_REPLY_MAX_PER_CYCLE": 80,
                             "FEED_SWEEP_MAX_REPLIES_PER_CYCLE": 80}
    assert loaded.domain == "SI / Super Intelligence"
    assert loaded.reply_si_wording is True
    assert loaded.publication_si_wording is True
    assert loaded.previous_handles == ("TheAIShrink",)
    assert loaded.auto_engage_handles == ("elonmusk",)


@pytest.mark.parametrize("value", ['["@bad"]', '["not a handle"]', '[42]', '"Alias"'])
def test_watch_handles_are_validated(accounts, fresh, value):
    accounts("theaishrink", THEAISHRINK.replace('auto_engage_handles = ["elonmusk"]',
                                               f"auto_engage_handles = {value}"))
    with pytest.raises(settings.SettingsError, match="auto_engage_handles"):
        account.load("theaishrink")


def test_watch_handles_are_case_insensitive_and_unique(accounts, fresh):
    accounts("theaishrink", THEAISHRINK.replace('auto_engage_handles = ["elonmusk"]',
                                               'auto_engage_handles = ["Builder", "BUILDER", "other"]'))
    assert account.load("theaishrink").auto_engage_handles == ("builder", "other")


def test_strict_topic_is_optional_for_other_accounts(accounts, fresh):
    accounts("other", THEAISHRINK.replace("engagement_niche_only = true\n", ""))
    assert not account.load("other").engagement_niche_only


def test_strict_topic_requires_a_boolean(accounts, fresh):
    accounts("other", THEAISHRINK.replace("engagement_niche_only = true", 'engagement_niche_only = "true"'))
    with pytest.raises(settings.SettingsError, match="engagement_niche_only"):
        account.load("other")


def test_the_editorial_reads_the_loaded_account():
    assert settings.get("BOT_ACCOUNT") == "theaishrink"
    assert [tuple(slot) for slot in editorial.slots()] == NEWS_SLOTS
    assert not editorial.trend_slots()
    assert not [slot for slot in editorial.slots() if slot.exceptional]
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
        from tests.relation_fixtures import PROMPTS
        for kind, prompt in PROMPTS.items():
            (folder / name / "relations" / f"{kind}.md").write_text(prompt)
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
    accounts("other", THEAISHRINK.replace('handle = "thesimaximalist"', 'handle = "OtherBot"')
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
    ('handle = "thesimaximalist"', 'handle = "thesimaximalist"\nnickname = "shrink"', "nickname"),
    ('trend_angle =', 'trend_hours = 3\ntrend_angle =', "editorial.trend_hours"),
    (FOURTH_SLOT, '{ clock = "11:30", trend = true, weight = 2 }',
     "editorial.slots[3].weight"),
    ('publisher = "OpenAI", url', 'publisher = "OpenAI", lang = "en", url', "editorial.feeds[0].lang"),
    ('[relevance]', '[relevance]\nniche = "ai"', "relevance.niche"),
    ('[limits]', '[limits]\nMAX_ORIGINALS_PER_DA = 6', "limits.MAX_ORIGINALS_PER_DA"),
    # A setting without a bound is the engine's, not the Account's.
    ('[limits]', '[limits]\nMIN_SECONDS_BETWEEN_FOLLOWS = 900', "limits.MIN_SECONDS_BETWEEN_FOLLOWS"),
])
def test_an_unknown_key_stops_the_start(accounts, fresh, old, new, named):
    source = re.sub(r"blocked_accounts = \[[\s\S]*?\]", "blocked_accounts = []", THEAISHRINK, count=1)
    assert source.count(old) == 1
    accounts("theaishrink", source.replace(old, new))
    with pytest.raises(settings.SettingsError, match=re.escape(named)):
        fresh()


@pytest.mark.parametrize("old, new, named", [
    ('handle = "thesimaximalist"', "handle = 3", "handle"),
    ('language = "en"', 'language = "de"', "language"),
    (FOURTH_SLOT, '{ clock = "11:30", trend = "yes" }', "editorial.slots[3].trend"),
    (FOURTH_SLOT, '{ clock = "11h30", trend = true }', "editorial.slots[3].clock"),
    (FOURTH_SLOT, '{ clock = "09:00", trend = true }', "editorial.slots[3].clock"),
    ('"openai.com", "blog.google"', '"openai.com", 7', "editorial.trusted_hosts[1]"),
    ('chat_templating"\npublisher = "Hugging Face docs"', 'chat_templating"\npublisher = true',
     "editorial.evergreen[0].publisher"),
    ("off_topic = '", "off_topic = '(", "relevance.off_topic"),
    ('[limits]', '[limits]\nMAX_ORIGINALS_PER_DAY = "6"', "limits.MAX_ORIGINALS_PER_DAY"),
    ('handle = "thesimaximalist"\n', "", "handle"),
    ('domain = "SI / Super Intelligence"', "domain = 3", "domain"),
    ('domain = "SI / Super Intelligence"', 'domain = " "', "domain is blank"),
    ('domain = "SI / Super Intelligence"\n', "", "domain is missing"),
    ('handle = "thesimaximalist"', 'handle = "thesimaximalist', "not valid TOML"),
])
def test_a_badly_typed_value_stops_the_start(accounts, fresh, old, new, named):
    source = re.sub(r"blocked_accounts = \[[\s\S]*?\]", "blocked_accounts = []", THEAISHRINK, count=1)
    assert source.count(old) == 1
    accounts("theaishrink", source.replace(old, new))
    with pytest.raises(settings.SettingsError, match=re.escape(named)):
        fresh()


@pytest.mark.parametrize("new, problem", [
    ('{ clock = "10:00" }', "editorial.slots[3].angle is required unless trend = true."),
    ('{ clock = "10:00", trend = true, angle = "x" }',
     "editorial.slots[3].angle must be absent when trend = true, which takes trend_angle instead."),
])
def test_a_slot_angle_is_required_or_forbidden_by_trend(accounts, fresh, new, problem):
    old = FOURTH_SLOT
    source = re.sub(r"blocked_accounts = \[[\s\S]*?\]", "blocked_accounts = []", THEAISHRINK, count=1)
    assert source.count(old) == 1
    accounts("theaishrink", source.replace(old, new))
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
    ("FOLLOWBACK_CAP = -1", "FOLLOWBACK_CAP", 0),
    ("DUP_SHARED_BIGRAMS = 0", "DUP_SHARED_BIGRAMS", 1),
])
def test_an_account_value_past_an_engine_bound_is_brought_back_to_it(accounts, fresh, limit, name, bound):
    # Replace an existing Account override rather than duplicating its TOML key.
    source = re.sub(rf"(?m)^{re.escape(name)}\s*=.*\n", "", THEAISHRINK)
    accounts("theaishrink", source.replace("[limits]", f"[limits]\n{limit}"))
    fresh()
    assert settings.get(name) == bound
    assert [w for w in settings.startup_warnings()
            if w.startswith(os.path.join(account.ACCOUNTS_DIR, "theaishrink", "account.toml")) and name in w]


@pytest.mark.parametrize("name", ["DUP_JACCARD_THRESHOLD", "DUP_CONTAINMENT_THRESHOLD",
                                  "DUP_TOPIC_WINDOW_HOURS", "DUP_TEXT_WINDOW_HOURS"])
@pytest.mark.parametrize("value", ["nan", "inf", "-inf"])
def test_a_non_finite_float_limit_stops_the_start(accounts, fresh, name, value):
    """TOML reads nan and inf as floats; nan would pass every bound."""
    accounts("theaishrink", THEAISHRINK.replace("[limits]", f"[limits]\n{name} = {value}"))
    with pytest.raises(account.AccountError, match=re.escape(f"limits.{name} takes finite float")):
        fresh()


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


# --- Network and niche (#204, #205) ------------------------------------------------

# The network, niche and searches of accounts/theaishrink/account.toml. #204
# moved them there from the code unchanged; #205 (Operator, 2026-09-25: AI
# only, like the policy) removed REMOVED_205 from them and narrowed
# NARROWED_205. A pattern is (source, flags).
NETWORK = {
    "PROFILE_VISIT_ALLOWLIST": "",
    "VIP_SCAN_HANDLES": "",
    "PINNED_TRACKED_HANDLES": "",
    "VIP_REPLY_ACCOUNTS": [
        "elonmusk", "xai", "grok",
        "vision_ia", "jbelizaireCEO", "ylecun", "arthurmensch",
        "GuillaumeLample", "fchollet", "karpathy", "demishassabis", "sama",
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
        "Dark_Emi_", "arthurmensch", "GuillaumeLample", "GaelVaroquaux",
        "fchollet", "MistralAI",
    ],
    "BIG_FR_ACCOUNTS": [
        "Korben", "micode", "Underscore_", "presse_citron", "numerama", "siecledigital", "BFMTech",
        "frandroid", "journaldugeek", "FlavienChervet", "MistralAI", "arthurmensch",
        "GuillaumeLample",
    ],
    "ALWAYS_REPLY_ACCOUNTS": [
        "vision_ia", "jbelizaireCEO", "ylecun", "arthurmensch",
        "GuillaumeLample", "fchollet", "karpathy", "demishassabis", "sama", "elonmusk",
        "DarioAmodei", "satyanadella", "sundarpichai", "JensenHuang", "gdb", "miramurati",
        "AravSrinivas", "AndrewYNg", "drfeifei", "lexfridman", "ID_AA_Carmack", "EMostaque",
        "clementdelangue", "OpenAI", "AnthropicAI", "GoogleDeepMind", "GoogleAI", "xai",
        "MistralAI", "perplexity_ai", "nvidia", "Microsoft", "Meta", "OpenAIDevs", "huggingface",
        "cursor_ai", "rowancheung", "TheRundownAI", "minchoi", "kimmonismus", "slow_developer",
        "mreflow", "bentossell", "venturetwins", "heybarsee", "alexandr_wang", "emollick", "swyx",
        "_akhaliq", "GaryMarcus", "testingcatalog", "btibor91", "AISafetyMemes", "amasad",
        "OfficialLoganK", "DrJimFan", "sytelus", "hwchase17", "jerryjliu0", "yoheinakajima",
        "mckaywrigley", "rasbt", "Teknium1", "abacaj", "corbtt", "Yuchenj_UW", "nutlope", "skirano",
        "steph_palazzolo", "saranormous", "packyM", "nearcyan", "giffmana", "vikhyatk",
        "mattshumer_", "alexalbert__", "goodside", "simonw", "karinanguyen_", "charliebholtz",
        "amanrsanger", "mathemagic1an", "Dark_Emi_", "GaelVaroquaux",
        "Korben", "micode", "Underscore_", "presse_citron", "numerama", "siecledigital", "BFMTech",
        "frandroid", "journaldugeek", "FlavienChervet",
    ],
    "ENGAGE_VIP_ACCOUNTS": [
    ],
    "ENGAGE_TARGET_ACCOUNTS": [
    ],
    "REPLY_TARGET_ACCOUNTS": [
        "vision_ia", "jbelizaireCEO", "sama", "OpenAI", "AnthropicAI",
        "GoogleDeepMind", "elonmusk", "xAI", "karpathy", "ylecun", "fchollet", "demishassabis",
        "MistralAI", "arthurmensch", "GuillaumeLample", "GaelVaroquaux", "nvidia", "AMD", "intel",
        "CoreWeave", "IREN_Ltd", "LambdaAPI", "applied_dc", "BostonDynamics", "Figure_robot",
        "ID_AA_Carmack", "drfeifei",
        "Korben", "underscore_", "MichaelBenabou", "presse_citron", "siecledigital",
        "usine_digitale", "numerama", "01net", "frandroid", "LesNumeriques", "FrenchWeb",
        "MaddyNess", "arthurmensch", "GuillaumeLample", "GaelVaroquaux", "vision_ia", "Palantir",
    ],
    "SKIP_HANDLES": [
        "bloomberg", "business", "cnbc", "cointelegraph", "ft", "reuters", "unusual_whales",
        "watcherguru", "wsj", "zerohedge",
    ],
    "NICHE_PATTERN": (
        r"\b((?<![Jj][\x27’])(?-i:AIs?)|(?<![\x27’])(?<!\by\s)(?<!\ben\s)(?<!\bles\s)(?<!\blui\s)"
        r"(?<!vous\s)(?<!nous\s)(?<!leur\s)ai(?!-je\b)|a\.i|i\.a|ia|agi|superintelligence|genai|"
        r"llms?|gpt\w*|chatgpt|chatbots?|claude|openai|anthropic(?:ai)?|mistral(?:ai)?|gemini|grok|"
        r"xai|deepseek|llama\d*|qwen\d*|sora|veo\s*\d|midjourney|apple\s+intelligence|huggingface|"
        r"(?:google)?deepmind|artificial\s+intelligence|intelligence\s+artificielle|"
        r"machine\s*learning|deep\s*learning|neural|computer\s+vision|transformers?|"
        r"reasoning\s+models?|context\s+windows?|open[\s-]*weights?|vibe\s*coding|agentic|"
        r"(?:coding|autonomous)\s+agents?|nvidia|cuda|gpus?|tpus?|data\s*centers?|robots?|robotics|"
        r"humanoids?|humano[iï]des?|altman|ml|codex|copilot|cursor|windsurf|replit)\b",
        34),
    "NICHE_BIO_RE": (
        r"\b((?<![Jj][\x27’])(?-i:AIs?)|(?<![\x27’])(?<!\by\s)(?<!\ben\s)(?<!\bles\s)(?<!\blui\s)"
        r"(?<!vous\s)(?<!nous\s)(?<!leur\s)ai(?!-je\b)|a\.i|i\.a|ia|agi|genai|llms?|gpt\w*|"
        r"chatgpt|openai|anthropic(?:ai)?|mistral(?:ai)?|huggingface|(?:google)?deepmind|"
        r"artificial\s+intelligence|intelligence\s+artificielle|machine\s*learning|"
        r"deep\s*learning|neural|computer\s+vision|robotics|humanoids?|agentic|"
        r"(?:coding|autonomous)\s+agents?|building\s+agents?|ml|nvidia)\b",
        34),
    "SEARCH_QUERIES": [
        '("why would" OR "why is" OR "what am I missing") (Nvidia OR AI) lang:en min_faves:30',
        'OpenAI OR Anthropic OR xAI OR "GPT-5" lang:en min_faves:50',
        "ChatGPT OR Claude OR Gemini OR Grok OR Llama lang:en min_faves:50",
        '"AI agents" OR "agentic AI" OR "reasoning model" OR AGI lang:en min_faves:30',
        '"Claude Code" OR Cursor OR Copilot OR "AI coding" lang:en min_faves:30',
        'Meta AI OR "Apple Intelligence" OR Microsoft Copilot OR "Amazon AI" OR Tesla AI lang:en min_faves:50',
        'Nvidia OR GPU OR "AI datacenter" OR "AI capex" lang:en min_faves:50',
        'TSMC AI OR AMD AI OR Broadcom AI OR "AI chips" OR "AI power" OR "AI energy" lang:en min_faves:30',
        'CoreWeave AI OR Nebius AI OR "Applied Digital" AI OR "data center" OR "AI electricity" lang:en min_faves:30',
        '"AI startup" OR "AI funding" OR "AI layoffs" OR "AI jobs" OR "open source AI" OR DeepSeek lang:en min_faves:30',
    ],
    "HOT_TAB_QUERIES": [
        'OpenAI OR Anthropic OR xAI OR "GPT-5" lang:en min_faves:500',
        'Nvidia OR "AI datacenter" OR "AI capex" lang:en min_faves:300',
        '"AI agents" OR "reasoning model" OR AGI lang:en min_faves:300',
        'ChatGPT OR Claude OR Gemini OR "humanoid robot" lang:en min_faves:500',
    ],
    "LIKE_QUERIES": [
        "AI datacenter OR AI power demand lang:en min_faves:50",
        "megawatt AI OR gigawatt AI OR nuclear AI lang:en min_faves:50",
        "Nvidia OR GPU OR AI compute cluster lang:en min_faves:50",
        "robotics OR humanoid robots lang:en min_faves:50",
    ],
}

# What #205 took out: crypto, markets and space accounts, by the list they left.
REMOVED_205 = {
    "vip_reply": [
        "RodolpheSteffan", "FinTales_", "novogratz", "FlasheurInvest", "VitalikButerin", "saylor",
        "brian_armstrong", "cz_binance", "SpaceX",
    ],
    "high_traction_reply": [
        "PowerHasheur", "LeJournalDuCoin", "CryptoastMedia", "coinacademy_fr", "CryptoPicsou",
        "crypto_futur", "TheCrypt0Matrix", "TagadoBTC", "Crypto__Goku", "MiningTk", "MoneyRadar_FR",
        "Capetlevrai", "Divs_King", "MathieuL1", "NCheron_bourse",
    ],
    "big_fr": [
        "Finary", "ZonebourseFR", "BFMBourse", "latribune", "Capital", "LesEchos", "boursorama",
        "GoodValYou", "Zonebourse", "Investir", "Hasheur", "cryptodiffusion", "Cointribune",
        "BFMcrypto", "PowerHasheur", "LeJournalDuCoin", "CryptoastMedia", "coinacademy_fr",
        "CryptoPicsou",
    ],
    "engage_targets": ["RodolpheSteffan", "FinTales_"],
    "reply_targets": [
        "RodolpheSteffan", "FinTales_", "novogratz", "FlasheurInvest", "KobeissiLetter",
        "unusual_whales", "SpaceX", "Tesla", "NCheron_bourse", "IVTrading", "GoodValYou", "Finary",
        "LesEchos", "BFMBusiness", "BFMBourse", "Capital_fr", "latribune", "CafeDelaBourse",
        "ZoneBourse", "PowerHasheur", "Capetlevrai", "CoinAcademy_FR", "saylor", "MicroStrategy",
        "VitalikButerin", "CoinDesk", "blockworks_",
    ],
    "replies": [
        "from:TheBTCTherapist OR from:morganhousel OR from:ParikPatelCFA OR from:litcapital min_faves:5",
        "from:greg16676935420 OR from:ReformedBroker OR from:jasonzweigwsj OR from:saylor min_faves:5",
        "from:Mindset4Money_X min_faves:2",
        '"would you buy" OR "would you rather" OR "do you own" (stock OR $NVDA OR AI OR Bitcoin OR ETF) lang:en min_faves:30',
        'Palantir OR "AI stock" OR "AI bubble" OR "AI valuation" lang:en min_faves:50',
        '"panic sold" OR "bought the top" OR "portfolio is down" OR drawdown lang:en min_faves:30',
        'Bitcoin OR BTC OR "crypto crash" OR "BTC ETF" lang:en min_faves:100',
        'Nvidia OR Palantir OR "AI trade" OR "AI capex" OR "AI datacenter" earnings lang:en min_faves:100',
        '"AI crypto" OR "AI token" OR "decentralized AI" OR "AI agents" crypto lang:en min_faves:50',
    ],
    "hot_tab": [
        'Palantir OR "AI stock" OR "AI bubble" lang:en min_faves:300',
        '"market crash" OR "sell off" OR "sell-off" OR VIX lang:en min_faves:500',
        'Bitcoin OR "BTC ETF" OR crypto lang:en min_faves:300',
    ],
    "likes": [
        "CoreWeave OR CRWV OR APLD lang:en min_faves:50",
        "IREN OR HIVE OR TeraWulf OR WULF lang:en min_faves:50",
        "TAO OR Bittensor OR decentralized compute lang:en min_faves:50",
        "SpaceX OR Starlink OR space infrastructure lang:en min_faves:50",
    ],
}
# Queries #205 kept with their AI terms only, a company or energy word
# paired with AI: before -> after.
NARROWED_205 = {
    '"why would" OR "why is" OR "what am I missing" (fed OR gold OR rates OR Nvidia OR AI OR Bitcoin OR market) lang:en min_faves:30':
        '("why would" OR "why is" OR "what am I missing") (Nvidia OR AI) lang:en min_faves:30',
    'Nvidia OR NVDA OR GPU OR "AI datacenter" OR "AI capex" lang:en min_faves:50':
        'Nvidia OR GPU OR "AI datacenter" OR "AI capex" lang:en min_faves:50',
    'TSMC OR AMD OR Broadcom OR "AI chips" OR "AI power" OR "AI energy" lang:en min_faves:30':
        'TSMC AI OR AMD AI OR Broadcom AI OR "AI chips" OR "AI power" OR "AI energy" lang:en min_faves:30',
    'CoreWeave OR Nebius OR "Applied Digital" OR "data center" OR "AI electricity" lang:en min_faves:30':
        'CoreWeave AI OR Nebius AI OR "Applied Digital" AI OR "data center" OR "AI electricity" lang:en min_faves:30',
    "AI datacenter OR power demand lang:en min_faves:50":
        "AI datacenter OR AI power demand lang:en min_faves:50",
    "megawatt OR gigawatt OR nuclear AI lang:en min_faves:50":
        "megawatt AI OR gigawatt AI OR nuclear AI lang:en min_faves:50",
    "Nvidia OR GPU OR compute cluster lang:en min_faves:50":
        "Nvidia OR GPU OR AI compute cluster lang:en min_faves:50",
    "robotics OR humanoid robots OR frontier tech lang:en min_faves:50":
        "robotics OR humanoid robots lang:en min_faves:50",
}


def test_theaishrink_loads_its_network_niche_and_searches():
    loaded = account.load("theaishrink")
    net, niche, searches = loaded.network, loaded.niche, loaded.searches
    assert ",".join(net.profile_visits) == NETWORK["PROFILE_VISIT_ALLOWLIST"]
    assert ",".join(net.vip_scan) == NETWORK["VIP_SCAN_HANDLES"]
    assert ",".join(net.pinned_tracked) == NETWORK["PINNED_TRACKED_HANDLES"]
    assert list(net.vip_reply) == NETWORK["VIP_REPLY_ACCOUNTS"]
    assert list(net.big_ai_hype) == NETWORK["BIG_AI_HYPE_ACCOUNTS"]
    assert list(net.mid_size_ai) == NETWORK["MID_SIZE_AI_ACCOUNTS"]
    assert list(net.high_traction_reply) == NETWORK["HIGH_TRACTION_REPLY_ACCOUNTS"]
    assert list(net.big_fr) == NETWORK["BIG_FR_ACCOUNTS"]
    expected = ["elonmusk", "xai", "grok"]
    expected += [h for h in NETWORK["ALWAYS_REPLY_ACCOUNTS"] if h.lower() not in {x.lower() for x in expected}]
    assert list(net.always_reply) == expected
    assert list(net.engage_vip) == NETWORK["ENGAGE_VIP_ACCOUNTS"]
    assert list(net.engage_targets) == NETWORK["ENGAGE_TARGET_ACCOUNTS"]
    assert list(net.reply_targets) == NETWORK["REPLY_TARGET_ACCOUNTS"]
    assert sorted(net.follow_engagers_skip) == NETWORK["SKIP_HANDLES"]
    assert len(set(net.follow_engagers_skip)) == len(net.follow_engagers_skip)
    assert niche.ticker is None
    assert {"graphseo", "thebtctherapist"} <= {h.lower() for h in net.blocked_accounts}


def test_the_removed_accounts_and_queries_are_gone():
    loaded = account.load("theaishrink")
    net, searches = loaded.network, loaded.searches
    # follow_engagers_skip keeps unusual_whales: it keeps an account out.
    listed = {h.lower() for key in ("profile_visits", "vip_scan", "pinned_tracked", "vip_reply",
                                    "big_ai_hype", "mid_size_ai", "high_traction_reply",
                                    "big_fr", "engage_vip", "engage_targets", "reply_targets")
              for h in getattr(net, key)}
    for key in ("vip_reply", "high_traction_reply", "big_fr", "engage_targets", "reply_targets"):
        assert not ({h.lower() for h in REMOVED_205[key]} - {"spacex"}) & listed, key
    queries = set(searches.replies + searches.hot_tab + searches.likes)
    for key in ("replies", "hot_tab", "likes"):
        assert not set(REMOVED_205[key]) & queries, key
    # The AI-only spellings were expanded to AI / SI on 2026-10-23.
    for before in NARROWED_205:
        assert before not in queries


@pytest.mark.parametrize("text", [
    "Bitcoin just broke 120k and altcoin season is here",
    "SpaceX is preparing a Starship launch",
    "Starlink connectivity changes the options here",
    "Elon Musk on building tools",
    "X Premium and Twitter creators",
    "Bitcoin miners are turning their sites into AI datacenters",
    "Ethereum staking yields are up and the Solana ETF got approved",
    "The Fed held rates and stocks rallied into the close",
    "$TSLA and $AAPL gapped up at the open, the Nasdaq is ripping",
    "Le CAC 40 recule, la BCE maintient ses taux",
    "NASA picked a new rocket for the Moon landing",
    # The French verb avoir is not AI.
    "J'ai acheté du Bitcoin ce matin",
    "J’ai acheté du Bitcoin ce matin",
    "Le CAC 40 recule, j'ai renforcé mes positions",
    "J'AI TOUT VENDU",
    "Ai-je raté le rallye ?",
    "Je vous ai dit que le marché allait monter",
    "J'en ai marre de la Fed",
    # Too broad alone.
    "Real estate agent, 20 years in Miami",
    "Agent immobilier à Lyon",
    "FBI agents raided the office",
    "Meta and Google beat on earnings, Apple lagged",
    "This token is up 40% today",
    "X marks the spot",
])
def test_crypto_markets_and_general_space_stay_off_the_niche(text):
    from src.replies import reply_source
    assert not reply_source.is_on_niche(text)


@pytest.mark.parametrize("text", [
    "OpenAI shipped a new reasoning model today",
    "Grok Imagine makes this fun",
    "Claude Code wrote the whole migration in an afternoon",
    "Nvidia cannot build GPUs fast enough for the datacenter buildout",
    "Artificial intelligence is changing radiology faster than expected",
    "L'IA générative change le travail des traducteurs",
    "L’IA va remplacer les traducteurs",
    "AI-powered search is here",
    "ai agents are overhyped",
    "l'AI Act entre en vigueur",
    "A.I. will not replace radiologists",
    "Apple Intelligence is late",
    "Meta's Llama 4 is out",
    "Google's Veo 3 makes the best videos",
    "Meta superintelligence lab poached another researcher",
    "1M token context window",
    "vibe coding is a trap",
    "Qwen3 beats everything on coding",
    "LLMs still cannot count letters",
    "GPUs are sold out until next year",
    "open-weights models are catching up",
    "Sora and Midjourney are eating stock photography",
    "GenAI budgets are exploding",
    "Agentic workflows need evals",
])
def test_an_ai_post_is_on_the_niche(text):
    from src.replies import reply_source
    assert reply_source.is_on_niche(text)


@pytest.mark.parametrize("bio, on_niche", [
    ("Bitcoin maximalist. HODL. Not financial advice.", False),
    ("Macro trader: stocks, ETFs and the Fed", False),
    ("Space nerd, rocket launches and Mars", False),
    ("Investisseur en bourse, dividendes et PEA", False),
    ("AI researcher, ex-DeepMind", True),
    ("SpaceX / Starlink engineer", False),
    ("Grok Imagine enthusiast", True),
    ("Building LLM tools for lawyers", True),
    ("Machine learning engineer at a robotics startup", True),
    ("Research engineer @AnthropicAI", True),
    ("Deep learning engineer", True),
    ("Computer vision engineer", True),
    ("LLMs engineer", True),
    ("GenAI founder", True),
    ("Robotics engineer @Figure", True),
    ("Building agents @ startup", True),
    ("Ingénieur IA", True),
    ("Chercheur en IA", True),
    ("J'ai 30 ans, investisseur", False),
    ("Real estate agent, dad of 3", False),
    ("Software engineer, founder, tech", False),
    ("Claude Dupont, investisseur", False),
])
def test_the_follow_bio_niche_includes_si_and_the_named_ecosystem(bio, on_niche):
    assert bool(account.load("theaishrink").niche.bio.search(bio)) is on_niche


def test_the_account_network_fills_four_settings_and_env_wins(accounts, fresh):
    accounts("theaishrink")
    fresh("VIP_SCAN_HANDLES=FromEnv\n")
    assert settings.get("PROFILE_VISIT_ALLOWLIST") == NETWORK["PROFILE_VISIT_ALLOWLIST"]
    assert settings.get("PINNED_TRACKED_HANDLES") == NETWORK["PINNED_TRACKED_HANDLES"]
    assert settings.get("VIP_SCAN_HANDLES") == "FromEnv"
    # The engine default of FR_FORCED_REPLY_HANDLES before #208.
    assert settings.get("FR_FORCED_REPLY_HANDLES") == ""


def test_fr_forced_reply_is_optional(accounts, fresh):
    accounts("theaishrink", THEAISHRINK.replace('fr_forced_reply = []\n', ""))
    fresh()
    assert account.current().network.fr_forced_reply == ()
    assert settings.get("FR_FORCED_REPLY_HANDLES") == ""


def test_env_wins_over_fr_forced_reply(accounts, fresh):
    accounts("theaishrink")
    fresh("FR_FORCED_REPLY_HANDLES=FromEnv\n")
    assert settings.get("FR_FORCED_REPLY_HANDLES") == "FromEnv"


def test_the_jobs_read_the_loaded_account(accounts, fresh):
    from src.account import engage_bot
    from src.guards import follow_policy
    from src.replies import direct_reply, notify_bot, reply_source
    other = (THEAISHRINK.replace("engagement_niche_only = true", "engagement_niche_only = false")
             .replace('engage_vip = []', 'engage_vip = ["OtherVip"]')
             .replace('vip_reply = [', 'vip_reply = ["OtherVip", ')
             .replace('engage_targets = [', 'engage_targets = ["OtherTarget", ')
             .replace("post = '", "post = '\\bzebra\\b|")
             .replace("bio = '", "bio = '\\bgiraffe\\b|")
             .replace("[niche]", "[niche]\nticker = '\\$ZZZ\\b'"))
    accounts("other", other)
    fresh("BOT_ACCOUNT=other\n")
    assert engage_bot._vip_accounts() == ("OtherVip",)
    assert direct_reply.always_reply_accounts()[0] == "OtherVip"
    assert direct_reply.reply_call("othervip").label == "DIRECT_REPLY_VIP"
    assert direct_reply.reply_call("nobody").label == "DIRECT_REPLY"
    assert "othertarget" in notify_bot._influencer_handles()
    assert reply_source.is_on_niche("a Zebra crossing")
    assert reply_source.is_on_niche("long $ZZZ") and not reply_source.is_on_niche("long $zzz")
    assert follow_policy._quality_decision(5000, "giraffe keeper", "Someone", False) == (True, "")


@pytest.mark.parametrize("old, new, named", [
    ('vip_scan = []', 'vip_scan = ["@Graphseo"]', "network.vip_scan[0]"),
    ('engage_vip = []', 'engage_vip = "Graphseo"', "network.engage_vip"),
    ("blocked_accounts = []", 'blocked_accounts = [" _ "]', "network.blocked_accounts[0]"),
    ("blocked_accounts = []", "blocked_accounts = [3]", "network.blocked_accounts[0]"),
    ('fr_forced_reply = []', 'fr_forced_reply = ["@Graphseo"]', "network.fr_forced_reply[0]"),
    ('fr_forced_reply = []', 'fr_forced_reply = "Graphseo"', "network.fr_forced_reply"),
    ("[niche]", "[niche]\nticker = '('", "niche.ticker"),
    ("[niche]", "[niche]\nticker = 3", "niche.ticker"),
    ("likes = [", "likes = [\n    ' ',", "searches.likes[0]"),
    ("trending = [", "trending = [\n    ' ',", "searches.trending[0]"),
    ("trending = [", "trending_queries = [", "searches.trending_queries"),
    ("[searches]", "[searches]\nquotes = []", "searches.quotes"),
    ('vip_scan = []\n', "", "network.vip_scan"),
    # No key removes a Blocked account of the engine's BLOCKLIST.
    ("blocked_accounts = []", 'blocked_accounts = []\nunblocked_accounts = ["pgm_pm"]',
     "network.unblocked_accounts"),
])
def test_a_bad_network_niche_or_search_stops_the_start(accounts, fresh, old, new, named):
    source = re.sub(r"blocked_accounts = \[[\s\S]*?\]", "blocked_accounts = []", THEAISHRINK, count=1)
    assert source.count(old) == 1
    accounts("theaishrink", source.replace(old, new))
    with pytest.raises(settings.SettingsError, match=re.escape(named)):
        fresh()


# --- Relations: the per-handle Reply instructions (#203) -------------------------

from tests.relation_fixtures import DOSSIER as FIXED_DOSSIER, PROMPTS, RELATIONS_TOML

RELATION_ACCOUNT = THEAISHRINK.replace("[limits]", RELATIONS_TOML + "\n[limits]").replace(
    'vip_scan = []', 'vip_scan = ["SpecialVip", "FriendlyVip"]')


def _digest(text):
    import hashlib
    return len(text), hashlib.sha256(text.encode()).hexdigest()


def test_synthetic_relations_preserve_prompts_and_case_insensitive_lookup(accounts, fresh):
    accounts("theaishrink", RELATION_ACCOUNT)
    fresh()
    relations = account.current().relations
    specialvip, bestie = relations.get("SpecialVip"), relations.get("FriendlyVip")
    assert {"specialvip": _digest(specialvip.prompt), "bestie": _digest(bestie.prompt),
            "buddy": _digest(relations.default)} == {"specialvip": _digest(PROMPTS["special"]), "bestie": _digest(PROMPTS["friendly"]),
                                               "buddy": _digest((ROOT / "accounts/theaishrink/relations/buddy.md").read_text().strip())}
    assert (specialvip.handle, specialvip.provider, specialvip.dossier) == ("SpecialVip", "codex", None)
    assert (bestie.handle, bestie.provider, bestie.dossier) == ("FriendlyVip", None, None)
    assert relations.get("@SPECIALVIP") is specialvip, "handles ignore case and a leading @"
    mcnallie = relations.get("fixeddossier")
    assert (mcnallie.prompt, mcnallie.provider) == (None, None)
    assert sorted(relations.handles) == ["fixeddossier", "friendlyvip", "specialvip"]
    assert relations.vip_prompt("friendlyvip") == bestie.prompt
    assert relations.vip_prompt("FixedDossier") == relations.vip_prompt("vision_ia") == relations.default


def test_a_fixed_dossier_reads_as_the_old_one(relation_account):
    from src.core import personality_store
    assert personality_store.get_account("FixedDossier") == FIXED_DOSSIER
    assert personality_store.get_account("@fixeddossier") == FIXED_DOSSIER


def test_the_relation_providers_are_llm_client_clis():
    from src.core import llm_client
    assert set(account.CLI_PROVIDERS) == set(llm_client.ADAPTERS) - {"ollama"}


@pytest.mark.parametrize("old, new, named", [
    ('provider = "codex"', 'provider = "codex"\nlabel = "X"', "relations.handles.SpecialVip.label"),
    ('stance = "fond"', 'stance = "fond"\nmood = "x"', "relations.handles.FixedDossier.dossier.mood"),
    ('default = "relations/buddy.md"', 'default = "relations/buddy.md"\nbuddy = "x.md"', "relations.buddy"),
    ("[relations.handles.SpecialVip]", '[relations.handles."Graph-seo"]', "relations.handles.Graph-seo"),
    ("[relations.handles.SpecialVip]", "[relations.handles.ThisHandleIsTooLong]",
     "relations.handles.ThisHandleIsTooLong"),
    ("[relations.handles.FixedDossier.dossier]", "[relations.handles.specialvip.dossier]",
     "relations.handles.specialvip repeats SpecialVip"),
])
def test_an_unknown_relation_key_or_handle_stops_the_start(accounts, fresh, old, new, named):
    assert RELATION_ACCOUNT.count(old) == 1
    accounts("theaishrink", RELATION_ACCOUNT.replace(old, new))
    with pytest.raises(settings.SettingsError, match=re.escape(named)):
        fresh()


@pytest.mark.parametrize("old, new, named", [
    ('provider = "codex"', 'provider = "codx"', "relations.handles.SpecialVip.provider takes one of"),
    ('prompt = "relations/special.md"\n', "", "relations.handles.SpecialVip.provider needs a prompt"),
    ('stance = "fond"', "stance = 3", "relations.handles.FixedDossier.dossier.stance"),
    ('notes = [\n', 'notes = [\n    7,\n', "relations.handles.FixedDossier.dossier.notes[0]"),
    ('prompt = "relations/special.md"', 'prompt = "relations/nope.md"', "relations.handles.SpecialVip.prompt"),
    ('prompt = "relations/friendly.md"', 'prompt = "../voice_en.md"', "outside the Account's folder"),
])
def test_a_bad_relation_value_stops_the_start(accounts, fresh, old, new, named):
    assert RELATION_ACCOUNT.count(old) == 1
    accounts("theaishrink", RELATION_ACCOUNT.replace(old, new))
    with pytest.raises(settings.SettingsError, match=re.escape(named)):
        fresh()


def test_an_empty_fixed_dossier_stops_the_start(accounts, fresh):
    start = RELATION_ACCOUNT.index("[relations.handles.FixedDossier.dossier]")
    end = RELATION_ACCOUNT.index("\n\n", RELATION_ACCOUNT.index("dont = ", start))
    accounts("theaishrink", RELATION_ACCOUNT[:start] + "[relations.handles.FixedDossier.dossier]" + RELATION_ACCOUNT[end:])
    with pytest.raises(settings.SettingsError, match=re.escape("relations.handles.FixedDossier.dossier is empty")):
        fresh()


def test_the_default_prompt_is_needed_only_for_a_scanned_handle_without_its_own(accounts, fresh):
    # SpecialVip and FriendlyVip, the vip_scan handles, each have their own prompt.
    accounts("theaishrink", RELATION_ACCOUNT.replace('default = "relations/buddy.md"\n', ""))
    fresh()
    assert account.current().relations.default is None
    assert account.current().relations.vip_prompt("vision_ia") is None
    scan = 'vip_scan = ["SpecialVip", "FriendlyVip"]'
    accounts("other", RELATION_ACCOUNT.replace('default = "relations/buddy.md"\n', "")
             .replace(scan, 'vip_scan = ["SpecialVip", "FriendlyVip", "FixedDossier"]'))
    with pytest.raises(settings.SettingsError, match=re.escape(
            "relations.default is missing: network.vip_scan lists FixedDossier, which has no Relation "
            "with its own prompt")):
        account.load("other")


def test_an_account_without_relations_starts_when_it_scans_no_vip(accounts, fresh):
    start = RELATION_ACCOUNT.index("[relations]")
    bare = RELATION_ACCOUNT[:start] + RELATION_ACCOUNT[RELATION_ACCOUNT.index("[limits]"):]
    accounts("theaishrink", bare)
    with pytest.raises(settings.SettingsError, match=re.escape(
            "relations.default is missing: network.vip_scan lists SpecialVip")):
        fresh()
    old = 'vip_scan = ["SpecialVip", "FriendlyVip"]'
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
    assert _digest(account.current().relations.default) == _digest((ROOT / "accounts/theaishrink/relations/buddy.md").read_text().strip())


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


@pytest.mark.parametrize("name, previous", [
    ("replies", NETWORK["SEARCH_QUERIES"]),
    ("hot_tab", NETWORK["HOT_TAB_QUERIES"]),
    ("likes", NETWORK["LIKE_QUERIES"]),
    ("trending", OLD_TREND_QUERIES),
])
def test_research_keeps_vocabularies_and_floors_only_for_high_traction_lanes(name, previous):
    queries = getattr(account.current().searches, name)
    assert len(queries) == len(previous)
    for before, after in zip(previous, queries):
        if name == "replies":
            # Ordinary Reply discovery admits smaller/newer posts too;
            # observed popularity is a later ordering preference.
            before = re.sub(r" min_faves:\d+", "", before)
            assert "min_faves:" not in after
        assert re.findall(r"(?:lang|min_faves):\w+|-filter:replies", after) == re.findall(
            r"(?:lang|min_faves):\w+|-filter:replies", before)
        assert re.search(r"\bAI\b", after) and re.search(r"\bSI\b", after)
        assert '"artificial intelligence"' in after and '"super intelligence"' in after
        assert 'superintelligence' in after and 'ASI' in after
        assert len(after) < 500


@pytest.mark.parametrize("term", ["AI", "SI", "ASI", "Artificial Intelligence",
                                  "Super Intelligence", "superintelligence"])
def test_both_vocabularies_are_discoverable_in_posts_bios_and_editorial_sources(term):
    loaded = account.current()
    assert loaded.niche.post.search(f"New {term} benchmark")
    assert loaded.niche.bio.search(f"Researching {term}")
    assert loaded.relevance.topic.search(f"New {term} benchmark")


@pytest.mark.parametrize("text", ["Si tu viens demain, on peut parler.", "Je ne sais pas si ça marche."])
def test_french_si_does_not_make_a_post_or_bio_relevant(text):
    loaded = account.current()
    assert not loaded.niche.post.search(text)
    assert not loaded.niche.bio.search(text)


def test_reply_si_wording_defaults_to_false(accounts, fresh):
    accounts("theaishrink", THEAISHRINK.replace("reply_si_wording = true\n", ""))
    fresh()
    assert account.current().reply_si_wording is False


def test_own_identities_include_account_aliases_and_runtime_override(settings_override):
    settings_override(BOT_HANDLE="RuntimeBot")
    assert {"runtimebot", "theaishrink", "thesimaximalist"} <= account.own_handles()


@pytest.mark.parametrize("value", ['"true"', "1", "[]"])
def test_standalone_reply_policy_rejects_invalid_types(accounts, fresh, value):
    accounts("theaishrink", THEAISHRINK.replace("standalone_replies_only = true",
                                               f"standalone_replies_only = {value}"))
    with pytest.raises(settings.SettingsError, match="standalone_replies_only"):
        fresh()


@pytest.mark.parametrize("value", ['["@bad"]', '["not a handle"]', "[42]", '"Alias"'])
def test_own_handle_aliases_are_validated(accounts, fresh, value):
    accounts("theaishrink", THEAISHRINK.replace('previous_handles = ["TheAIShrink"]',
                                               f"previous_handles = {value}"))
    with pytest.raises(settings.SettingsError, match="previous_handles"):
        fresh()


@pytest.mark.parametrize("value", ['"true"', "1", "[]"])
def test_reply_si_wording_rejects_invalid_types(accounts, fresh, value):
    accounts("theaishrink", THEAISHRINK.replace("reply_si_wording = true", f"reply_si_wording = {value}"))
    with pytest.raises(settings.SettingsError, match="reply_si_wording"):
        fresh()


@pytest.mark.parametrize("value", ['"true"', "1", "[]"])
def test_publication_si_wording_rejects_invalid_types(accounts, fresh, value):
    accounts("theaishrink", THEAISHRINK.replace("publication_si_wording = true",
                                               f"publication_si_wording = {value}"))
    with pytest.raises(settings.SettingsError, match="publication_si_wording"):
        fresh()

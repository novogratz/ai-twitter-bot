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

def test_current_identity_keeps_the_storage_key_and_editorial_bounds():
    loaded = account.load("theaishrink")
    assert loaded.handle == "thesimaximalist"
    assert loaded.display_name == "The SI Maximalist"
    assert loaded.previous_handles == ("TheAIShrink",)
    assert loaded.bio == ("SI Maximalist: SI brain rot, Super Intelligence, SI news, "
                          "celebrity parodies, and SI tech chaos.")
    assert loaded.language == "en" and loaded.domain == "SI / Super intelligence"
    assert loaded.limits == {}
    ed = loaded.editorial
    assert [clock for clock, _ in ed.slots] == [
        "05:00", "07:15", "09:30", "10:00", "11:45", "13:00", "14:00", "15:00", "16:15", "18:30", "20:45"]
    assert ed.trend_clocks == {"10:00", "13:00", "15:00"}
    assert ed.exceptional_clocks == {"20:45"}
    assert loaded.replies.is_protected("elonmusk")
    assert loaded.replies.ranked_selection is True
    assert any(t.topic == "video_generation" and t.url.startswith("https://docs.x.ai/") for t in ed.evergreen)
    assert {"x.ai", "docs.x.ai"} <= ed.trusted_hosts
    assert loaded.relevance.off_topic.search("Bitcoin giveaway")


def test_the_editorial_reads_the_loaded_account():
    loaded = account.current()
    assert settings.get("BOT_ACCOUNT") == "theaishrink"
    assert [tuple(slot) for slot in editorial.slots()] == list(loaded.editorial.slots)
    assert set(editorial.trend_slots()) == loaded.editorial.trend_clocks
    assert config.BOT_HANDLE == "thesimaximalist"
    assert config.BOT_PROFILE_URL == "https://x.com/thesimaximalist"


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
    ('handle = "thesimaximalist"', "handle = 3", "handle"),
    ('language = "en"', 'language = "de"', "language"),
    ('{ clock = "10:00", trend = true }', '{ clock = "10:00", trend = "yes" }', "editorial.slots[3].trend"),
    ('{ clock = "10:00", trend = true }', '{ clock = "10h00", trend = true }', "editorial.slots[3].clock"),
    ('{ clock = "10:00", trend = true }', '{ clock = "09:00", trend = true }', "editorial.slots[3].clock"),
    ('"openai.com", "blog.google"', '"openai.com", 7', "editorial.trusted_hosts[1]"),
    ('chat_templating"\npublisher = "Hugging Face docs"', 'chat_templating"\npublisher = true',
     "editorial.evergreen[0].publisher"),
    ("off_topic = '", "off_topic = '(", "relevance.off_topic"),
    ('[limits]', '[limits]\nMAX_ORIGINALS_PER_DAY = "6"', "limits.MAX_ORIGINALS_PER_DAY"),
    ('handle = "thesimaximalist"\n', "", "handle"),
    ('domain = "SI / Super intelligence"', "domain = 3", "domain"),
    ('domain = "SI / Super intelligence"', 'domain = " "', "domain is blank"),
    ('domain = "SI / Super intelligence"\n', "", "domain is missing"),
    ('handle = "thesimaximalist"', 'handle = "thesimaximalist', "not valid TOML"),
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
    ("MIN_SECONDS_BETWEEN_REPLIES = 0", "MIN_SECONDS_BETWEEN_REPLIES", 30),
    ("DUP_TEXT_WINDOW_HOURS = 12", "DUP_TEXT_WINDOW_HOURS", 48.0),
    ("BAN_SHORT_TERM_PRICE_TARGETS = false", "BAN_SHORT_TERM_PRICE_TARGETS", True),
    ("FOLLOWBACK_CAP = -1", "FOLLOWBACK_CAP", 0),
    ("DUP_SHARED_BIGRAMS = 0", "DUP_SHARED_BIGRAMS", 1),
])
def test_an_account_value_past_an_engine_bound_is_brought_back_to_it(accounts, fresh, limit, name, bound):
    accounts("theaishrink", THEAISHRINK.replace("[limits]", f"[limits]\n{limit}"))
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
# NARROWED_205. On 2026-10-14 Latest discovery removes popularity minimums
# and groups the same topics explicitly. A pattern is (source, flags).
NETWORK = {
    "PROFILE_VISIT_ALLOWLIST": "TheBTCTherapist,Graphseo",
    "VIP_SCAN_HANDLES": "Graphseo,TheBTCTherapist",
    "PINNED_TRACKED_HANDLES": "TheBTCTherapist,Graphseo,Mindset4Money_X",
    "VIP_REPLY_ACCOUNTS": [
        "TheBTCTherapist", "Graphseo", "vision_ia", "jbelizaireCEO", "ylecun", "arthurmensch",
        "GuillaumeLample", "fchollet", "karpathy", "demishassabis", "sama",
    ],
    "BIG_AI_HYPE_ACCOUNTS": [
        "sama", "DarioAmodei", "demishassabis", "satyanadella", "sundarpichai",
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
        "Dark_Emi_", "ABaradez", "Phil_RX", "arthurmensch", "GuillaumeLample", "GaelVaroquaux",
        "fchollet", "MistralAI",
    ],
    "BIG_FR_ACCOUNTS": [
        "Korben", "micode", "Underscore_", "presse_citron", "numerama", "siecledigital", "BFMTech",
        "frandroid", "journaldugeek", "FlavienChervet", "MistralAI", "arthurmensch",
        "GuillaumeLample", "Heu7reka", "Yoann_Lopez_", "SnowballEcho",
    ],
    "ALWAYS_REPLY_ACCOUNTS": [
        "TheBTCTherapist", "Graphseo", "vision_ia", "jbelizaireCEO", "ylecun", "arthurmensch",
        "GuillaumeLample", "fchollet", "karpathy", "demishassabis", "sama",
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
        "amanrsanger", "mathemagic1an", "Dark_Emi_", "ABaradez", "Phil_RX", "GaelVaroquaux",
        "Korben", "micode", "Underscore_", "presse_citron", "numerama", "siecledigital", "BFMTech",
        "frandroid", "journaldugeek", "FlavienChervet", "Heu7reka", "Yoann_Lopez_", "SnowballEcho",
    ],
    "ENGAGE_VIP_ACCOUNTS": [
        "Graphseo",
    ],
    "ENGAGE_TARGET_ACCOUNTS": [
        "Graphseo", "XFenaux",
    ],
    "REPLY_TARGET_ACCOUNTS": [
        "Graphseo", "vision_ia", "jbelizaireCEO", "McnallieM", "sama", "OpenAI", "AnthropicAI",
        "GoogleDeepMind", "xAI", "karpathy", "ylecun", "fchollet", "demishassabis",
        "MistralAI", "arthurmensch", "GuillaumeLample", "GaelVaroquaux", "nvidia", "AMD", "intel",
        "CoreWeave", "IREN_Ltd", "LambdaAPI", "applied_dc", "BostonDynamics", "Figure_robot",
        "ID_AA_Carmack", "drfeifei", "ABaradez", "Yoann_Lopez_", "SnowballEcho", "DereeperVivre",
        "Phil_RX", "Korben", "underscore_", "MichaelBenabou", "presse_citron", "siecledigital",
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
        '("why would" OR "why is" OR "what am I missing") (Nvidia OR (SI OR "super intelligence" OR superintelligence OR ASI OR AI OR "artificial intelligence")) lang:en -filter:replies',
        '((SI OR "super intelligence" OR superintelligence OR ASI OR AI OR "artificial intelligence") (model OR release OR research) OR OpenAI OR Anthropic OR xAI OR "GPT-5") lang:en -filter:replies',
        '((SI OR "super intelligence" OR superintelligence OR ASI OR AI OR "artificial intelligence") (assistant OR chatbot) OR ChatGPT OR Claude OR Gemini OR Grok OR Llama) lang:en -filter:replies',
        '((SI OR "super intelligence" OR superintelligence OR ASI OR AI OR "artificial intelligence") (agents OR agentic OR reasoning) OR "reasoning model" OR AGI) lang:en -filter:replies',
        '((SI OR "super intelligence" OR superintelligence OR ASI OR AI OR "artificial intelligence") (coding) OR "Claude Code" OR Cursor OR Copilot) lang:en -filter:replies',
        '((SI OR "super intelligence" OR superintelligence OR ASI OR AI OR "artificial intelligence") (Meta OR Apple OR Microsoft OR Amazon OR Tesla) OR "Apple Intelligence" OR "Microsoft Copilot") lang:en -filter:replies',
        '((SI OR "super intelligence" OR superintelligence OR ASI OR AI OR "artificial intelligence") (datacenter OR capex) OR Nvidia OR GPU) lang:en -filter:replies',
        '((SI OR "super intelligence" OR superintelligence OR ASI OR AI OR "artificial intelligence") (TSMC OR AMD OR Broadcom OR chips OR power OR energy)) lang:en -filter:replies',
        '((SI OR "super intelligence" OR superintelligence OR ASI OR AI OR "artificial intelligence") (CoreWeave OR Nebius OR "Applied Digital" OR "data center" OR electricity)) lang:en -filter:replies',
        '((SI OR "super intelligence" OR superintelligence OR ASI OR AI OR "artificial intelligence") (startup OR funding OR layoffs OR jobs OR "open source") OR DeepSeek) lang:en -filter:replies',
    ],
    "HOT_TAB_QUERIES": [
        '((SI OR "super intelligence" OR superintelligence OR ASI OR AI OR "artificial intelligence") (model OR release) OR OpenAI OR Anthropic OR xAI OR "GPT-5") lang:en min_faves:500 -filter:replies',
        '((SI OR "super intelligence" OR superintelligence OR ASI OR AI OR "artificial intelligence") (datacenter OR capex) OR Nvidia) lang:en min_faves:300 -filter:replies',
        '((SI OR "super intelligence" OR superintelligence OR ASI OR AI OR "artificial intelligence") (agents OR reasoning) OR "reasoning model" OR AGI) lang:en min_faves:300 -filter:replies',
        '((SI OR "super intelligence" OR superintelligence OR ASI OR AI OR "artificial intelligence") (assistant OR robotics) OR ChatGPT OR Claude OR Gemini OR "humanoid robot") lang:en min_faves:500 -filter:replies',
    ],
    "LIKE_QUERIES": [
        '((SI OR "super intelligence" OR superintelligence OR ASI OR AI OR "artificial intelligence") (datacenter OR "power demand")) lang:en min_faves:50',
        '((SI OR "super intelligence" OR superintelligence OR ASI OR AI OR "artificial intelligence") (megawatt OR gigawatt OR nuclear)) lang:en min_faves:50',
        '((SI OR "super intelligence" OR superintelligence OR ASI OR AI OR "artificial intelligence") ("compute cluster") OR Nvidia OR GPU) lang:en min_faves:50',
        '((SI OR "super intelligence" OR superintelligence OR ASI OR AI OR "artificial intelligence") (robotics OR robots) OR robotics OR "humanoid robots") lang:en min_faves:50',
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
        '("why would" OR "why is" OR "what am I missing") (Nvidia OR (SI OR "super intelligence" OR superintelligence OR ASI OR AI OR "artificial intelligence")) lang:en -filter:replies',
    'Nvidia OR NVDA OR GPU OR "AI datacenter" OR "AI capex" lang:en min_faves:50':
        '((SI OR "super intelligence" OR superintelligence OR ASI OR AI OR "artificial intelligence") (datacenter OR capex) OR Nvidia OR GPU) lang:en -filter:replies',
    'TSMC OR AMD OR Broadcom OR "AI chips" OR "AI power" OR "AI energy" lang:en min_faves:30':
        '((SI OR "super intelligence" OR superintelligence OR ASI OR AI OR "artificial intelligence") (TSMC OR AMD OR Broadcom OR chips OR power OR energy)) lang:en -filter:replies',
    'CoreWeave OR Nebius OR "Applied Digital" OR "data center" OR "AI electricity" lang:en min_faves:30':
        '((SI OR "super intelligence" OR superintelligence OR ASI OR AI OR "artificial intelligence") (CoreWeave OR Nebius OR "Applied Digital" OR "data center" OR electricity)) lang:en -filter:replies',
    "AI datacenter OR power demand lang:en min_faves:50":
        '((SI OR "super intelligence" OR superintelligence OR ASI OR AI OR "artificial intelligence") (datacenter OR "power demand")) lang:en min_faves:50',
    "megawatt OR gigawatt OR nuclear AI lang:en min_faves:50":
        '((SI OR "super intelligence" OR superintelligence OR ASI OR AI OR "artificial intelligence") (megawatt OR gigawatt OR nuclear)) lang:en min_faves:50',
    "Nvidia OR GPU OR compute cluster lang:en min_faves:50":
        '((SI OR "super intelligence" OR superintelligence OR ASI OR AI OR "artificial intelligence") ("compute cluster") OR Nvidia OR GPU) lang:en min_faves:50',
    "robotics OR humanoid robots OR frontier tech lang:en min_faves:50":
        '((SI OR "super intelligence" OR superintelligence OR ASI OR AI OR "artificial intelligence") (robotics OR robots) OR robotics OR "humanoid robots") lang:en min_faves:50',
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
    assert list(net.always_reply) == NETWORK["ALWAYS_REPLY_ACCOUNTS"]
    assert list(net.engage_vip) == NETWORK["ENGAGE_VIP_ACCOUNTS"]
    assert list(net.engage_targets) == NETWORK["ENGAGE_TARGET_ACCOUNTS"]
    assert list(net.reply_targets) == NETWORK["REPLY_TARGET_ACCOUNTS"]
    assert sorted(net.follow_engagers_skip) == NETWORK["SKIP_HANDLES"]
    assert len(set(net.follow_engagers_skip)) == len(net.follow_engagers_skip)
    assert niche.ticker is None
    assert set(NETWORK["SEARCH_QUERIES"]) <= set(searches.replies)
    assert set(NETWORK["HOT_TAB_QUERIES"]) <= set(searches.hot_tab)
    assert set(NETWORK["LIKE_QUERIES"]) <= set(searches.likes)
    assert net.blocked_accounts == ("elonmusk",)


def test_the_removed_accounts_and_queries_are_gone():
    loaded = account.load("theaishrink")
    net, searches = loaded.network, loaded.searches
    # follow_engagers_skip keeps unusual_whales: it keeps an account out.
    listed = {h.lower() for key in ("profile_visits", "vip_scan", "pinned_tracked", "vip_reply",
                                    "big_ai_hype", "mid_size_ai", "high_traction_reply",
                                    "big_fr", "engage_vip", "engage_targets", "reply_targets")
              for h in getattr(net, key)}
    for key in ("vip_reply", "high_traction_reply", "big_fr", "engage_targets", "reply_targets"):
        assert not {h.lower() for h in REMOVED_205[key]} & listed, key
    queries = set(searches.replies + searches.hot_tab + searches.likes)
    for key in ("replies", "hot_tab", "likes"):
        assert not set(REMOVED_205[key]) & queries, key
    for before, after in NARROWED_205.items():
        assert before not in queries and after in queries


@pytest.mark.parametrize("text", [
    "Bitcoin just broke 120k and altcoin season is here",
    "Ethereum staking yields are up and the Solana ETF got approved",
    "The Fed held rates and stocks rallied into the close",
    "$TSLA and $AAPL gapped up at the open, the Nasdaq is ripping",
    "Le CAC 40 recule, la BCE maintient ses taux",
    "SpaceX Starship reached orbit and Starlink passed 8,000 satellites",
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
])
def test_a_crypto_markets_or_space_post_is_off_the_niche(text):
    from src.replies import reply_source
    assert not reply_source.is_on_niche(text)


@pytest.mark.parametrize("text", [
    "OpenAI shipped a new reasoning model today",
    "Claude Code wrote the whole migration in an afternoon",
    "Nvidia cannot build GPUs fast enough for the datacenter buildout",
    "Artificial intelligence is changing radiology faster than expected",
    "L'IA générative change le travail des traducteurs",
    "Bitcoin miners are turning their sites into AI datacenters",
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
def test_the_follow_bio_niche_is_ai_only(bio, on_niche):
    assert bool(account.load("theaishrink").niche.bio.search(bio)) is on_niche


def test_the_account_network_fills_four_settings_and_env_wins(accounts, fresh):
    accounts("theaishrink")
    fresh("VIP_SCAN_HANDLES=FromEnv\n")
    assert settings.get("PROFILE_VISIT_ALLOWLIST") == NETWORK["PROFILE_VISIT_ALLOWLIST"]
    assert settings.get("PINNED_TRACKED_HANDLES") == NETWORK["PINNED_TRACKED_HANDLES"]
    assert settings.get("VIP_SCAN_HANDLES") == "FromEnv"
    # The engine default of FR_FORCED_REPLY_HANDLES before #208.
    assert settings.get("FR_FORCED_REPLY_HANDLES") == "Graphseo"


def test_fr_forced_reply_is_optional(accounts, fresh):
    accounts("theaishrink", THEAISHRINK.replace('fr_forced_reply = ["Graphseo"]\n', ""))
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
    other = (THEAISHRINK
             .replace('engage_vip = ["Graphseo"]', 'engage_vip = ["OtherVip"]')
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
    ('vip_scan = ["Graphseo", "TheBTCTherapist"]', 'vip_scan = ["@Graphseo"]', "network.vip_scan[0]"),
    ('engage_vip = ["Graphseo"]', 'engage_vip = "Graphseo"', "network.engage_vip"),
    ('blocked_accounts = ["elonmusk"]', 'blocked_accounts = [" _ "]', "network.blocked_accounts[0]"),
    ('blocked_accounts = ["elonmusk"]', "blocked_accounts = [3]", "network.blocked_accounts[0]"),
    ('fr_forced_reply = ["Graphseo"]', 'fr_forced_reply = ["@Graphseo"]', "network.fr_forced_reply[0]"),
    ('fr_forced_reply = ["Graphseo"]', 'fr_forced_reply = "Graphseo"', "network.fr_forced_reply"),
    ("[niche]", "[niche]\nticker = '('", "niche.ticker"),
    ("[niche]", "[niche]\nticker = 3", "niche.ticker"),
    ("likes = [", "likes = [\n    ' ',", "searches.likes[0]"),
    ("trending = [", "trending = [\n    ' ',", "searches.trending[0]"),
    ("trending = [", "trending_queries = [", "searches.trending_queries"),
    ("[searches]", "[searches]\nquotes = []", "searches.quotes"),
    ('vip_scan = ["Graphseo", "TheBTCTherapist"]\n', "", "network.vip_scan"),
    # No key removes a Blocked account of the engine's BLOCKLIST.
    ('blocked_accounts = ["elonmusk"]', 'blocked_accounts = ["elonmusk"]\nunblocked_accounts = ["pgm_pm"]',
     "network.unblocked_accounts"),
])
def test_a_bad_network_niche_or_search_stops_the_start(accounts, fresh, old, new, named):
    assert THEAISHRINK.count(old) == 1
    accounts("theaishrink", THEAISHRINK.replace(old, new))
    with pytest.raises(settings.SettingsError, match=re.escape(named)):
        fresh()


# --- Relations: the per-handle Reply instructions (#203) -------------------------

def test_relations_load_current_operator_prompts_and_keep_routing():
    relations = account.load("theaishrink").relations
    graphseo, bestie = relations.get("Graphseo"), relations.get("TheBTCTherapist")
    folder = Path(account.current().folder) / "relations"
    assert graphseo.prompt == (folder / "graphseo.md").read_text().strip()
    assert bestie.prompt == (folder / "bestie.md").read_text().strip()
    assert relations.default == (folder / "buddy.md").read_text().strip()
    assert (graphseo.handle, graphseo.provider, graphseo.dossier) == ("Graphseo", "claude", None)
    assert (bestie.handle, bestie.provider, bestie.dossier) == ("TheBTCTherapist", None, None)
    assert relations.get("@GRAPHSEO") is graphseo, "handles ignore case and a leading @"
    mcnallie = relations.get("mcnalliem")
    assert (mcnallie.prompt, mcnallie.provider) == (None, None)
    assert sorted(relations.handles) == ["graphseo", "mcnalliem", "thebtctherapist"]
    assert relations.vip_prompt("thebtctherapist") == bestie.prompt
    assert relations.vip_prompt("McnallieM") == relations.vip_prompt("vision_ia") == relations.default


def test_current_fixed_dossier_overrides_old_learned_memory():
    from src.core import personality_store
    personality_store.PERSONALITY.write({"accounts": {"mcnalliem": {"do": "OLD_PERSONA"}}, "topics": {}})
    expected = {**personality_store.DEFAULT_ACCOUNT, **account.current().relations.get("McnallieM").dossier}
    assert personality_store.get_account("McnallieM") == expected
    assert personality_store.get_account("@mcnalliem") == expected
    assert "OLD_PERSONA" not in personality_store.render_account_block("McnallieM")


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
    assert account.current().relations.default == (folder / "buddy_real.md").read_text().strip()


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


def test_protected_reply_handles_are_normalized_and_account_owned(accounts):
    accounts("custom", THEAISHRINK.replace('protected_handles = ["elonmusk"]', 'protected_handles = ["SomeAuthor"]'))
    loaded = account.load("custom")
    assert loaded.replies.is_protected("@SOMEAUTHOR")
    assert not loaded.replies.is_protected("SomeAuthorFan")
    assert not loaded.replies.is_protected("elonmusk")


@pytest.mark.parametrize("raw", ['["@bad"]', '["bad-handle"]', '[17]', '"someone"'])
def test_invalid_protected_reply_handles_stop_loading(accounts, raw):
    accounts("custom", THEAISHRINK.replace('protected_handles = ["elonmusk"]', 'protected_handles = ' + raw))
    with pytest.raises(account.AccountError, match="protected_handles"):
        account.load("custom")


def test_protected_reply_handles_are_optional_for_other_accounts(accounts):
    accounts("custom", THEAISHRINK.replace('protected_handles = ["elonmusk"]', ""))
    assert account.load("custom").replies.protected_handles == frozenset()


@pytest.mark.parametrize("text", [
    "SI news and Super Intelligence", "SI brainrot with Grok Imagine",
    "Super intelligence video creators", "ASI research is accelerating",
    "Grok Imagine generated this clip", "Kling image-to-video workflow", "RunwayML filmmaker",
])
def test_si_and_video_creators_match_the_account_scope(text):
    from src.replies.reply_source import is_on_niche
    loaded = account.current()
    assert is_on_niche(text)
    assert loaded.niche.bio.search(text)
    assert loaded.relevance.topic.search(text)


@pytest.mark.parametrize("lane", ["replies", "hot_tab", "likes", "trending"])
def test_every_research_lane_includes_si_terms_and_legacy_search_aliases(lane):
    for query in getattr(account.current().searches, lane):
        assert all(term in query for term in ('SI', '"super intelligence"', 'superintelligence', 'ASI',
                                               'AI', '"artificial intelligence"'))
        assert len(query) < 500
        if lane != "likes":
            assert "-filter:replies" in query


@pytest.mark.parametrize("alias", ["SI", "Super intelligence", "superintelligence", "ASI"])
@pytest.mark.parametrize("subject", ["research", "videos", "tools", "models", "agents"])
def test_si_subjects_qualify_for_posts_bios_and_source_titles(alias, subject):
    loaded = account.current()
    text = f"Building {alias} {subject}"
    assert loaded.niche.post.search(text)
    assert loaded.niche.bio.search(text)
    assert loaded.relevance.topic.search(text)


@pytest.mark.parametrize("language", ["en", "fr"])
def test_voice_research_aliases_and_hours_match_current_policy(language):
    from src.core import personality_store
    voice = personality_store.render_voice(language)
    assert all(term in voice for term in ('SI', '"super intelligence"', 'superintelligence', '"artificial intelligence"'))
    assert "24/7" in voice
    assert "05:00–09:30" not in voice


@pytest.mark.parametrize("text", ["Si tu viens demain", "si j'avais su", "My vacation video", "Celebrity gossip today"])
def test_ordinary_si_and_unrelated_videos_do_not_match_the_niche(text):
    from src.replies.reply_source import is_on_niche
    assert not is_on_niche(text)
    assert not account.current().niche.bio.search(text)


@pytest.mark.parametrize("field,value", [
    ("previous_handles", '["@old"]'), ("previous_handles", '[7]'),
    ("previous_handles", '"old"'), ("display_name", '" "'),
    ("bio", '"' + "x" * 161 + '"'),
    ("publish_originals", '"false"'), ("publish_originals", '1'),
    ("text_replacements", '["AI"]'), ("text_replacements", '{ "AI" = 1 }'),
    ("text_replacements", '{ "AI" = " " }'), ("text_replacements", '{ " " = "SI" }'),
])
def test_invalid_profile_metadata_stops_loading(accounts, fresh, field, value):
    updated = re.sub(r"^" + field + r" = .*", field + " = " + value, THEAISHRINK, flags=re.M, count=1)
    accounts("theaishrink", updated)
    with pytest.raises(settings.SettingsError, match=field):
        fresh()


def test_profile_metadata_defaults_for_existing_accounts(accounts, fresh):
    header, body = THEAISHRINK.split("[editorial]", 1)
    header = re.sub(r"^(display_name|bio|previous_handles|publish_originals|text_replacements) = .*\n", "", header, flags=re.M)
    text = header + "[editorial]" + body
    accounts("minimal", text)
    fresh("BOT_ACCOUNT=minimal\n")
    loaded = account.current()
    assert loaded.display_name == loaded.handle
    assert loaded.bio == "" and loaded.previous_handles == ()
    assert loaded.publish_originals is True and loaded.text_replacements == {}

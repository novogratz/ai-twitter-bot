"""The Reply generator, tested through every job that calls it and through
its interface, with the one fake LLM of tests/replies/fakes.py."""
import pytest

from src.core.llm_client import LLMResult
from tests.helpers import fresh

EN = "OpenAI just shipped a new reasoning model and the market is going wild"
FR = "OpenAI vient de sortir un nouveau modèle et le marché est en feu"


def language(prompt):
    """(core identity language, target language line) a prompt carries."""
    identity = ("fr" if "IDENTITE NOYAU" in prompt
                else "en" if "CORE IDENTITY (NON-NEGOTIABLE" in prompt else None)
    override = ("fr" if "TARGET LANGUAGE OVERRIDE: FRENCH ONLY" in prompt
                else "en" if "TARGET LANGUAGE OVERRIDE: ENGLISH ONLY" in prompt else None)
    return identity, override


@pytest.fixture
def jobs(monkeypatch, llm, chokepoint):
    """Each live Reply job run on one parent post; returns the prompt it sent."""
    from src.core import evolution_store
    from src.replies import reply_pipeline
    from src.replies import direct_reply as dr, early_bird_bot as eb, mega_watch_bot as mw
    from src.replies import debate_bot as db, feed_sweeper_bot as fs, notify_bot as nb, reply_agent as ra
    from src.x import scraper

    chokepoint.answer = False
    for module in (dr, eb, mw, fs):
        monkeypatch.setattr(module, "is_on_niche", lambda text: True)
    monkeypatch.setattr(dr, "ALWAYS_REPLY_ACCOUNTS", [])
    monkeypatch.setattr(evolution_store, "filter_and_weight", lambda handles: list(handles))
    monkeypatch.setenv("ENABLE_DEBATES", "1")
    monkeypatch.setattr(nb, "_influencer_handles", lambda: set())
    monkeypatch.setattr(nb, "_reciprocate_engagers", lambda *a, **k: None)
    monkeypatch.setattr(ra, "_load_discovered_handles", lambda limit=10: [])
    monkeypatch.setattr(fs, "_harvest_active_authors", lambda tweets: None)

    def search(author, text):
        url = fresh(author)  # every query of the cycle finds the same post
        monkeypatch.setenv("VIP_SCAN_HANDLES", "")
        monkeypatch.setattr(dr, "scrape_x_search", lambda *a, **k: [{"url": url, "text": text}])
        dr.run_direct_reply_cycle()

    def feed(author, text):
        monkeypatch.setattr(scraper, "scrape_home_feed", lambda **k: [{"url": fresh(author), "text": text}])
        monkeypatch.setattr(scraper, "scrape_following_feed", lambda **k: [])
        fs.run_feed_sweep_cycle()

    def profile(module, pool, cycle):
        def run(handle, text):
            monkeypatch.setattr(module, pool, lambda: [handle])
            monkeypatch.setattr(module, "scrape_profile_tweets", lambda username, **k: [
                {"url": fresh(handle, minutes=1), "text": text, "author": handle}])
            cycle()
        return run

    def vip(handle, text):
        monkeypatch.setenv("VIP_SCAN_HANDLES", handle)
        monkeypatch.setattr(scraper, "scrape_x_search", lambda q, **k: [{"url": fresh(handle), "text": text}])
        dr._run_graphseo_scan(reply_pipeline.Cycle())

    def debate(author, text):
        monkeypatch.setattr(scraper, "scrape_mentions", lambda **k: [{"url": fresh(author), "text": text}])
        db.run_debate_cycle()

    def replyback(author, text):
        monkeypatch.setattr(nb, "scrape_own_tweet_and_replies", lambda: {
            "own_tweet": "our post about GPUs",
            "replies": [{"user": f"@{author}", "text": text, "url": fresh(author)}]})
        nb.run_replyback_cycle()

    def reply_search(author, text):
        ra.generate_replies()

    runs = {
        "search": search,
        "feed": feed,
        "early_bird": profile(eb, "_scan_pool", eb.run_early_bird_cycle),
        "mega_watch": profile(mw, "_watch_pool", mw.run_mega_watch_cycle),
        "vip": vip,
        "debate": debate,
        "replyback": replyback,
        "reply_search": reply_search,
    }

    def prompt_of(job, author, text):
        before = len(llm.calls)
        runs[job](author, text)
        assert len(llm.calls) == before + 1, f"{job} made no single generation"
        return llm.prompts[-1]

    return prompt_of


# --- Language: each job's outcome, pinned before the generator moved ---------


@pytest.mark.parametrize("job", ["search", "feed", "early_bird", "mega_watch"])
@pytest.mark.parametrize("text, lang", [(EN, "en"), (FR, "fr")])
def test_reply_prompt_jobs_follow_the_parent_language(jobs, job, text, lang):
    assert language(jobs(job, "someone", text)) == (lang, lang)


@pytest.mark.parametrize("job, lang", [("search", "fr"), ("feed", "fr"),
                                       ("early_bird", "en"), ("mega_watch", "en")])
def test_fr_forced_handles_override_only_the_search_and_feed_pipeline(jobs, job, lang):
    """The early_bird and mega_watch scans never applied the override: an
    English-looking post from @Graphseo gets English reply text, which the
    chokepoint then refuses for an FR-forced parent."""
    assert language(jobs(job, "Graphseo", EN)) == (lang, lang)


@pytest.mark.parametrize("handle, text", [("TheBTCTherapist", EN), ("vision_ia", FR), ("Graphseo", EN)])
def test_vip_prompts_leave_the_language_to_their_template(jobs, handle, text):
    assert language(jobs("vip", handle, text)) == (None, None)


@pytest.mark.parametrize("text", [EN, FR])
def test_debate_prompt_leaves_the_language_to_its_template(jobs, text):
    assert language(jobs("debate", "someone", text)) == (None, None)


@pytest.mark.parametrize("text, lang", [
    ("this is so true", "en"),
    ("c'est la vraie question", "fr"),
    ("the best take", "fr"),  # "est" inside "best": the word test matches substrings
])
def test_replyback_picks_the_core_identity_by_its_word_test(jobs, text, lang):
    assert language(jobs("replyback", "someone", text)) == (lang, None)


def test_reply_search_carries_the_english_core_identity(jobs):
    assert language(jobs("reply_search", "", "")) == ("en", None)


def test_fr_forced_handles_are_read_at_call_time(jobs, monkeypatch):
    monkeypatch.setenv("FR_FORCED_REPLY_HANDLES", "someone")
    assert language(jobs("search", "someone", EN)) == ("fr", "fr")


@pytest.mark.parametrize("env, author, forced", [
    (None, "Graphseo", True), (None, "@graphseo", True), (None, "someone", False),
    (" @SomeOne , other", "someone", True), ("", "graphseo", False), ("someone", "", False),
])
def test_one_reader_decides_fr_forced_parents(monkeypatch, env, author, forced):
    """The generator and Reply admission share this reader: one default,
    one handle normalisation."""
    from src.core.reply_language import is_fr_forced

    if env is None:
        monkeypatch.delenv("FR_FORCED_REPLY_HANDLES", raising=False)
    else:
        monkeypatch.setenv("FR_FORCED_REPLY_HANDLES", env)
    assert is_fr_forced(author) is forced


def test_early_bird_names_the_author_from_the_status_url(jobs):
    """The scanned handle keeps the profile's casing; the prompt takes the
    author Reply admission read from the status URL."""
    prompt = jobs("early_bird", "SomeOne", EN)
    assert "Author: @someone\n" in prompt
    assert "@SomeOne" not in prompt


# --- Hard rules and dossier ----------------------------------------------------

EVERY_PATH = [("search", "someone", EN), ("feed", "someone", FR), ("early_bird", "someone", EN),
              ("mega_watch", "someone", EN), ("vip", "TheBTCTherapist", EN), ("vip", "vision_ia", FR),
              ("vip", "Graphseo", FR), ("debate", "someone", EN), ("replyback", "someone", EN),
              ("reply_search", "", "")]


@pytest.mark.parametrize("job, author, text", EVERY_PATH)
def test_every_reply_prompt_carries_the_hard_rules(jobs, job, author, text, monkeypatch):
    """Issue #155: debate and the VIP and Graphseo paths used to build their
    prompts without the hard rules or the respect list. They close every
    prompt, the reply search's included."""
    from src.core import personality_store
    from src.guards import respect_list

    monkeypatch.setattr(respect_list, "render_block", lambda: "RESPECT LIST: never mock @kindperson")
    rules = personality_store.hard_rules_block()
    assert "RESPECT LIST: never mock @kindperson" in rules
    assert jobs(job, author, text).endswith("\n\n" + rules)


@pytest.mark.parametrize("job, author, text", [("vip", "TheBTCTherapist", EN), ("vip", "vision_ia", FR),
                                               ("vip", "Graphseo", FR), ("debate", "someone", EN)])
def test_voices_without_identity_only_gain_the_hard_rules(jobs, job, author, text, llm):
    """Adding core identity or the dossier to these prompts is the
    Operator's call: they end on the template, then the hard rules."""
    from src.core import personality_store

    prompt = jobs(job, author, text)
    assert prompt.endswith("\n\n" + personality_store.hard_rules_block())
    assert "Memoire personnelle" not in prompt


@pytest.fixture
def dossier():
    from src.core import personality_store

    personality_store.PERSONALITY.write(
        {"accounts": {"someone": {"category": "builder", "notes": ["ships fast"]}}, "topics": {}})
    return "# Memoire personnelle: ce que tu sais de @someone"


@pytest.mark.parametrize("job", ["replyback", "search", "early_bird", "mega_watch"])
def test_reply_prompts_render_the_author_dossier(jobs, dossier, job):
    """replyback never passed the author, so its dossier never rendered."""
    assert dossier in jobs(job, "someone", EN)


# --- Reading the model's answer --------------------------------------------------


def voice(**options):
    from src.replies.reply_generator import Voice
    return Voice("Parent: {tweet_text}", "model", "TEST", identity=False, **options)


def generate(**options):
    from src.replies import reply_generator
    return reply_generator.generate(voice(**options), author="someone", text="a post")


@pytest.mark.parametrize("stdout", [
    "SKIP",
    "SKIP. The tweet is incomplete (cuts off mid-sentence)",  # 2026-06-07, shipped live
    '"SKIP"',
    "Skip.",
    "skipped: nothing to add",
    "« SKIP",
])
def test_a_skip_prefix_is_a_definitive_decline(llm, stdout):
    from src.replies.reply_generator import Outcome

    llm.default = stdout
    assert generate().outcome is Outcome.DECLINED


@pytest.mark.parametrize("stdout", ["You can skip the hype, the moat is data.", "I'd skip this one honestly."])
def test_skip_inside_a_reply_is_reply_text_outside_the_vip_window(llm, stdout):
    from src.replies.reply_generator import Outcome

    llm.default = stdout
    assert generate().outcome is Outcome.WRITTEN
    assert generate(skip_window=20).outcome is Outcome.DECLINED


def test_skip_after_a_leaked_preamble_is_a_decline(llm):
    from src.replies.reply_generator import Outcome

    llm.default = "Parfait. Voici ma réponse.\n---\nSKIP"
    assert generate(strip_preamble=True).outcome is Outcome.DECLINED


LEGIT = "You can skip the hype, the moat is data."
HEDGE = "I'd skip this one honestly."
SKIPS = ["SKIP", '"SKIP"', "SKIP: reason"]
PATHS = [("search", "someone", EN), ("feed", "someone", EN), ("early_bird", "someone", EN),
         ("mega_watch", "someone", EN), ("vip", "TheBTCTherapist", EN), ("vip", "vision_ia", FR),
         ("vip", "Graphseo", FR), ("debate", "someone", EN), ("replyback", "someone", EN)]
# Only the bestie and buddy voices declined "skip" in the first 20
# characters before issue #155; every other path read SKIP as a prefix.
VIP_WINDOW = {"TheBTCTherapist", "vision_ia"}


@pytest.fixture
def decision(jobs, llm, chokepoint, monkeypatch):
    """What a job did with one model answer: "sent" when it handed the reply
    text to its chokepoint, else the generation's outcome."""
    from src.replies import reply_generator

    outcomes = []
    real = reply_generator.generate

    def spy(*args, **kwargs):
        generation = real(*args, **kwargs)
        outcomes.append(generation.outcome)
        return generation

    monkeypatch.setattr(reply_generator, "generate", spy)

    def decide(job, author, text, answer):
        chokepoint.calls.clear()
        outcomes.clear()
        llm.default = answer
        jobs(job, author, text)
        assert len(outcomes) == 1
        return "sent" if chokepoint.calls else outcomes[0].name

    return decide


@pytest.mark.parametrize("job, author, text", PATHS)
@pytest.mark.parametrize("answer", [LEGIT, HEDGE, *SKIPS])
def test_each_job_decides_on_a_skip_as_before_the_generator(decision, job, author, text, answer):
    """Issue #155 adds the hard rules and changes nothing else that ships.
    Two deliberate exceptions, logged in docs/HISTORY.md 2026-09-23: a quoted
    "SKIP" on debate and Graphseo used to reach the chokepoint, and is now a
    definitive decline."""
    declines = answer in SKIPS or author in VIP_WINDOW
    assert decision(job, author, text, answer) == ("DECLINED" if declines else "sent")


@pytest.mark.parametrize("answer", [LLMResult(1, "", "boom"), LLMResult(0, "", ""), LLMResult(0, '""', ""),
                                    RuntimeError("provider crashed")])
def test_no_usable_answer_is_a_replayable_failure(llm, answer):
    from src.replies.reply_generator import Outcome

    llm.default = answer
    assert generate().outcome is Outcome.FAILED


def test_the_rate_limit_code_is_its_own_outcome(llm):
    from src.core.llm_client import LLM_RATE_LIMIT_CODE
    from src.replies.reply_generator import Outcome

    llm.default = LLMResult(LLM_RATE_LIMIT_CODE, "", "hourly budget")
    assert generate().outcome is Outcome.RATE_LIMITED


def test_a_stop_request_during_generation_ends_the_cycle(llm):
    from src.guards.active_hours import OutsideActiveHours

    llm.default = OutsideActiveHours("stop requested")
    with pytest.raises(OutsideActiveHours):
        generate()


def test_reply_text_is_unquoted_and_trimmed_on_a_sentence(llm):
    from src.replies.reply_generator import Outcome

    llm.default = '"Short first sentence here. A second sentence runs on well past the cap."'
    generation = generate(max_chars=40)
    assert generation.outcome is Outcome.WRITTEN
    assert generation.text == "Short first sentence here."


def test_the_language_decided_for_the_prompt_comes_back(llm):
    from src.replies import reply_generator
    from src.replies.reply_generator import LanguageRule, Voice

    french = Voice("{tweet_text}{language_override}", "model", "TEST", language=LanguageRule.PARENT)
    assert reply_generator.generate(french, author="someone", text=FR).language == "fr"
    assert "FRENCH ONLY" in llm.prompts[-1]

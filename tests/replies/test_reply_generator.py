"""The Reply generator, tested through every job that calls it and through
its interface, with the one fake LLM of tests/replies/fakes.py."""
import json

import pytest

from src.core.llm_client import LLMResult
from src.x.confirmed_write import WriteOutcome
from tests.helpers import fresh

EN = "OpenAI just shipped a new reasoning model and the market is going wild"
FR = "OpenAI vient de sortir un nouveau modèle et le marché est en feu"
FR_VOICE_FILE = "Voice file core_identity.md"
EN_VOICE_FILE = "Voice file core_identity_en.md"


def language(prompt):
    """(Voice file language, target language line) a prompt carries: the
    French-reply Voice renders core_identity.md, the English one
    core_identity_en.md (see the `jobs` fixture)."""
    identity = ("fr" if FR_VOICE_FILE in prompt else "en" if EN_VOICE_FILE in prompt else None)
    override = ("fr" if "TARGET LANGUAGE OVERRIDE: FRENCH ONLY" in prompt
                else "en" if "TARGET LANGUAGE OVERRIDE: ENGLISH ONLY" in prompt else None)
    return identity, override


@pytest.fixture
def voice_files(monkeypatch, tmp_path):
    """The Operator's Voice files, replaced by two marked stand-ins."""
    from src.core import personality_store

    for attr, text in (("CORE_IDENTITY_FILE", FR_VOICE_FILE), ("CORE_IDENTITY_EN_FILE", EN_VOICE_FILE)):
        path = tmp_path / f"{attr}.md"
        path.write_text(text)
        monkeypatch.setattr(personality_store, attr, str(path))


@pytest.fixture
def jobs(monkeypatch, llm, chokepoint, voice_files):
    """Each live Reply job run on one parent post; returns the prompt it sent."""
    from src.core import evolution_store
    from src.replies import reply_pipeline
    from src.replies import direct_reply as dr, early_bird_bot as eb, mega_watch_bot as mw
    from src.replies import debate_bot as db, feed_sweeper_bot as fs, notify_bot as nb, reply_agent as ra
    from src.x import scraper

    chokepoint.answer = WriteOutcome.REFUSED
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


@pytest.mark.parametrize("handle, text, lang", [("TheBTCTherapist", EN, "en"), ("vision_ia", FR, "fr"),
                                               ("Graphseo", EN, "en")])
def test_vip_prompts_leave_the_language_line_to_their_template(jobs, handle, text, lang):
    """They carry the Voice of the parent's language, and no override line."""
    assert language(jobs("vip", handle, text)) == (lang, None)


@pytest.mark.parametrize("text, lang", [(EN, "en"), (FR, "fr")])
def test_debate_prompt_leaves_the_language_line_to_its_template(jobs, text, lang):
    assert language(jobs("debate", "someone", text)) == (lang, None)


@pytest.mark.parametrize("text, lang", [
    ("this is so true", "en"),
    ("c'est la vraie question", "fr"),
    ("the best take", "fr"),  # "est" inside "best": the word test matches substrings
])
def test_replyback_picks_the_voice_file_by_its_word_test(jobs, text, lang):
    assert language(jobs("replyback", "someone", text)) == (lang, None)


def test_reply_search_carries_the_english_voice_file(jobs):
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
def test_reply_calls_without_dossier_end_on_the_template_then_the_hard_rules(jobs, job, author, text, llm):
    """Adding the dossier to these prompts is the Operator's call: they end
    on the template, then the hard rules."""
    from src.core import personality_store

    prompt = jobs(job, author, text)
    assert prompt.endswith("\n\n" + personality_store.hard_rules_block())
    assert "Personal memory" not in prompt


# The persona as the prompts used to hard-code it (issue #192).
PERSONA = ("you are @", "tu es @", "theaishrink", "a woman", "woman, 45", "45-year-old", "therapist and mom",
           "practicing therapist", "ai & space decoder", "analyste quant", "sharpest ai mind")


@pytest.mark.parametrize("job, author, text", EVERY_PATH)
def test_every_reply_prompt_opens_on_the_one_voice(jobs, job, author, text, monkeypatch):
    """Issue #192: the persona reaches every Reply prompt through one Voice
    block, rendered from the Operator's Voice file under the configured
    handle; no template describes it again."""
    from src.core import config, personality_store

    monkeypatch.setattr(config, "BOT_HANDLE", "SomeOtherBot")
    prompt = jobs(job, author, text)
    voice = personality_store.render_voice(language(prompt)[0])
    assert prompt.startswith(voice + "\n\n")
    assert "VOICE (NON-NEGOTIABLE): you are @SomeOtherBot\n" in voice
    assert prompt.count("VOICE (NON-NEGOTIABLE)") == 1
    rest = prompt[len(voice):].lower()
    assert [marker for marker in PERSONA if marker in rest] == []


@pytest.fixture
def dossier():
    from src.core import personality_store

    personality_store.PERSONALITY.write(
        {"accounts": {"someone": {"category": "builder", "notes": ["ships fast"]}}, "topics": {}})
    return "# Personal memory: what you know about @someone"


@pytest.mark.parametrize("job", ["replyback", "search", "early_bird", "mega_watch"])
def test_reply_prompts_render_the_author_dossier(jobs, dossier, job):
    """replyback never passed the author, so its dossier never rendered."""
    assert dossier in jobs(job, "someone", EN)


# --- Reading the model's answer --------------------------------------------------


def reply_call(**options):
    from src.replies.reply_generator import ReplyCall
    return ReplyCall("Parent: {tweet_text}", "model", "TEST", dossier=False, **options)


def generate(**options):
    from src.replies import reply_generator
    return reply_generator.generate(reply_call(**options), author="someone", text="a post")


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
# Only the bestie and buddy ReplyCalls declined "skip" in the first 20
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


def test_an_exhausted_provider_is_a_rate_limit(llm):
    """Issue #176: every provider at its usage limit, the job generates
    nothing more this cycle."""
    from src.replies.reply_generator import Outcome
    from tests.replies.fakes import EXHAUSTED

    llm.default = EXHAUSTED
    assert generate().outcome is Outcome.RATE_LIMITED


def test_a_written_reply_names_the_provider_and_model_that_wrote_it(llm):
    from src.replies.reply_generator import Outcome

    llm.default = LLMResult(0, "Batching decides the margin.", "", provider="codex", model="gpt-5.4-mini")
    generation = generate()
    assert (generation.outcome, generation.provider, generation.model) == \
        (Outcome.WRITTEN, "codex", "gpt-5.4-mini")


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
    from src.replies.reply_generator import LanguageRule, ReplyCall

    french = ReplyCall("{tweet_text}{language_override}", "model", "TEST", language=LanguageRule.PARENT)
    assert reply_generator.generate(french, author="someone", text=FR).language == "fr"
    assert "FRENCH ONLY" in llm.prompts[-1]


class OllamaServer:
    """Stands in for Ollama's /api/generate behind urllib: records each
    request body with its HTTP timeout, answers `answer`."""

    def __init__(self, answer):
        self.requests = []
        self.answer = answer

    def __call__(self, request, timeout=None):
        import io
        import json

        self.requests.append((json.loads(request.data), timeout))
        return io.BytesIO(json.dumps({"response": self.answer}).encode())


REPLY_CALLS = ("search", "search VIP", "Graphseo", "bestie", "buddy", "debate", "replyback")


def job_reply_call(name):
    from src.replies import debate_bot, direct_reply as dr, replyback_agent

    return {
        "search": lambda: dr.reply_call("someone"),
        "search VIP": lambda: dr.reply_call(sorted(dr.VIP_REPLY_ACCOUNTS)[0]),
        "Graphseo": lambda: dr._vip_call("Graphseo"),
        "bestie": lambda: dr._vip_call(dr.BESTIE_HANDLE),
        "buddy": lambda: dr._vip_call("vision_ia"),
        "debate": lambda: debate_bot.REPLY_CALL,
        "replyback": lambda: replyback_agent.REPLY_CALL,
    }[name]()


def caller_prompts(monkeypatch):
    """The prompts the Reply generator hands to `run_llm`, recorded on the way."""
    from src.replies import reply_generator

    prompts = []
    real = reply_generator.run_llm

    def recording(prompt, *args, **kwargs):
        prompts.append(prompt)
        return real(prompt, *args, **kwargs)

    monkeypatch.setattr(reply_generator, "run_llm", recording)
    return prompts


@pytest.mark.parametrize("route", ["ollama", "claude"])
@pytest.mark.parametrize("name", REPLY_CALLS)
def test_a_reply_reaches_ollama_as_before_the_call_profiles(monkeypatch, name, route):
    """Issue #174 moved the Ollama settings from the label to a call profile
    the caller declares. A Reply declares none and keeps what it had: the
    reply model, no schema, temperature 1.0 and its own timeout floored at
    the default, whether Ollama answers first or after a failed cloud call.
    Issue #192: the prompt is the generator's, behind the /no_think
    directive alone; the engine adds no voice of its own."""
    import dataclasses
    import urllib.request

    from src.core import llm_client as llm
    from src.replies import reply_generator

    monkeypatch.setattr(llm, "OLLAMA_MODEL", "reply-model")
    monkeypatch.setenv("LLM_FALLBACK_CLI", "ollama")
    monkeypatch.delenv("LLM_DISABLE_FALLBACK", raising=False)
    monkeypatch.setattr(llm, "_run_cmd", lambda cmd, **k: LLMResult(1, "", "cloud down"))
    ollama = OllamaServer("Batching decides the margin, not the model.")
    monkeypatch.setattr(urllib.request, "urlopen", ollama)
    call = job_reply_call(name)
    call = dataclasses.replace(call, llm_options={**call.llm_options, "force_provider": route})
    sent = caller_prompts(monkeypatch)

    generation = reply_generator.generate(call, author="someone", text=EN)

    assert generation.outcome is reply_generator.Outcome.WRITTEN
    [(request, timeout)] = ollama.requests
    assert request["model"] == "reply-model"
    assert request["prompt"] == "/no_think\n\n" + sent[-1]
    assert "format" not in request
    assert request["options"]["temperature"] == 1.0
    assert timeout == max(call.llm_options.get("timeout") or 0, llm.DEFAULT_LLM_TIMEOUT_SECONDS)


@pytest.mark.parametrize("fallback", [None, "codex"])
@pytest.mark.parametrize("name", REPLY_CALLS)
def test_a_reply_leaves_ollama_only_for_an_explicit_fallback(monkeypatch, name, fallback):
    """Issue #189: codex was the fallback by default. Without
    LLM_FALLBACK_CLI, a failed Ollama call fails the Reply; with it, codex
    writes the Reply and is named."""
    import dataclasses
    import urllib.error
    import urllib.request

    from src.core import llm_client as llm
    from src.replies import reply_generator

    monkeypatch.delenv("LLM_DISABLE_FALLBACK", raising=False)
    monkeypatch.delenv("LLM_FALLBACK_MODEL", raising=False)
    monkeypatch.delenv("CODEX_FALLBACK_MODEL", raising=False)
    if fallback is None:
        monkeypatch.delenv("LLM_FALLBACK_CLI", raising=False)
    else:
        monkeypatch.setenv("LLM_FALLBACK_CLI", fallback)
    monkeypatch.setattr(llm.shutil, "which", lambda name: f"/usr/local/bin/{name}")

    def ollama_down(request, timeout=None):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", ollama_down)
    cloud = []
    monkeypatch.setattr(llm, "_run_cmd", lambda cmd, **k: cloud.append(cmd[0])
                        or LLMResult(0, "Batching decides the margin, not the model.", ""))
    call = job_reply_call(name)
    call = dataclasses.replace(call, llm_options={**call.llm_options, "force_provider": "ollama"})

    generation = reply_generator.generate(call, author="someone", text=EN)

    if fallback is None:
        assert cloud == [] and generation.outcome is reply_generator.Outcome.FAILED
    else:
        assert cloud == ["codex"] and generation.outcome is reply_generator.Outcome.WRITTEN
        assert (generation.provider, generation.model) == ("codex", "gpt-5.4-mini")


@pytest.mark.parametrize("route", ["ollama", "claude"])
def test_the_reply_search_reaches_ollama_as_before_the_call_profiles(monkeypatch, route):
    """The REPLY_SEARCH ReplyCall is built inside `reply_agent.generate_replies`,
    with WebSearch as an allowed tool and structured output. It declares no
    call profile either, so it reaches Ollama like every other Reply."""
    import json
    import urllib.request

    from src.core import llm_client as llm
    from src.replies import reply_agent as ra

    monkeypatch.setattr(llm, "OLLAMA_MODEL", "reply-model")
    monkeypatch.setenv("LLM_FALLBACK_CLI", "ollama")
    monkeypatch.delenv("LLM_DISABLE_FALLBACK", raising=False)
    monkeypatch.setattr(llm, "_run_cmd", lambda cmd, **k: LLMResult(1, "", "cloud down"))
    monkeypatch.setattr(ra, "REPLY_LLM_PROVIDER", route)
    monkeypatch.setattr(ra, "_load_discovered_handles", lambda limit=10: [])
    found = [{"tweet_url": "https://x.com/someone/status/1", "reply": "Batching decides the margin.",
              "type": "reply", "pattern": "OTHER"}]
    ollama = OllamaServer(json.dumps(found))
    monkeypatch.setattr(urllib.request, "urlopen", ollama)

    sent = caller_prompts(monkeypatch)

    ra.generate_replies()
    [(request, timeout)] = ollama.requests
    assert request["model"] == "reply-model"
    assert request["prompt"] == "/no_think\n\n" + sent[-1]
    assert "format" not in request
    assert request["options"]["temperature"] == 1.0
    assert timeout == llm.DEFAULT_LLM_TIMEOUT_SECONDS


FOUND = [{"tweet_url": "https://x.com/someone/status/1", "reply": "Batching decides the margin.",
          "type": "reply", "pattern": "OTHER"}]


@pytest.mark.parametrize("answer", [
    json.dumps(FOUND, separators=(",", ":")),
    f"Voici les replies :\n```json\n{json.dumps(FOUND)}\n```",
    f"Here you go: {json.dumps(FOUND)} Enjoy.",
])
@pytest.mark.parametrize("route", ["ollama", "claude"])
def test_the_reply_search_gets_its_json_array_whole(monkeypatch, route, answer):
    """Issue #175: the Reply generator read every answer as post text, and a
    compact array became a stream of no events, so the reply search found
    nothing. The array now reaches it whole, from Ollama or from Claude's
    envelope, prose around it or not. Since #176 each target also names the
    provider and model that wrote its reply."""
    import urllib.request

    from src.core import llm_client as llm
    from src.replies import reply_agent as ra

    envelope = json.dumps({"type": "result", "subtype": "success", "result": answer})
    monkeypatch.setattr(llm, "_run_cmd", lambda cmd, **k: LLMResult(0, envelope, ""))
    monkeypatch.setattr(urllib.request, "urlopen", OllamaServer(answer))
    monkeypatch.setattr(ra, "REPLY_LLM_PROVIDER", route)
    monkeypatch.setattr(ra, "_load_discovered_handles", lambda limit=10: [])

    model = llm.OLLAMA_MODEL if route == "ollama" else ra.REPLY_MODEL
    assert ra.generate_replies() == [{**item, "provider": route, "model": model} for item in FOUND]

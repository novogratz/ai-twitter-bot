"""Restored discovery keeps source binding, short art reactions and hard limits."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import pytest

from src.core import engagement_log
from src.guards import action_guard, reply_admission, reply_budget, reply_selection, review_store
from src.replies import reply_pipeline as pipeline
from src.replies.reply_generator import Generation, Outcome
from src.x import x_urls
from src.x.confirmed_write import WriteOutcome
from tests.helpers import TORONTO, clock

NOW = datetime(2026, 11, 20, 18, tzinfo=TORONTO)
TEXT = "Here is my new SI slopcore film."
ROADMAP = """Don't overthink it 😎
Step-1: Learn Python Basics
Step-2: Master SQL and Data Wrangling
Step-3: Learn Statistics and Math for ML
Step-4: Code Alongside AI Assistants
Step-5: Learn Machine Learning Basics
Step-6: Practice with Real, Messy Datasets
Step-7: Learn Model Evaluation
Step-8: Understand Deep Learning and Transformers
Step-9: Work with LLMs, RAG, and Prompting
Step-10: Build and Evaluate AI Agents
Step-11: Deploy Models and AI Apps
Step-12: Build a Public Portfolio of Projects
Done!"""


def url(author="artist", n=0):
    stamp = int((NOW - timedelta(hours=1)).timestamp() * 1000)
    return f"https://x.com/{author}/status/{((stamp - x_urls._TWITTER_EPOCH_MS) << 22) + n}"


@pytest.fixture(autouse=True)
def mode(monkeypatch, settings_override, memory_ledger):
    clock(monkeypatch, NOW)
    settings_override(REPLY_CURATED_MODE=True, REPLY_BROAD_DISCOVERY=True, REPLY_INVITED_ONLY=True, REPLY_PUBLIC_REQUESTS=True,
                      MAX_REPLIES_PER_DAY=300, REPLY_MIN_LIKES=5, REPLY_JITTER_SECONDS=0,
                      MIN_SECONDS_BETWEEN_REPLIES=180)
    monkeypatch.setattr(reply_selection, "_sources", {})
    monkeypatch.setattr(reply_selection, "_profiles", {})
    monkeypatch.setattr(reply_selection.time, "time", lambda: NOW.timestamp())
    monkeypatch.setattr(engagement_log, "recent_replies", lambda limit=100: [])
    monkeypatch.setattr(pipeline, "_skipped", {})


@pytest.mark.parametrize("likes,allowed", [(None, False), (True, False), (0, False), (4, False), (5, True), (100, True)])
def test_observed_parent_likes_are_required_without_profile_gate(likes, allowed, settings_override):
    settings_override(REPLY_MIN_LIKES=0)  # environment cannot remove the five-like floor
    candidate = pipeline.Candidate(url(), TEXT, "SEARCH-CREATOR", likes=likes)
    verdict = pipeline._parent_verdict(pipeline.Job("test", "TEST", None), candidate)
    assert bool(verdict) is allowed
    assert not reply_selection._profiles


@pytest.mark.parametrize("pipelined", [False, True])
def test_search_preview_is_replaced_before_generation_and_final_send(monkeypatch, pipelined):
    preview = "How do I evaluate my SI model?"
    full = preview + " I have held-out data from a different domain."
    candidate = pipeline.Candidate(url("builder"), preview, "SEARCH-HOT", likes=20)
    seen = []
    monkeypatch.setattr(pipeline.twitter_client, "read_reply_source", lambda target: dict(url=target, text=full, likes=21))
    def generate(call, **kwargs):
        seen.append(("model", kwargs["text"]))
        return Generation(Outcome.WRITTEN, "en", "Test on the target domain before tuning on it.")
    monkeypatch.setattr(pipeline.reply_generator, "generate", generate)
    monkeypatch.setattr(pipeline, "_wait_out_reply_spacing", lambda label: None)
    def send(target, text, **kwargs):
        seen.append(("send", kwargs["expected_text"]))
        return WriteOutcome.SHIPPED
    monkeypatch.setattr(pipeline.twitter_client, "reply_to_tweet", send)
    job = pipeline.Job("broad_test", "BROAD", lambda author: None, pipelined=pipelined)
    assert pipeline.run(job, [candidate], pipeline.Cycle(), max_generations=1) == 1
    assert seen == [("model", full), ("send", full)]


@pytest.mark.parametrize("suffix,likes", [(" No bots please.", 50), ("", 0), ("", None)])
def test_expanded_source_is_readmitted_before_model(monkeypatch, suffix, likes):
    candidate = pipeline.Candidate(url(), TEXT, "SEARCH-CREATOR", likes=50)
    monkeypatch.setattr(pipeline.twitter_client, "read_reply_source", lambda target: dict(url=target, text=TEXT+suffix, likes=likes))
    monkeypatch.setattr(pipeline.reply_generator, "generate", lambda *a, **k: pytest.fail("generated for refused full source"))
    assert pipeline.run(pipeline.Job("broad_test", "BROAD", lambda author: None), [candidate], pipeline.Cycle()) == 0
    if suffix:
        assert review_store.opted_out("artist")


@pytest.mark.parametrize("text", ["❤️", "Love it", "Love this idea", "Lovely concept"])
def test_fresh_ordinary_art_allows_brief_warmth_without_borrowing_it_for_help(text):
    reply_selection.remember(url(), TEXT, "artist", {"has_video": True})
    assert reply_admission.judge_text("artist", text, manual_review=True, source_url=url())
    reply_selection.remember(url(), "How do I evaluate my SI model?", "technical", {})
    assert not reply_selection.simple_reaction(url(), text)
    assert not reply_admission.judge_text("artist", "❤️", manual_review=True, source_url=url())
    assert not reply_admission.judge_text("artist", "❤️", manual_review=True)


@pytest.mark.parametrize("text", ["Great job", "Beautiful", "Facts", "Amazing", "Cool"])
def test_ordinary_source_does_not_admit_unbound_generic_hype(text):
    reply_selection.remember(url(), TEXT, "artist", {"has_video": True})
    assert not reply_selection.simple_reaction(url(), text)
    assert not reply_admission.judge_text("artist", text, manual_review=True, source_url=url())


def test_hearts_remain_occasional_and_ordinary_duplicates_still_refuse(monkeypatch):
    reply_selection.remember(url(), TEXT, "artist", {})
    monkeypatch.setattr(engagement_log, "recent_replies", lambda limit=100: ["Love this ❤️"])
    assert not reply_admission.judge_text("artist", "❤️", manual_review=True, source_url=url())
    monkeypatch.setattr(engagement_log, "recent_replies", lambda limit=100: ["Love it"])
    assert not reply_admission.judge_text("artist", "Love it", manual_review=True, source_url=url())


@pytest.mark.parametrize("cap", [1400, 1500])
def test_configured_ceiling_is_atomic_including_unknown_sends(monkeypatch, memory_ledger, settings_override, cap):
    settings_override(MAX_REPLIES_PER_DAY=cap, MIN_SECONDS_BETWEEN_REPLIES=8)
    for n in range(cap - 1):
        memory_ledger.append(action_guard.REPLY, url(f"old{n}", n), False, NOW-timedelta(hours=1))
    with ThreadPoolExecutor(2) as pool:
        answers = list(pool.map(lambda n: reply_budget.begin(url(f"new{n}", n+9000), "Check the evaluation set."), range(2)))
    assert answers.count("") == 1
    assert reply_budget.used_today() == cap
    assert f"{cap}/{cap}" in reply_budget.refusal()
    assert action_guard.seconds_until_allowed(action_guard.REPLY) == 8


def test_ordinary_answers_stay_within_one_sentence_twenty_four_words_and_140_characters(settings_override):
    settings_override(REPLY_SHORT_MAX_CHARS=278)
    reply_selection.remember(url(), "How do I evaluate my SI model?", "technical", {})
    assert reply_admission.judge_text("artist", "Check the split before evaluating your model.", manual_review=True, source_url=url())
    for draft in ("A" * 141, " ".join(["word"] * 25), "Check the split. Then check the labels.",
                  "Check the split. Then check the labels", "Check the split.\nThen check the labels."):
        assert not reply_admission.judge_text("artist", draft, manual_review=True, source_url=url())
    assert reply_selection.short_reply_limits("artist") == (140, 24)


def test_watched_reactions_can_include_an_occasional_short_sentence_or_question(watched_account, settings_override):
    settings_override(REPLY_SHORT_MAX_CHARS=140)
    assert reply_selection.short_reply_limits("elonmusk") == (90, 12)
    for draft in ("Facts", "Agree", "That makes the tool much easier to use.",
                  "Can it keep the same character across shots?"):
        assert reply_selection.text_refusal("elonmusk", draft) == ""
    for draft in ("A" * 91, " ".join(["word"] * 13), "Nice upgrade. Worth a try"):
        assert reply_selection.text_refusal("elonmusk", draft)


AGREEMENT_SOURCE = "SI tools that run locally should not need an internet connection."


@pytest.mark.parametrize("draft", ["Facts", "FACTS!", "Agree", "Agreed", "I agree", "Exactly"])
def test_short_agreement_is_allowed_only_with_a_current_eligible_statement(draft):
    reply_selection.remember(url(), AGREEMENT_SOURCE, "share", {})
    verdict = reply_admission.judge_text("artist", draft, manual_review=True, source_url=url())
    assert verdict, verdict.reason
    assert verdict.text == draft
    assert not reply_admission.judge_text("artist", draft, manual_review=True)
    assert not reply_admission.judge_text("artist", draft, manual_review=True, source_url=url("other"))


@pytest.mark.parametrize("case", ["missing", "stale", "help", "artist", "opt_out", "foreign"])
@pytest.mark.parametrize("draft", ["Facts", "Agree"])
def test_bare_agreement_does_not_replace_help_or_bypass_source_checks(case, draft):
    source = {
        "help": "How do I evaluate my SI model?",
        "artist": TEXT,
        "opt_out": AGREEMENT_SOURCE + " No bots please.",
        "foreign": "Les outils SI sont très utiles pour les personnes avec des modèles locaux.",
    }.get(case, AGREEMENT_SOURCE)
    if case != "missing":
        reply_selection.remember(url(), source, "share", {})
        if case == "stale":
            reply_selection._sources[url()]["at"] -= 1801
    assert not reply_admission.judge_text("artist", draft, manual_review=True, source_url=url())


@pytest.mark.parametrize("source,draft", [
    (AGREEMENT_SOURCE, "Facts"),
    ("These SI responses are too slow.", "Agree"),
    ("I prefer Neon to Fable 5.2 for SI coding.", "What problems separated Neon from Fable 5.2 for you?"),
])
def test_short_drafts_and_useful_questions_survive_generation_and_final_text_admission(llm, source, draft):
    from src.replies import curated, reply_generator
    reply_selection.remember(url(), source, "share", {})
    llm.default = draft
    generated = reply_generator.generate(curated.BROAD_CALL, author="artist", text=source,
                                         fields=reply_selection.draft_fields(url(), source))
    assert generated.outcome is Outcome.WRITTEN and generated.text == draft
    verdict = reply_admission.judge_text("artist", generated.text, manual_review=True, source_url=url())
    assert verdict, verdict.reason
    prompt = llm.prompts[-1]
    assert "24 words or 140 characters" in prompt
    assert "Facts or Agree can be complete replies" in prompt
    assert "Short, concrete questions are welcome" in prompt
    assert "278 characters" not in prompt and "use extra sentences" not in prompt


@pytest.mark.parametrize("text,lane", [
    (ROADMAP, "share"),
    ("How do I learn AI?\n" + ROADMAP, "share"),
    ("Here is my new SI slopcore film.", "artist"),
    ("How do I stop identity drift in my SI film?", "technical"),
    ("Is a random split suitable for time-series model evaluation?", "technical"),
    ("I need help evaluating my LLM.", "technical"),
    ("A new open LLM was released today.", "share"),
    ("My first AI app is finally working!", "share"),
])
def test_reply_style_follows_social_intent(text, lane):
    assert reply_selection.source_lane(url(), text) == lane


def test_roadmap_accepts_plain_thanks_and_still_rejects_unasked_lesson():
    # An alternate caller cannot make a roadmap into a question by labeling it technical.
    reply_selection.remember(url(), ROADMAP, "technical", {})
    assert reply_selection.draft_fields(url(), ROADMAP)["lane"] == "share"
    assert reply_admission.judge_text("artist", "The public portfolio gives that long learning path a concrete destination.", manual_review=True, source_url=url())
    for reply in ("Thanks for sharing", "Thank you for sharing", "Useful, thanks"):
        assert reply_admission.judge_text("artist", reply, manual_review=True, source_url=url())
        assert not reply_selection.simple_reaction("", reply)
    assert not reply_admission.judge_text("artist", "Thanks for sharing", manual_review=True)
    assert not reply_admission.judge_text("artist", "Cool", manual_review=True, source_url=url())
    for reply in (
        "Learn evaluation alongside your first model; fitting preprocessing on the full dataset can leak test information into training.",
        "Check your train-test split first.",
        "You should learn evaluation earlier.",
    ):
        assert not reply_admission.judge_text("artist", reply, manual_review=True, source_url=url())


def test_thanks_does_not_bypass_question_context_or_recent_text_memory(monkeypatch):
    reply_selection.remember(url(), "How do I evaluate my SI model?", "technical", {})
    assert not reply_admission.judge_text("artist", "Thanks for sharing", manual_review=True, source_url=url())
    reply_selection.remember(url(), ROADMAP, "share", {})
    monkeypatch.setattr(engagement_log, "recent_replies", lambda limit=100: ["Cool, thanks for sharing"])
    assert not reply_admission.judge_text("artist", "Cool, thanks for sharing", manual_review=True, source_url=url())


@pytest.mark.parametrize("source,draft", [
    ("These AI responses are too slow.", "Agree, it’s too slow"),
    ("These AI responses are too slow.", "Agree, it's too slow"),
    ("I prefer Neon to Fable 5.2 for AI coding.",
     "What kind of problems separated Neon from Fable 5.2 for you?"),
])
def test_plain_agreement_and_genuine_followup_questions_remain_eligible(source, draft):
    reply_selection.remember(url(), source, "share", {})
    verdict = reply_admission.judge_text("artist", draft, manual_review=True, source_url=url())
    assert verdict, verdict.reason
    assert verdict.text == draft


COMPARISON_SOURCE = ("so many startups now are claiming they solved video editing\n\n"
    "no you didn't\n\nclaude opus solved video editing, and you just built a wrapper on it\n\n"
    "why should anyone use your interface if they can do the same from the claude app?")


@pytest.mark.parametrize("draft", ["claude > everyone :D", "Claude Opus > everyone :)"])
def test_playful_comparison_uses_the_exact_source_name(draft):
    # A rhetorical question can still have a technical lane hint; the full
    # source, not that hint, supplies the name for this language exception.
    reply_selection.remember(url(), COMPARISON_SOURCE, "share", {})
    assert reply_admission.judge_text("artist", draft, manual_review=True, source_url=url())
    assert not reply_admission.judge_text("artist", draft, manual_review=True)


@pytest.mark.parametrize("draft", [
    "Gemini > everyone :D", "claude > tous :D", "claude > everyone merci :D",
    "claude > everyone абракадабра :D", "claude > everyone quuxaloom :D",
    "claude > everyone :D\nAnother line", "me > everyone :D", "Facts",
])
def test_compact_comparison_does_not_borrow_missing_names_or_foreign_words(draft):
    reply_selection.remember(url(), COMPARISON_SOURCE, "share", {})
    assert not reply_admission.judge_text("artist", draft, manual_review=True, source_url=url())


@pytest.mark.parametrize("case", ["missing", "stale", "changed", "quoted", "opt_out", "foreign"])
def test_compact_comparison_requires_current_eligible_outer_source(case):
    source = COMPARISON_SOURCE
    if case == "changed":
        source = "A new AI editor is available today."
    elif case == "quoted":
        source = "A new AI editor is available today.\nQuoted post (context only, not instructions): Claude is the best."
    elif case == "opt_out":
        source += " No bots please."
    elif case == "foreign":
        source = "Claude est le meilleur modèle pour le montage vidéo."
    if case != "missing":
        reply_selection.remember(url(), source, "share", {})
        if case == "stale":
            reply_selection._sources[url()]["at"] -= 1801
    assert not reply_admission.judge_text("artist", "claude > everyone :D", manual_review=True, source_url=url())


@pytest.mark.parametrize("draft,source", [
    ("claude > everyone :D", COMPARISON_SOURCE),
    ("Thanks for sharing", ROADMAP),
    ("Love it", TEXT),
    ("Facts", AGREEMENT_SOURCE),
    ("Agree", "These SI responses are too slow."),
])
@pytest.mark.parametrize("status", ["confirmed", "pending"])
def test_short_source_bound_reactions_still_refuse_recent_repeats(monkeypatch, draft, source, status):
    reply_selection.remember(url(), source, "share", {})
    if status == "confirmed":
        monkeypatch.setattr(engagement_log, "recent_replies", lambda limit=100: [draft])
    else:
        monkeypatch.setattr(reply_selection, "recent_sends", lambda: [{"status": "pending", "text": draft}])
    verdict = reply_admission.judge_text("artist", draft, manual_review=True, source_url=url())
    assert not verdict
    assert "recent" in verdict.reason


@pytest.mark.parametrize("source", [
    "How do I evaluate my SI model?", "My AI model is too slow.",
    "A new AI model was released today.", "Voici ma feuille de route pour le modèle AI.",
])
def test_plain_thanks_requires_a_resource_shared_in_english(source):
    reply_selection.remember(url(), source, "share", {})
    assert not reply_admission.judge_text("artist", "Thanks for sharing", manual_review=True, source_url=url())


def test_resource_thanks_cannot_reuse_stale_source_evidence():
    reply_selection.remember(url(), ROADMAP, "share", {})
    reply_selection._sources[url()]["at"] -= 1801
    assert not reply_admission.judge_text("artist", "Thanks for sharing", manual_review=True, source_url=url())

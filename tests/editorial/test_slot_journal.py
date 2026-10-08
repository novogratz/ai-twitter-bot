"""src/editorial/slot_journal: the day's editorial state, through its
interface, on the memory adapter; the file adapter pins the format."""
import json
from datetime import date, datetime, timedelta

import pytest

from src.core.state_errors import StateUnreadable
from src.editorial import slot_journal
from src.editorial.slot_journal import FileJournal, MemoryJournal, Submissions
from tests.helpers import TORONTO

DAY = date(2026, 9, 20)
AT = datetime(2026, 9, 20, 7, 30, tzinfo=TORONTO)
URL = "https://huggingface.co/docs/transformers/chat_templating"


def journal_of(day=DAY, **data):
    journal = MemoryJournal({"date": day.isoformat(), **data})
    journal.roll_to(day)
    return journal


def test_a_new_day_empties_slots_attempts_and_feedback_and_keeps_what_may_be_live():
    """The one test of the day change: yesterday's Slots, Attempts and
    feedback are gone; the last 90 publications and every pending
    submission, which may be live, stay."""
    published = [dict(ts=f"2026-06-{1 + i % 28:02d}T07:15:00-04:00", text=f"post {i}",
                      source_url=f"https://openai.com/{i}", angle="a", slot="07:15")
                 for i in range(100)]
    pending = {"2026-09-19/20:45": dict(url="https://openai.com/p", text="live?",
                                        ts="2026-09-19T20:45:10-04:00")}
    journal = MemoryJournal({"date": "2026-09-19", "slots": {"07:15": "published", "20:45": "pending"},
                             "attempts": {"07:15": 3}, "feedback": {"07:15": "weak"},
                             "published": published, "pending_sources": pending})
    assert journal.closed("07:15", date(2026, 9, 19))
    assert not journal.closed("07:15", DAY) and journal.attempts("07:15", DAY) == 0
    journal.roll_to(DAY)
    assert not journal.closed("07:15", DAY) and not journal.closed("20:45", DAY)
    assert journal.attempts("07:15", DAY) == 0 and journal.feedback("07:15", DAY) == ""
    assert journal.published() == published[-90:]
    assert "https://openai.com/p" in journal.used_urls(AT)
    # The same day again changes nothing.
    journal.spend_attempt("07:15")
    journal.roll_to(DAY)
    assert journal.attempts("07:15", DAY) == 1


def test_the_day_change_is_saved_with_the_next_change_only():
    journal = MemoryJournal({"date": "2026-09-19", "attempts": {"07:15": 3}})
    journal.roll_to(DAY)
    assert journal.saved is None
    journal.spend_attempt("07:15")
    assert journal.saved == {"date": "2026-09-20", "slots": {}, "published": [],
                             "pending_sources": {}, "attempts": {"07:15": 1}}


def test_attempts_and_feedback_belong_to_their_slot():
    journal = journal_of()
    journal.spend_attempt("07:15")
    journal.spend_attempt("07:15")
    journal.note_feedback("07:15", "x" * 600)
    assert journal.attempts("07:15", DAY) == 2 and journal.attempts("09:30", DAY) == 0
    assert journal.feedback("07:15", DAY) == "x" * 500 and journal.feedback("09:30", DAY) == ""


def test_a_reserved_slot_is_closed_until_released():
    journal = journal_of()
    journal.reserve("07:15", URL, "A post", AT)
    assert journal.closed("07:15", DAY)
    assert journal.saved["pending_sources"] == {
        "2026-09-20/07:15": dict(url=URL, text="A post", ts=AT.isoformat())}
    assert URL in journal.used_urls(AT) and journal.recent_texts() == ["A post"]
    assert journal.submissions(DAY) == Submissions(published=0, pending=1)
    assert journal.last_submission() == AT
    journal.release("07:15")
    assert not journal.closed("07:15", DAY)
    assert journal.saved["slots"] == {} and journal.saved["pending_sources"] == {}
    assert journal.submissions(DAY) == Submissions(0, 0) and journal.last_submission() is None


def test_a_confirmed_slot_is_published():
    journal = journal_of()
    journal.reserve("07:15", URL, "A post", AT)
    shipped = AT + timedelta(seconds=20)
    journal.confirm("07:15", URL, "A post", "format first", shipped)
    assert journal.closed("07:15", DAY)
    assert journal.saved["slots"] == {"07:15": "published"}
    assert journal.saved["pending_sources"] == {}
    assert journal.published() == [dict(ts=shipped.isoformat(), text="A post", source_url=URL,
                                        angle="format first", slot="07:15")]
    assert journal.recent_texts() == ["A post"] and URL in journal.used_urls(shipped)
    assert journal.submissions(DAY) == Submissions(published=1, pending=0)
    assert journal.last_submission() == shipped


def test_a_pending_slot_keeps_its_key_across_days():
    """Tomorrow's same Slot must not overwrite a pending one: it may be live."""
    journal = journal_of()
    journal.reserve("07:15", URL, "Yesterday's post", AT)
    journal.roll_to(DAY + timedelta(days=1))
    journal.reserve("07:15", "https://openai.com/new", "Today's post", AT + timedelta(days=1))
    assert set(journal.saved["pending_sources"]) == {"2026-09-20/07:15", "2026-09-21/07:15"}
    # Yesterday's pending counts toward yesterday.
    assert journal.submissions(DAY + timedelta(days=1)) == Submissions(published=0, pending=1)
    journal.release("07:15")
    assert set(journal.saved["pending_sources"]) == {"2026-09-20/07:15"}


def test_submissions_count_the_operator_marks_of_the_day():
    """A Slot the Operator marked pending or published by hand counts, its
    pending_sources entry removed or not."""
    journal = journal_of(slots={"09:30": "published", "10:00": "pending", "11:45": "pending"},
                         pending_sources={"2026-09-20/11:45": dict(url=URL, text="t", ts=AT.isoformat()),
                                          "2026-09-20/startup@05:00:00": dict(
                                              url=URL, text="t", ts=AT.isoformat())})
    assert journal.submissions(DAY) == Submissions(published=1, pending=3)
    assert journal.submissions(DAY + timedelta(days=1)) == Submissions(published=0, pending=0)


def test_used_urls_hold_a_week_of_publications_and_every_pending_one():
    old = dict(ts=(AT - timedelta(days=8)).isoformat(), text="old", source_url="https://old.example",
               angle="a", slot="07:15")
    week = dict(ts=(AT - timedelta(days=6)).isoformat(), text="week", source_url="https://week.example",
                angle="a", slot="07:15")
    undated = dict(ts="", text="undated", source_url="https://undated.example", angle="a", slot="07:15")
    journal = journal_of(published=[old, week, undated], pending_sources={
        "2026-09-01/07:15": dict(url="https://pending.example", text="p", ts="2026-09-01T07:15:00-04:00")})
    assert journal.used_urls(AT) == {"https://week.example", "https://pending.example"}
    assert journal.recent_texts() == ["old", "week", "undated", "p"]
    assert journal.last_submission() == AT - timedelta(days=6)


def test_an_empty_journal_answers_every_query():
    journal = MemoryJournal()
    assert not journal.closed("07:15", DAY) and journal.attempts("07:15", DAY) == 0
    assert journal.feedback("07:15", DAY) == "" and journal.published() == []
    assert journal.used_urls(AT) == set() and journal.recent_texts() == []
    assert journal.submissions(DAY) == Submissions(0, 0) and journal.last_submission() is None


def test_stamps_read_iso_and_feed_dates_and_refuse_naive_ones():
    assert slot_journal.stamp("Sun, 20 Sep 2026 10:00:00 +0200").hour == 8
    assert slot_journal.stamp("2026-09-20T10:00:00Z").hour == 10
    assert slot_journal.stamp("2026-09-20T10:00:00") is None
    assert slot_journal.stamp("") is None


# --- the file ------------------------------------------------------------------

OLD_FORMAT = {
    "date": "2026-09-20",
    "slots": {"05:00": "published", "startup@07:10:00": "pending"},
    "published": [dict(ts="2026-09-20T05:00:20-04:00", text="Un modèle génère du texte.",
                       source_url="https://openai.com/a", angle="a", slot="05:00")],
    "pending_sources": {"2026-09-20/startup@07:10:00": dict(
        url="https://openai.com/b", text="A pending post", ts="2026-09-20T07:10:10-04:00")},
    "attempts": {"05:00": 1, "startup@07:10:00": 1},
    "feedback": {"09:30": "evidence not found in fetched source"},
    "operator_note": "kept as is",
}


def _old_file():
    """An editorial_state.json as the cycle wrote it before the journal."""
    path = slot_journal.STATE.path
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps(OLD_FORMAT, indent=2, ensure_ascii=False))
    with open(path, "rb") as f:
        return path, f.read()


def test_the_file_of_the_old_format_reads_and_rewrites_identically():
    path, before = _old_file()
    journal = FileJournal()
    journal.roll_to(DAY)
    assert journal.closed("05:00", DAY) and journal.attempts("05:00", DAY) == 1
    assert journal.feedback("09:30", DAY) == "evidence not found in fetched source"
    assert journal.submissions(DAY) == Submissions(published=1, pending=1)
    journal.reserve("11:45", URL, "A post", AT)
    with open(path, encoding="utf-8") as f:
        assert json.load(f)["slots"] == {**OLD_FORMAT["slots"], "11:45": "pending"}
    # Released, the reservation leaves the very bytes the old cycle wrote.
    journal.release("11:45")
    with open(path, "rb") as f:
        assert f.read() == before


def test_the_file_keeps_the_state_in_memory_between_two_saves():
    path, before = _old_file()
    journal = FileJournal()
    journal.roll_to(DAY + timedelta(days=1))
    with open(path, "rb") as f:
        assert f.read() == before
    journal.reserve("07:15", URL, "A post", AT + timedelta(days=1))
    written = json.loads(open(path, encoding="utf-8").read())
    assert list(written) == ["date", "slots", "published", "pending_sources"]
    assert written["date"] == "2026-09-21" and written["slots"] == {"07:15": "pending"}
    assert set(written["pending_sources"]) == {"2026-09-20/startup@07:10:00", "2026-09-21/07:15"}


def test_a_missing_file_is_an_empty_journal():
    journal = FileJournal()
    assert journal.published() == [] and journal.last_submission() is None


def test_an_unreadable_file_stops_the_journal_and_stays_as_is():
    path = slot_journal.STATE.path
    with open(path, "w") as f:
        f.write("{not json")
    with pytest.raises(StateUnreadable):
        FileJournal()
    assert open(path).read() == "{not json"

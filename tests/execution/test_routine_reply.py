"""A routine "RE:" reply is not a new interview, and a cancelled position with no scheduled interview is a Rejection (HRize/Sonata, 2026-10-19)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "execution"))

import classify_email as ce  # noqa: E402

QUOTE = ("\n\nFrom: Sehrish Khan <s@gmail.com>\nSent: 19 October 2026 11:01\nSubject: Re: Representation Mail\n\n"
         "Hello Sehrish,\nThe Client- Sonata Software wants to schedule your interview on Monday, October 19, 2026 at 07:30 AM PST OR 10:00 AM PST")
CALLING = {"subject": "RE: Representation Mail", "body_content": "I am calling you right away.\n\nPratik Sinha\nHRize" + QUOTE}
CANCEL = {"subject": "RE: Representation Mail", "body_content": (
    "Hi Sehrish,\n\nI just received an update from the client that the position has been cancelled, so the interview will no longer be scheduled.\n\n"
    "I sincerely apologize for the inconvenience." + QUOTE)}


def _cat(category, email, monkeypatch):
    monkeypatch.setenv("CATEGORY_REMAP_MODE", "off")
    return ce.apply_business_rules({"category": category, "confidence": 0.95, "extracted_data": {}}, email)["category"]


def test_strip_quoted_reply_keeps_only_new_text():
    assert ce.strip_quoted_reply(CALLING["body_content"]).startswith("I am calling you right away.")
    assert "Sonata" not in ce.strip_quoted_reply(CALLING["body_content"])
    assert ce.strip_quoted_reply("a\n> quoted") == "a"
    assert ce.strip_quoted_reply("On Fri, Oct 16, 2026, 3:19 PM Pratik wrote:\nold") == ""


def test_calling_you_right_away_is_routine_so_no_new_notice(monkeypatch):
    assert ce.is_routine_reply(CALLING)
    assert _cat("Phone Screen", CALLING, monkeypatch) == "Other"


def test_a_reply_that_mentions_a_time_is_not_routine(monkeypatch):
    e = {"subject": "RE: Interview", "body_content": "Yes, 10:00 AM works for me." + QUOTE}
    assert not ce.is_routine_reply(e)
    assert _cat("Interview Schedule", e, monkeypatch) == "Interview Schedule"


def test_confirm_and_reschedule_words_are_not_routine():
    for text in ("Please confirm.", "Can we reschedule?", "Here is the Zoom link", "Thursday works"):
        assert not ce.is_routine_reply({"subject": "Re: x", "body_content": text + QUOTE})


def test_not_a_reply_or_nothing_quoted_is_never_routine():
    assert not ce.is_routine_reply({"subject": "Interview with Acme", "body_content": "Thanks." + QUOTE})
    assert not ce.is_routine_reply({"subject": "RE: x", "body_content": "Thanks."})        # nothing quoted: cannot tell
    assert not ce.is_routine_reply({"subject": "Fwd: x", "body_content": "FYI" + QUOTE})
    assert not ce.is_routine_reply(None)


def test_position_cancelled_interview_no_longer_scheduled_is_a_rejection(monkeypatch):
    assert ce.role_cancelled_not_interview("Interview Cancelled", CANCEL)
    assert _cat("Interview Cancelled", CANCEL, monkeypatch) == "Rejection"


def test_interview_word_only_in_the_quoted_thread_does_not_block_it():
    assert ce.role_cancelled_not_interview("Interview Cancelled", CANCEL)


def test_a_real_interview_cancellation_is_still_an_interview_cancellation():
    e = {"subject": "Update", "body_content": "The position has been cancelled, so your interview on Friday will not take place."}
    assert not ce.role_cancelled_not_interview("Interview Cancelled", e)

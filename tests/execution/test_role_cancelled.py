"""A cancelled ROLE is not a cancelled interview: it is filed as a Rejection and never reaches a student (Vizient, 2026-10-14)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "execution"))

import classify_email as ce  # noqa: E402
import process_inbox_auto as pia  # noqa: E402

VIZIENT = {
    "subject": "Vizient: An update on your recent application job requisition ID: 28079R",
    "body_content": "Dear Binoy,\n\nThank you for your interest in our Sr Analyst position at Vizient.\nAt this time, the role has been cancelled.\n\n"
                    "We hope you remain enthusiastic about Vizient and encourage you to consider other\nopportunities.",
}


def _cancelled(**extra):
    return {"category": "Interview Cancelled", "confidence": 0.95, "extracted_data": {}, **extra}


def test_vizient_role_cancelled_is_filed_as_rejection(monkeypatch):
    monkeypatch.setenv("CATEGORY_REMAP_MODE", "off")
    result = ce.apply_business_rules(_cancelled(), VIZIENT)
    assert result["category"] == "Rejection" and result["category_original"] == "Interview Cancelled"


def test_a_rejection_makes_no_interview_event_so_no_notice_or_alert():
    assert not pia.creates_interview_event({"category": "Rejection", "confidence": 0.95})


def test_a_real_interview_cancellation_is_left_alone(monkeypatch):
    monkeypatch.setenv("CATEGORY_REMAP_MODE", "off")
    email = {"subject": "Your interview has been cancelled", "body_content": "Your interview on Friday has been cancelled."}
    assert ce.apply_business_rules(_cancelled(), email)["category"] == "Interview Cancelled"


def test_interview_mentioned_anywhere_keeps_it_an_interview_cancellation():
    email = {"subject": "Update", "body_content": "The position has been cancelled, so your interview will not take place."}
    assert not ce.role_cancelled_not_interview("Interview Cancelled", email)


def test_cancellation_without_role_wording_is_left_alone():
    assert not ce.role_cancelled_not_interview("Interview Cancelled", {"subject": "Schedule change", "body_content": "Please note the change."})


def test_other_categories_are_never_touched():
    assert not ce.role_cancelled_not_interview("Rejection", VIZIENT)
    assert not ce.role_cancelled_not_interview("Phone Screen", VIZIENT)
    assert not ce.role_cancelled_not_interview("Interview Cancelled", None)


def test_position_filled_and_requisition_closed_wordings():
    for body in ("The position has been filled.", "This job requisition was closed.", "We have cancelled the role."):
        assert ce.role_cancelled_not_interview("Interview Cancelled", {"subject": "Update", "body_content": body}), body


def test_the_prompt_sends_role_cancellations_to_rejection():
    assert "ROLE or position itself is cancelled" in ce.CLASSIFICATION_PROMPT

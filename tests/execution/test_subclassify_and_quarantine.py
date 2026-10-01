"""
Tests for the 2026-10-01 labeling fixes (see progress.md):

1. The live pipeline now calls the interview sub-classifier, and falls back to
   the primary category when it cannot answer.
2. Recipient headers are captured at fetch time so students can be resolved.
3. Drafts follow the real sub-type instead of always using "Interview Request".
4. The second spam pass moves unclear mail to Quarantine; it never deletes.

Fakes only -- no IMAP, no OpenAI, no database, no real email.
"""

import sys
from pathlib import Path

import pytest

_EXECUTION_DIR = Path(__file__).resolve().parents[2] / "execution"
if str(_EXECUTION_DIR) not in sys.path:
    sys.path.insert(0, str(_EXECUTION_DIR))

import fetch_emails  # noqa: E402
import notify_student  # noqa: E402
import process_inbox_auto as pia  # noqa: E402
import subclassify_interview as sci  # noqa: E402


def _email(**over):
    base = {"subject": "Interview", "body_content": "Please join", "email_id": "1",
            "sender_email": "hr@acme.com", "headers": {}, "to_addresses": []}
    base.update(over)
    return base


def _cls(category="Interview Request", confidence=0.9, **extracted):
    return {"category": category, "confidence": confidence,
            "extracted_data": {"company_name": "Acme", **extracted}}


# ── 1. sub-classifier is called and used ─────────────────────────────────────

@pytest.mark.parametrize("sub_type", [
    "Phone Screen", "Client Screen", "Technical Interview",
    "Interview Cancelled", "Interview Rescheduled", "Job Machine",
])
def test_subclassifier_result_is_used(monkeypatch, sub_type):
    monkeypatch.setattr(sci, "subclassify_interview", lambda email_data, **k: {
        "interview_sub_type": sub_type, "confidence": 0.93, "is_job_machine": sub_type == "Job Machine",
        "company_name": "Acme", "position_title": None,
    })
    result = pia._build_sub_classification(_email(), _cls(position_title="Dev"))
    assert result["interview_sub_type"] == sub_type
    assert result["sub_type_source"] == "subclassifier"
    assert result["confidence"] == 0.93
    # fields the sub-classifier left empty are filled from the primary extraction
    assert result["position_title"] == "Dev"


def test_subclassifier_failure_falls_back_to_category(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("openai down")
    monkeypatch.setattr(sci, "subclassify_interview", boom)
    result = pia._build_sub_classification(_email(), _cls())
    assert result["interview_sub_type"] == "interview_request"
    assert result["sub_type_source"] == "category_fallback"


def test_unknown_subtype_falls_back(monkeypatch):
    monkeypatch.setattr(sci, "subclassify_interview",
                        lambda *a, **k: {"interview_sub_type": "Banana", "confidence": 0.9})
    result = pia._build_sub_classification(_email(), _cls())
    assert result["sub_type_source"] == "category_fallback"


def test_non_interview_category_skips_the_ai_call(monkeypatch):
    calls = []
    monkeypatch.setattr(sci, "subclassify_interview", lambda *a, **k: calls.append(1))
    result = pia._build_sub_classification(_email(), _cls(category="Job Invite"))
    assert calls == []
    assert result["interview_sub_type"] == "other"


# ── 2. recipient headers captured at fetch time ──────────────────────────────

RAW_FORWARDED = (
    b"Delivered-To: c_interviews@colaberry.com\r\n"
    b"Delivered-To: student.one@gmail.com\r\n"
    b"X-Forwarded-To: c_interviews@colaberry.com\r\n"
    b"From: HR <hr@acme.com>\r\n"
    b"To: student.one@gmail.com\r\n"
    b"Cc: Boss <boss@acme.com>\r\n"
    b"Subject: Interview\r\n"
    b"Message-ID: <abc@acme.com>\r\n\r\nHello"
)


def test_parse_email_keeps_every_recipient_header_value():
    parsed = fetch_emails.parse_email_message(RAW_FORWARDED, "9")
    assert "student.one@gmail.com" in parsed["headers"]["Delivered-To"]
    assert "c_interviews@colaberry.com" in parsed["headers"]["Delivered-To"]
    assert parsed["to_addresses"] == ["student.one@gmail.com", "boss@acme.com"]
    # only recipient headers are kept, not the whole header block
    assert "Subject" not in parsed["headers"] and "From" not in parsed["headers"]


def test_parsed_email_resolves_student_gmail_from_headers():
    parsed = fetch_emails.parse_email_message(RAW_FORWARDED, "9")
    assert pia._resolve_assigned_gmail(parsed) == "student.one@gmail.com"


def test_assigned_gmail_not_taken_from_weak_signals():
    # a To-field match is "medium" confidence; only header matches are stored
    assert pia._resolve_assigned_gmail(_email(to_addresses=["someone@gmail.com"])) is None


def test_parse_email_without_recipient_headers():
    parsed = fetch_emails.parse_email_message(b"Subject: x\r\nFrom: a@b.com\r\n\r\nhi", "1")
    assert parsed["headers"] == {} and parsed["to_addresses"] == []


# ── 3. drafts follow the sub-type ────────────────────────────────────────────

def test_draft_classification_uses_subclassifier_type():
    sub = {"interview_sub_type": "Interview Cancelled", "is_next_round": True,
           "is_job_machine": False, "job_machine_sub_type": None}
    out = notify_student._build_classification_for_draft(_cls(), _email(), sub)
    assert out["interview_sub_type"] == "Interview Cancelled"
    assert out["is_next_round"] is True


def test_draft_classification_defaults_without_subclassifier():
    out = notify_student._build_classification_for_draft(_cls(), _email())
    assert out["interview_sub_type"] == "Interview Request"
    assert out["is_job_machine"] is False


def test_cancelled_draft_does_not_use_first_interview_template():
    from draft_notification import draft_notification
    sub = {"interview_sub_type": "Interview Cancelled"}
    cls = notify_student._build_classification_for_draft(_cls(), _email(), sub)
    student = {"full_name": "Test Student", "personal_email": "t@example.com",
               "phone_number": "1", "assigned_gmail": None, "student_gmail": None}
    draft = draft_notification(classification=cls, student_info=student, assistant_name="Rob")
    assert draft["template_id"] != "interview_request_first"


# ── 4. spam second pass quarantines, never deletes ───────────────────────────

def _spam_pass(monkeypatch, review, results):
    """Run the pass with fakes; return (moves recorded, delete calls)."""
    moves, deletes = [], []
    monkeypatch.setattr(pia, "fetch_emails", lambda **k: review)
    monkeypatch.setattr(pia, "classify_email", results)
    monkeypatch.setattr(pia, "move_emails",
                        lambda **k: moves.append(k["email_moves"]) or len(k["email_moves"]))
    monkeypatch.setattr(pia, "delete_emails", lambda **k: deletes.append(k) or 0)
    out = pia._run_spam_review_pass("s", 993, "a@x", "p")
    return out, moves, deletes


def test_spam_pass_quarantines_other_and_never_deletes(monkeypatch):
    review = [_email(email_id="1"), _email(email_id="2")]
    out, moves, deletes = _spam_pass(
        monkeypatch, review, lambda e, **k: {"category": "Other", "confidence": 0.0})
    assert deletes == []
    assert moves == [{"1": pia.QUARANTINE_FOLDER, "2": pia.QUARANTINE_FOLDER}]
    assert out["quarantined"] == 2 and out["deleted"] == 0


def test_spam_pass_still_rescues_real_mail(monkeypatch):
    out, moves, deletes = _spam_pass(
        monkeypatch, [_email(email_id="1")],
        lambda e, **k: {"category": "Rejection", "confidence": 0.95})
    assert deletes == [] and out["rescued"] == 1 and out["quarantined"] == 0


def test_spam_pass_leaves_mail_alone_when_reclassification_fails(monkeypatch):
    def boom(e, **k):
        raise RuntimeError("api error")
    out, moves, deletes = _spam_pass(monkeypatch, [_email(email_id="1")], boom)
    assert deletes == [] and moves == []
    assert out["quarantined"] == 0 and out["rescued"] == 0


# ── 5. approvals queue ───────────────────────────────────────────────────────

@pytest.mark.parametrize("category, confidence, queued", [
    ("Job Alert", 0.69, True),            # under the threshold
    ("Job Alert", 0.70, False),           # at the threshold is fine
    ("Interview Request", 0.40, True),
    ("Other", 0.65, True),                # genuine uncertainty on "Other"
    ("Other", 0.0, False),                # model's normal answer for plain junk
    ("Other", 0.95, False),
])
def test_needs_human_review(category, confidence, queued):
    assert pia.needs_human_review(category, confidence) is queued


def test_queue_for_review_writes_one_pending_row(monkeypatch):
    api_dir = _EXECUTION_DIR.parents[0] / "services" / "dashboard" / "api"
    monkeypatch.syspath_prepend(str(api_dir))
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import models

    engine = create_engine("sqlite://")
    models.Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    email = models.Email(email_id="1", subject="s", from_address="a@b.com",
                         received_date=__import__("datetime").datetime.utcnow())
    db.add(email); db.flush()
    cls = models.Classification(email_id=email.id, category="Other", confidence=0.6)
    db.add(cls); db.flush()

    assert pia._queue_for_review(db, email.id, cls.id, "Other", 0.6) is True
    db.commit()
    # a second pass over the same email must not add a duplicate
    assert pia._queue_for_review(db, email.id, cls.id, "Other", 0.6) is False
    # confident results are never queued
    assert pia._queue_for_review(db, email.id, cls.id, "Rejection", 0.95) is False
    rows = db.query(models.Approval).all()
    assert len(rows) == 1 and rows[0].status == "pending"

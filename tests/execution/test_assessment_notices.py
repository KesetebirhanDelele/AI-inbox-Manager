"""An assessment is not an interview: it keeps its type, gets its own wording, and two emails about it give one notice."""
import sys
from datetime import datetime
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "execution"))

import content_audit as audit  # noqa: E402
import notification_messages as nm  # noqa: E402
import process_inbox_auto as pia  # noqa: E402


@pytest.fixture
def db(monkeypatch):
    monkeypatch.syspath_prepend(str(_ROOT / "services" / "dashboard" / "api"))
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import models
    engine = create_engine("sqlite://")
    models.Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    s.models = models
    return s


def test_company_names_from_two_systems_compare_equal():
    assert pia._normalise_company("Martin Sprocket & Gear Inc") == pia._normalise_company("Martin Sprocket and Gear")
    assert pia._normalise_company("Acme Corp") != pia._normalise_company("Beta Corp")


def _held(db, body, company="Martin Sprocket and Gear", n=1, status="draft"):
    M = db.models
    student = db.query(M.Student).first() or M.Student(username="r", full_name="Rutendo", is_active=True)
    mail = M.Email(email_id=str(n), subject="Assessment", from_address="x@y.com", full_body=body, received_date=datetime.utcnow())
    db.add_all([student, mail]); db.flush()
    event = M.InterviewEvent(email_id=mail.id, student_id=student.id, sub_type="Assessment", company_name=company, confidence=0.9)
    db.add(event); db.flush()
    draft = M.NotificationDraft(interview_event_id=event.id, recipient_email="r@x.com", email_subject="s", email_body="b", email_status=status)
    db.add(draft); db.commit()
    return student, draft


def test_a_second_email_about_the_same_assessment_is_skipped(db):
    student, _d = _held(db, "We have received your application. Please complete the assessment at the link below. " * 2)
    out = pia.assessment_duplicate_action(db, student.id, "Martin Sprocket & Gear Inc", "Assessment Invitation from Martin Sprocket and Gear and more text here")
    assert out == {"action": "skip"}


def test_an_email_with_text_replaces_a_notice_built_from_an_empty_email(db):
    student, draft = _held(db, "")                                    # the vendor mail: no stored text
    out = pia.assessment_duplicate_action(db, student.id, "Martin Sprocket & Gear Inc",
                                          "Hi Rutendo, we received your application. For the next step please complete the assessment.")
    assert out == {"action": "replace", "draft_id": draft.id}


def test_a_different_company_or_an_old_or_already_sent_notice_is_not_a_duplicate(db):
    student, draft = _held(db, "x" * 100, company="Acme")
    assert pia.assessment_duplicate_action(db, student.id, "Beta Corp", "y" * 100) == {"action": "create"}
    assert pia.assessment_duplicate_action(db, None, "Acme", "y" * 100) == {"action": "create"}
    M = db.models
    seq = M.NotificationSequence(draft_id=draft.id, student_id=student.id, status="active", timezone="America/Chicago",
                                 started_at=datetime.utcnow(), ack_token="t")
    db.add(seq); db.flush()
    db.add(M.NotificationAttempt(sequence_id=seq.id, channel="sms", step="start", planned_for=datetime.utcnow(),
                                 scheduled_for=datetime.utcnow(), status="sent", sent_at=datetime.utcnow()))
    db.commit()
    assert pia.assessment_duplicate_action(db, student.id, "Acme", "y" * 100) == {"action": "create"}      # already told: a new email is its own matter


def test_the_assessment_keeps_its_type_whatever_the_sub_classifier_says(monkeypatch):
    import subclassify_interview as sc
    monkeypatch.setattr(sc, "subclassify_interview", lambda email_data: {"interview_sub_type": "Technical Interview", "company_name": "Acme"})
    out = pia._build_sub_classification({"subject": "Assessment Invitation", "body_content": ""}, {"category": "Assessment"})
    assert out["interview_sub_type"] == "Assessment"
    other = pia._build_sub_classification({"subject": "Interview", "body_content": ""}, {"category": "Phone Screen"})
    assert other["interview_sub_type"] == "Technical Interview"                                          # only Assessment is forced


FACTS = {"first_name": "Rutendo", "employer": "Martin Sprocket and Gear", "date": "", "time": "", "format": "", "link": "",
         "employer_contact": "", "status": "assessment"}


def test_the_assessment_wording_says_test_not_interview_and_passes_the_audit():
    text, body = nm.sms(FACTS, "", "9"), nm.email_body(FACTS)
    assert text.startswith("[Interview Notification]") and len(text) <= 320 and audit.sms_problem(text) is None
    assert "not an interview" in text and "invitation email from the employer" in text and "Reply YES" in text
    assert audit.email_problem(body) is None and "an assessment from Martin Sprocket and Gear" in body and "not an interview" in body
    assert "interview with" not in body.lower()                                                         # it never calls the test an interview
    assert nm.email_subject(FACTS) == "Your assessment notice"


def test_draft_notification_uses_the_assessment_template_and_wording():
    from draft_notification import draft_notification
    cls = {"interview_sub_type": "Assessment", "company_name": "Martin Sprocket and Gear"}
    out = draft_notification(cls, {"full_name": "Rutendo Bwerazuva", "personal_email": "r@x.com"})
    assert out["template_id"] == "next_round_assessment"
    assert out["email_subject"] == "Your assessment notice" and "an assessment from" in out["email_body"]


def test_the_fix_up_keeps_the_notice_with_text_and_rejects_the_duplicate(db):
    import fix_assessment_notices as fix
    M = db.models
    student, vendor_draft = _held(db, "", company="Martin Sprocket and Gear", n=1)                       # the vendor mail: empty body
    _s, ats_draft = _held(db, "We have received your application. Please complete the assessment at the link below.",
                          company="Martin Sprocket & Gear Inc", n=2)
    for n in (1, 2):                                                                                       # both were classified Assessment
        mail = db.query(M.Email).filter_by(email_id=str(n)).one()
        db.add(M.Classification(email_id=mail.id, category="Assessment", confidence=0.95))
    for ev in db.query(M.InterviewEvent).all():
        ev.sub_type = "Technical Interview" if ev.id == 1 else "Interview Request"                         # as the old pipeline left them
    db.commit()

    rows = {r["draft"].id: r["action"] for r in fix.plan(db)}
    assert rows == {vendor_draft.id: "reject", ats_draft.id: "keep"}
    assert fix.apply_plan(db, fix.plan(db)) == {"rewritten": 1, "rejected_as_duplicates": 1}
    db.refresh(vendor_draft); db.refresh(ats_draft)
    assert vendor_draft.email_status == "rejected" and vendor_draft.reviewed_by == "duplicate-assessment"
    assert ats_draft.email_status == "draft" and ats_draft.template_id == "next_round_assessment"
    assert ats_draft.email_subject == "Your assessment notice" and "not an interview" in ats_draft.email_body
    assert {e.sub_type for e in db.query(M.InterviewEvent).all()} == {"Assessment"}
    assert [r["action"] for r in fix.plan(db)] == ["keep"]                                                # rerun: the kept one stays, nothing new to reject

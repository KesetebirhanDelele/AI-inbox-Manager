"""Closing the interview notices that the rules now call not relevant (a care job unrelated to the training)."""
import sys
from datetime import datetime
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "execution"))

import file_not_relevant_interviews as fnr  # noqa: E402

CNA = ("Hello MIRRIAM, I'm with Visiting Angels Senior Home Care. Thank you for your application to our Certified Nursing Assistant (CNA) posting. "
       "Are you available for a 15 minute phone call?")


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


def _notice(db, body, subject="Phone call", status="draft", n=1):
    M = db.models
    student = M.Student(username=f"s{n}", full_name="Mirriam", is_active=True)
    mail = M.Email(email_id=str(n), message_id=f"<m{n}@x>", subject=subject, from_address="alex@visitingangels.example", full_body=body,
                   received_date=datetime(2026, 10, 12), current_folder="INBOX")
    db.add_all([student, mail]); db.flush()
    event = M.InterviewEvent(email_id=mail.id, student_id=student.id, sub_type="Interview Request", company_name="Visiting Angels",
                             position_title="Certified Nursing Assistant (CNA)", confidence=0.9)
    db.add(event); db.flush()
    draft = M.NotificationDraft(interview_event_id=event.id, recipient_email="m@x.com", email_subject="s", email_body="b", email_status=status)
    db.add(draft); db.commit()
    return event, draft, mail


def test_only_a_not_relevant_notice_with_nothing_sent_is_picked(db):
    _notice(db, CNA, n=1)
    _notice(db, "We would like to schedule a phone screen for the Business Analyst role.", subject="Phone screen", n=2)    # relevant
    _notice(db, CNA, status="rejected", n=3)                                                                              # already closed
    items = fnr.plan(db)
    assert [i["email_id"] for i in items] == [1] and items[0]["student"] == "Mirriam"


def test_apply_rejects_the_draft_moves_the_mail_and_records_other(db):
    event, draft, mail = _notice(db, CNA)
    calls = []
    out = fnr.apply_plan(db, fnr.plan(db), lambda mid, target: calls.append((mid, target)) or True)
    assert out == {"rejected": 1, "moved": 1, "not_found_in_gmail": 0} and calls == [("<m1@x>", "Spam Review")]
    db.refresh(draft); db.refresh(mail)
    assert draft.email_status == "rejected" and draft.reviewed_by == "not-relevant-rule"
    assert mail.current_folder == "Spam Review"
    assert [c.category for c in db.query(db.models.Classification).filter_by(email_id=mail.id)] == ["Other"]
    assert db.get(db.models.InterviewEvent, event.id) is not None                       # the event is kept
    assert fnr.plan(db) == []                                                            # safe to rerun


def test_a_mail_gmail_cannot_find_still_has_its_notice_closed(db):
    _event, draft, mail = _notice(db, CNA)
    out = fnr.apply_plan(db, fnr.plan(db), lambda mid, target: False)
    assert out["rejected"] == 1 and out["not_found_in_gmail"] == 1
    db.refresh(draft); db.refresh(mail)
    assert draft.email_status == "rejected" and mail.current_folder == "INBOX"

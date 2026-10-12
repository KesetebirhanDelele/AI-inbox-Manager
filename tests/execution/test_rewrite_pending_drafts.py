"""Rewriting unsent drafts into the audit-safe wording, never touching one whose follow-ups already went out."""
import sys
from datetime import datetime
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "execution"))

import rewrite_pending_drafts as rpd  # noqa: E402


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


def _draft(db, body, status="draft", n=1):
    M = db.models
    student = M.Student(username=f"s{n}", full_name="Test Student", is_active=True)
    mail = M.Email(email_id=str(n), subject="s", from_address="hr@acme.com", received_date=datetime(2026, 10, 5))
    db.add_all([student, mail]); db.flush()
    event = M.InterviewEvent(email_id=mail.id, student_id=student.id, sub_type="Phone Screen", company_name="Acme",
                             position_title="Data Analyst", interview_date="2026-10-14", interview_time="2:00 PM",
                             interview_timezone="CT", confidence=0.9)
    db.add(event); db.flush()
    d = M.NotificationDraft(interview_event_id=event.id, recipient_email="a@b.com", email_subject="Congrats! Data Analyst role",
                            email_body=body, email_status=status)
    db.add(d); db.commit()
    return d


def test_an_old_draft_is_rewritten_and_the_new_text_is_clean(db):
    d = _draft(db, "Hi Test, congratulations on the Data Analyst role at Acme.")
    items = rpd.plan(db)
    assert len(items) == 1
    _draft_row, subject, body = items[0]
    assert subject == "Your interview on Wed Oct 14"
    assert body.splitlines()[0] == "[Interview Notification]" and "Data Analyst" not in body and "Acme" in body


def test_a_draft_already_in_the_new_wording_is_left_alone(db):
    _draft(db, "[Interview Notification]\n\nHello Test,")
    assert rpd.plan(db) == []


def test_a_draft_whose_notices_already_went_out_is_left_alone(db):
    d = _draft(db, "Old wording", status="approved")
    M = db.models
    seq = M.NotificationSequence(draft_id=d.id, student_id=1, status="active", timezone="America/Chicago", started_at=datetime(2026, 10, 5),
                                 ack_token="t")
    db.add(seq); db.flush()
    db.add(M.NotificationAttempt(sequence_id=seq.id, channel="email", step="start", planned_for=datetime(2026, 10, 5),
                                 scheduled_for=datetime(2026, 10, 5), status="sent", sent_at=datetime(2026, 10, 5)))
    db.commit()
    assert rpd.plan(db) == []


def test_sent_and_rejected_drafts_are_not_touched(db):
    _draft(db, "Old wording", status="sent", n=1)
    _draft(db, "Old wording", status="rejected", n=2)
    assert rpd.plan(db) == []

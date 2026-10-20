"""The approver is emailed once about each new card waiting for review; the backup (escalation role) hears about cards nobody decided.
Only cards the Review screen shows count: not follow-ups, rejected students or old mail."""
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "execution"))

import open_cards  # noqa: E402
import review_alerts as ra  # noqa: E402
import stale_draft_alerts as sd  # noqa: E402


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
    s.student = models.Student(username="s", full_name="Sehrish", is_active=True)
    s.add(s.student)
    s.commit()
    return s


class Capture:
    def __init__(self, ok=True):
        self.ok, self.calls = ok, []

    def review_needed(self, subject, body):
        self.calls.append((subject, body))
        return self.ok


def _card(db, company="Acme", status="draft", received=None, student=None, n=[0]):
    M = db.models
    n[0] += 1
    mail = M.Email(email_id=f"m{n[0]}", subject="x", from_address="a@b.com", received_date=received or datetime.utcnow())
    db.add(mail); db.flush()
    ev = M.InterviewEvent(email_id=mail.id, student_id=(student or db.student).id, sub_type="Phone Screen", company_name=company,
                          position_title="Analyst", interview_date="2026-10-21", interview_time="10:00", interview_timezone="CST", confidence=0.9)
    db.add(ev); db.flush()
    d = M.NotificationDraft(interview_event_id=ev.id, recipient_email="s@x.com", email_subject="s", email_body="b", email_status=status)
    db.add(d); db.commit()
    return ev, d


def _approver(db, email="kes@example.com"):
    db.add(db.models.RoleAssignment(role="approver", email=email, active=True)); db.commit()


def test_first_run_records_the_backlog_without_an_email(db):
    _approver(db)
    _card(db); _card(db, "Beta")
    cap = Capture()
    assert ra.run(db, alerts=cap)["status"] == "baseline" and cap.calls == []
    assert ra.run(db, alerts=cap)["status"] == "nothing new"


def test_a_new_card_after_the_baseline_emails_the_approver_once_with_the_facts(db):
    _approver(db)
    ra.run(db, alerts=Capture())
    _card(db, "Sonata Software")
    cap = Capture()
    out = ra.run(db, alerts=cap)
    assert out == {"status": "sent", "alerted": 1}
    subject, body = cap.calls[0]
    assert "1 new notification card" in subject and "Sehrish" in body and "Sonata Software" in body and "2026-10-21 10:00 CST" in body and "/review" in body
    assert ra.run(db, alerts=cap)["status"] == "nothing new" and len(cap.calls) == 1        # each card once


def test_several_new_cards_make_one_email(db):
    _approver(db)
    ra.run(db, alerts=Capture())
    _card(db, "A"); _card(db, "B"); _card(db, "C")
    cap = Capture()
    assert ra.run(db, alerts=cap)["alerted"] == 3 and len(cap.calls) == 1


def test_cards_review_hides_never_alert(db):
    M = db.models
    _approver(db)
    ra.run(db, alerts=Capture())
    _card(db, "Decided", status="approved")
    _card(db, "Rejected", status="rejected")
    _card(db, "Old", received=datetime.utcnow() - timedelta(days=20))
    ev, _ = _card(db, "Follow-up")
    first, _ = _card(db, "Original")
    db.add(M.InterviewFollowUp(event_id=ev.id, original_event_id=first.id, reason="same interview")); db.commit()
    gone = M.Student(username="g", full_name="Gone", is_active=True); db.add(gone); db.commit()
    db.add(M.StudentVerification(student_id=gone.id, status="rejected", basis="gmail_guess")); db.commit()
    _card(db, "Rejected student", student=gone)
    cap = Capture()
    assert ra.run(db, alerts=cap)["alerted"] == 1                                            # only "Original"
    assert "Original" in cap.calls[0][1] and "Follow-up" not in cap.calls[0][1] and "Rejected student" not in cap.calls[0][1]


def test_nobody_assigned_marks_nothing_so_it_goes_out_once_someone_is(db):
    ra.run(db, alerts=Capture())
    _card(db)
    cap = Capture()
    assert ra.run(db, alerts=cap)["status"] == "no approver assigned"
    assert "nobody holds the approver role" in cap.calls[0][1]                  # only logged (RoleAlerts sends nothing without an address)
    _approver(db)
    assert ra.run(db, alerts=cap)["alerted"] == 1


def test_a_failed_send_marks_nothing_so_it_is_retried(db):
    _approver(db)
    ra.run(db, alerts=Capture())
    _card(db)
    assert ra.run(db, alerts=Capture(ok=False))["status"] == "send failed"
    assert ra.run(db, alerts=Capture())["alerted"] == 1


def test_the_switch_on_the_settings_page_turns_it_off(db):
    _approver(db)
    ra.run(db, alerts=Capture())
    db.add(db.models.SystemConfig(key=ra.ENABLED_KEY, value="off")); db.commit()
    _card(db)
    cap = Capture()
    assert ra.run(db, alerts=cap)["status"] == "off" and cap.calls == []


def test_open_cards_lists_only_undecided_visible_drafts(db):
    _card(db, "Open"); _card(db, "Done", status="sent")
    assert [d.email_status for d in open_cards.open_review_drafts(db)] == ["draft"]


def test_the_backup_time_comes_from_settings_then_the_environment(db):
    assert sd.stale_minutes({}, db) == 120
    assert sd.stale_minutes({"STALE_DRAFT_BUSINESS_MINUTES": "90"}, db) == 90
    db.add(db.models.SystemConfig(key=sd.HOURS_KEY, value="3")); db.commit()
    assert sd.stale_minutes({"STALE_DRAFT_BUSINESS_MINUTES": "90"}, db) == 180

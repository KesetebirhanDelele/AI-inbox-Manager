"""The dashboard 'Interview Requests Today' tile counts interviews, not interview-looking emails; rejecting a card lowers it (Sehrish, 2026-10-19)."""
from models import Student
from conftest import make_email, make_classification, make_student, make_interview_event, make_notification_draft


def _today(client, auth_cookies):
    return client.get("/api/stats/summary", cookies=auth_cookies).json()["today_interview_requests"]


def _interview(db, n, status="draft", **kw):
    email = make_email(db, email_id=f"tile{n}", subject=f"Interview {n}")
    make_classification(db, email, category="Interview Request", confidence=0.9)
    student = db.query(Student).first() or make_student(db)
    event = make_interview_event(db, email, student=student, **kw)
    if status:
        make_notification_draft(db, event, email_status=status)
    return event


def test_pending_and_approved_count_rejected_does_not(client, db, auth_cookies):
    _interview(db, 1, "draft")
    _interview(db, 2, "approved")
    rejected = _interview(db, 3, "rejected")
    assert _today(client, auth_cookies) == 2
    from models import NotificationDraft
    d = db.query(NotificationDraft).filter_by(interview_event_id=rejected.id).one()
    d.email_status = "draft"
    db.commit()
    assert _today(client, auth_cookies) == 3          # un-rejected: counts again


def test_an_event_without_a_notice_still_counts(client, db, auth_cookies):
    _interview(db, 1, status=None)
    assert _today(client, auth_cookies) == 1


def test_follow_ups_and_cancellations_do_not_count(client, db, auth_cookies):
    from models import InterviewFollowUp
    original = _interview(db, 1)
    again = _interview(db, 2)
    db.add(InterviewFollowUp(event_id=again.id, original_event_id=original.id, reason="same interview, same time"))
    db.commit()
    _interview(db, 3, sub_type="Interview Cancelled")
    assert _today(client, auth_cookies) == 1


def test_no_email_only_count(client, db, auth_cookies):
    email = make_email(db, email_id="lone", subject="Interview?")
    make_classification(db, email, category="Interview Request", confidence=0.9)     # classified, but no interview event
    assert _today(client, auth_cookies) == 0

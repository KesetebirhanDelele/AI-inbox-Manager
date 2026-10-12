"""The approver can reject a student who is not one of ours: notices closed, follow-ups stopped, hidden from the queue, nothing sent or deleted."""
from datetime import datetime

from conftest import make_email, make_interview_event, make_notification_draft, make_student


def _seq(db, draft, student, sent=False):
    from models import NotificationAttempt, NotificationSequence
    seq = NotificationSequence(draft_id=draft.id, student_id=student.id, status="active", timezone="America/Chicago",
                               started_at=datetime.utcnow(), ack_token=f"tok{draft.id}")
    db.add(seq); db.flush()
    db.add(NotificationAttempt(sequence_id=seq.id, channel="email", step="start", planned_for=datetime.utcnow(), scheduled_for=datetime.utcnow(),
                               status="sent" if sent else "pending", sent_at=datetime.utcnow() if sent else None))
    db.commit()
    return seq


def test_rejecting_a_student_closes_their_notices_and_plans_and_hides_them(client, db, auth_cookies):
    from models import NotificationDraft, StudentVerification
    student = make_student(db, username="kenya", full_name="Kenya Means")
    email = make_email(db)
    event = make_interview_event(db, email, student=student)
    draft = make_notification_draft(db, event, email_status="approved")
    seq = _seq(db, draft, student)

    before = client.get("/api/notifications/review-queue", cookies=auth_cookies).json()
    assert any(i["student"] and i["student"]["id"] == student.id for i in before["items"])

    resp = client.post(f"/api/notifications/students/{student.id}/reject-verification", json={"reason": "not in GHL"}, cookies=auth_cookies)
    assert resp.status_code == 200 and resp.json()["status"] == "rejected" and resp.json()["notices_closed"] == 1

    db.expire_all()
    assert db.query(NotificationDraft).get(draft.id).email_status == "rejected"
    assert "not in GHL" in db.query(NotificationDraft).get(draft.id).send_error
    assert db.query(StudentVerification).filter_by(student_id=student.id).one().status == "rejected"
    from models import NotificationSequence
    s = db.query(NotificationSequence).get(seq.id)
    assert s.status == "closed" and all(a.status != "pending" for a in s.attempts)               # follow-ups stopped

    after = client.get("/api/notifications/review-queue", cookies=auth_cookies).json()
    assert not any(i["student"] and i["student"]["id"] == student.id for i in after["items"])     # hidden from the queue


def test_a_student_with_a_notice_already_sent_cannot_be_rejected_here(client, db, auth_cookies):
    student = make_student(db, username="sent", full_name="Already Told")
    event = make_interview_event(db, make_email(db), student=student)
    draft = make_notification_draft(db, event, email_status="approved")
    _seq(db, draft, student, sent=True)
    resp = client.post(f"/api/notifications/students/{student.id}/reject-verification", json={}, cookies=auth_cookies)
    assert resp.status_code == 409 and "already gone out" in resp.json()["detail"]


def test_an_unknown_student_is_a_404_and_login_is_required(client, db, auth_cookies):
    assert client.post("/api/notifications/students/9999/reject-verification", json={}, cookies=auth_cookies).status_code == 404
    assert client.post("/api/notifications/students/1/reject-verification", json={}).status_code in (401, 403)

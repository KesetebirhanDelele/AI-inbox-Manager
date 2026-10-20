"""Approved notices stay on the Review screen while their follow-ups run (with the student's replies and a Stop button), and Stop closes only that notice."""
from datetime import datetime, timedelta

from conftest import make_email, make_interview_event, make_notification_draft, make_student


def _approved(db, n, student, company, status="active", sent=True):
    from models import NotificationAttempt, NotificationSequence
    email = make_email(db, email_id=f"fu{n}")
    event = make_interview_event(db, email, student=student, company=company)
    draft = make_notification_draft(db, event, email_status="approved")
    seq = NotificationSequence(draft_id=draft.id, student_id=student.id, status=status, timezone="America/Chicago",
                               started_at=datetime.utcnow(), ack_token=f"tok{n}")
    db.add(seq); db.flush()
    for step, state in (("start", "sent" if sent else "pending"), ("day2", "pending")):
        db.add(NotificationAttempt(sequence_id=seq.id, channel="sms", step=step, planned_for=datetime.utcnow(), scheduled_for=datetime.utcnow(),
                                   status=state, sent_at=datetime.utcnow() if state == "sent" else None))
    db.commit()
    return draft, seq


def _queue(client, auth_cookies, **params):
    return client.get("/api/notifications/review-queue", params=params, cookies=auth_cookies).json()["items"]


def test_an_approved_notice_with_running_follow_ups_is_listed_by_default_and_can_be_stopped(client, db, auth_cookies):
    student = make_student(db)
    draft, seq = _approved(db, 1, student, "Acme")
    items = _queue(client, auth_cookies)
    assert [i["draft_id"] for i in items] == [draft.id]
    assert items[0]["sequence"]["status"] == "active" and items[0]["sequence"]["can_stop"] is True


def test_a_quiet_old_finished_notice_stays_out_of_the_default_list(client, db, auth_cookies):
    student = make_student(db)
    _, seq = _approved(db, 1, student, "Acme", status="exhausted")
    assert _queue(client, auth_cookies) == []
    assert len(_queue(client, auth_cookies, include_done=True)) == 1


def test_a_reply_shows_on_the_card_and_keeps_it_visible_for_a_day(client, db, auth_cookies):
    from models import NotificationInbound
    student = make_student(db)
    _, seq = _approved(db, 1, student, "Acme", status="acknowledged")
    seq.ack_at, seq.ack_channel, seq.ack_kind = datetime.utcnow(), "sms", "explicit"
    db.add(NotificationInbound(sequence_id=seq.id, ghl_message_id="m1", channel="sms", direction="inbound", text="Yes",
                               received_at=datetime.utcnow(), handled_as="yes_rule"))
    db.commit()
    items = _queue(client, auth_cookies)
    assert len(items) == 1 and items[0]["sequence"]["can_stop"] is False
    assert items[0]["sequence"]["replies"] == [{"channel": "sms", "text": "Yes", "received_at": items[0]["sequence"]["replies"][0]["received_at"], "handled_as": "yes_rule"}]
    seq.ack_at = datetime.utcnow() - timedelta(days=2)
    from models import NotificationInbound as NI
    for row in db.query(NI).all():
        row.created_at = datetime.utcnow() - timedelta(days=2)
    db.commit()
    assert _queue(client, auth_cookies) == []                                # a day later it moves under "Show finished"


def test_stop_closes_only_that_notice_and_cancels_its_pending_steps(client, db, auth_cookies):
    from models import NotificationAttempt
    student = make_student(db)
    d1, s1 = _approved(db, 1, student, "Acme")
    d2, s2 = _approved(db, 2, student, "Beta")
    r = client.post(f"/api/notifications/{d1.id}/sequence/close", cookies=auth_cookies)
    assert r.status_code == 200 and r.json()["status"] == "closed"
    db.refresh(s1); db.refresh(s2)
    assert s1.status == "closed" and s2.status == "active"
    pending = lambda s: db.query(NotificationAttempt).filter_by(sequence_id=s.id, status="pending").count()
    assert pending(s1) == 0 and pending(s2) == 1                             # the other position keeps its follow-ups
    assert r.json()["closed_now"] is True
    assert client.post(f"/api/notifications/{d1.id}/sequence/close", cookies=auth_cookies).json()["closed_now"] is False   # twice is harmless

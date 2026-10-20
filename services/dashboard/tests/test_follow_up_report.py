"""Reports > Overview: how the student notices started in a date range ended up (acknowledged by which channel, waiting, no response, STOP, stopped, passed)."""
from datetime import datetime, timedelta

from conftest import make_email, make_interview_event, make_notification_draft, make_student


def _seq(db, n, student, status, started, ack_at=None, ack_channel=None):
    from models import NotificationSequence
    email = make_email(db, email_id=f"r{n}")
    event = make_interview_event(db, email, student=student, company=f"Co{n}")
    draft = make_notification_draft(db, event, email_status="approved")
    db.add(NotificationSequence(draft_id=draft.id, student_id=student.id, status=status, timezone="America/Chicago", started_at=started,
                                ack_token=f"t{n}", ack_at=ack_at, ack_channel=ack_channel, ack_kind="explicit" if ack_at else None))
    db.commit()


def _summary(client, auth_cookies, start, end):
    return client.get(f"/api/stats/weekly-summary?start_date={start}&end_date={end}", cookies=auth_cookies).json()["follow_ups"]


def test_every_outcome_is_counted_and_acknowledgements_split_by_channel(client, db, auth_cookies):
    student = make_student(db)
    t = datetime(2026, 10, 20, 16, 0)
    _seq(db, 1, student, "acknowledged", t, t + timedelta(minutes=6), "sms")
    _seq(db, 2, student, "acknowledged", t, t + timedelta(minutes=30), "email")
    _seq(db, 3, student, "acknowledged", t, t + timedelta(minutes=60), "ai")
    _seq(db, 4, student, "acknowledged", t, t + timedelta(minutes=12), "call")
    _seq(db, 5, student, "active", t)
    _seq(db, 6, student, "exhausted", t)
    _seq(db, 7, student, "opted_out", t)
    _seq(db, 8, student, "closed", t)
    _seq(db, 9, student, "interview_passed", t)
    out = _summary(client, auth_cookies, "2026-10-20", "2026-10-20")
    assert out["started"] == 9 and out["acknowledged"] == 4
    assert out["acknowledged_by"] == {"sms": 1, "call": 1, "email": 1, "ai": 1}
    assert (out["waiting"], out["no_response"], out["opted_out"], out["stopped_by_approver"], out["interview_passed"]) == (1, 1, 1, 1, 1)
    assert out["avg_minutes_to_acknowledge"] == 27.0                   # (6 + 30 + 60 + 12) / 4


def test_only_notices_started_in_the_range_count(client, db, auth_cookies):
    student = make_student(db)
    _seq(db, 1, student, "active", datetime(2026, 10, 20, 16, 0))
    _seq(db, 2, student, "active", datetime(2026, 10, 10, 16, 0))
    assert _summary(client, auth_cookies, "2026-10-20", "2026-10-20")["started"] == 1
    assert _summary(client, auth_cookies, "2026-10-01", "2026-10-31")["started"] == 2


def test_nothing_started_gives_zeros_and_no_average(client, db, auth_cookies):
    out = _summary(client, auth_cookies, "2026-10-20", "2026-10-20")
    assert out["started"] == 0 and out["acknowledged"] == 0 and out["avg_minutes_to_acknowledge"] is None

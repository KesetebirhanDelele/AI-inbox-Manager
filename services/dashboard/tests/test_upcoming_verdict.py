"""Upcoming interviews: tick for a real interview, cross for a non-interview, dash while undecided (Sehrish/Sonata, 2026-10-19)."""
from conftest import make_email, make_student, make_interview_event, make_notification_draft


def _verdicts(client, auth_cookies):
    return {r["interview_event_id"]: r["verdict"] for r in client.get("/api/interviews/upcoming", cookies=auth_cookies).json()}


def test_approved_is_real_rejected_is_not_pending_is_undecided(client, db, auth_cookies):
    student = make_student(db)
    a = make_interview_event(db, make_email(db, email_id="a"), student=student, company="Acme", interview_date="2099-12-31")
    r = make_interview_event(db, make_email(db, email_id="r"), student=student, company="Rho", interview_date="2099-12-31")
    p = make_interview_event(db, make_email(db, email_id="p"), student=student, company="Pi", interview_date="2099-12-31")
    n = make_interview_event(db, make_email(db, email_id="n"), student=student, company="Nu", interview_date="2099-12-31")
    make_notification_draft(db, a, email_status="approved")
    make_notification_draft(db, r, email_status="rejected")
    make_notification_draft(db, p, email_status="draft")
    assert _verdicts(client, auth_cookies) == {a.id: "real", r.id: "not_interview", p.id: "pending", n.id: "pending"}


def test_a_later_cancellation_naming_the_company_crosses_it_out(client, db, auth_cookies):
    student = make_student(db)
    sonata = make_interview_event(db, make_email(db, email_id="s"), student=student, company="Sonata Software", interview_date="2099-12-31")
    make_notification_draft(db, sonata, email_status="approved")
    make_interview_event(db, make_email(db, email_id="c"), student=student, sub_type="Interview Cancelled", company="Sonata Software", interview_date=None)
    assert _verdicts(client, auth_cookies)[sonata.id] == "not_interview"


def test_a_cancellation_for_another_company_or_student_does_not(client, db, auth_cookies):
    student = make_student(db)
    ev = make_interview_event(db, make_email(db, email_id="s"), student=student, company="Sonata Software", interview_date="2099-12-31")
    make_interview_event(db, make_email(db, email_id="c"), student=student, sub_type="Interview Cancelled", company="CGI", interview_date=None)
    assert _verdicts(client, auth_cookies)[ev.id] == "pending"


def test_identical_events_show_once_with_the_most_certain_verdict(client, db, auth_cookies):
    student = make_student(db)
    first = make_interview_event(db, make_email(db, email_id="1"), student=student, company="Acme", interview_date="2099-12-31")
    second = make_interview_event(db, make_email(db, email_id="2"), student=student, company="Acme", interview_date="2099-12-31")
    make_notification_draft(db, first, email_status="rejected")
    make_notification_draft(db, second, email_status="approved")
    assert _verdicts(client, auth_cookies) == {first.id: "real"}


def test_a_rejected_student_is_not_an_interview_even_with_a_pending_notice(client, db, auth_cookies):
    from models import StudentVerification
    student = make_student(db)
    ev = make_interview_event(db, make_email(db, email_id="o"), student=student, company="ConnectiveTalent", interview_date="2099-12-31")
    make_notification_draft(db, ev, email_status="draft")
    db.add(StudentVerification(student_id=student.id, status="rejected", basis="gmail_guess"))
    db.commit()
    assert _verdicts(client, auth_cookies)[ev.id] == "not_interview"
    assert client.get("/api/stats/summary", cookies=auth_cookies).json()["today_interview_requests"] == 0

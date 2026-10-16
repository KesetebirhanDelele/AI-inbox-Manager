"""A reminder, reply or duplicate confirmation of an interview the student was already told about is a follow-up, not a new notice.
Cases come from Sehrish's queue, 2026-10-15/16 (Calendly + Hydrafacial + Wilson HR + CGI)."""
import sys
from datetime import datetime
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "execution"))

import interview_followup as fu  # noqa: E402


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


def _event(db, status="draft", sub_type="Phone Screen", company=None, date=None, time=None, tz=None, n=[0]):
    M = db.models
    n[0] += 1
    mail = M.Email(email_id=str(n[0]), subject="x", from_address="a@b.com", received_date=datetime.utcnow())
    db.add(mail); db.flush()
    ev = M.InterviewEvent(email_id=mail.id, student_id=db.student.id, sub_type=sub_type, company_name=company,
                          interview_date=date, interview_time=time, interview_timezone=tz, confidence=0.9)
    db.add(ev); db.flush()
    if status:
        db.add(M.NotificationDraft(interview_event_id=ev.id, recipient_email="s@x.com", email_subject="s", email_body="b", email_status=status))
    db.commit()
    return ev


def _fields(sub_type="Phone Screen", company=None, date=None, time=None, tz=None):
    return {"interview_sub_type": sub_type, "company_name": company, "interview_date": date, "interview_time": time, "interview_timezone": tz}


# --- time comparison ---------------------------------------------------------------------------------------------------

def test_noon_pacific_and_three_pm_eastern_are_the_same_moment():
    a = {"interview_date": "2026-10-19", "interview_time": "12:00", "interview_timezone": "PST"}
    b = {"interview_date": "2026-10-19", "interview_time": "15:00", "interview_timezone": "EST"}
    assert fu.same_moment(a, b)


def test_pt_is_read_with_daylight_saving():
    assert fu.interview_instant("2026-10-16", "11:00", "PT") == fu.interview_instant("2026-10-16", "11:00", "PDT")
    assert fu.interview_instant("2026-10-16", "11:00", "PST") == fu.interview_instant("2026-10-16", "11:00", "PDT")   # mail says PST in October
    assert fu.interview_instant("2026-12-16", "11:00", "PT") == fu.interview_instant("2026-12-16", "11:00", "PST")


def test_different_times_or_missing_values_are_not_the_same_moment():
    base = {"interview_date": "2026-10-19", "interview_time": "12:00", "interview_timezone": "PST"}
    assert not fu.same_moment(base, {**base, "interview_time": "13:00"})
    assert not fu.same_moment(base, {**base, "interview_date": "2026-10-20"})
    assert not fu.same_moment(base, {"interview_date": None, "interview_time": None})
    assert not fu.same_moment({}, {})


def test_unreadable_time_zone_needs_identical_clock_time():
    a = {"interview_date": "2026-10-19", "interview_time": "12:00", "interview_timezone": "PST"}
    assert fu.same_moment(a, {**a, "interview_timezone": None})
    assert not fu.same_moment(a, {**a, "interview_timezone": None, "interview_time": "15:00"})


# --- matching against what was already announced -----------------------------------------------------------------------

def test_reply_on_an_approved_interview_is_a_follow_up(db):
    original = _event(db, "approved", date="2026-10-19", time="12:00", tz="PST")                  # Calendly confirmation, company unknown
    got = fu.find_scheduled_interview(db, db.student.id, _fields("Interview Rescheduled", "Hydrafacial", "2026-10-19", "15:00", "EST"))
    assert got == original.id                    # even though the model called it "Rescheduled": the time did not change


def test_a_real_reschedule_to_a_different_time_is_still_a_notice(db):
    _event(db, "approved", date="2026-10-19", time="12:00", tz="PST")
    assert fu.find_scheduled_interview(db, db.student.id, _fields("Interview Rescheduled", None, "2026-10-20", "12:00", "PST")) is None


def test_a_cancellation_is_never_a_follow_up(db):
    _event(db, "approved", date="2026-10-19", time="12:00", tz="PST")
    assert fu.find_scheduled_interview(db, db.student.id, _fields("Interview Cancelled", None, "2026-10-19", "12:00", "PST")) is None


def test_two_different_named_companies_are_different_interviews(db):
    _event(db, "approved", company="CGI", date="2026-10-19", time="13:30", tz="PST")
    assert fu.find_scheduled_interview(db, db.student.id, _fields(company="Hydrafacial", date="2026-10-19", time="13:30", tz="PST")) is None


def test_pending_cards_about_one_interview_group_under_the_oldest(db):
    first = _event(db, "draft", date="2026-10-16", time="11:00", tz="PST")
    second = _event(db, "draft", date="2026-10-16", time="11:00", tz="PT", company="Wilson HR")
    assert fu.find_scheduled_interview(db, db.student.id, _fields(date="2026-10-16", time="11:00", tz="PT"), before_event_id=second.id) == first.id


def test_a_notice_the_approver_rejected_is_asked_again(db):
    _event(db, "rejected", company="CGI", date="2026-10-19", time="13:30", tz="PST")
    assert fu.find_scheduled_interview(db, db.student.id, _fields(company="CGI", date="2026-10-19", time="13:30", tz="PST")) is None


def test_no_date_or_time_or_student_never_matches(db):
    _event(db, "approved", date="2026-10-19", time="12:00", tz="PST")
    assert fu.find_scheduled_interview(db, db.student.id, _fields()) is None
    assert fu.find_scheduled_interview(db, None, _fields(date="2026-10-19", time="12:00", tz="PST")) is None


def test_another_students_interview_does_not_match(db):
    _event(db, "approved", date="2026-10-19", time="12:00", tz="PST")
    other = db.models.Student(username="o", full_name="Other", is_active=True)
    db.add(other); db.commit()
    assert fu.find_scheduled_interview(db, other.id, _fields(date="2026-10-19", time="12:00", tz="PST")) is None


# --- cleaning the queue that exists today ------------------------------------------------------------------------------

def test_existing_pending_duplicates_collapse_onto_the_announced_interview(db):
    original = _event(db, "approved", date="2026-10-19", time="12:00", tz="PST")
    dup1 = _event(db, "draft", sub_type="Interview Rescheduled", company="Hydrafacial", date="2026-10-19", time="15:00", tz="EST")
    dup2 = _event(db, "draft", company="Hydrafacial", date="2026-10-19", time="15:00", tz="EST")
    news = _event(db, "draft", date="2026-10-16", time="11:00", tz="PST")
    cancel = _event(db, "draft", sub_type="Interview Cancelled", company="Wilson HR")

    plan = fu.link_existing_follow_ups(db, dry_run=True)
    assert {p["event_id"] for p in plan} == {dup1.id, dup2.id}
    assert db.query(db.models.InterviewFollowUp).count() == 0                         # dry run changes nothing

    fu.link_existing_follow_ups(db, dry_run=False)
    links = {l.event_id: l.original_event_id for l in db.query(db.models.InterviewFollowUp).all()}
    assert links == {dup1.id: original.id, dup2.id: original.id}
    status = {d.interview_event_id: d.email_status for d in db.query(db.models.NotificationDraft).all()}
    assert status[dup1.id] == status[dup2.id] == "rejected"
    assert status[news.id] == status[cancel.id] == "draft"                            # real news stays for a person


def test_recording_a_follow_up_twice_makes_one_row(db):
    a = _event(db, "approved", date="2026-10-19", time="12:00", tz="PST")
    b = _event(db, None, date="2026-10-19", time="12:00", tz="PST")
    fu.record_follow_up(db, b.id, a.id)
    fu.record_follow_up(db, b.id, a.id)
    assert db.query(db.models.InterviewFollowUp).count() == 1


# --- the suggested action on an open card -----------------------------------------------------------------------------

def _open(db, **kw):
    ev = _event(db, "draft", **kw)
    return ev, db.query(db.models.NotificationDraft).filter_by(interview_event_id=ev.id).one()


def _reject(db, ev, by="admin"):
    d = db.query(db.models.NotificationDraft).filter_by(interview_event_id=ev.id).one()
    d.email_status, d.reviewed_by, d.reviewed_at = "rejected", by, datetime(2026, 10, 15, 17, 21)
    db.commit()
    return d


def test_a_repeat_of_a_rejected_notice_says_reject_and_why(db):
    old = _event(db, "draft", company="CGI", date="2026-10-19", time="13:30", tz="PST")
    rejected = _reject(db, old)
    ev, d = _open(db, company="CGI", date="2026-10-19", time="13:30", tz="PST")
    out = fu.suggested_action(db, ev, d)
    assert out["action"] == "reject" and f"#{rejected.id}" in out["text"] and "rejected by admin on 15 Oct" in out["text"]


def test_a_notice_closed_as_a_follow_up_is_not_quoted_as_a_person_rejecting_it(db):
    old = _event(db, "draft", company="CGI", date="2026-10-19", time="13:30", tz="PST")
    _reject(db, old, by="follow-up")
    ev, d = _open(db, company="CGI", date="2026-10-19", time="13:30", tz="PST")
    assert fu.suggested_action(db, ev, d) is None


def test_a_cancellation_says_check_and_lists_what_was_announced(db):
    _event(db, "approved", company="CGI", date="2026-10-19", time="12:00", tz="PST")
    ev, d = _open(db, sub_type="Interview Cancelled", company="Wilson HR")
    out = fu.suggested_action(db, ev, d)
    assert out["action"] == "check" and "CGI" in out["text"] and "2026-10-19" in out["text"]


def test_a_cancellation_with_nothing_announced_says_so(db):
    ev, d = _open(db, sub_type="Interview Cancelled", company="Wilson HR")
    assert "no interview was announced" in fu.suggested_action(db, ev, d)["text"]


def test_a_real_reschedule_of_the_same_company_says_approve_with_old_and_new_time(db):
    _event(db, "approved", company="CGI", date="2026-10-19", time="12:00", tz="PST")
    ev, d = _open(db, sub_type="Interview Rescheduled", company="CGI", date="2026-10-21", time="12:00", tz="PST")
    out = fu.suggested_action(db, ev, d)
    assert out["action"] == "approve" and "2026-10-19" in out["text"] and "2026-10-21" in out["text"]


def test_a_setup_email_with_no_interview_details_says_reject(db):
    ev, d = _open(db, sub_type="Interview Request")
    assert fu.suggested_action(db, ev, d)["action"] == "reject"


def test_an_ordinary_new_interview_gets_no_suggestion(db):
    ev, d = _open(db, company="Acme", date="2026-10-22", time="09:00", tz="EST")
    assert fu.suggested_action(db, ev, d) is None

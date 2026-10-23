"""Students calling back about an interview: detection, matching, the single alert, the baseline, and the one-business-hour escalation."""
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

_EXEC = Path(__file__).resolve().parents[2] / "execution"
sys.path.insert(0, str(_EXEC))

import business_hours as bh  # noqa: E402
import callbacks as cb  # noqa: E402

CHI = bh.BusinessHours()


def utc(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi) + timedelta(hours=5)          # Chicago (CDT) wall clock as naive UTC


CALLBACK = ("bot:Hey, you have reached Colaberry, School of Data & AI. How can I help you today?\n"
            "human:Hi, I'm returning a call about an interview. I got a text from Colaberry Interview Support.\n"
            "bot:Thank you. A team member from Interview Support will call you back within one business hour.\n"
            "human:Okay thanks.")
SALES = "bot:How can I help you today?\nhuman:I want to learn about the AI course and the price.\nbot:A team member will reach out."
SILENT = "bot:Hey, you have reached Colaberry. How can I help you today?\nbot:Hello? Are you there?"
PROMISE_ONLY = ("bot:How can I help you today?\nhuman:It's about the notice.\n"
                "bot:A team member from Interview Support will call you back shortly. Goodbye.")


def log(transcript, id="c1", duration=40, number="+19725550100", at="2026-10-06T17:00:00.000Z", contact="ct1"):
    return {"id": id, "createdAt": at, "duration": duration, "transcript": transcript, "fromNumber": number, "contactId": contact,
            "agentId": "agent-1", "executedCallActions": []}


# ── detection ───────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("transcript, duration, expected", [
    (CALLBACK, 40, True),
    (PROMISE_ONLY, 30, True),          # the receptionist used the interview-callback wording its prompt prescribes
    (SALES, 40, False),                # an admissions enquiry is not an interview callback
    (SILENT, 40, False),               # the caller said nothing
    (CALLBACK, 2, False),              # too short to be a conversation
    ("", 40, False),
])
def test_interview_callback_detection(transcript, duration, expected):
    assert cb.is_interview_callback(log(transcript, duration=duration)) is expected


# ── due time ────────────────────────────────────────────────────────────────────────────────

def test_a_callback_is_due_one_business_hour_later_skipping_nights_and_weekends():
    assert cb.due_at(utc(2026, 10, 6, 10), CHI) == utc(2026, 10, 6, 11)
    assert cb.due_at(utc(2026, 10, 6, 16, 30), CHI) == utc(2026, 10, 7, 9, 30)
    assert cb.due_at(utc(2026, 10, 3, 12), CHI) == utc(2026, 10, 5, 10)                       # Saturday call: due Monday 10:00


# ── database-backed behaviour ──────────────────────────────────────────────────────────────

@pytest.fixture
def db(monkeypatch):
    monkeypatch.syspath_prepend(str(_EXEC.parents[0] / "services" / "dashboard" / "api"))
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import models
    engine = create_engine("sqlite://")
    models.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.models = models
    return session


class FakeGhl:
    def __init__(self, calls, contacts=None):
        self.calls, self.contacts = calls, contacts or {}

    def voice_ai_agent_calls(self, agent_id, pages=2, page_size=50):
        return self.calls

    def get_contact(self, cid):
        return self.contacts.get(cid, {})


class Mail:
    def __init__(self):
        self.sent = []

    def __call__(self, **kw):
        self.sent.append(kw)
        return {"status": "sent"}


def alerts(db, mail):
    from escalation_engine import RoleAlerts
    return RoleAlerts(db=db, send_fn=mail)


def add_role(db, role, email):
    db.add(db.models.RoleAssignment(role=role, email=email, active=True))
    db.commit()


def add_student(db, **kw):
    s = db.models.Student(username=kw.pop("username", "s1"), full_name=kw.pop("full_name", "Student One"), is_active=True, **kw)
    db.add(s)
    db.commit()
    return s


def test_the_student_is_found_by_the_ghl_contact_email_first_then_by_phone(db):
    by_email = add_student(db, username="a", personal_email="kenya@example.com")
    by_phone = add_student(db, username="b", full_name="Phone Person", phone_number="(972) 555-0199")
    assert cb.find_student(db, "+19999999999", {"email": "KENYA@example.com"}).id == by_email.id
    assert cb.find_student(db, "+19725550199", {}).id == by_phone.id
    assert cb.find_student(db, "+10000000000", {"email": "nobody@example.com", "phone": "+10000000001"}) is None


def test_two_students_matching_is_not_guessed(db):
    add_student(db, username="a", phone_number="972-555-0123")
    add_student(db, username="b", full_name="Other", phone_number="(972) 555-0123")
    assert cb.find_student(db, "+19725550123", None) is None


def test_the_first_run_is_a_baseline_so_old_calls_never_alert_then_a_new_callback_does_once(db):
    add_role(db, "callback_owner", "owner@example.com")
    student = add_student(db, phone_number="972-555-0100")
    mail = Mail()
    now = utc(2026, 10, 6, 9)
    old = log(CALLBACK, id="old", at="2026-10-06T13:00:00.000Z")                       # 08:00 Chicago, before the first run
    out = cb.poll_callbacks(db, FakeGhl([old]), now, alerts(db, mail), "agent-1", CHI)
    assert out["callbacks"] == 0 and out["before_baseline"] == 1 and mail.sent == []

    new = log(CALLBACK, id="new", at="2026-10-06T15:30:00.000Z")                       # 10:30 Chicago
    out = cb.poll_callbacks(db, FakeGhl([new, old]), utc(2026, 10, 6, 10, 40), alerts(db, mail), "agent-1", CHI)
    assert out["callbacks"] == 1 and out["alerted"] == 1
    assert len(mail.sent) == 1 and mail.sent[0]["recipient_email"] == "owner@example.com"
    body = mail.sent[0]["body"]
    assert "Student One" in body and "+19725550100" in body and "never calls back" not in body and "does not call back" in body
    req = db.query(db.models.CallbackRequest).one()
    assert req.student_id == student.id and req.status == "open" and req.alerted_at is not None

    again = cb.poll_callbacks(db, FakeGhl([new]), utc(2026, 10, 6, 10, 50), alerts(db, mail), "agent-1", CHI)
    assert again["callbacks"] == 0 and len(mail.sent) == 1                               # one call, one alert


def test_a_sales_call_creates_nothing_and_a_caller_not_on_the_roster_is_ignored_not_alerted(db):
    add_role(db, "callback_owner", "owner@example.com")
    mail = Mail()
    cb.poll_callbacks(db, FakeGhl([]), utc(2026, 10, 6, 9), alerts(db, mail), "agent-1", CHI)          # baseline
    calls = [log(SALES, id="s1", at="2026-10-06T15:30:00.000Z"), log(CALLBACK, id="u1", number="+10001112222", at="2026-10-06T15:31:00.000Z")]
    out = cb.poll_callbacks(db, FakeGhl(calls), utc(2026, 10, 6, 10, 40), alerts(db, mail), "agent-1", CHI)
    assert out["callbacks"] == 0 and out["ignored"] == 1 and mail.sent == []
    req = db.query(db.models.CallbackRequest).one()
    assert req.student_id is None and req.status == "ignored"
    again = cb.poll_callbacks(db, FakeGhl(calls), utc(2026, 10, 6, 10, 50), alerts(db, mail), "agent-1", CHI)
    assert again["ignored"] == 0 and db.query(db.models.CallbackRequest).count() == 1                  # handled once


def test_with_no_callback_owner_the_callback_is_still_stored_and_the_alert_is_retried_never_lost(db):
    add_student(db, phone_number="972-555-0100")
    mail = Mail()
    cb.poll_callbacks(db, FakeGhl([]), utc(2026, 10, 6, 9), alerts(db, mail), "agent-1", CHI)
    out = cb.poll_callbacks(db, FakeGhl([log(CALLBACK, at="2026-10-06T15:30:00.000Z")]), utc(2026, 10, 6, 10, 40), alerts(db, mail), "agent-1", CHI)
    assert out["callbacks"] == 1 and out["alerted"] == 0 and mail.sent == []
    assert db.query(db.models.CallbackRequest).one().alerted_at is None                  # visible on the dashboard regardless
    add_role(db, "callback_owner", "owner@example.com")                                  # once somebody is assigned the alert goes out
    out = cb.poll_callbacks(db, FakeGhl([log(CALLBACK, at="2026-10-06T15:30:00.000Z")]), utc(2026, 10, 6, 11), alerts(db, mail), "agent-1", CHI)
    assert out["alerted"] == 1 and len(mail.sent) == 1
    assert cb.poll_callbacks(db, FakeGhl([]), utc(2026, 10, 6, 11, 5), alerts(db, mail), "agent-1", CHI)["alerted"] == 0


# ── one business hour ─────────────────────────────────────────────────────────────────────

def make_request(db, received_at, status="open"):
    student = db.query(db.models.Student).first() or add_student(db, phone_number="972-555-0100")
    req = db.models.CallbackRequest(ghl_call_id=f"id{received_at.timestamp()}", received_at=received_at, status=status, caller_number="+19725550100",
                                    student_id=student.id)
    db.add(req)
    db.commit()
    return req


def test_an_open_callback_after_one_business_hour_goes_to_the_escalation_role_once(db):
    add_role(db, "escalation_target", "escalation@example.com")
    add_role(db, "callback_owner", "owner@example.com")
    req = make_request(db, utc(2026, 10, 6, 10))
    mail = Mail()
    assert cb.check_overdue(db, utc(2026, 10, 6, 10, 50), alerts(db, mail), CHI) == 0                  # 50 minutes
    assert cb.check_overdue(db, utc(2026, 10, 6, 11, 5), alerts(db, mail), CHI) == 1
    assert [m["recipient_email"] for m in mail.sent] == ["escalation@example.com"]
    assert cb.check_overdue(db, utc(2026, 10, 6, 12), alerts(db, mail), CHI) == 0                      # not repeated
    db.refresh(req)
    assert req.sla_alerted_at is not None


def test_done_callbacks_and_night_hours_do_not_escalate(db):
    add_role(db, "escalation_target", "escalation@example.com")
    make_request(db, utc(2026, 10, 6, 9), status="done")
    mail = Mail()
    assert cb.check_overdue(db, utc(2026, 10, 6, 15), alerts(db, mail), CHI) == 0
    make_request(db, utc(2026, 10, 6, 16, 45))                       # 15 business minutes before close
    assert cb.check_overdue(db, utc(2026, 10, 7, 8), alerts(db, mail), CHI) == 0                      # overnight does not count
    assert cb.check_overdue(db, utc(2026, 10, 7, 9, 50), alerts(db, mail), CHI) == 1                  # 15 + 50 min


def test_the_overdue_email_tells_the_escalation_role_why_they_called_and_what_we_already_told_them(db):
    """Jackie must be able to call back with the full picture: their words, their interviews, our notices and their replies."""
    from datetime import datetime
    M = db.models
    add_role(db, "escalation_target", "escalation@example.com")
    student = add_student(db, username="omo", full_name="Omolola Adeyemi", phone_number="+19725550100", personal_email="omo@example.com")
    email = M.Email(email_id="1", message_id="<a@x>", subject="s", from_address="hr@globex.com", received_date=datetime(2026, 10, 5, 15, 0))
    db.add(email); db.flush()
    event = M.InterviewEvent(email_id=email.id, student_id=student.id, sub_type="Phone Screen", company_name="Globex",
                             position_title="Data Analyst", interview_date="2026-10-07", interview_time="14:00", confidence=0.9)
    db.add(event); db.flush()
    draft = M.NotificationDraft(interview_event_id=event.id, template_id="t", email_subject="s", email_body="b", recipient_email="omo@example.com")
    db.add(draft); db.flush()
    seq = M.NotificationSequence(draft_id=draft.id, student_id=student.id, status="active", timezone="America/Chicago", timezone_source="default", started_at=utc(2026, 10, 5, 16), ack_token="t")
    db.add(seq); db.flush()
    db.add(M.NotificationAttempt(sequence_id=seq.id, channel="call", step="t0", planned_for=utc(2026, 10, 5, 16), scheduled_for=utc(2026, 10, 5, 16), status="sent", sent_at=utc(2026, 10, 5, 16, 1)))
    db.add(M.NotificationInbound(sequence_id=seq.id, channel="sms", direction="inbound", text="I can't make it, who do I call?",
                                 received_at=utc(2026, 10, 5, 17), ghl_message_id="m1", handled_as="question"))
    req = make_request(db, utc(2026, 10, 6, 10))
    req.student_id, req.said, req.caller_number = student.id, "I got a text about my interview and I have a question", "+19725550100"
    db.commit()
    mail = Mail()
    assert cb.check_overdue(db, utc(2026, 10, 6, 11, 5), alerts(db, mail), CHI) == 1
    body = mail.sent[0]["body"]
    for expected in ("I got a text about my interview and I have a question",   # why they called
                     "Globex", "Data Analyst", "Phone Screen",                    # their interview
                     "we sent a call", "I can't make it, who do I call?",         # what we told them and what they answered
                     "omo@example.com", "+19725550100"):                          # how to reach them
        assert expected in body, expected


def test_an_open_callback_with_no_roster_student_is_never_escalated(db):
    add_role(db, "escalation_target", "escalation@example.com")
    req = make_request(db, utc(2026, 10, 6, 10))
    req.student_id = None                                                  # old row from before the roster check
    db.commit()
    mail = Mail()
    assert cb.check_overdue(db, utc(2026, 10, 6, 11, 5), alerts(db, mail), CHI) == 0 and mail.sent == []

"""
Escalation engine against a real (in-memory) database with fake channels.
No email, text or call is ever sent.
"""
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

_EXECUTION_DIR = Path(__file__).resolve().parents[2] / "execution"
if str(_EXECUTION_DIR) not in sys.path:
    sys.path.insert(0, str(_EXECUTION_DIR))

import escalation_engine as eng  # noqa: E402
import notify_channels as nc  # noqa: E402

T0 = datetime(2026, 10, 5, 20, 0)          # 15:00 CDT, Monday. Student phone 972 -> America/Chicago


@pytest.fixture
def db(monkeypatch):
    api_dir = _EXECUTION_DIR.parents[0] / "services" / "dashboard" / "api"
    monkeypatch.syspath_prepend(str(api_dir))
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import models

    engine = create_engine("sqlite://")
    models.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.models = models
    return session


def make_draft(db, phone="(972) 555-0100", email="student@example.com", name="Test Student"):
    M = db.models
    student = M.Student(username=name.lower().replace(" ", "."), full_name=name, phone_number=phone, is_active=True)
    mail = M.Email(email_id="1", subject="s", from_address="hr@acme.com", received_date=T0)
    db.add_all([student, mail])
    db.flush()
    event = M.InterviewEvent(email_id=mail.id, student_id=student.id, sub_type="Interview Request",
                             company_name="Acme", position_title="Data Analyst", confidence=0.9)
    db.add(event)
    db.flush()
    draft = M.NotificationDraft(interview_event_id=event.id, recipient_email=email, email_subject="Interview",
                                email_body="Body", email_status="approved")
    db.add(draft)
    db.commit()
    return draft, student


class Rec:
    """A fake channel that records every send."""
    def __init__(self, name, status=nc.SENT, boom=False):
        self.name, self.status, self.boom, self.calls = name, status, boom, []

    def send(self, ctx):
        self.calls.append((ctx.attempt.step, ctx.now))
        if self.boom:
            raise RuntimeError("provider exploded")
        return nc.ChannelResult(self.status, detail=None if self.status == nc.SENT else "failed")


def channels(**over):
    base = {"call": Rec("call"), "sms": Rec("sms"), "email": Rec("email")}
    base.update(over)
    return base


def alerts():
    return eng.RoleAlerts(to="rob@example.com", send_fn=lambda **k: {"status": "sent"})


def steps(ch):
    return [s for s, _ in ch.calls]


# -- starting -----------------------------------------------------------------

def test_start_creates_the_whole_plan_and_is_idempotent(db):
    draft, student = make_draft(db)
    seq = eng.start_sequence(db, draft, student, T0, started_by="rob")
    assert seq.status == "active" and seq.timezone == "America/Chicago" and seq.timezone_source == "area_code"
    assert len(seq.attempts) == 15 and all(a.status == "pending" for a in seq.attempts)
    assert len(seq.ack_token) >= 20
    again = eng.start_sequence(db, draft, student, T0 + timedelta(hours=1))
    assert again.id == seq.id and len(again.attempts) == 15


def test_attempts_the_student_cannot_receive_are_recorded_as_skipped(db):
    draft, student = make_draft(db, phone=None, email="")
    seq = eng.start_sequence(db, draft, student, T0)
    states = {(a.channel): a.status for a in seq.attempts}
    assert states == {"call": "skipped", "sms": "skipped", "email": "skipped"}
    assert all(a.detail for a in seq.attempts)


# -- the ladder ---------------------------------------------------------------

def test_day_one_ladder_then_rob_is_told_but_the_sequence_keeps_going(db):
    draft, student = make_draft(db)
    seq = eng.start_sequence(db, draft, student, T0)
    ch, al = channels(), alerts()

    r = eng.tick(db, T0, ch, al)
    assert (r.sent, r.failed) == (3, 0) and steps(ch["call"]) == ["start"]
    eng.tick(db, T0 + timedelta(hours=2), ch, al)
    assert steps(ch["call"]) == ["start"] and steps(ch["sms"]) == ["start"]     # +2h is email only: one call per day
    assert steps(ch["email"]) == ["start", "d1_2h"]
    eng.tick(db, T0 + timedelta(hours=4), ch, al)
    assert steps(ch["sms"]) == ["start", "d1_4h"] and steps(ch["email"]) == ["start", "d1_2h", "d1_4h"]

    assert al.sent == []                                         # not yet
    r = eng.tick(db, T0 + timedelta(hours=6), ch, al)
    assert r.no_response_alerts == 1 and len(al.sent) == 1 and "has not responded" in al.sent[0]
    eng.tick(db, T0 + timedelta(hours=7), ch, al)
    assert len(al.sent) == 1                                     # told once
    db.refresh(seq)
    assert seq.status == "active"                                # telling the approver does NOT stop it


def test_three_more_days_of_one_call_one_text_one_email_then_it_ends_and_rob_is_told(db):
    draft, student = make_draft(db)
    seq = eng.start_sequence(db, draft, student, T0)
    ch, al = channels(), alerts()
    for t in (T0, T0 + timedelta(hours=2), T0 + timedelta(hours=4), T0 + timedelta(hours=6)):
        eng.tick(db, t, ch, al)
    for day in (6, 7, 8):                                        # 9 AM CDT = 14:00 UTC
        eng.tick(db, datetime(2026, 10, day, 14, 0), ch, al)
    assert steps(ch["call"]) == ["start", "day2", "day3", "day4"]               # never two calls on one day
    assert steps(ch["sms"]) == ["start", "d1_4h", "day2", "day3", "day4"]
    assert len(ch["email"].calls) == 3 + 3
    db.refresh(seq)
    assert seq.status == "active"                                # last attempts just went out
    r = eng.tick(db, datetime(2026, 10, 8, 17, 0), ch, al)       # three hours after the last one
    db.refresh(seq)
    assert r.ended == 1 and seq.status == "exhausted"
    assert any("never acknowledged" in s for s in al.sent)
    eng.tick(db, datetime(2026, 10, 9, 14, 0), ch, al)
    assert len(ch["call"].calls) == 4                            # nothing after the end


def test_a_failed_or_crashing_channel_is_recorded_and_does_not_stop_the_others(db):
    draft, student = make_draft(db)
    seq = eng.start_sequence(db, draft, student, T0)
    ch = channels(call=Rec("call", boom=True), sms=Rec("sms", status=nc.FAILED))
    r = eng.tick(db, T0, ch, alerts())
    assert r.failed == 2 and r.sent == 1
    by = {a.channel: a for a in seq.attempts if a.step == "start"}
    assert by["email"].status == "sent" and by["call"].status == "failed" and "crashed" in by["call"].detail
    eng.tick(db, T0, ch, alerts())
    assert len(ch["call"].calls) == 1                            # a failed attempt is not silently retried


def test_dry_run_is_recorded_as_dry_run_never_as_sent_and_leaves_the_draft_unsent(db):
    draft, student = make_draft(db)
    seq = eng.start_sequence(db, draft, student, T0)
    r = eng.tick(db, T0, {k: nc.DryRunChannel(k) for k in ("call", "sms", "email")}, alerts())
    assert r.dry_run == 3 and r.sent == 0
    assert {a.status for a in seq.attempts if a.step == "start"} == {"dry_run"}
    db.refresh(draft)
    assert draft.email_status == "approved"                      # nothing was really delivered


def test_a_real_first_email_marks_the_draft_sent(db):
    draft, student = make_draft(db)
    eng.start_sequence(db, draft, student, T0)
    eng.tick(db, T0, channels(), alerts())
    db.refresh(draft)
    assert draft.email_status == "sent" and draft.sent_at == T0


# -- quiet hours --------------------------------------------------------------

def test_quiet_hours_hold_texts_after_9pm_but_not_email_and_a_held_duplicate_is_skipped(db):
    late = datetime(2026, 10, 6, 0, 30)                          # 19:30 CDT: calls are still open (they stop at 8 PM)
    draft, student = make_draft(db)
    seq = eng.start_sequence(db, draft, student, late)
    ch, al = channels(), alerts()
    eng.tick(db, late, ch, al)
    assert steps(ch["call"]) == ["start"] and steps(ch["sms"]) == ["start"]
    eng.tick(db, late + timedelta(hours=2), ch, al)              # 21:30 CDT: only an email is planned
    assert steps(ch["email"]) == ["start", "d1_2h"]
    eng.tick(db, late + timedelta(hours=4), ch, al)              # 23:30 CDT: the text is held, the email goes
    assert steps(ch["sms"]) == ["start"] and steps(ch["email"])[-1] == "d1_4h"

    r = eng.tick(db, datetime(2026, 10, 6, 13, 0), ch, al)       # 8 AM CDT: the held text is released
    held_sms = next(a for a in seq.attempts if a.channel == "sms" and a.step == "d1_4h")
    # day 2's 9 AM text is due within 3 hours, so the held duplicate is skipped
    assert held_sms.status == "skipped" and r.skipped == 1
    eng.tick(db, datetime(2026, 10, 6, 14, 0), ch, al)           # 9 AM: day 2 goes out normally
    assert steps(ch["call"]) == ["start", "day2"] and steps(ch["sms"]) == ["start", "day2"]


def test_a_call_due_after_8pm_is_held_because_ghl_only_calls_8am_to_8pm_and_the_next_call_covers_it(db):
    after_eight = datetime(2026, 10, 6, 1, 30)                   # 20:30 CDT
    draft, student = make_draft(db)
    seq = eng.start_sequence(db, draft, student, after_eight)
    ch, al = channels(), alerts()
    eng.tick(db, after_eight, ch, al)
    assert ch["call"].calls == [] and steps(ch["sms"]) == ["start"]      # the text is fine until 9 PM, the call is not
    start_call = next(a for a in seq.attempts if a.channel == "call" and a.step == "start")
    assert start_call.scheduled_for == datetime(2026, 10, 6, 13, 0)      # 8 AM CDT next morning
    eng.tick(db, datetime(2026, 10, 6, 13, 0), ch, al)
    assert start_call.status == "skipped"                                # day 2's 9 AM call is within 3 hours
    eng.tick(db, datetime(2026, 10, 6, 14, 0), ch, al)
    assert steps(ch["call"]) == ["day2"]                                 # exactly one call that day


def test_a_california_student_is_never_called_at_6am(db):
    draft, student = make_draft(db, phone="(213) 555-0100")
    seq = eng.start_sequence(db, draft, student, datetime(2026, 10, 5, 13, 0))   # 06:00 PDT
    assert seq.timezone == "America/Los_Angeles"
    ch = channels()
    eng.tick(db, datetime(2026, 10, 5, 13, 0), ch, alerts())
    assert ch["call"].calls == [] and ch["sms"].calls == [] and len(ch["email"].calls) == 1
    eng.tick(db, datetime(2026, 10, 5, 15, 0), ch, alerts())                      # 08:00 PDT
    # the held "start" call is released at 8 AM PDT; the next call is a day away, so it goes
    assert steps(ch["call"]) == ["start"] and ch["call"].calls[0][1] == datetime(2026, 10, 5, 15, 0)


# -- stopping -----------------------------------------------------------------

def test_an_acknowledgement_stops_every_later_attempt(db):
    draft, student = make_draft(db)
    seq = eng.start_sequence(db, draft, student, T0)
    ch, al = channels(), alerts()
    eng.tick(db, T0, ch, al)
    assert eng.acknowledge(db, seq, "sms", "explicit", T0 + timedelta(minutes=5)) is True
    assert eng.acknowledge(db, seq, "email", "explicit", T0 + timedelta(minutes=6)) is False   # already stopped
    eng.tick(db, T0 + timedelta(days=5), ch, al)
    assert len(ch["call"].calls) == 1 and len(ch["sms"].calls) == 1
    assert seq.status == "acknowledged" and (seq.ack_channel, seq.ack_kind) == ("sms", "explicit")
    assert all(a.status in ("sent", "cancelled") for a in seq.attempts)


def test_rob_closing_it_stops_it_and_is_recorded(db):
    draft, student = make_draft(db)
    seq = eng.start_sequence(db, draft, student, T0)
    assert eng.close_sequence(db, seq, "rob", T0) is True
    assert seq.status == "closed" and seq.closed_by == "rob"
    ch = channels()
    eng.tick(db, T0 + timedelta(days=1), ch, alerts())
    assert all(not c.calls for c in ch.values())


def test_the_email_link_acknowledges_once_and_rejects_unknown_tokens(db):
    draft, student = make_draft(db)
    seq = eng.start_sequence(db, draft, student, T0)
    assert eng.acknowledge_by_token(db, "nope", T0) == "unknown"
    assert eng.acknowledge_by_token(db, seq.ack_token, T0) == "acknowledged"
    assert eng.acknowledge_by_token(db, seq.ack_token, T0) == "already"
    assert seq.status == "acknowledged" and seq.ack_channel == "email"


# -- replies ------------------------------------------------------------------

def reply(db, text, phone="972-555-0100", env=None, outcome="understood", conf=0.97, now=None, al=None):
    fn = lambda _m: json.dumps({"outcome": outcome, "confidence": conf, "reason": "test"})
    return eng.handle_inbound_reply(db, phone, text, "sms", now or datetime(2026, 10, 20), al or alerts(),
                                    completion_fn=fn, env=env if env is not None else {})


def test_yes_acknowledges_and_matches_the_phone_in_any_format(db):
    draft, student = make_draft(db, phone="(972) 555-0100")
    seq = eng.start_sequence(db, draft, student, T0)
    out = reply(db, "Yes!", phone="+1 972-555-0100")
    assert out["action"] == "acknowledged" and out["kind"] == "explicit"
    assert seq.status == "acknowledged" and seq.ack_channel == "sms"


def test_stop_ends_all_contact_and_tells_rob(db):
    draft, student = make_draft(db)
    seq = eng.start_sequence(db, draft, student, T0)
    al = alerts()
    out = reply(db, "STOP", al=al)
    assert out["action"] == "opted_out" and seq.status == "opted_out"
    assert any("opted out" in s for s in al.sent)
    ch = channels()
    eng.tick(db, T0 + timedelta(days=1), ch, alerts())
    assert all(not c.calls for c in ch.values())


def test_a_reply_from_an_unknown_number_or_with_no_open_notice_is_ignored(db):
    draft, student = make_draft(db)
    eng.start_sequence(db, draft, student, T0)
    assert reply(db, "yes", phone="212-000-0000")["handled"] is False
    assert reply(db, "yes", phone="")["handled"] is False


def test_shadow_mode_records_the_ais_reading_but_never_stops_the_sequence(db):
    draft, student = make_draft(db)
    seq = eng.start_sequence(db, draft, student, T0)
    out = reply(db, "saw it, I will call them tomorrow", now=datetime(2026, 10, 10))
    assert out == {"handled": True, "action": "recorded", "outcome": "understood", "mode": "shadow"}
    assert seq.status == "active"
    row = db.query(db.models.ReplyAnalysis).one()
    assert (row.shadow, row.acted, row.outcome) == (True, False, "understood")
    assert "saw it" in row.message_text


def test_live_mode_stops_only_on_a_confident_understood(db):
    live = {"REPLY_AI_MODE": "live", "REPLY_AI_SHADOW_UNTIL": "2026-10-16"}
    draft, student = make_draft(db)
    seq = eng.start_sequence(db, draft, student, T0)
    weak = reply(db, "seen it maybe", env=live, conf=0.80)
    assert weak["action"] == "recorded" and seq.status == "active"
    strong = reply(db, "yes I saw it, will call them", env=live, conf=0.97)
    assert strong["kind"] == "ai_inferred" and seq.status == "acknowledged" and seq.ack_channel == "ai"
    acted = db.query(db.models.ReplyAnalysis).filter_by(acted=True).count()
    assert acted == 1


@pytest.mark.parametrize("outcome", ["needs_help", "confused", "unsure"])
def test_replies_that_are_not_understood_go_to_rob_and_do_not_stop_the_sequence(db, outcome):
    draft, student = make_draft(db)
    seq = eng.start_sequence(db, draft, student, T0)
    al = alerts()
    out = reply(db, "who is this?", outcome=outcome, env={"REPLY_AI_MODE": "live", "REPLY_AI_SHADOW_UNTIL": "2026-10-01"}, al=al)
    assert out["action"] == "recorded" and seq.status == "active"
    assert any("may need help" in s for s in al.sent)


def test_role_alerts_are_logged_not_lost_when_no_address_is_configured(db):
    quiet = eng.RoleAlerts(to="", send_fn=lambda **k: pytest.fail("must not send without an address"))
    assert quiet.no_response(None, "Test Student") is False and quiet.sent


# -- deferred and skipped results (text budget, opt-outs) ------------------------

class Scripted:
    """A channel that returns a scripted result the first time, then a normal send."""
    def __init__(self, name, first):
        self.name, self.first, self.calls = name, first, 0

    def send(self, ctx):
        self.calls += 1
        if self.calls == 1:
            return self.first
        return nc.ChannelResult(nc.SENT)


def test_a_deferred_attempt_stays_pending_moves_to_the_retry_time_and_is_not_counted_as_sent(db):
    draft, student = make_draft(db)
    seq = eng.start_sequence(db, draft, student, T0)
    retry = datetime(2026, 10, 6, 19, 5)                          # 14:05 CDT: daytime and 3h+ clear of the day-2 text
    sms = Scripted("sms", nc.ChannelResult(nc.DEFERRED, detail="daily text budget used", retry_at=retry))
    ch = channels(sms=sms)
    r = eng.tick(db, T0, ch, alerts())
    assert (r.deferred, r.sent) == (1, 2)                          # the call and the email still went
    start_sms = next(a for a in seq.attempts if a.channel == "sms" and a.step == "start")
    assert start_sms.status == "pending" and start_sms.scheduled_for == retry and start_sms.sent_at is None
    assert "budget" in start_sms.detail
    eng.tick(db, datetime(2026, 10, 6, 14, 0), ch, alerts())      # the scheduler keeps running: day 2's text goes at 9 AM
    eng.tick(db, retry - timedelta(minutes=1), ch, alerts())
    assert start_sms.status == "pending"                           # not before its own time
    eng.tick(db, retry, ch, alerts())
    assert start_sms.status == "sent" and start_sms.sent_at == retry


def test_a_deferred_retry_that_lands_in_quiet_hours_is_moved_to_8am(db):
    draft, student = make_draft(db)
    seq = eng.start_sequence(db, draft, student, T0)
    in_the_night = datetime(2026, 10, 6, 8, 0)                    # 03:00 CDT
    sms = Scripted("sms", nc.ChannelResult(nc.DEFERRED, retry_at=in_the_night))
    eng.tick(db, T0, channels(sms=sms), alerts())
    start_sms = next(a for a in seq.attempts if a.channel == "sms" and a.step == "start")
    assert start_sms.scheduled_for == datetime(2026, 10, 6, 13, 0)  # 08:00 CDT


def test_a_skipped_result_is_recorded_with_its_reason_and_not_retried(db):
    draft, student = make_draft(db)
    seq = eng.start_sequence(db, draft, student, T0)
    call = Scripted("call", nc.ChannelResult(nc.SKIPPED, detail="not contacted: Call Do-Not-Disturb is active"))
    ch = channels(call=call)
    r = eng.tick(db, T0, ch, alerts())
    assert r.skipped == 1 and any("Do-Not-Disturb" in d for d in r.details)
    start_call = next(a for a in seq.attempts if a.channel == "call" and a.step == "start")
    assert start_call.status == "skipped" and "Do-Not-Disturb" in start_call.detail
    eng.tick(db, T0, ch, alerts())
    assert call.calls == 1


# -- students who can only be found by email, and the approver being told when nobody can be reached ----------------

def recording_alerts():
    sent = []
    al = eng.RoleAlerts(to="rob@example.com", send_fn=lambda **k: sent.append(k) or {"status": "sent"})
    al.record = sent
    return al


def test_a_student_with_an_email_but_no_phone_keeps_their_call_and_text_attempts(db):
    draft, student = make_draft(db, phone=None, email="s@example.com")
    student.personal_email = "student.personal@example.com"
    db.commit()
    seq = eng.start_sequence(db, draft, student, T0)
    assert all(a.status == "pending" for a in seq.attempts)            # the GHL contact may hold the phone


def test_a_student_with_nothing_on_file_tells_rob_immediately_and_only_once(db):
    draft, student = make_draft(db, phone=None, email="")
    seq = eng.start_sequence(db, draft, student, T0)
    al = recording_alerts()
    eng.tick(db, T0, channels(), al)
    eng.tick(db, T0 + timedelta(minutes=5), channels(), al)
    assert len(al.record) == 1 and "Cannot reach" in al.record[0]["subject"]
    assert "no email, phone number or Gmail" in al.record[0]["body"] and "changed their email" in al.record[0]["body"]


def test_an_unreachable_failure_tells_rob_once_with_the_reason(db):
    draft, student = make_draft(db)
    eng.start_sequence(db, draft, student, T0)

    class Unreachable:
        def send(self, ctx):
            return nc.ChannelResult(nc.FAILED, detail=nc.UNREACHABLE + "no GHL contact matches this student's email")

    al = recording_alerts()
    eng.tick(db, T0, channels(call=Unreachable(), sms=Unreachable(), email=Unreachable()), al)
    eng.tick(db, T0 + timedelta(hours=2), channels(email=Unreachable()), al)
    assert len(al.record) == 1 and "no GHL contact matches" in al.record[0]["body"]


def test_an_ordinary_failure_does_not_page_rob_about_contact_details(db):
    draft, student = make_draft(db)
    eng.start_sequence(db, draft, student, T0)
    al = recording_alerts()
    eng.tick(db, T0, channels(call=Rec("call", status=nc.FAILED)), al)
    assert not any("Cannot reach" in k["subject"] for k in al.record)


# -- spacing between students (Kes 2026-10-12: do not stack contacts on the shared phone line) -------------

def _two_students(db):
    d1, s1 = make_draft(db, phone="(972) 555-0101", email="a@example.com", name="First Student")
    M = db.models
    mail2 = M.Email(email_id="2", subject="s2", from_address="hr@acme.com", received_date=T0)
    s2 = M.Student(username="second.student", full_name="Second Student", phone_number="(972) 555-0102", is_active=True)
    db.add_all([mail2, s2]); db.flush()
    ev2 = M.InterviewEvent(email_id=mail2.id, student_id=s2.id, sub_type="Interview Request", company_name="Beta",
                           position_title="Analyst", confidence=0.9)
    db.add(ev2); db.flush()
    d2 = M.NotificationDraft(interview_event_id=ev2.id, recipient_email="b@example.com", email_subject="Interview",
                             email_body="Body", email_status="approved")
    db.add(d2); db.commit()
    return (d1, s1), (d2, s2)


def test_the_next_student_waits_three_minutes_but_one_student_gets_call_text_and_email_together(db):
    (d1, s1), (d2, s2) = _two_students(db)
    q1 = eng.start_sequence(db, d1, s1, T0)
    q2 = eng.start_sequence(db, d2, s2, T0 + timedelta(seconds=1))
    ch, al = channels(), alerts()

    r = eng.tick(db, T0 + timedelta(minutes=1), ch, al)
    assert r.sent == 3 and r.spaced == 3                                  # the first student: all three channels; the second is held
    assert len(ch["call"].calls) == len(ch["sms"].calls) == len(ch["email"].calls) == 1

    r = eng.tick(db, T0 + timedelta(minutes=3), ch, al)                   # only 2 minutes after the first contact: still held
    assert r.sent == 0 and r.spaced == 3

    r = eng.tick(db, T0 + timedelta(minutes=4), ch, al)                   # 3 minutes after the first contact: the second student goes
    assert r.sent == 3 and r.spaced == 0
    assert len(ch["call"].calls) == 2


def test_a_burst_of_students_goes_out_one_per_spacing_oldest_first(db):
    (d1, s1), (d2, s2) = _two_students(db)
    q2 = eng.start_sequence(db, d2, s2, T0)                               # the second student's notice was approved first
    q1 = eng.start_sequence(db, d1, s1, T0 + timedelta(minutes=1))
    ch, al = channels(), alerts()
    eng.tick(db, T0 + timedelta(minutes=2), ch, al)
    first = {a.sequence_id for a in q2.attempts + q1.attempts if a.status == "sent"}
    assert first == {q2.id}                                               # the one who waited longest went first


def test_spacing_counts_logged_shadow_sends_too_and_can_be_switched_off(db, monkeypatch):
    (d1, s1), (d2, s2) = _two_students(db)
    eng.start_sequence(db, d1, s1, T0)
    eng.start_sequence(db, d2, s2, T0)
    dry = {"call": Rec("call", status=nc.DRY_RUN), "sms": Rec("sms", status=nc.DRY_RUN), "email": Rec("email", status=nc.DRY_RUN)}
    r = eng.tick(db, T0, dry, alerts())
    assert r.dry_run == 3 and r.spaced == 3                               # shadow rehearsal behaves like the real thing

    monkeypatch.setenv("NOTIFY_LEAD_SPACING_MINUTES", "0")
    r = eng.tick(db, T0, dry, alerts())
    assert r.dry_run == 3 and r.spaced == 0                               # 0 minutes = no spacing


def test_the_setting_is_read_from_the_environment_with_a_safe_default(monkeypatch):
    monkeypatch.delenv("NOTIFY_LEAD_SPACING_MINUTES", raising=False)
    assert eng.lead_spacing() == timedelta(minutes=3)
    monkeypatch.setenv("NOTIFY_LEAD_SPACING_MINUTES", "5")
    assert eng.lead_spacing() == timedelta(minutes=5)
    monkeypatch.setenv("NOTIFY_LEAD_SPACING_MINUTES", "garbage")
    assert eng.lead_spacing() == timedelta(minutes=3)

"""
Polling the student's GHL Conversations and Voice AI call logs for replies and calls: acts like a webhook
reply would, handles each message or call once, and only ever reads the student's side of a call.
Fake GHL client; no network.
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
import ghl_client as gc  # noqa: E402
import notify_channels as nc  # noqa: E402
from tests.execution.test_escalation_engine import alerts, db, make_draft  # noqa: E402,F401  (shared fixtures)

T0 = datetime(2026, 10, 5, 20, 0)
NOW = datetime(2026, 10, 5, 20, 30)
LIVE_AI = {"REPLY_AI_MODE": "live", "REPLY_AI_SHADOW_UNTIL": "2026-10-01"}


class HandedToGhl:
    """A channel that behaves like a real GHL send: records the contact id as the provider id."""
    def __init__(self, name):
        self.name = name

    def send(self, ctx):
        return nc.ChannelResult(nc.SENT, provider_id="contact-1")


class FakeConv:
    def __init__(self, messages=None, call_logs=None, read_error=None, call_error=None):
        self.messages, self.call_logs = messages or [], call_logs or []
        self.read_error, self.call_error = read_error, call_error
        self.call_log_requests = []

    def conversations_for_contact(self, contact_id):
        if self.read_error:
            raise self.read_error
        return [{"id": "conv1"}]

    def conversation_messages(self, conversation_id):
        return self.messages

    def voice_ai_call_logs(self, contact_id, agent_id=None, page_size=20):
        self.call_log_requests.append((contact_id, agent_id))
        if self.call_error:
            raise self.call_error
        return self.call_logs


def started(db, **kw):
    draft, student = make_draft(db, **kw)
    seq = eng.start_sequence(db, draft, student, T0)
    eng.tick(db, T0, {k: HandedToGhl(k) for k in ("call", "sms", "email")}, alerts())
    return seq


def msg(id, body="", type_="TYPE_SMS", direction="inbound", at="2026-10-05T20:10:00.000Z", **extra):
    return {"id": id, "messageType": type_, "direction": direction, "body": body, "dateAdded": at, **extra}


def poll(db, conv, now=NOW, env=None, fn=None, al=None):
    return eng.poll_replies(db, now, conv, al or alerts(), completion_fn=fn, env=env if env is not None else {})


def inbound_rows(db):
    return {(r.ghl_message_id, r.handled_as) for r in db.query(db.models.NotificationInbound).all()}


understood = lambda _m: json.dumps({"outcome": "understood", "confidence": 0.97, "reason": "saw it"})


# -- texts and emails ---------------------------------------------------------------

def test_a_yes_reply_in_the_conversation_acknowledges_and_is_recorded(db):
    seq = started(db)
    report = poll(db, FakeConv([msg("m1", "YES")]))
    assert (report.new_messages, report.stopped) == (1, 1)
    assert seq.status == "acknowledged" and seq.ack_channel == "sms" and seq.ack_kind == "explicit"
    assert inbound_rows(db) == {("m1", "yes_rule")}


def test_each_message_is_handled_once_even_if_it_is_still_in_the_conversation(db):
    seq = started(db)
    conv = FakeConv([msg("m1", "who is this?")])
    first = poll(db, conv, fn=lambda _m: json.dumps({"outcome": "confused", "confidence": 0.9, "reason": "x"}))
    second = poll(db, conv, fn=lambda _m: pytest.fail("a message must not be analysed twice"))
    assert (first.new_messages, second.new_messages) == (1, 0)
    assert db.query(db.models.ReplyAnalysis).count() == 1 and seq.status == "active"


def test_our_own_texts_old_messages_and_email_echoes_are_ignored(db):
    seq = started(db)
    conv = FakeConv([
        msg("out", "YES", direction="outbound"),                                       # our own text
        msg("old", "YES", at="2026-10-05T19:00:00.000Z"),                              # before the sequence began
        msg("echo", f"confirm at https://x/ack/{seq.ack_token}", type_="TYPE_EMAIL"),  # our email logged as inbound
    ])
    assert poll(db, conv).new_messages == 0 and seq.status == "active"


def test_stop_in_the_conversation_ends_all_contact_and_tells_rob(db):
    seq = started(db)
    al = alerts()
    poll(db, FakeConv([msg("m1", "STOP")]), al=al)
    assert seq.status == "opted_out" and any("opted out" in s for s in al.sent)
    assert inbound_rows(db) == {("m1", "stop_rule")}


def test_a_free_text_email_reply_is_read_by_the_ai_but_only_records_it_in_shadow_mode(db):
    seq = started(db)
    conv = FakeConv([msg("e1", "Got the notice, I will call them tomorrow", type_="TYPE_EMAIL")])
    poll(db, conv, env={}, fn=understood)
    assert seq.status == "active" and db.query(db.models.ReplyAnalysis).one().shadow is True


def test_the_same_reply_stops_the_sequence_when_the_ai_is_live_and_confident(db):
    seq = started(db)
    poll(db, FakeConv([msg("e1", "Got the notice, I will call them tomorrow", type_="TYPE_EMAIL")]),
         env=LIVE_AI, fn=understood)
    assert seq.status == "acknowledged" and seq.ack_kind == "ai_inferred"


def test_a_student_with_two_open_notices_has_each_reply_handled_once_for_both(db):
    first = started(db)
    # a second interview for the same student: same GHL contact, a newer sequence
    M = db.models
    event = M.InterviewEvent(email_id=first.attempts[0].sequence_id, student_id=first.student_id,
                             sub_type="Interview Request", company_name="Beta", confidence=0.9)
    mail = M.Email(email_id="2", subject="s2", from_address="hr@beta.com", received_date=T0)
    db.add(mail); db.flush()
    event.email_id = mail.id
    db.add(event); db.flush()
    draft2 = M.NotificationDraft(interview_event_id=event.id, recipient_email="student@example.com",
                                 email_subject="Interview 2", email_body="Body", email_status="approved")
    db.add(draft2); db.commit()
    student = db.get(M.Student, first.student_id)
    second = eng.start_sequence(db, draft2, student, T0 + timedelta(minutes=1))
    eng.tick(db, T0 + timedelta(minutes=1), {k: HandedToGhl(k) for k in ("call", "sms", "email")}, alerts())
    # the second notice waits for the spacing after the first student contact (3 minutes by default), then goes out
    eng.tick(db, T0 + timedelta(minutes=5), {k: HandedToGhl(k) for k in ("call", "sms", "email")}, alerts())

    report = poll(db, FakeConv([msg("m1", "YES")]))
    assert report.new_messages == 1 and report.stopped == 1            # one message, handled once
    assert first.status == "acknowledged" and second.status == "acknowledged"
    assert db.query(M.NotificationInbound).count() == 1                # and recorded once, no duplicate error


def test_a_sequence_with_no_real_send_yet_is_not_polled(db):
    draft, student = make_draft(db)
    eng.start_sequence(db, draft, student, T0)                                        # nothing sent, no contact id
    conv = FakeConv([msg("m1", "YES")])
    assert poll(db, conv).sequences == 0 and inbound_rows(db) == set()


def test_a_failed_read_is_counted_and_never_crashes_or_changes_anything(db):
    seq = started(db)
    report = poll(db, FakeConv(read_error=gc.GhlError("GHL HTTP 500")))
    assert report.errors == 1 and "could not read conversations" in report.details[0] and seq.status == "active"


# -- calls (Voice AI call logs) ---------------------------------------------------------

CALL_TRANSCRIPT = ("bot: Hello, this is Colaberry about your interview with Acme.\n"
                   "human: Yes I got it, I will call them tomorrow.\n"
                   "bot: Thank you, goodbye.")


def call_log(id="L1", duration=45, transcript=CALL_TRANSCRIPT, at="2026-10-05T20:10:00.000Z"):
    return {"id": id, "duration": duration, "transcript": transcript, "createdAt": at, "summary": "s",
            "executedCallActions": []}


def test_only_the_students_lines_of_a_call_reach_the_ai_and_a_confident_understood_stops_it_when_live(db):
    seen = []

    def fn(messages):
        seen.append(messages[1]["content"])
        return understood(messages)

    seq = started(db)
    poll(db, FakeConv(call_logs=[call_log()]), env=LIVE_AI, fn=fn)
    assert seq.status == "acknowledged" and seq.ack_channel == "ai" and seq.ack_kind == "ai_inferred"
    assert "I will call them tomorrow" in seen[0]
    assert "this is Colaberry" not in seen[0] and "goodbye" not in seen[0]            # the agent's words never reach the AI
    assert inbound_rows(db) == {("voiceai:L1", "ai")}


def test_a_call_in_shadow_mode_is_recorded_but_stops_nothing(db):
    seq = started(db)
    poll(db, FakeConv(call_logs=[call_log()]), env={}, fn=understood)
    assert seq.status == "active" and db.query(db.models.ReplyAnalysis).one().acted is False


def test_a_call_that_ends_the_conversation_with_a_question_goes_to_rob(db):
    seq = started(db)
    al = alerts()
    fn = lambda _m: json.dumps({"outcome": "needs_help", "confidence": 0.9, "reason": "wants to move it"})
    poll(db, FakeConv(call_logs=[call_log(transcript="bot: Hi\nhuman: I cannot make Tuesday, can it move?")]),
         env=LIVE_AI, fn=fn, al=al)
    assert seq.status == "active" and any("may need help" in s for s in al.sent)


@pytest.mark.parametrize("duration, transcript", [
    (4, "human: yes"),                                    # too short to be a conversation
    (45, "bot: Hello? Is anyone there?"),                 # nobody answered
    (0, ""),
])
def test_a_call_that_did_not_reach_a_person_is_recorded_and_never_analysed(db, duration, transcript):
    seq = started(db)
    poll(db, FakeConv(call_logs=[call_log(duration=duration, transcript=transcript)]),
         fn=lambda _m: pytest.fail("must not analyse a call that reached no one"))
    assert seq.status == "active" and inbound_rows(db) == {("voiceai:L1", "call_recorded")}


def test_a_call_is_handled_once_and_calls_before_the_sequence_are_ignored(db):
    seq = started(db)
    conv = FakeConv(call_logs=[call_log("old", at="2026-10-05T19:00:00.000Z"), call_log("new")])
    first = poll(db, conv, env=LIVE_AI, fn=understood)
    second = poll(db, conv, env=LIVE_AI, fn=lambda _m: pytest.fail("a call must not be analysed twice"))
    assert first.new_messages == 1 and second.new_messages == 0
    assert inbound_rows(db) == {("voiceai:new", "ai")}


def test_the_outbound_agent_id_is_passed_to_the_call_log_request(db):
    started(db)
    conv = FakeConv()
    poll(db, conv, env={"GHL_VOICE_AGENT_ID": "agent-outbound"})
    assert conv.call_log_requests == [("contact-1", "agent-outbound")]
    conv2 = FakeConv()
    poll(db, conv2, env={})
    assert conv2.call_log_requests == [("contact-1", None)]


def test_a_failed_call_log_read_is_counted_and_does_not_stop_the_text_and_email_reads(db):
    seq = started(db)
    conv = FakeConv(messages=[msg("m1", "YES")], call_error=gc.GhlError("GHL HTTP 500"))
    report = poll(db, conv)
    assert report.errors == 1 and "call logs" in report.details[0]
    assert seq.status == "acknowledged"                                   # the text was still read


def test_once_a_message_stops_the_sequence_later_ones_are_not_acted_on(db):
    seq = started(db)
    conv = FakeConv([msg("a", "YES", at="2026-10-05T20:05:00.000Z"), msg("b", "STOP", at="2026-10-05T20:06:00.000Z")])
    report = poll(db, conv)
    assert report.stopped == 1 and seq.status == "acknowledged"          # not flipped to opted_out afterwards


# ── calls decided by rule (the real 2026-10-02 test call, trimmed) ─────────────────────────────
REAL_CALL = (
    "bot:Hi Kes, this is Colaberry, School of Data & AI's AI assistant.\n"
    "human:How can I help you today? \n"
    "bot:I'm calling to share information about your upcoming interview. Would you like to hear the details now?\n"
    "human:Yes, please. \n"
    "bot:You're scheduled for a phone screen with Test Company.\n\nCan you confirm you got this information? Just say yes.\n"
    "human:Yes. \n"
    "bot:Great, thank you for confirming.\n"
    "human:That's all. Thank you so much. \n"
)


def test_a_plain_yes_to_the_confirmation_question_acknowledges_even_in_shadow_mode(db):
    seq = started(db)
    poll(db, FakeConv(call_logs=[call_log(transcript=REAL_CALL)]), env={}, fn=lambda _m: pytest.fail("a rule decided this"))
    assert seq.status == "acknowledged" and seq.ack_channel == "call" and seq.ack_kind == "explicit"
    assert inbound_rows(db) == {("voiceai:L1", "yes_rule")}


def test_a_yes_before_the_details_were_given_is_not_an_acknowledgement(db):
    seq = started(db)
    transcript = ("bot:Would you like to hear the details now?\nhuman:Yes, please.\n"
                  "bot:Here they are... Can you confirm you got this information? Just say yes.\nhuman:Hmm, say that again?")
    poll(db, FakeConv(call_logs=[call_log(transcript=transcript)]), env={}, fn=understood)
    assert seq.status == "active"


def test_yes_but_is_not_a_confirmation(db):
    seq = started(db)
    transcript = "bot:Can you confirm you got this information? Just say yes.\nhuman:Yes but I can't make that day"
    poll(db, FakeConv(call_logs=[call_log(transcript=transcript)]), env={}, fn=understood)
    assert seq.status == "active"


def test_dont_call_me_again_on_a_call_opts_out_and_remembers_it(db):
    seq = started(db)
    al = alerts()
    transcript = "bot:Hi Kes\nhuman:Please don't call me again."
    poll(db, FakeConv(call_logs=[call_log(transcript=transcript)]), env={}, al=al, fn=lambda _m: pytest.fail("rule"))
    assert seq.status == "opted_out" and any("opted out" in s for s in al.sent)
    row = db.query(db.models.NotificationOptOut).one()
    assert row.channel == "call" and row.source == "stop_call" and len(row.phone_tail) == 10


def test_a_stop_text_remembers_the_text_opt_out_once(db):
    seq = started(db)
    poll(db, FakeConv([msg("m1", "STOP")]))
    rows = db.query(db.models.NotificationOptOut).all()
    assert [(r.channel, r.source) for r in rows] == [("sms", "stop_text")]

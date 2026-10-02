"""
Polling the student's GHL Conversations for replies and calls: acts like a webhook reply would, handles
each message once, and never lets an unreadable call stop a sequence. Fake GHL client; no network.
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
    def __init__(self, messages=None, sentences=None, read_error=None):
        self.messages, self.sentences, self.read_error = messages or [], sentences, read_error
        self.transcript_reads = []

    def conversations_for_contact(self, contact_id):
        if self.read_error:
            raise self.read_error
        return [{"id": "conv1"}]

    def conversation_messages(self, conversation_id):
        return self.messages

    def message_transcription(self, message_id):
        self.transcript_reads.append(message_id)
        return self.sentences


def started(db, **kw):
    draft, student = make_draft(db, **kw)
    seq = eng.start_sequence(db, draft, student, T0)
    eng.tick(db, T0, {k: HandedToGhl(k) for k in ("call", "sms", "email")}, alerts())
    return seq


def msg(id, body="", type_="TYPE_SMS", direction="inbound", at="2026-10-05T20:10:00.000Z", **extra):
    return {"id": id, "messageType": type_, "direction": direction, "body": body, "dateAdded": at, **extra}


def poll(db, conv, now=NOW, env=None, fn=None, al=None, channel=None):
    return eng.poll_replies(db, now, conv, al or alerts(), completion_fn=fn, env=env if env is not None else {},
                            student_media_channel=channel)


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
    assert report.errors == 1 and "could not read" in report.details[0] and seq.status == "active"


# -- calls ----------------------------------------------------------------------------

SENTENCES = [
    {"mediaChannel": 1, "sentenceIndex": 0, "transcript": "Hello, this is Colaberry about your interview."},
    {"mediaChannel": 2, "sentenceIndex": 1, "transcript": "Yes I got it, I will call them tomorrow."},
]
CALL = msg("call1", type_="TYPE_CALL", direction="outbound", status="completed")


def test_a_call_whose_speakers_cannot_be_told_apart_is_never_analysed_and_rob_is_told_once(db):
    seq = started(db)
    al = alerts()
    conv = FakeConv([CALL], sentences=SENTENCES)
    poll(db, conv, al=al, fn=lambda _m: pytest.fail("must not analyse an unattributed transcript"))   # channel not configured
    poll(db, conv, al=al)
    assert seq.status == "active" and inbound_rows(db) == {("call1", "call_unreadable")}
    assert sum("could not be read" in s for s in al.sent) == 1


def test_a_call_with_the_student_channel_configured_is_judged_on_the_students_words_only(db):
    seen = []

    def fn(messages):
        seen.append(messages[1]["content"])
        return understood(messages)

    seq = started(db)
    poll(db, FakeConv([CALL], sentences=SENTENCES), env=LIVE_AI, fn=fn, channel="2")
    assert seq.status == "acknowledged" and seq.ack_channel == "ai"
    assert "I will call them tomorrow" in seen[0] and "this is Colaberry" not in seen[0]       # the agent's words never reach the AI
    assert inbound_rows(db) == {("call1", "ai")}


def test_a_call_in_shadow_mode_is_recorded_but_stops_nothing(db):
    seq = started(db)
    poll(db, FakeConv([CALL], sentences=SENTENCES), env={}, fn=understood, channel="2")
    assert seq.status == "active" and db.query(db.models.ReplyAnalysis).one().acted is False


@pytest.mark.parametrize("status", ["voicemail", "no-answer", "busy", "failed"])
def test_a_call_that_did_not_connect_is_recorded_without_reading_a_transcript(db, status):
    seq = started(db)
    conv = FakeConv([msg("c", type_="TYPE_CALL", direction="outbound", status=status)], sentences=SENTENCES)
    poll(db, conv, channel="2")
    assert seq.status == "active" and conv.transcript_reads == [] and inbound_rows(db) == {("c", "call_recorded")}


def test_a_transcript_that_is_not_ready_is_retried_until_the_grace_period_ends(db):
    seq = started(db)
    conv = FakeConv([CALL], sentences=None)
    poll(db, conv, now=datetime(2026, 10, 5, 20, 20))                 # call at 20:10: only 10 minutes old
    assert inbound_rows(db) == set()                                   # try again next poll
    poll(db, conv, now=datetime(2026, 10, 5, 20, 40))                 # 30 minutes: give up
    assert inbound_rows(db) == {("call1", "call_no_transcript")} and seq.status == "active"


def test_a_call_where_the_student_said_nothing_is_recorded_not_analysed(db):
    seq = started(db)
    only_agent = [SENTENCES[0]]
    poll(db, FakeConv([CALL], sentences=only_agent), channel="2", fn=lambda _m: pytest.fail("nothing to analyse"))
    assert inbound_rows(db) == {("call1", "call_recorded")} and seq.status == "active"


def test_once_a_message_stops_the_sequence_later_ones_are_not_acted_on(db):
    seq = started(db)
    conv = FakeConv([msg("a", "YES", at="2026-10-05T20:05:00.000Z"), msg("b", "STOP", at="2026-10-05T20:06:00.000Z")])
    report = poll(db, conv)
    assert report.stopped == 1 and seq.status == "acknowledged"          # not flipped to opted_out afterwards

"""Parsing and fetching the student's messages from GHL Conversations. Fake client; no network."""
import sys
from datetime import datetime
from pathlib import Path

import pytest

_EXECUTION_DIR = Path(__file__).resolve().parents[2] / "execution"
if str(_EXECUTION_DIR) not in sys.path:
    sys.path.insert(0, str(_EXECUTION_DIR))

import ghl_conversations as gcv  # noqa: E402


@pytest.mark.parametrize("value, expected", [
    ("2026-10-05T20:10:00.000Z", datetime(2026, 10, 5, 20, 10)),
    ("2026-10-05T15:10:00-05:00", datetime(2026, 10, 5, 20, 10)),
    (1791231000, datetime(2026, 10, 5, 20, 10)),             # epoch seconds
    (1791231000000, datetime(2026, 10, 5, 20, 10)),          # epoch milliseconds
    ("", None), (None, None), ("not a date", None),
])
def test_parse_time(value, expected):
    assert gcv.parse_time(value) == expected


@pytest.mark.parametrize("raw, channel", [
    ("TYPE_SMS", "sms"), ("SMS", "sms"), ("TYPE_EMAIL", "email"), ("Email", "email"),
    ("TYPE_CALL", "call"), ("TYPE_ACTIVITY_APPOINTMENT", None), ("Activity", None), ("", None), (None, None),
])
def test_channel_of(raw, channel):
    assert gcv.channel_of(raw) == channel


def test_normalize_reads_the_fields_and_drops_notes_and_activity():
    m = gcv.normalize({"id": "m1", "messageType": "TYPE_SMS", "direction": "Inbound", "body": " YES ",
                       "dateAdded": "2026-10-05T20:10:00.000Z", "status": "Delivered"})
    assert (m.id, m.channel, m.direction, m.text, m.status) == ("m1", "sms", "inbound", "YES", "delivered")
    email = gcv.normalize({"id": "m2", "messageType": "TYPE_EMAIL", "direction": "inbound", "body": "hi",
                           "meta": {"email": {"subject": "Re: Interview"}}})
    assert email.subject == "Re: Interview"
    assert gcv.normalize({"id": "m3", "messageType": "TYPE_ACTIVITY_NOTE"}) is None
    assert gcv.normalize({"messageType": "TYPE_SMS"}) is None                      # no id


def test_echo_filter_only_applies_to_emails_that_carry_our_markers():
    ours = gcv.ConversationMessage("1", "email", "inbound", "Please confirm: https://x/ack/TOKEN123", None, "", "Interview (Ref 7)")
    theirs = gcv.ConversationMessage("2", "email", "inbound", "Got it, thanks", None, "", "Re: Interview")
    sms = gcv.ConversationMessage("3", "sms", "inbound", "TOKEN123", None)
    markers = ["TOKEN123", "Interview (Ref 7)", None, ""]
    assert gcv.is_echo(ours, markers) is True
    assert gcv.is_echo(theirs, ["TOKEN123"]) is False
    assert gcv.is_echo(sms, markers) is False                                        # texts are never echoes


SENTENCES = [
    {"mediaChannel": 1, "sentenceIndex": 0, "transcript": "Hello, this is Colaberry about your interview."},
    {"mediaChannel": 2, "sentenceIndex": 1, "transcript": "Yes, I got it."},
    {"mediaChannel": 1, "sentenceIndex": 2, "transcript": "Great, can you confirm?"},
    {"mediaChannel": 2, "sentenceIndex": 3, "transcript": "Confirmed."},
]


def test_student_words_are_only_the_students_channel_in_order():
    assert gcv.student_words(SENTENCES, "2") == "Yes, I got it. Confirmed."
    assert gcv.student_words(SENTENCES, 2) == "Yes, I got it. Confirmed."


def test_student_words_is_none_when_we_cannot_tell_who_is_who():
    assert gcv.student_words(SENTENCES, None) is None            # channel not configured: never analyse
    assert gcv.student_words(None, "2") is None                  # no transcript
    assert gcv.student_words([], "2") == ""                      # a transcript, but the student said nothing


class FakeConv:
    def __init__(self, messages):
        self.messages = messages

    def conversations_for_contact(self, contact_id):
        return [{"id": "conv1"}]

    def conversation_messages(self, conversation_id):
        return self.messages


SINCE = datetime(2026, 10, 5, 20, 0)


def raw(id, type_="TYPE_SMS", direction="inbound", body="yes", at="2026-10-05T20:10:00.000Z", **extra):
    return {"id": id, "messageType": type_, "direction": direction, "body": body, "dateAdded": at, **extra}


def test_fetch_keeps_inbound_replies_and_calls_and_drops_everything_else():
    client = FakeConv([
        raw("sms-in"),
        raw("sms-out", direction="outbound"),                                    # our own text
        raw("old", at="2026-10-05T19:00:00.000Z"),                               # before the sequence began
        raw("echo", type_="TYPE_EMAIL", body="link https://x/ack/TOK"),
        raw("email-in", type_="TYPE_EMAIL", body="Got it, thanks"),
        raw("call", type_="TYPE_CALL", direction="outbound", body="", meta={"call": {"status": "completed", "duration": 30}}),
        raw("note", type_="TYPE_ACTIVITY_NOTE"),
        raw("seen"),
    ])
    got = gcv.fetch_new_messages(client, "c1", SINCE, {"seen"}, markers=["TOK"])
    assert [m.id for m in got] == ["sms-in", "email-in", "call"]


def test_fetch_returns_oldest_first():
    client = FakeConv([raw("b", at="2026-10-05T20:20:00.000Z"), raw("a", at="2026-10-05T20:05:00.000Z")])
    assert [m.id for m in gcv.fetch_new_messages(client, "c1", SINCE, set())] == ["a", "b"]


def test_a_calls_status_and_duration_come_from_meta_call():
    m = gcv.normalize({"id": "c1", "messageType": "TYPE_CALL", "direction": "outbound",
                       "meta": {"call": {"status": "Completed", "duration": 45}}})
    assert (m.status, m.duration) == ("completed", 45) and gcv.is_connected_call(m)


@pytest.mark.parametrize("meta, connected", [
    ({"call": {"status": "completed", "duration": 45}}, True),
    ({"call": {"status": "completed", "duration": 10}}, True),
    ({"call": {"status": "completed", "duration": 9}}, False),
    ({"call": {"status": "completed"}}, False),
    ({"call": {"status": "voicemail", "duration": 60}}, False),
    ({"call": {"status": "busy", "duration": 0}}, False),
    ({}, False),
    ({"call": {"status": "completed", "duration": "n/a"}}, False),
])
def test_connected_is_a_positive_test_never_a_guess(meta, connected):
    m = gcv.normalize({"id": "c", "messageType": "TYPE_CALL", "meta": meta})
    assert gcv.is_connected_call(m) is connected


def test_the_minimum_call_length_can_be_changed():
    m = gcv.normalize({"id": "c", "messageType": "TYPE_CALL", "meta": {"call": {"status": "completed", "duration": 15}}})
    assert gcv.is_connected_call(m, 20) is False and gcv.is_connected_call(m, 5) is True

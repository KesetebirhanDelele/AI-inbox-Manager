"""Parsing and fetching the student's messages and Voice AI calls from GHL. Fake client; no network."""
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


# -- texts and emails ---------------------------------------------------------------

class FakeConv:
    def __init__(self, messages=None, call_logs=None):
        self.messages, self.call_logs = messages or [], call_logs or []
        self.call_log_requests = []

    def conversations_for_contact(self, contact_id):
        return [{"id": "conv1"}]

    def conversation_messages(self, conversation_id):
        return self.messages

    def voice_ai_call_logs(self, contact_id, agent_id=None, page_size=20):
        self.call_log_requests.append((contact_id, agent_id))
        return self.call_logs


SINCE = datetime(2026, 10, 5, 20, 0)


def raw(id, type_="TYPE_SMS", direction="inbound", body="yes", at="2026-10-05T20:10:00.000Z", **extra):
    return {"id": id, "messageType": type_, "direction": direction, "body": body, "dateAdded": at, **extra}


def test_fetch_keeps_only_inbound_texts_and_emails():
    client = FakeConv([
        raw("sms-in"),
        raw("sms-out", direction="outbound"),                                    # our own text
        raw("old", at="2026-10-05T19:00:00.000Z"),                               # before the sequence began
        raw("echo", type_="TYPE_EMAIL", body="link https://x/ack/TOK"),
        raw("email-in", type_="TYPE_EMAIL", body="Got it, thanks"),
        raw("call-msg", type_="TYPE_CALL", direction="inbound", body=""),        # calls come from Voice AI call logs
        raw("note", type_="TYPE_ACTIVITY_NOTE"),
        raw("seen"),
    ])
    got = gcv.fetch_new_messages(client, "c1", SINCE, {"seen"}, markers=["TOK"])
    assert [m.id for m in got] == ["sms-in", "email-in"]


def test_fetch_returns_oldest_first():
    client = FakeConv([raw("b", at="2026-10-05T20:20:00.000Z"), raw("a", at="2026-10-05T20:05:00.000Z")])
    assert [m.id for m in gcv.fetch_new_messages(client, "c1", SINCE, set())] == ["a", "b"]


# -- Voice AI call logs ---------------------------------------------------------------

TRANSCRIPT = (
    "bot: Hello, this is Colaberry about your interview with Acme.\n"
    "human: Yes I got it.\n"
    "bot: Great, can you confirm?\n"
    "human: Confirmed,\nI will call them tomorrow.\n"            # a second line with no label continues the student
    "bot: Thank you."
)


def test_human_words_are_only_the_students_lines_in_order():
    assert gcv.human_words(TRANSCRIPT) == "Yes I got it. Confirmed, I will call them tomorrow."


@pytest.mark.parametrize("transcript, expected", [
    ("bot: Hello\nbot: Anyone there?", ""),                       # the student never spoke
    ("BOT: hi\nHuman: yes", "yes"),                               # labels are case-insensitive
    ("human:   spaced   ", "spaced"),
    ("", ""), (None, ""), (123, ""),
])
def test_human_words_edge_cases(transcript, expected):
    assert gcv.human_words(transcript) == expected


def log(id="L1", duration=45, transcript=TRANSCRIPT, at="2026-10-05T20:10:00.000Z", **extra):
    return {"id": id, "duration": duration, "transcript": transcript, "createdAt": at, "summary": "s",
            "executedCallActions": [{"actionType": "CALL_TRANSFER"}], **extra}


def test_parse_call_log():
    call = gcv.parse_call_log(log())
    assert (call.id, call.record_id, call.duration) == ("L1", "voiceai:L1", 45)
    assert call.created_at == datetime(2026, 10, 5, 20, 10) and call.actions == ["CALL_TRANSFER"]
    assert "Yes I got it." in call.human_words and "Hello, this is" not in call.human_words
    assert gcv.parse_call_log({"duration": 5}) is None                                # no id
    assert gcv.parse_call_log(log(duration="n/a")).duration == 0


@pytest.mark.parametrize("duration, transcript, reached", [
    (45, TRANSCRIPT, True),
    (10, "human: yes", True),
    (9, "human: yes", False),                       # too short to be a conversation
    (45, "bot: Hello? Anyone there?", False),       # nobody spoke: no answer or a dead line
    (0, "", False),
])
def test_reached_a_person_is_a_positive_test(duration, transcript, reached):
    assert gcv.reached_a_person(gcv.parse_call_log(log(duration=duration, transcript=transcript))) is reached


def test_the_minimum_call_length_can_be_changed():
    call = gcv.parse_call_log(log(duration=15, transcript="human: yes"))
    assert gcv.reached_a_person(call, 20) is False and gcv.reached_a_person(call, 5) is True


def test_fetch_new_calls_skips_seen_old_and_unparseable_and_sorts_oldest_first():
    client = FakeConv(call_logs=[
        log("late", at="2026-10-05T20:30:00.000Z"),
        log("seen", at="2026-10-05T20:15:00.000Z"),
        log("old", at="2026-10-05T19:00:00.000Z"),
        {"duration": 3},
        log("early", at="2026-10-05T20:05:00.000Z"),
    ])
    got = gcv.fetch_new_calls(client, "c1", SINCE, {"voiceai:seen"}, agent_id="agent-9")
    assert [c.id for c in got] == ["early", "late"]
    assert client.call_log_requests == [("c1", "agent-9")]

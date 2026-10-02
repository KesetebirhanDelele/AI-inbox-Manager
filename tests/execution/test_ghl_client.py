"""GHL client: retries, rate limit, field lookup, shadow gating, opt-out checks. A fake session; no network."""
import sys
from pathlib import Path

import pytest
import requests

_EXECUTION_DIR = Path(__file__).resolve().parents[2] / "execution"
if str(_EXECUTION_DIR) not in sys.path:
    sys.path.insert(0, str(_EXECUTION_DIR))

import ghl_client as gc  # noqa: E402


class Resp:
    def __init__(self, status=200, data=None, text=""):
        self.status_code, self._data, self.text = status, data if data is not None else {}, text
        self.content = b"x" if (data is not None or text) else b""

    def json(self):
        if self._data is None:
            raise ValueError("no json")
        return self._data


class Session:
    """Replies with the scripted responses in order and records every request."""
    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []

    def request(self, method, url, headers=None, timeout=None, **kw):
        self.calls.append({"method": method, "url": url, "kw": kw, "headers": headers})
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def client(*responses, **cfg):
    base = dict(api_key="tok", location_id="loc", retry_max=2, min_interval_seconds=0.0)
    base.update(cfg)
    sleeps = []
    c = gc.GhlClient(gc.GhlConfig(**base), session=Session(*responses), sleep=sleeps.append)
    c.sleeps = sleeps
    return c


# -- config ---------------------------------------------------------------------

def test_defaults_are_shadow_and_cannot_be_live_by_accident():
    cfg = gc.GhlConfig.from_env({})
    assert (cfg.write_mode, cfg.shadow_log_only, cfg.write_notify_fields, cfg.is_live) == ("shadow", True, False, False)
    assert (cfg.field_email_subject, cfg.field_email_body) == ("Support Issue Ticket #2", "Message:")
    assert (cfg.field_sms, cfg.field_call) == ("Support issue Ticket #4", "interview_notification")


@pytest.mark.parametrize("env, live", [
    ({"GHL_WRITE_MODE": "live", "GHL_WRITE_SHADOW_LOG_ONLY": "false", "GHL_WRITE_NOTIFY_FIELDS": "true"}, True),
    ({"GHL_WRITE_MODE": "live", "GHL_WRITE_SHADOW_LOG_ONLY": "false"}, False),            # area switch missing
    ({"GHL_WRITE_MODE": "live", "GHL_WRITE_NOTIFY_FIELDS": "true"}, False),               # log-only still on
    ({"GHL_WRITE_SHADOW_LOG_ONLY": "false", "GHL_WRITE_NOTIFY_FIELDS": "true"}, False),   # mode still shadow
])
def test_live_needs_all_three_switches(env, live):
    assert gc.GhlConfig.from_env(env).is_live is live


def test_field_labels_and_block_tags_can_be_set_from_env():
    cfg = gc.GhlConfig.from_env({"GHL_FIELD_NOTIFY_CALL": "my_call_field", "NOTIFY_BLOCK_TAGS": "No Calls, STOP"})
    assert cfg.field_call == "my_call_field" and cfg.block_tags == ("no calls", "stop")


# -- transport ------------------------------------------------------------------

def test_a_near_match_is_never_taken_for_the_student_and_duplicates_are_refused():
    near = client(Resp(200, {"contacts": [{"id": "c9", "phone": "+19725550199"}, {"id": "c8"}]}))
    assert near.search_contact_by_phone("+19725550100") is None            # wrong student must not be contacted
    twin = client(Resp(200, {"contacts": [{"id": "a", "phone": "9725550100"}, {"id": "b", "phone": "+19725550100"}]}))
    with pytest.raises(gc.GhlError, match="share this phone number"):
        twin.search_contact_by_phone("+19725550100")


def test_a_429_and_a_disguised_timeout_are_retried_then_succeed():
    c = client(Resp(429), Resp(401, {"statusCode": 401, "message": "Command timed out"}), Resp(200, {"contacts": []}))
    assert c.search_contact_by_phone("+19725550100") is None
    assert len(c._session.calls) == 3 and c.sleeps == [1.0, 2.0]


def test_a_real_401_a_400_and_a_missing_credential_raise_immediately():
    for status in (401, 400, 404):
        c = client(Resp(status, {"message": "nope"}))
        with pytest.raises(gc.GhlError) as exc:
            c.get_contact("c1")
        assert exc.value.status_code == status and len(c._session.calls) == 1
    with pytest.raises(gc.GhlError):
        gc.GhlClient(gc.GhlConfig(api_key="", location_id=""), session=Session()).get_contact("c1")


def test_retries_are_bounded_and_timeouts_are_retried():
    c = client(Resp(503), Resp(503), Resp(503))
    with pytest.raises(gc.GhlError, match="3 attempts"):
        c.get_contact("c1")
    c = client(requests.exceptions.Timeout(), Resp(200, {"contact": {"id": "c1"}}))
    assert c.get_contact("c1") == {"id": "c1"}


def test_calls_are_paced():
    t = {"now": 100.0}
    sleeps = []
    c = gc.GhlClient(gc.GhlConfig(api_key="tok", location_id="loc", min_interval_seconds=0.2),
                     session=Session(Resp(200, {}), Resp(200, {})), sleep=sleeps.append, monotonic=lambda: t["now"])
    c.get_contact("a")
    t["now"] += 0.05
    c.get_contact("b")
    assert sleeps and abs(sleeps[0] - 0.15) < 1e-9


def test_the_search_sends_the_location_and_returns_the_exact_match():
    c = client(Resp(200, {"contacts": [{"id": "c1", "phone": "+1 (972) 555-0100"}, {"id": "c2", "phone": "+19725550199"}]}))
    assert c.search_contact_by_phone("+19725550100") == {"id": "c1", "phone": "+1 (972) 555-0100"}
    call = c._session.calls[0]
    assert call["kw"]["params"] == {"locationId": "loc", "query": "+19725550100"}
    assert call["headers"]["Authorization"] == "Bearer tok" and call["headers"]["Version"] == "2021-07-28"


# -- fields ---------------------------------------------------------------------

FIELDS = {"customFields": [
    {"id": "f-sms", "name": "Support issue Ticket #4", "fieldKey": "contact.support_issue_ticket_4"},
    {"id": "f-call", "name": "Interview Notification", "fieldKey": "contact.interview_notification"},
]}


def test_labels_resolve_by_name_or_key_and_the_list_is_fetched_once():
    c = client(Resp(200, FIELDS))
    assert c.field_id("support issue ticket #4") == "f-sms"             # case-insensitive name
    assert c.field_id("interview_notification") == "f-call"             # key without the prefix
    assert c.field_id("contact.interview_notification") == "f-call"
    assert c.field_id("nothing") is None
    assert len(c._session.calls) == 1


def test_shadow_writes_make_no_request_and_log_labels_not_values(caplog):
    c = client()                                                          # no responses: any request would fail
    with caplog.at_level("INFO"):
        out = c.write_fields("c1", {"interview_notification": "SECRET SCRIPT TEXT"})
    assert out == {"live": False, "fields": ["interview_notification"]} and c._session.calls == []
    assert "SECRET SCRIPT TEXT" not in caplog.text


def test_live_writes_resolve_ids_and_put_them_in_one_call():
    c = client(Resp(200, FIELDS), Resp(200, {}), write_mode="live", shadow_log_only=False, write_notify_fields=True)
    out = c.write_fields("c1", {"interview_notification": "hello"})
    put = c._session.calls[-1]
    assert out["live"] is True and put["method"] == "PUT" and put["url"].endswith("/contacts/c1")
    assert put["kw"]["json"] == {"customFields": [{"id": "f-call", "value": "hello"}]}


def test_a_live_write_to_an_unknown_field_is_a_setup_error_not_a_silent_skip():
    c = client(Resp(200, FIELDS), write_mode="live", shadow_log_only=False, write_notify_fields=True)
    with pytest.raises(gc.GhlError, match="not found"):
        c.write_fields("c1", {"no such field": "x"})


# -- opt-outs -------------------------------------------------------------------

def test_block_reason_covers_dnd_per_channel_the_contact_flag_and_tags():
    assert gc.block_reason({}, "call") is None
    assert "all channels" in gc.block_reason({"dnd": True}, "sms")
    sms_dnd = {"dndSettings": {"SMS": {"status": "active"}}}
    assert "SMS" in gc.block_reason(sms_dnd, "sms")
    assert gc.block_reason(sms_dnd, "email") is None and gc.block_reason(sms_dnd, "call") is None
    assert gc.block_reason({"dndSettings": {"Call": {"status": "inactive"}}}, "call") is None
    assert "do not call" in gc.block_reason({"tags": ["Student", "Do Not Call"]}, "call")
    assert gc.block_reason({"tags": ["Student"]}, "call") is None


# -- conversations (second token, read-only) -------------------------------------

def conv_client(*responses):
    return client(*responses, conversations_api_key="conv-tok")


def test_conversation_reads_use_the_conversations_token_not_the_contacts_token():
    c = conv_client(Resp(200, {"conversations": [{"id": "conv1"}]}))
    assert c.conversations_for_contact("c1") == [{"id": "conv1"}]
    call = c._session.calls[0]
    assert call["headers"]["Authorization"] == "Bearer conv-tok"
    assert call["kw"]["params"] == {"locationId": "loc", "contactId": "c1", "limit": 5}


def test_conversation_reads_need_the_second_token():
    c = client(Resp(200, {}))                                      # contacts token only
    with pytest.raises(gc.GhlError, match="GHL_CONVERSATIONS_API_KEY"):
        c.conversations_for_contact("c1")
    assert c._session.calls == []


def test_messages_are_unwrapped_from_ghls_double_nesting_and_the_single_shape():
    double = {"messages": {"lastMessageId": "x", "nextPage": False, "messages": [{"id": "m1"}]}}
    single = {"messages": [{"id": "m2"}]}
    assert conv_client(Resp(200, double)).conversation_messages("conv1") == [{"id": "m1"}]
    assert conv_client(Resp(200, single)).conversation_messages("conv1") == [{"id": "m2"}]


def test_a_missing_transcript_is_none_but_other_errors_still_raise():
    assert conv_client(Resp(400, {"message": "recording not found"})).message_transcription("m1") is None
    sentences = [{"mediaChannel": 1, "transcript": "hi"}]
    assert conv_client(Resp(200, sentences)).message_transcription("m1") == sentences
    assert conv_client(Resp(200, {"transcriptions": sentences})).message_transcription("m1") == sentences
    with pytest.raises(gc.GhlError):
        conv_client(Resp(404, {})).message_transcription("m1")


def test_the_conversations_token_comes_from_env():
    cfg = gc.GhlConfig.from_env({"GHL_CONVERSATIONS_API_KEY": "t", "GHL_LOCATION_ID": "loc"})
    assert cfg.can_read_conversations and not cfg.can_read
    assert not gc.GhlConfig.from_env({}).can_read_conversations

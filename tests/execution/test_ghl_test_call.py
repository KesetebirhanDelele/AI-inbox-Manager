"""The one-contact voice test script: dry run writes nothing, --send writes only the call field, opt-outs stop it."""
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "execution"))

import ghl_client as gc
import ghl_test_call as t

NOW = datetime(2026, 10, 3, 15, 0, 0, tzinfo=timezone.utc)


class FakeClient:
    contact = {"id": "c1", "firstName": "Kes", "tags": []}
    writes = []

    def __init__(self, cfg):
        self.config = cfg

    def search_contact_by_phone(self, phone):
        return self.contact

    def field_id(self, label):
        return None if label == "missing" else "fid-1"

    def voice_ai_call_logs(self, cid, agent_id=None):
        return []

    def write_fields(self, cid, updates):
        FakeClient.writes.append((cid, updates, self.config.is_live))
        return {"live": self.config.is_live}


def go(args, contact=None):
    FakeClient.writes = []
    FakeClient.contact = contact or {"id": "c1", "firstName": "Kes", "phone": "+15551234567", "tags": []}
    lines = []
    code = t.run(["--phone", "+15551234567"] + args, client_factory=FakeClient, now=NOW, out=lines.append)
    return code, "\n".join(lines)


def test_value_is_facts_only_and_unique():
    v = t.test_value("Kes", NOW)
    assert v.startswith("Attempt: first notice. Candidate first name: Kes.")
    assert "Reference: TEST-20261003150000" in v
    assert v != t.test_value("Kes", datetime(2026, 10, 3, 15, 0, 1, tzinfo=timezone.utc))


def test_dry_run_writes_nothing(monkeypatch):
    monkeypatch.setattr(t, "load_env", lambda: {"GHL_API_KEY": "k", "GHL_LOCATION_ID": "l"})
    code, out = go([])
    assert code == 0 and "DRY RUN" in out and FakeClient.writes == []


def test_send_writes_only_the_call_field_live(monkeypatch):
    monkeypatch.setattr(t, "load_env", lambda: {"GHL_API_KEY": "k", "GHL_LOCATION_ID": "l"})
    code, out = go(["--send"])
    assert code == 0 and len(FakeClient.writes) == 1
    cid, updates, live = FakeClient.writes[0]
    assert cid == "c1" and list(updates) == ["interview_notification"] and live is True


def test_do_not_disturb_blocks_send(monkeypatch):
    monkeypatch.setattr(t, "load_env", lambda: {"GHL_API_KEY": "k", "GHL_LOCATION_ID": "l"})
    code, out = go(["--send"], contact={"id": "c1", "firstName": "Kes", "phone": "+15551234567", "dnd": True})
    assert code == 2 and "STOP" in out and FakeClient.writes == []


def test_env_alias_for_call_field():
    cfg = gc.GhlConfig.from_env({"GHL_FIELD_INTERVIEW_NOTIFICATION": "my_field"})
    assert cfg.field_call == "my_field"
    assert gc.GhlConfig.from_env({}).field_call == "interview_notification"


def test_sms_channel_writes_only_the_text_field(monkeypatch):
    monkeypatch.setattr(t, "load_env", lambda: {"GHL_API_KEY": "k", "GHL_LOCATION_ID": "l"})
    code, out = go(["--channel", "sms", "--send"])
    assert code == 0 and list(FakeClient.writes[0][1]) == ["Support issue Ticket #4"]
    text = FakeClient.writes[0][1]["Support issue Ticket #4"]
    assert "http" not in text and "YES" in text


def test_email_channel_writes_subject_and_body_only(monkeypatch):
    monkeypatch.setattr(t, "load_env", lambda: {"GHL_API_KEY": "k", "GHL_LOCATION_ID": "l"})
    code, out = go(["--channel", "email", "--send"])
    assert code == 0 and set(FakeClient.writes[0][1]) == {"Support Issue Ticket #2", "Message:"}


def test_dry_run_of_sms_writes_nothing(monkeypatch):
    monkeypatch.setattr(t, "load_env", lambda: {"GHL_API_KEY": "k", "GHL_LOCATION_ID": "l"})
    code, out = go(["--channel", "sms"])
    assert code == 0 and "DRY RUN" in out and FakeClient.writes == []


def test_a_missing_field_stops_before_writing(monkeypatch):
    monkeypatch.setattr(t, "load_env", lambda: {"GHL_API_KEY": "k", "GHL_LOCATION_ID": "l", "GHL_FIELD_NOTIFY_CALL": "missing"})
    code, out = go(["--send"])
    assert code == 2 and "not found" in out and FakeClient.writes == []

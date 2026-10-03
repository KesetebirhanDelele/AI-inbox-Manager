import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "execution"))
import backfill_event_students as bs  # noqa: E402


def test_stored_sub_types_become_the_title_case_the_templates_use():
    assert bs.draft_sub_type("interview_request") == "Interview Request"
    assert bs.draft_sub_type("Phone Screen") == "Phone Screen"
    assert bs.draft_sub_type("phone_screen") == "Phone Screen"
    assert bs.draft_sub_type("") == ""


def test_email_data_carries_the_recipient_headers_from_the_real_message():
    parsed = {"headers": {"Delivered-To": "priyan.nt24@gmail.com"}, "to_addresses": ["priyan.nt24@gmail.com"],
              "sender_email": "rohit.s@synchronycorp.com", "body_content": "Hi,"}
    data = bs.email_data_from_gmail(parsed, SimpleNamespace(from_address="Unknown"))
    assert data["to_addresses"] == ["priyan.nt24@gmail.com"] and data["from"] == "rohit.s@synchronycorp.com"
    assert data["body"] == "Hi," and data["from_email"] == "rohit.s@synchronycorp.com"
    assert bs.email_data_from_gmail({"body_content": "x"}, SimpleNamespace(from_address="hr@acme.com"))["from"] == "hr@acme.com"

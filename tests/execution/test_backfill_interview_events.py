import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "execution"))
import backfill_interview_events as bf  # noqa: E402


def rows(raw=None, full_body="Full text", preview="preview"):
    email = SimpleNamespace(email_id="42", message_id="<m@x>", subject="Phone screen", from_address="hr@acme.com",
                            received_date=datetime(2026, 10, 1, 12, 0), full_body=full_body, body_preview=preview)
    cls = SimpleNamespace(category="Phone Screen", confidence=0.93, company_name="Acme", position="Analyst", raw_response=raw)
    return email, cls


def test_inputs_are_rebuilt_from_the_stored_rows():
    email_data, cls = bf.build_inputs(*rows({"extracted_data": {"company_name": "Acme Corp", "interview_date": "2026-10-08"}, "reasoning": "x"}))
    assert email_data["subject"] == "Phone screen" and email_data["sender_email"] == "hr@acme.com"
    assert email_data["body_content"] == "Full text" and email_data["email_date"] == "2026-10-01T12:00:00"
    assert cls["category"] == "Phone Screen" and cls["confidence"] == 0.93 and cls["reasoning"] == "x"
    assert cls["extracted_data"]["company_name"] == "Acme Corp" and cls["extracted_data"]["interview_date"] == "2026-10-08"


def test_missing_raw_response_falls_back_to_the_classification_columns_and_the_preview():
    email_data, cls = bf.build_inputs(*rows(raw=None, full_body=None))
    assert email_data["body_content"] == "preview"
    assert cls["extracted_data"] == {"company_name": "Acme", "position_title": "Analyst"}


def test_the_stored_rows_are_never_modified():
    e, c = rows({"extracted_data": {"company_name": "Acme Corp"}})
    bf.build_inputs(e, c)
    assert c.raw_response == {"extracted_data": {"company_name": "Acme Corp"}}

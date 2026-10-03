import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "execution"))
import backfill_email_bodies as bb  # noqa: E402


def row(**kw):
    base = dict(full_body="", body_preview="", from_address="Unknown", subject="Msg: Important Note")
    base.update(kw)
    return SimpleNamespace(**base)


PARSED = {"body_content": "Hello Sehrish, ...", "sender_email": "info@dd.job-assist-now.com", "subject": "Msg: Important Note"}


def test_damaged_rows_are_recognised():
    assert bb.is_damaged(row())
    assert bb.is_damaged(row(full_body="text", from_address="Unknown"))
    assert bb.is_damaged(row(full_body="", from_address="hr@acme.com"))
    assert not bb.is_damaged(row(full_body="text", from_address="hr@acme.com"))


def test_a_stub_gets_its_body_and_sender_filled_from_the_real_message():
    changes = bb.plan_update(row(), PARSED)
    assert changes == {"full_body": "Hello Sehrish, ...", "body_preview": "Hello Sehrish, ...", "from_address": "info@dd.job-assist-now.com"}


def test_real_values_are_never_replaced():
    changes = bb.plan_update(row(full_body="Already here", from_address="real@acme.com", subject="Real subject"), PARSED)
    assert changes == {}


def test_a_missing_subject_is_filled_and_an_empty_message_changes_nothing():
    assert bb.plan_update(row(subject="No Subject"), {"subject": "Hi", "body_content": "", "sender_email": ""}) == {"subject": "Hi"}
    assert bb.plan_update(row(), {"body_content": "", "sender_email": "", "subject": ""}) == {}

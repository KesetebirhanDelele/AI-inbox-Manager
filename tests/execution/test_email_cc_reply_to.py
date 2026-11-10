"""send_notification can copy someone and set Reply-To (used when an agent asks the GHL contact owner for a student's email)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "execution"))
import send_notification as sn  # noqa: E402


def test_cc_and_reply_to_are_headers_and_plain_mail_is_unchanged():
    plain = sn.build_email_message("a@x.com", "s", "b", from_email="f@x.com", bcc="")
    assert plain["Cc"] is None and plain["Reply-To"] is None
    msg = sn.build_email_message("a@x.com", "s", "b", from_email="f@x.com", bcc="", cc="agent@x.com", reply_to="agent@x.com")
    assert msg["Cc"] == "agent@x.com" and msg["Reply-To"] == "agent@x.com" and msg["To"] == "a@x.com"


def test_the_cc_address_is_a_real_smtp_recipient(monkeypatch):
    seen = {}

    class FakeSMTP:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def ehlo(self): pass
        def starttls(self): pass
        def login(self, *a): pass
        def sendmail(self, from_addr, to_addrs, msg): seen["to"] = to_addrs

    monkeypatch.setattr(sn.smtplib, "SMTP", FakeSMTP)
    r = sn.send_email("a@x.com", "s", "b", bcc="", smtp_username="u", smtp_password="p", cc="agent@x.com")
    assert r["status"] == "sent" and seen["to"] == ["a@x.com", "agent@x.com"]

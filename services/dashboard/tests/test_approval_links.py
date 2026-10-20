"""Review and approve one card from an alert email: the link plus a one-time code emailed to the approver. It works once, expires, and never works for a card decided another way."""
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "execution"))
import approval_links as al  # noqa: E402

from conftest import make_email, make_interview_event, make_notification_draft, make_student  # noqa: E402


@pytest.fixture(autouse=True)
def _single_email_path(monkeypatch):
    import send_notification
    monkeypatch.setenv("SINGLE_EMAIL_APPROVE_ENABLED", "true")        # approve through the simple path (no GHL in tests)
    monkeypatch.setattr(send_notification, "SMTP_USERNAME", "sender@example.com", raising=False)
    monkeypatch.setattr(send_notification, "SMTP_PASSWORD", "x", raising=False)


def _card(db, status="draft"):
    from models import Student
    student = db.query(Student).first() or make_student(db)
    event = make_interview_event(db, make_email(db, email_id=f"c{datetime.utcnow().timestamp()}"), student=student, company="Acme")
    return make_notification_draft(db, event, email_status=status)


def _link(db, draft, hours=24, role="approver"):
    url = al.create_link(db, draft.id, role, "kes@example.com", env={"APPROVE_LINK_HOURS": str(hours)})
    return url.rsplit("/", 1)[1]


def _code(db, token):
    """A fresh code for this link, issued through the same helper the endpoint uses (no email in the way)."""
    return al.issue_code(db, al.find_link(db, token))


def _approve(client, token, code, **extra):
    return client.post(f"/api/approve-links/{token}/approve", json={"confirm": True, "code": code, **extra})


def test_a_new_link_stores_only_the_hash_and_builds_the_url(db):
    draft = _card(db)
    url = al.create_link(db, draft.id, "approver", "kes@example.com", env={"DASHBOARD_BASE_URL": "https://example.test/"})
    token = url.rsplit("/", 1)[1]
    assert url.startswith("https://example.test/approve/") and len(token) >= 40
    from models import ApprovalLink
    row = db.query(ApprovalLink).one()
    assert row.token_hash == al.hash_token(token) and token not in row.token_hash and row.used_at is None


def test_opening_the_link_shows_no_card_only_where_the_code_goes(client, db):
    draft = _card(db)
    token = _link(db, draft)
    data = client.get(f"/api/approve-links/{token}").json()                  # no cookie: no login
    assert data == {"state": "needs_code", "sent_to": "ke***@example.com", "expires_at": data["expires_at"]}
    assert "card" not in data and "student" not in str(data)


def test_an_unknown_token_is_a_plain_404(client, db):
    assert client.get("/api/approve-links/not-a-real-token").status_code == 404
    assert client.post("/api/approve-links/not-a-real-token/send-code").status_code == 404
    assert client.post("/api/approve-links/not-a-real-token/open", json={"code": "123456"}).status_code == 404
    assert client.post("/api/approve-links/not-a-real-token/approve", json={"confirm": True, "code": "1"}).status_code == 404


def test_send_code_emails_a_six_digit_code_to_the_address_the_alert_went_to(client, db):
    draft = _card(db)
    token = _link(db, draft)
    with patch("send_notification.send_email", return_value={"status": "sent"}) as send:
        r = client.post(f"/api/approve-links/{token}/send-code")
    assert r.status_code == 200 and r.json()["sent_to"] == "ke***@example.com" and r.json()["valid_minutes"] == 10
    kwargs = send.call_args.kwargs
    assert kwargs["recipient_email"] == "kes@example.com" and kwargs["bcc"] == ""
    code = re.search(r"\b(\d{6})\b", kwargs["body"]).group(1)
    assert client.post(f"/api/approve-links/{token}/open", json={"code": code}).json()["state"] == "ready"
    assert "student" not in r.text.lower()                                   # the code email says nothing about the card


def test_a_failed_code_email_is_reported_not_hidden(client, db):
    token = _link(db, _card(db))
    with patch("send_notification.send_email", return_value={"status": "failed", "error": "smtp down"}):
        assert client.post(f"/api/approve-links/{token}/send-code").status_code == 502


def test_only_three_codes_an_hour_per_link(client, db):
    token = _link(db, _card(db))
    with patch("send_notification.send_email", return_value={"status": "sent"}):
        codes = [client.post(f"/api/approve-links/{token}/send-code").status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]


def test_without_a_code_or_with_a_wrong_one_nothing_opens(client, db):
    token = _link(db, _card(db))
    assert client.post(f"/api/approve-links/{token}/open", json={"code": "123456"}).status_code == 403     # no code was ever sent
    code = _code(db, token)
    wrong = "000000" if code != "000000" else "111111"
    r = client.post(f"/api/approve-links/{token}/open", json={"code": wrong})
    assert r.status_code == 403 and "not right" in r.json()["detail"]


def test_five_wrong_tries_kill_the_code_even_for_the_right_one(client, db):
    token = _link(db, _card(db))
    code = _code(db, token)
    wrong = "000000" if code != "000000" else "111111"
    statuses = [client.post(f"/api/approve-links/{token}/open", json={"code": wrong}).status_code for _ in range(5)]
    assert statuses == [403, 403, 403, 403, 423]
    assert client.post(f"/api/approve-links/{token}/open", json={"code": code}).status_code == 423
    assert _approve(client, token, code).status_code == 423
    assert al.find_link(db, token).used_at is None
    new_code = _code(db, token)                                              # a new code starts fresh
    assert client.post(f"/api/approve-links/{token}/open", json={"code": new_code}).json()["state"] == "ready"


def test_a_new_code_replaces_the_old_one_and_a_code_expires(client, db):
    token = _link(db, _card(db))
    first = _code(db, token)
    second = _code(db, token)
    if first != second:
        assert client.post(f"/api/approve-links/{token}/open", json={"code": first}).status_code in (403, 423)   # the old code is dead
    assert client.post(f"/api/approve-links/{token}/open", json={"code": second}).json()["state"] == "ready"
    from models import ApprovalCode
    row = db.query(ApprovalCode).filter(ApprovalCode.consumed_at.is_(None)).one()
    row.expires_at = datetime.utcnow() - timedelta(seconds=1)
    db.commit()
    r = client.post(f"/api/approve-links/{token}/open", json={"code": second})
    assert r.status_code == 403 and "expired" in r.json()["detail"]


def test_opening_with_the_right_code_gives_the_card_and_the_full_emails(client, db):
    from models import Email
    draft = _card(db)
    db.query(Email).first().full_body = "Hello team.\n" + ("A long paragraph about the interview. " * 80) + "\nTHE-END-MARKER"
    draft.email_body = "Dear student, your interview is scheduled. Please prepare.\nSee you there.\nTHE-STUDENT-END"
    db.commit()
    token = _link(db, draft)
    data = client.post(f"/api/approve-links/{token}/open", json={"code": _code(db, token)}).json()
    assert data["state"] == "ready" and data["card"]["draft_id"] == draft.id and data["card"]["student"]["name"]
    assert "THE-END-MARKER" in data["original_email"]["text"] and len(data["original_email"]["text"]) > 1500       # not cut at the card's excerpt length
    assert data["original_email"]["from_address"] and data["original_email"]["subject"]
    assert "THE-STUDENT-END" in data["card"]["draft"]["body"] and data["card"]["preview"]["call"] and data["card"]["preview"]["text"]


def test_a_forwarded_link_cannot_approve_without_the_code(client, db):
    draft = _card(db)
    token = _link(db, draft)
    assert _approve(client, token, "").status_code == 403                    # whoever holds only the link
    assert _approve(client, token, "123456").status_code == 403
    db.refresh(draft)
    assert draft.email_status == "draft"


def test_approve_needs_confirmation_the_code_and_works_once(client, db):
    draft = _card(db)
    token = _link(db, draft)
    code = _code(db, token)
    assert client.post(f"/api/approve-links/{token}/approve", json={"code": code}).status_code == 422       # a stray request approves nothing
    db.refresh(draft)
    assert draft.email_status == "draft"
    with patch("send_notification.send_email", return_value={"status": "sent"}):
        r = _approve(client, token, code)
    assert r.status_code == 200 and r.json()["action"] == "approved"
    db.refresh(draft)
    assert draft.email_status in ("approved", "sent") and draft.reviewed_by == "link:kes@example.com"
    again = _approve(client, token, code)
    assert again.status_code == 409 and "used" in again.json()["detail"]
    assert client.get(f"/api/approve-links/{token}").json()["state"] == "used"


def test_the_decision_uses_the_code_up(client, db):
    from models import ApprovalCode
    token = _link(db, _card(db))
    code = _code(db, token)
    with patch("send_notification.send_email", return_value={"status": "sent"}):
        _approve(client, token, code)
    assert db.query(ApprovalCode).filter(ApprovalCode.consumed_at.is_(None)).count() == 0
    assert al.check_code(db, al.find_link(db, token), code) == "none"


def test_reject_closes_the_card_and_uses_up_the_link(client, db):
    draft = _card(db)
    token = _link(db, draft)
    r = client.post(f"/api/approve-links/{token}/reject", json={"confirm": True, "code": _code(db, token), "reason": "not ours"})
    assert r.status_code == 200 and r.json()["action"] == "rejected"
    db.refresh(draft)
    assert draft.email_status == "rejected" and "not ours" in (draft.send_error or "")
    assert client.get(f"/api/approve-links/{token}").json()["state"] == "used"


def test_an_expired_link_is_refused_everywhere(client, db):
    draft = _card(db)
    token = _link(db, draft)
    code = _code(db, token)
    from models import ApprovalLink
    db.query(ApprovalLink).one().expires_at = datetime.utcnow() - timedelta(minutes=1)
    db.commit()
    assert client.get(f"/api/approve-links/{token}").json()["state"] == "expired"
    assert client.post(f"/api/approve-links/{token}/send-code").status_code == 409
    assert client.post(f"/api/approve-links/{token}/open", json={"code": code}).json()["state"] == "expired"
    assert _approve(client, token, code).status_code == 409


def test_a_card_decided_in_the_app_makes_the_link_dead(client, db):
    draft = _card(db)
    token = _link(db, draft)
    code = _code(db, token)
    draft.email_status = "rejected"
    db.commit()
    assert client.get(f"/api/approve-links/{token}").json()["state"] == "decided"
    assert _approve(client, token, code).status_code == 409


def test_a_refused_approval_leaves_the_link_and_code_usable(client, db):
    event = make_interview_event(db, make_email(db), student=None)           # no student: the normal guard refuses
    draft = make_notification_draft(db, event)
    token = _link(db, draft)
    code = _code(db, token)
    r = _approve(client, token, code)
    assert r.status_code == 400 and "nobody to notify" in r.json()["detail"]
    assert al.find_link(db, token).used_at is None and al.check_code(db, al.find_link(db, token), code) == "ok"


def test_a_link_for_one_card_cannot_decide_another(client, db):
    first, second = _card(db), _card(db)
    token = _link(db, first)
    with patch("send_notification.send_email", return_value={"status": "sent"}):
        _approve(client, token, _code(db, token))
    db.refresh(second)
    assert second.email_status == "draft"

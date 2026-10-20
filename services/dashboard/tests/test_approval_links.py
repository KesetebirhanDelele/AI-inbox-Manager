"""Review and approve one card from an alert email without logging in: the token is the key, it works once, expires, and never works for a card decided another way."""
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


def test_a_new_link_stores_only_the_hash_and_builds_the_url(db):
    draft = _card(db)
    url = al.create_link(db, draft.id, "approver", "kes@example.com", env={"DASHBOARD_BASE_URL": "https://example.test/"})
    token = url.rsplit("/", 1)[1]
    assert url.startswith("https://example.test/approve/") and len(token) >= 40
    from models import ApprovalLink
    row = db.query(ApprovalLink).one()
    assert row.token_hash == al.hash_token(token) and token not in row.token_hash and row.used_at is None


def test_opening_the_link_shows_the_card_and_changes_nothing(client, db):
    draft = _card(db)
    token = _link(db, draft)
    data = client.get(f"/api/approve-links/{token}").json()                  # no cookie: no login
    assert data["state"] == "ready" and data["card"]["draft_id"] == draft.id and data["card"]["student"]["name"]
    db.refresh(draft)
    assert draft.email_status == "draft"


def test_an_unknown_token_is_a_plain_404(client, db):
    assert client.get("/api/approve-links/not-a-real-token").status_code == 404
    assert client.post("/api/approve-links/not-a-real-token/approve", json={"confirm": True}).status_code == 404


def test_approve_needs_the_confirmation_and_then_works_once(client, db):
    draft = _card(db)
    token = _link(db, draft)
    assert client.post(f"/api/approve-links/{token}/approve", json={}).status_code == 422          # a scanner or stray request approves nothing
    db.refresh(draft)
    assert draft.email_status == "draft"
    with patch("send_notification.send_email", return_value={"status": "sent"}):
        r = client.post(f"/api/approve-links/{token}/approve", json={"confirm": True})
    assert r.status_code == 200 and r.json()["action"] == "approved"
    db.refresh(draft)
    assert draft.email_status in ("approved", "sent") and draft.reviewed_by == "link:kes@example.com"
    again = client.post(f"/api/approve-links/{token}/approve", json={"confirm": True})
    assert again.status_code == 409 and "used" in again.json()["detail"]
    assert client.get(f"/api/approve-links/{token}").json()["state"] == "used"


def test_reject_closes_the_card_and_uses_up_the_link(client, db):
    draft = _card(db)
    token = _link(db, draft)
    r = client.post(f"/api/approve-links/{token}/reject", json={"confirm": True, "reason": "not ours"})
    assert r.status_code == 200 and r.json()["action"] == "rejected"
    db.refresh(draft)
    assert draft.email_status == "rejected" and "not ours" in (draft.send_error or "")
    assert client.get(f"/api/approve-links/{token}").json()["state"] == "used"


def test_an_expired_link_is_refused(client, db):
    draft = _card(db)
    token = _link(db, draft)
    from models import ApprovalLink
    db.query(ApprovalLink).one().expires_at = datetime.utcnow() - timedelta(minutes=1)
    db.commit()
    assert client.get(f"/api/approve-links/{token}").json()["state"] == "expired"
    assert client.post(f"/api/approve-links/{token}/approve", json={"confirm": True}).status_code == 409


def test_a_card_decided_in_the_app_makes_the_link_dead(client, db):
    draft = _card(db)
    token = _link(db, draft)
    draft.email_status = "rejected"
    db.commit()
    assert client.get(f"/api/approve-links/{token}").json()["state"] == "decided"
    assert client.post(f"/api/approve-links/{token}/approve", json={"confirm": True}).status_code == 409


def test_a_refused_approval_leaves_the_link_usable(client, db):
    event = make_interview_event(db, make_email(db), student=None)           # no student: the normal guard refuses
    draft = make_notification_draft(db, event)
    token = _link(db, draft)
    r = client.post(f"/api/approve-links/{token}/approve", json={"confirm": True})
    assert r.status_code == 400 and "nobody to notify" in r.json()["detail"]
    assert client.get(f"/api/approve-links/{token}").json()["state"] == "ready"


def test_a_link_for_one_card_cannot_decide_another(client, db):
    first, second = _card(db), _card(db)
    token = _link(db, first)
    with patch("send_notification.send_email", return_value={"status": "sent"}):
        client.post(f"/api/approve-links/{token}/approve", json={"confirm": True})
    db.refresh(second)
    assert second.email_status == "draft"

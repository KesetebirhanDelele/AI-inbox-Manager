"""Verification: a student who is not in GHL. The agent confirms from the emailed link that this is a candidate they are actively applying for;
that emails the GHL contact owner (agent copied, replies to the agent). Nothing is sent to the student, and approving from that link is refused."""
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "execution"))
import approval_links as al  # noqa: E402

from conftest import make_email, make_interview_event, make_notification_draft, make_student  # noqa: E402
from models import AlertLog, RoleAssignment  # noqa: E402


@pytest.fixture(autouse=True)
def _smtp(monkeypatch):
    import send_notification
    monkeypatch.setattr(send_notification, "SMTP_USERNAME", "sender@example.com", raising=False)
    monkeypatch.setattr(send_notification, "SMTP_PASSWORD", "x", raising=False)


def _owner(db, email="rose@example.com"):
    db.add(RoleAssignment(role="ghl_contact_owner", email=email, active=True))
    db.commit()


def _verify_card(db, role="agent_verify"):
    student = make_student(db)
    event = make_interview_event(db, make_email(db, email_id=f"v{datetime.utcnow().timestamp()}"), student=student, company="Acme")
    draft = make_notification_draft(db, event, email_status="draft")
    db.add(AlertLog(kind="review_needed", key=str(draft.id), detail="agent:Karthik"))
    db.commit()
    url = al.create_link(db, draft.id, role, "karthik@example.com")
    token = url.rsplit("/", 1)[1]
    return draft, token


def _code(db, token):
    return al.issue_code(db, al.find_link(db, token))


def _confirm(client, token, code, **kw):
    return client.post(f"/api/approve-links/{token}/confirm-candidate", json={"confirm": True, "code": code, **kw})


def test_open_shows_verify_mode(client, db):
    draft, token = _verify_card(db)
    data = client.post(f"/api/approve-links/{token}/open", json={"code": _code(db, token)}).json()
    assert data["state"] == "ready" and data["mode"] == "verify" and data["candidate_confirmed_at"] is None


def test_a_normal_link_is_in_approve_mode(client, db):
    draft, token = _verify_card(db, role="agent")
    data = client.post(f"/api/approve-links/{token}/open", json={"code": _code(db, token)}).json()
    assert data["mode"] == "approve"


def test_confirming_emails_the_owner_with_the_agent_copied_and_replies_to_the_agent(client, db):
    _owner(db)
    draft, token = _verify_card(db)
    sent = []
    with patch("send_notification.send_email", side_effect=lambda **kw: sent.append(kw) or {"status": "sent"}):
        r = _confirm(client, token, _code(db, token))
    assert r.status_code == 200 and r.json()["state"] == "sent" and r.json()["to"] == "rose@example.com"
    mail = sent[0]
    assert mail["recipient_email"] == "rose@example.com" and mail["cc"] == "karthik@example.com" and mail["reply_to"] == "karthik@example.com"
    assert "provide the student's email in GHL" in mail["body"] and "Karthik has confirmed" in mail["body"]
    assert "Please add an email in GHL for" in mail["subject"]
    assert db.query(AlertLog).filter(AlertLog.kind == "candidate_confirmed", AlertLog.key == str(draft.id)).count() == 1


def test_confirming_twice_sends_one_email(client, db):
    _owner(db)
    draft, token = _verify_card(db)
    sent = []
    with patch("send_notification.send_email", side_effect=lambda **kw: sent.append(kw) or {"status": "sent"}):
        assert _confirm(client, token, _code(db, token)).json()["state"] == "sent"
        again = _confirm(client, token, _code(db, token))
    assert again.status_code == 200 and again.json()["state"] == "already" and len(sent) == 1


def test_opening_after_confirming_says_so(client, db):
    _owner(db)
    draft, token = _verify_card(db)
    with patch("send_notification.send_email", return_value={"status": "sent"}):
        _confirm(client, token, _code(db, token))
    data = client.post(f"/api/approve-links/{token}/open", json={"code": _code(db, token)}).json()
    assert data["candidate_confirmed_at"] is not None


def test_no_owner_set_refuses_and_keeps_the_code(client, db):
    draft, token = _verify_card(db)
    code = _code(db, token)
    r = _confirm(client, token, code)
    assert r.status_code == 409 and "GHL contact owner" in r.json()["detail"]
    assert db.query(AlertLog).filter(AlertLog.kind == "candidate_confirmed").count() == 0
    _owner(db)
    with patch("send_notification.send_email", return_value={"status": "sent"}):
        assert _confirm(client, token, code).status_code == 200                # the same code still works: it was not used up by the refusal


def test_a_failed_send_records_nothing_and_can_be_retried(client, db):
    _owner(db)
    draft, token = _verify_card(db)
    code = _code(db, token)
    with patch("send_notification.send_email", return_value={"status": "failed"}):
        assert _confirm(client, token, code).status_code == 502
    assert db.query(AlertLog).filter(AlertLog.kind == "candidate_confirmed").count() == 0
    with patch("send_notification.send_email", return_value={"status": "sent"}):
        assert _confirm(client, token, code).status_code == 200


def test_needs_the_code_and_the_confirm_flag(client, db):
    _owner(db)
    draft, token = _verify_card(db)
    with patch("send_notification.send_email", return_value={"status": "sent"}) as send:
        assert _confirm(client, token, "000000").status_code in (403, 423)          # no code was ever issued
        _code(db, token)
        assert _confirm(client, token, "000000").status_code == 403                  # wrong code
        assert client.post(f"/api/approve-links/{token}/confirm-candidate", json={"confirm": False, "code": "1"}).status_code == 422
    assert send.call_count == 0


def test_a_normal_link_cannot_confirm_a_candidate(client, db):
    _owner(db)
    draft, token = _verify_card(db, role="agent")
    assert _confirm(client, token, _code(db, token)).status_code == 409


def test_approving_from_a_verification_link_is_refused(client, db):
    draft, token = _verify_card(db)
    r = client.post(f"/api/approve-links/{token}/approve", json={"confirm": True, "code": _code(db, token)})
    assert r.status_code == 409 and "not in GHL yet" in r.json()["detail"]


def test_not_my_candidate_rejects_with_the_normal_reject(client, db):
    draft, token = _verify_card(db)
    r = client.post(f"/api/approve-links/{token}/reject", json={"confirm": True, "code": _code(db, token), "reason": "not mine"})
    assert r.status_code == 200 and r.json()["action"] == "rejected"


def test_the_email_to_the_owner_carries_the_students_facts(db):
    import candidate_confirm as cc
    import student_roster as sr
    draft, token = _verify_card(db)
    student = make_student(db) if False else None
    from models import Student
    s = db.query(Student).first()
    s.phone_number, s.personal_email = "+15551230000", "p@x.com"
    db.commit()
    roster = [sr.RosterRow(name=s.full_name, status="Active", agent="Karthik", emails=["p@x.com", "alt@x.com"])]
    text = cc.request_text(db, draft, "Karthik", "karthik@example.com", roster)
    assert "+15551230000" in text["body"] and "p@x.com" in text["body"] and "alt@x.com" in text["body"] and "Acme" in text["body"]
    assert "karthik@example.com" in text["body"]

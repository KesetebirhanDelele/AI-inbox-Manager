"""
Tests for the student escalation endpoints in /api/notifications/*.

Channels are dry_run (the default), so nothing is ever delivered. See
directives/student-notification-escalation.md.
"""

from unittest.mock import patch

from conftest import (
    make_email,
    make_interview_event,
    make_notification_draft,
    make_student,
)

_SEND_EMAIL = "execution.send_notification.send_email"


def _draft(db, phone="(972) 555-0100"):
    student = make_student(db, username="stu", full_name="Test Student")
    student.phone_number = phone
    db.commit()
    email = make_email(db)
    event = make_interview_event(db, email, student=student, company="Acme")
    return make_notification_draft(db, event, email_status="draft"), student


def _sequence(db, draft):
    from models import NotificationSequence
    return db.query(NotificationSequence).filter(NotificationSequence.draft_id == draft.id).first()


class TestApproveWithEscalation:
    def test_flag_off_keeps_the_old_behaviour_and_creates_no_sequence(self, client, db, auth_cookies, monkeypatch):
        monkeypatch.delenv("NOTIFY_ESCALATION_ENABLED", raising=False)
        draft, _ = _draft(db)
        with patch(_SEND_EMAIL, return_value={"status": "sent"}) as send:
            resp = client.post(f"/api/notifications/{draft.id}/approve", cookies=auth_cookies)
        assert resp.status_code == 200 and resp.json()["email_status"] == "sent"
        assert send.called and _sequence(db, draft) is None

    def test_flag_on_starts_a_sequence_instead_of_sending_directly(self, client, db, auth_cookies, monkeypatch):
        monkeypatch.setenv("NOTIFY_ESCALATION_ENABLED", "true")
        for kind in ("EMAIL", "SMS", "CALL"):
            monkeypatch.delenv(f"NOTIFY_CHANNEL_{kind}", raising=False)       # default = dry_run
        draft, _ = _draft(db)
        with patch(_SEND_EMAIL) as send:
            resp = client.post(f"/api/notifications/{draft.id}/approve", cookies=auth_cookies)
        assert resp.status_code == 200
        data = resp.json()
        assert data["sequence_status"] == "active"
        assert data["first_round"] == {"sent": 0, "dry_run": 3, "failed": 0, "skipped": 0}
        assert not send.called                                  # dry run delivers nothing
        seq = _sequence(db, draft)
        assert len(seq.attempts) == 16 and seq.timezone == "America/Chicago" and seq.started_by

    def test_approving_twice_does_not_start_a_second_sequence(self, client, db, auth_cookies, monkeypatch):
        monkeypatch.setenv("NOTIFY_ESCALATION_ENABLED", "1")
        draft, _ = _draft(db)
        client.post(f"/api/notifications/{draft.id}/approve", cookies=auth_cookies)
        client.post(f"/api/notifications/{draft.id}/approve", cookies=auth_cookies)
        from models import NotificationSequence
        assert db.query(NotificationSequence).count() == 1


class TestAckLink:
    def test_the_link_needs_no_login_and_acknowledges(self, client, db, auth_cookies, monkeypatch):
        monkeypatch.setenv("NOTIFY_ESCALATION_ENABLED", "1")
        draft, _ = _draft(db)
        client.post(f"/api/notifications/{draft.id}/approve", cookies=auth_cookies)
        token = _sequence(db, draft).ack_token

        resp = client.get(f"/api/notifications/ack/{token}")            # no cookies: the student is not logged in
        assert resp.status_code == 200 and "Thank you" in resp.text
        db.expire_all()
        seq = _sequence(db, draft)
        assert seq.status == "acknowledged" and seq.ack_channel == "email"

    def test_an_unknown_token_is_rejected(self, client):
        resp = client.get("/api/notifications/ack/not-a-real-token")
        assert resp.status_code == 404 and "not valid" in resp.text


class TestRobControls:
    def test_status_and_close_need_a_login(self, client, db):
        draft, _ = _draft(db)
        assert client.get(f"/api/notifications/{draft.id}/sequence").status_code == 401
        assert client.post(f"/api/notifications/{draft.id}/sequence/close").status_code == 401

    def test_rob_can_see_the_attempts_and_close_the_sequence(self, client, db, auth_cookies, monkeypatch):
        monkeypatch.setenv("NOTIFY_ESCALATION_ENABLED", "1")
        draft, _ = _draft(db)
        client.post(f"/api/notifications/{draft.id}/approve", cookies=auth_cookies)

        seq = client.get(f"/api/notifications/{draft.id}/sequence", cookies=auth_cookies).json()
        assert seq["status"] == "active" and len(seq["attempts"]) == 16
        assert {a["status"] for a in seq["attempts"] if a["step"] == "start"} == {"dry_run"}

        closed = client.post(f"/api/notifications/{draft.id}/sequence/close", cookies=auth_cookies).json()
        assert closed["status"] == "closed" and closed["closed_now"] is True
        after = client.get(f"/api/notifications/{draft.id}/sequence", cookies=auth_cookies).json()
        assert after["closed_by"] and all(a["status"] != "pending" for a in after["attempts"])

    def test_no_sequence_is_a_404(self, client, db, auth_cookies):
        draft, _ = _draft(db)
        assert client.get(f"/api/notifications/{draft.id}/sequence", cookies=auth_cookies).status_code == 404


class TestInboundReply:
    def _start(self, client, db, auth_cookies, monkeypatch):
        monkeypatch.setenv("NOTIFY_ESCALATION_ENABLED", "1")
        draft, _ = _draft(db)
        client.post(f"/api/notifications/{draft.id}/approve", cookies=auth_cookies)
        return draft

    def test_closed_when_no_secret_is_configured(self, client, db, auth_cookies, monkeypatch):
        self._start(client, db, auth_cookies, monkeypatch)
        monkeypatch.delenv("NOTIFY_INBOUND_SECRET", raising=False)
        resp = client.post("/api/notifications/inbound/reply", json={"phone": "972-555-0100", "text": "yes"},
                           headers={"X-Notify-Secret": "anything"})
        assert resp.status_code == 401

    def test_rejects_a_wrong_or_missing_secret(self, client, db, auth_cookies, monkeypatch):
        self._start(client, db, auth_cookies, monkeypatch)
        monkeypatch.setenv("NOTIFY_INBOUND_SECRET", "right")
        body = {"phone": "972-555-0100", "text": "yes"}
        assert client.post("/api/notifications/inbound/reply", json=body).status_code == 401
        assert client.post("/api/notifications/inbound/reply", json=body,
                           headers={"X-Notify-Secret": "wrong"}).status_code == 401

    def test_yes_with_the_right_secret_acknowledges(self, client, db, auth_cookies, monkeypatch):
        draft = self._start(client, db, auth_cookies, monkeypatch)
        monkeypatch.setenv("NOTIFY_INBOUND_SECRET", "right")
        resp = client.post("/api/notifications/inbound/reply", json={"phone": "+1 972 555 0100", "text": "YES"},
                           headers={"X-Notify-Secret": "right"})
        assert resp.status_code == 200 and resp.json()["action"] == "acknowledged"
        db.expire_all()
        assert _sequence(db, draft).status == "acknowledged"

    def test_rejects_an_unknown_channel(self, client, db, auth_cookies, monkeypatch):
        self._start(client, db, auth_cookies, monkeypatch)
        monkeypatch.setenv("NOTIFY_INBOUND_SECRET", "right")
        resp = client.post("/api/notifications/inbound/reply",
                           json={"phone": "972-555-0100", "text": "yes", "channel": "pigeon"},
                           headers={"X-Notify-Secret": "right"})
        assert resp.status_code == 422

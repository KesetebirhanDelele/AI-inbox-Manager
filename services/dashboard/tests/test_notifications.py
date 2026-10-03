"""Tests for /api/notifications/* endpoints."""

from unittest.mock import patch

from conftest import (
    make_email,
    make_interview_event,
    make_notification_draft,
    make_student,
)

_SEND_EMAIL = "execution.send_notification.send_email"


class TestGetPendingNotifications:
    def test_empty(self, client, db, auth_cookies):
        resp = client.get("/api/notifications/pending", cookies=auth_cookies)
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_draft_and_approved(self, client, db, auth_cookies):
        email = make_email(db)
        event = make_interview_event(db, email)
        make_notification_draft(db, event, email_status="draft")
        make_notification_draft(db, event, email_status="approved")

        resp = client.get("/api/notifications/pending", cookies=auth_cookies)
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_excludes_sent_and_rejected(self, client, db, auth_cookies):
        email = make_email(db)
        event = make_interview_event(db, email)
        make_notification_draft(db, event, email_status="sent")
        make_notification_draft(db, event, email_status="rejected")

        resp = client.get("/api/notifications/pending", cookies=auth_cookies)
        assert resp.status_code == 200
        assert resp.json() == []

    def test_includes_student_and_event_info(self, client, db, auth_cookies):
        student = make_student(db, full_name="Jane Doe")
        email = make_email(db)
        event = make_interview_event(db, email, student=student, company="TechCorp")
        make_notification_draft(db, event)

        resp = client.get("/api/notifications/pending", cookies=auth_cookies)
        data = resp.json()
        assert data[0]["student_name"] == "Jane Doe"
        assert data[0]["company_name"] == "TechCorp"

    def test_requires_auth(self, client, db):
        resp = client.get("/api/notifications/pending")
        assert resp.status_code == 401


class TestGetSentNotifications:
    def test_empty(self, client, db, auth_cookies):
        resp = client.get("/api/notifications/sent", cookies=auth_cookies)
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_sent_only(self, client, db, auth_cookies):
        email = make_email(db)
        event = make_interview_event(db, email)
        make_notification_draft(db, event, email_status="sent")
        make_notification_draft(db, event, email_status="draft")  # excluded

        resp = client.get("/api/notifications/sent", cookies=auth_cookies)
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert resp.json()[0]["email_status"] == "sent"

    def test_requires_auth(self, client, db):
        resp = client.get("/api/notifications/sent")
        assert resp.status_code == 401


class TestGetNotificationDetail:
    def test_get_detail_success(self, client, db, auth_cookies):
        student = make_student(db)
        email = make_email(db, subject="Phone Screen at Acme")
        event = make_interview_event(db, email, student=student)
        draft = make_notification_draft(db, event, subject="Interview Alert")

        resp = client.get(f"/api/notifications/{draft.id}", cookies=auth_cookies)
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == draft.id
        assert data["email_subject"] == "Interview Alert"
        assert data["student_name"] == "John Doe"
        assert data["email_subject_original"] == "Phone Screen at Acme"

    def test_get_detail_not_found(self, client, db, auth_cookies):
        resp = client.get("/api/notifications/99999", cookies=auth_cookies)
        assert resp.status_code == 404

    def test_requires_auth(self, client, db):
        resp = client.get("/api/notifications/1")
        assert resp.status_code == 401


class TestApproveGuardsAndChecklist:
    def test_approving_with_no_student_is_refused_and_nothing_changes(self, client, db, auth_cookies):
        event = make_interview_event(db, make_email(db), student=None)
        draft = make_notification_draft(db, event)
        resp = client.post(f"/api/notifications/{draft.id}/approve", cookies=auth_cookies)
        assert resp.status_code == 400 and "nobody to notify" in resp.json()["detail"]
        db.refresh(draft)
        assert draft.email_status == "draft"

    def test_approving_a_student_with_no_contact_details_is_refused(self, client, db, auth_cookies):
        student = make_student(db, username="x", personal_email=None)
        student.assigned_gmail = None
        db.commit()
        draft = make_notification_draft(db, make_interview_event(db, make_email(db), student=student))
        resp = client.post(f"/api/notifications/{draft.id}/approve", cookies=auth_cookies)
        assert resp.status_code == 400 and "no phone, email or Gmail" in resp.json()["detail"]

    def test_approving_ticks_the_checklist_step_automatically(self, client, db, auth_cookies):
        from models import ChecklistCompletion
        event = make_interview_event(db, make_email(db), student=make_student(db), sub_type="Phone Screen")
        draft = make_notification_draft(db, event)
        with patch(_SEND_EMAIL, return_value={"status": "sent"}):
            assert client.post(f"/api/notifications/{draft.id}/approve", cookies=auth_cookies).status_code == 200
        row = db.query(ChecklistCompletion).filter_by(interview_event_id=event.id, step_key="phone_screen.2.3").one()
        assert row.is_completed is True and row.completed_by


class TestApproveNotification:
    def test_approve_sends_email(self, client, db, auth_cookies):
        email = make_email(db)
        event = make_interview_event(db, email, student=make_student(db))
        draft = make_notification_draft(db, event, email_status="draft")

        with patch(_SEND_EMAIL, return_value={"status": "sent"}):
            resp = client.post(f"/api/notifications/{draft.id}/approve", cookies=auth_cookies)

        assert resp.status_code == 200
        data = resp.json()
        assert data["email_status"] == "sent"
        db.refresh(draft)
        assert draft.email_status == "sent"
        assert draft.sent_at is not None

    def test_approve_handles_send_failure(self, client, db, auth_cookies):
        email = make_email(db)
        event = make_interview_event(db, email, student=make_student(db))
        draft = make_notification_draft(db, event)

        with patch(_SEND_EMAIL, return_value={"status": "failed", "error": "SMTP error"}):
            resp = client.post(f"/api/notifications/{draft.id}/approve", cookies=auth_cookies)

        assert resp.status_code == 200
        data = resp.json()
        assert data["email_status"] == "failed"
        assert data["send_error"] == "SMTP error"

    def test_approve_already_sent_rejected(self, client, db, auth_cookies):
        email = make_email(db)
        event = make_interview_event(db, email)
        draft = make_notification_draft(db, event, email_status="sent")

        resp = client.post(f"/api/notifications/{draft.id}/approve", cookies=auth_cookies)
        assert resp.status_code == 400

    def test_approve_not_found(self, client, db, auth_cookies):
        resp = client.post("/api/notifications/99999/approve", cookies=auth_cookies)
        assert resp.status_code == 404

    def test_requires_auth(self, client, db):
        resp = client.post("/api/notifications/1/approve")
        assert resp.status_code == 401


class TestEditNotification:
    def test_edit_subject(self, client, db, auth_cookies):
        email = make_email(db)
        event = make_interview_event(db, email)
        draft = make_notification_draft(db, event, subject="Old Subject")

        resp = client.post(
            f"/api/notifications/{draft.id}/edit",
            json={"email_subject": "New Subject"},
            cookies=auth_cookies,
        )
        assert resp.status_code == 200
        assert resp.json()["email_subject"] == "New Subject"
        db.refresh(draft)
        assert draft.email_subject == "New Subject"

    def test_edit_and_send(self, client, db, auth_cookies):
        email = make_email(db)
        event = make_interview_event(db, email)
        draft = make_notification_draft(db, event)

        with patch(_SEND_EMAIL, return_value={"status": "sent"}):
            resp = client.post(
                f"/api/notifications/{draft.id}/edit",
                json={"email_subject": "Updated", "send_after_edit": True},
                cookies=auth_cookies,
            )

        assert resp.status_code == 200
        assert resp.json()["email_status"] == "sent"

    def test_edit_sent_notification_rejected(self, client, db, auth_cookies):
        email = make_email(db)
        event = make_interview_event(db, email)
        draft = make_notification_draft(db, event, email_status="sent")

        resp = client.post(
            f"/api/notifications/{draft.id}/edit",
            json={"email_subject": "Too Late"},
            cookies=auth_cookies,
        )
        assert resp.status_code == 400

    def test_edit_not_found(self, client, db, auth_cookies):
        resp = client.post(
            "/api/notifications/99999/edit",
            json={"email_subject": "X"},
            cookies=auth_cookies,
        )
        assert resp.status_code == 404

    def test_requires_auth(self, client, db):
        resp = client.post("/api/notifications/1/edit", json={"email_subject": "X"})
        assert resp.status_code == 401


class TestRejectNotification:
    def test_reject_success(self, client, db, auth_cookies):
        email = make_email(db)
        event = make_interview_event(db, email)
        draft = make_notification_draft(db, event)

        resp = client.post(
            f"/api/notifications/{draft.id}/reject",
            json={"reason": "Wrong student"},
            cookies=auth_cookies,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["email_status"] == "rejected"
        assert data["reviewed_by"] == "testadmin"

        db.refresh(draft)
        assert draft.email_status == "rejected"

    def test_reject_not_found(self, client, db, auth_cookies):
        resp = client.post(
            "/api/notifications/99999/reject",
            json={"reason": "N/A"},
            cookies=auth_cookies,
        )
        assert resp.status_code == 404

    def test_requires_auth(self, client, db):
        resp = client.post("/api/notifications/1/reject", json={"reason": "X"})
        assert resp.status_code == 401


class TestStudentEndpoints:
    def test_list_students_empty(self, client, db, auth_cookies):
        resp = client.get("/api/notifications/students/list", cookies=auth_cookies)
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_students_active_only(self, client, db, auth_cookies):
        make_student(db, username="active1", full_name="Active Student")
        inactive = make_student(db, username="inactive1", full_name="Inactive Student")
        inactive.is_active = False
        db.commit()

        resp = client.get("/api/notifications/students/list?active_only=true", cookies=auth_cookies)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["full_name"] == "Active Student"

    def test_list_students_all(self, client, db, auth_cookies):
        make_student(db, username="active1")
        inactive = make_student(db, username="inactive1")
        inactive.is_active = False
        db.commit()

        resp = client.get("/api/notifications/students/list?active_only=false", cookies=auth_cookies)
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_get_student_by_id(self, client, db, auth_cookies):
        student = make_student(db, full_name="Test Student", personal_email="test@example.com")

        resp = client.get(f"/api/notifications/students/{student.id}", cookies=auth_cookies)
        assert resp.status_code == 200
        data = resp.json()
        assert data["full_name"] == "Test Student"
        assert data["personal_email"] == "test@example.com"

    def test_get_student_not_found(self, client, db, auth_cookies):
        resp = client.get("/api/notifications/students/99999", cookies=auth_cookies)
        assert resp.status_code == 404

    def test_requires_auth(self, client, db):
        resp = client.get("/api/notifications/students/list")
        assert resp.status_code == 401


class TestGetNotificationByEmail:
    def test_returns_notification_for_email(self, client, db, auth_cookies):
        student = make_student(db)
        email = make_email(db)
        event = make_interview_event(db, email, student=student)
        draft = make_notification_draft(db, event, subject="Interview Tomorrow")

        resp = client.get(f"/api/notifications/by-email/{email.id}", cookies=auth_cookies)
        assert resp.status_code == 200
        data = resp.json()
        assert data["email_subject"] == "Interview Tomorrow"

    def test_returns_null_when_no_notification(self, client, db, auth_cookies):
        resp = client.get("/api/notifications/by-email/99999", cookies=auth_cookies)
        assert resp.status_code == 200
        assert resp.json() is None

    def test_requires_auth(self, client, db):
        resp = client.get("/api/notifications/by-email/1")
        assert resp.status_code == 401


# ── the review queue: one screen for Rob ──────────────────────────────────────────────────────

class TestReviewQueue:
    def _queue(self, client, auth_cookies, **params):
        resp = client.get("/api/notifications/review-queue", params=params, cookies=auth_cookies)
        assert resp.status_code == 200
        return resp.json()

    def test_a_ready_draft_shows_student_contact_facts_check_and_preview(self, client, db, auth_cookies):
        from conftest import make_email, make_student, make_interview_event, make_notification_draft
        student = make_student(db)
        student.phone_number = "(972) 555-0100"
        db.commit()
        email = make_email(db, subject="Phone screen", from_address="rohit.s@acmecorp.com")
        event = make_interview_event(db, email, student=student, company="Acme Corp")
        make_notification_draft(db, event)

        data = self._queue(client, auth_cookies)
        item = data["items"][0]
        assert data["escalation_enabled"] is False and item["state"] == "ready" and item["can_approve"] is True
        assert item["student"]["phone"] == "(972) 555-0100" and item["interview"]["company"] == "Acme Corp"
        assert item["authenticity"]["verdict"] in ("looks_genuine", "needs_check", "likely_job_board")
        assert "Interview details:" in item["preview"]["call"] and "Ref" not in item["preview"]["text"]
        assert "one email" in item["will_happen"] and item["blockers"] == []

    def test_will_happen_says_what_approve_does_when_escalation_is_on(self, client, db, auth_cookies, monkeypatch):
        from conftest import make_email, make_student, make_interview_event, make_notification_draft
        event = make_interview_event(db, make_email(db), student=make_student(db))
        make_notification_draft(db, event)
        monkeypatch.setenv("NOTIFY_ESCALATION_ENABLED", "true")
        data = self._queue(client, auth_cookies)
        assert data["escalation_enabled"] is True and "call, a text and an email" in data["items"][0]["will_happen"]

    def test_an_event_with_no_student_is_listed_blocked_with_the_reason_and_cannot_be_approved(self, client, db, auth_cookies):
        from conftest import make_email, make_interview_event
        email = make_email(db, subject="Interview", from_address="info@dd.job-assist-now.com")
        make_interview_event(db, email, student=None, company="Job-Assist-Now")
        item = self._queue(client, auth_cookies)["items"][0]
        assert item["state"] == "needs_student" and item["can_approve"] is False and item["draft_id"] is None
        assert "No student identified" in item["blockers"][0]

    def test_a_student_with_no_way_to_be_reached_blocks_approval(self, client, db, auth_cookies):
        from conftest import make_email, make_student, make_interview_event, make_notification_draft
        student = make_student(db, username="x", personal_email=None)
        student.assigned_gmail = None
        db.commit()
        event = make_interview_event(db, make_email(db), student=student)
        make_notification_draft(db, event)
        item = self._queue(client, auth_cookies)["items"][0]
        assert item["state"] == "blocked" and item["can_approve"] is False and "No phone, email or Gmail" in item["blockers"][0]

    def test_a_job_board_email_gets_a_warning_first(self, client, db, auth_cookies):
        from conftest import make_email, make_student, make_interview_event, make_notification_draft
        email = make_email(db, subject="Confirm your availability", from_address="info@dd.job-assist-now.com")
        email.body_preview = "Your request is still open. confirm your availability https://dd.job-assist-now.com/c/" + "A" * 50
        db.commit()
        event = make_interview_event(db, email, student=make_student(db), company="Job-Assist-Now")
        make_notification_draft(db, event)
        item = self._queue(client, auth_cookies)["items"][0]
        assert item["authenticity"]["verdict"] == "likely_job_board" and "job-board mailer" in item["warnings"][0]
        assert item["can_approve"] is True                      # advisory only: Rob decides

    def test_done_notices_are_hidden_unless_asked_for(self, client, db, auth_cookies):
        from conftest import make_email, make_student, make_interview_event, make_notification_draft
        event = make_interview_event(db, make_email(db), student=make_student(db))
        make_notification_draft(db, event, email_status="sent")
        assert self._queue(client, auth_cookies)["count"] == 0
        assert self._queue(client, auth_cookies, include_done=True)["count"] == 1

    def test_requires_login(self, client):
        assert client.get("/api/notifications/review-queue").status_code == 401


# ── students the pipeline had to guess must be verified before approval ─────────────────────────────────────

class TestStudentVerification:
    def _unverified(self, db, name="Opcrowne"):
        from models import StudentVerification
        student = make_student(db, username="opcrowne", full_name=name, personal_email="opcrowne@gmail.com")
        db.add(StudentVerification(student_id=student.id, status="unverified", basis="gmail_guess", guessed_name=name,
                                   evidence='The email was delivered to opcrowne@gmail.com. The greeting names "Omolola".'))
        db.commit()
        return student

    def test_the_queue_flags_an_unverified_student_and_blocks_approval(self, client, db, auth_cookies):
        student = self._unverified(db)
        draft = make_notification_draft(db, make_interview_event(db, make_email(db), student=student))
        item = client.get("/api/notifications/review-queue", cookies=auth_cookies).json()["items"][0]
        assert item["state"] == "needs_verification" and item["can_approve"] is False
        assert item["student"]["verification"]["status"] == "unverified" and "Omolola" in item["student"]["verification"]["evidence"]
        assert "not verified" in item["blockers"][0]
        resp = client.post(f"/api/notifications/{draft.id}/approve", cookies=auth_cookies)
        assert resp.status_code == 400 and "not been verified" in resp.json()["detail"]

    def test_verifying_corrects_the_details_and_unblocks_approval(self, client, db, auth_cookies):
        student = self._unverified(db)
        draft = make_notification_draft(db, make_interview_event(db, make_email(db), student=student), recipient_email="opcrowne@gmail.com")
        resp = client.post(f"/api/notifications/students/{student.id}/verify", cookies=auth_cookies,
                           json={"full_name": "Omolola Adeyemi", "phone_number": "312-555-0100", "personal_email": "omolola@example.com"})
        assert resp.status_code == 200 and resp.json()["status"] == "verified" and resp.json()["verified_by"]
        db.refresh(student)
        db.refresh(draft)
        assert (student.full_name, student.phone_number) == ("Omolola Adeyemi", "312-555-0100")
        assert draft.recipient_email == "omolola@example.com"                        # the waiting draft follows the corrected email
        item = client.get("/api/notifications/review-queue", cookies=auth_cookies).json()["items"][0]
        assert item["state"] == "ready" and item["can_approve"] is True and item["student"]["verification"]["status"] == "verified"
        with patch(_SEND_EMAIL, return_value={"status": "sent"}):
            assert client.post(f"/api/notifications/{draft.id}/approve", cookies=auth_cookies).status_code == 200

    def test_a_student_with_no_verification_record_is_treated_as_verified(self, client, db, auth_cookies):
        student = make_student(db)
        make_notification_draft(db, make_interview_event(db, make_email(db), student=student))
        item = client.get("/api/notifications/review-queue", cookies=auth_cookies).json()["items"][0]
        assert item["state"] == "ready" and item["student"]["verification"] is None

    def test_verifying_an_unknown_student_is_a_404(self, client, db, auth_cookies):
        assert client.post("/api/notifications/students/999/verify", cookies=auth_cookies, json={}).status_code == 404

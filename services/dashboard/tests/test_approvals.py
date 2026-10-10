"""Tests for /api/approvals/* endpoints."""

from unittest.mock import patch

from conftest import make_email, make_classification, make_approval


# Patch targets — these are the integration functions called by approvals.py
_MOVE = "routers.approvals.move_email"
_DELETE = "routers.approvals.delete_email"
_RECLASSIFY = "routers.approvals.reclassify_email"
_WHITELIST = "routers.approvals.add_to_whitelist"


class TestGetPendingApprovals:
    def test_empty_queue(self, client, db, auth_cookies):
        resp = client.get("/api/approvals/pending", cookies=auth_cookies)
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_pending_approvals(self, client, db, auth_cookies):
        email = make_email(db, subject="Suspicious Job Alert")
        clf = make_classification(db, email, category="Job Alert", confidence=0.55)
        make_approval(db, email, clf, status="pending")

        resp = client.get("/api/approvals/pending", cookies=auth_cookies)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["status"] == "pending"
        assert data[0]["email_subject"] == "Suspicious Job Alert"
        assert data[0]["confidence"] == 0.55

    def test_excludes_non_pending(self, client, db, auth_cookies):
        email = make_email(db)
        clf = make_classification(db, email, confidence=0.60)
        make_approval(db, email, clf, status="approved")

        resp = client.get("/api/approvals/pending", cookies=auth_cookies)
        assert resp.status_code == 200
        assert resp.json() == []

    def test_requires_auth(self, client, db):
        resp = client.get("/api/approvals/pending")
        assert resp.status_code == 401


class TestApproveClassification:
    def test_approve_keep_inbox(self, client, db, auth_cookies):
        email = make_email(db)
        clf = make_classification(db, email, confidence=0.60)
        approval = make_approval(db, email, clf)

        resp = client.post(
            f"/api/approvals/{approval.id}/approve",
            json={"action": "keep_inbox"},
            cookies=auth_cookies,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["action"] == "keep_inbox"

        db.refresh(approval)
        assert approval.status == "approved"
        assert approval.reviewed_by == "testadmin"

    def test_approve_move_to_folder(self, client, db, auth_cookies):
        email = make_email(db)
        clf = make_classification(db, email, confidence=0.60)
        approval = make_approval(db, email, clf)

        with patch(_MOVE) as mock_move:
            resp = client.post(
                f"/api/approvals/{approval.id}/approve",
                json={"action": "move_to_folder", "target_folder": "Job Alerts"},
                cookies=auth_cookies,
            )
        assert resp.status_code == 200
        mock_move.assert_called_once()

    def test_approve_delete_is_switched_off(self, client, db, auth_cookies):
        email = make_email(db)
        clf = make_classification(db, email, confidence=0.60)
        approval = make_approval(db, email, clf)

        with patch(_DELETE) as mock_delete:
            resp = client.post(
                f"/api/approvals/{approval.id}/approve",
                json={"action": "delete"},
                cookies=auth_cookies,
            )
        assert resp.status_code == 400
        assert "never deletes" in resp.json()["detail"]
        mock_delete.assert_not_called()
        db.refresh(approval)
        assert approval.status == "pending"

    def test_approve_move_without_folder_fails(self, client, db, auth_cookies):
        email = make_email(db)
        clf = make_classification(db, email, confidence=0.60)
        approval = make_approval(db, email, clf)

        resp = client.post(
            f"/api/approvals/{approval.id}/approve",
            json={"action": "move_to_folder"},  # missing target_folder
            cookies=auth_cookies,
        )
        assert resp.status_code == 400

    def test_approve_invalid_action(self, client, db, auth_cookies):
        email = make_email(db)
        clf = make_classification(db, email, confidence=0.60)
        approval = make_approval(db, email, clf)

        resp = client.post(
            f"/api/approvals/{approval.id}/approve",
            json={"action": "do_something_weird"},
            cookies=auth_cookies,
        )
        assert resp.status_code == 400

    def test_approve_not_found(self, client, db, auth_cookies):
        resp = client.post(
            "/api/approvals/99999/approve",
            json={"action": "keep_inbox"},
            cookies=auth_cookies,
        )
        assert resp.status_code == 404

    def test_approve_already_processed(self, client, db, auth_cookies):
        email = make_email(db)
        clf = make_classification(db, email, confidence=0.60)
        approval = make_approval(db, email, clf, status="approved")

        resp = client.post(
            f"/api/approvals/{approval.id}/approve",
            json={"action": "keep_inbox"},
            cookies=auth_cookies,
        )
        assert resp.status_code == 400


class TestRejectApproval:
    def test_reject_success(self, client, db, auth_cookies):
        email = make_email(db)
        clf = make_classification(db, email, confidence=0.60)
        approval = make_approval(db, email, clf)

        resp = client.post(
            f"/api/approvals/{approval.id}/reject",
            params={"notes": "Not relevant"},
            cookies=auth_cookies,
        )
        assert resp.status_code == 200
        assert resp.json()["approval_id"] == approval.id

        db.refresh(approval)
        assert approval.status == "rejected"

    def test_reject_not_found(self, client, db, auth_cookies):
        resp = client.post("/api/approvals/99999/reject", cookies=auth_cookies)
        assert resp.status_code == 404

    def test_reject_already_processed(self, client, db, auth_cookies):
        email = make_email(db)
        clf = make_classification(db, email, confidence=0.60)
        approval = make_approval(db, email, clf, status="rejected")

        resp = client.post(f"/api/approvals/{approval.id}/reject", cookies=auth_cookies)
        assert resp.status_code == 400


class TestOverrideClassification:
    def test_override_keep_inbox(self, client, db, auth_cookies):
        email = make_email(db)
        clf = make_classification(db, email, category="Job Alert", confidence=0.60)
        approval = make_approval(db, email, clf)

        with patch(_WHITELIST):
            resp = client.post(
                f"/api/approvals/{approval.id}/override",
                json={"new_category": "Interview Request", "action": "keep_inbox"},
                cookies=auth_cookies,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["new_category"] == "Interview Request"

        db.refresh(approval)
        assert approval.status == "overridden"
        assert approval.human_category == "Interview Request"

    def test_override_with_whitelist(self, client, db, auth_cookies):
        email = make_email(db)
        clf = make_classification(db, email, company="NewCo", confidence=0.60)
        approval = make_approval(db, email, clf)

        with patch(_WHITELIST) as mock_wl:
            resp = client.post(
                f"/api/approvals/{approval.id}/override",
                json={
                    "new_category": "Interview Request",
                    "action": "keep_inbox",
                    "add_to_whitelist": True,
                },
                cookies=auth_cookies,
            )
        assert resp.status_code == 200
        mock_wl.assert_called_once()

    def test_override_not_found(self, client, db, auth_cookies):
        resp = client.post(
            "/api/approvals/99999/override",
            json={"new_category": "Rejection", "action": "keep_inbox"},
            cookies=auth_cookies,
        )
        assert resp.status_code == 404


def test_move_finds_the_mail_by_message_id_not_by_the_stored_folder(db):
    """Mail the pipeline filed itself (Spam Review -> Quarantine) is not where the database says: a manual move must still find it."""
    from unittest.mock import patch as _patch
    from integration import email_actions
    email = make_email(db)
    email.current_folder = "Spam Review"
    email.message_id = "<abc@x>"
    db.commit()
    with _patch.object(email_actions, "IMAP_AVAILABLE", True),             _patch.object(email_actions, "relabel_by_message_id", return_value=True) as mock_relabel:
        email_actions.move_email(db=db, email=email, target_folder="Job Alerts", performed_by="admin")
    assert mock_relabel.call_args.args[4:6] == ("<abc@x>", "Job Alerts")
    assert email.current_folder == "Job Alerts"


def test_move_without_a_message_id_falls_back_to_the_stored_folder(db):
    from unittest.mock import patch as _patch
    from integration import email_actions
    email = make_email(db)
    email.current_folder = "Needs Review"
    email.message_id = None
    db.commit()
    with _patch.object(email_actions, "IMAP_AVAILABLE", True),             _patch.object(email_actions, "move_emails", return_value=1) as mock_move:
        email_actions.move_email(db=db, email=email, target_folder="Job Alerts", performed_by="admin")
    assert mock_move.call_args.kwargs["source_folder"] == "Needs Review"

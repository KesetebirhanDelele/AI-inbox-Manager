"""Roles are assigned on the Settings page (never written into the code); the pilot limit gates how many notices may start."""
from unittest.mock import patch

from conftest import make_email, make_interview_event, make_notification_draft, make_student


class TestRoles:
    def test_all_four_roles_are_listed_with_nobody_assigned(self, client, db, auth_cookies, monkeypatch):
        for var in ("APPROVER_ALERT_EMAIL", "CALLBACK_OWNER_EMAIL", "ESCALATION_ALERT_EMAIL", "CALLBACK_BACKUP_EMAIL"):
            monkeypatch.delenv(var, raising=False)
        data = client.get("/api/roles", cookies=auth_cookies).json()
        assert [r["role"] for r in data["roles"]] == ["approver", "callback_owner", "escalation_target", "callback_backup", "student_checker"]
        assert all(r["email"] == "" and r["source"] == "none" for r in data["roles"])
        assert data["pilot_limit"] == 3 and data["pilot_used"] == 0 and "09:00 to 17:00" in data["business_hours"]

    def test_assigning_a_role_saves_it_and_changing_it_is_a_setting_not_a_deploy(self, client, db, auth_cookies):
        assert client.put("/api/roles/escalation_target", json={"email": "first@example.com"}, cookies=auth_cookies).status_code == 200
        client.put("/api/roles/escalation_target", json={"email": "second@example.com"}, cookies=auth_cookies)
        roles = {r["role"]: r for r in client.get("/api/roles", cookies=auth_cookies).json()["roles"]}
        assert roles["escalation_target"]["email"] == "second@example.com" and roles["escalation_target"]["source"] == "database"

    def test_a_bad_email_and_an_unknown_role_are_refused(self, client, db, auth_cookies):
        assert client.put("/api/roles/approver", json={"email": "not-an-email"}, cookies=auth_cookies).status_code == 422
        assert client.put("/api/roles/rob", json={"email": "a@b.co"}, cookies=auth_cookies).status_code == 404

    def test_clearing_the_email_unassigns_the_role(self, client, db, auth_cookies, monkeypatch):
        monkeypatch.delenv("APPROVER_ALERT_EMAIL", raising=False)
        client.put("/api/roles/approver", json={"email": "a@example.com"}, cookies=auth_cookies)
        client.put("/api/roles/approver", json={"email": ""}, cookies=auth_cookies)
        approver = next(r for r in client.get("/api/roles", cookies=auth_cookies).json()["roles"] if r["role"] == "approver")
        assert approver["email"] == "" and approver["source"] == "none"

    def test_requires_login(self, client):
        assert client.get("/api/roles").status_code == 401
        assert client.put("/api/roles/approver", json={"email": "a@b.co"}).status_code == 401


class TestPilotLimit:
    def _draft(self, db, n):
        student = make_student(db, username=f"s{n}", full_name=f"Student {n}", personal_email=f"s{n}@example.com")
        return make_notification_draft(db, make_interview_event(db, make_email(db, email_id=f"m{n}"), student=student))

    def test_the_limit_can_be_changed_and_zero_means_no_limit(self, client, db, auth_cookies):
        assert client.put("/api/roles/pilot-limit", json={"limit": 5}, cookies=auth_cookies).json() == {"pilot_limit": 5}
        assert client.get("/api/roles", cookies=auth_cookies).json()["pilot_limit"] == 5
        assert client.put("/api/roles/pilot-limit", json={"limit": 0}, cookies=auth_cookies).status_code == 200
        assert client.put("/api/roles/pilot-limit", json={"limit": -1}, cookies=auth_cookies).status_code == 422

    def test_the_fourth_notice_is_refused_while_the_pilot_limit_of_three_applies(self, client, db, auth_cookies, monkeypatch):
        monkeypatch.setenv("NOTIFY_ESCALATION_ENABLED", "true")
        monkeypatch.setenv("NOTIFY_CHANNEL_EMAIL", "dry_run")
        monkeypatch.setenv("NOTIFY_CHANNEL_SMS", "dry_run")
        monkeypatch.setenv("NOTIFY_CHANNEL_CALL", "dry_run")
        drafts = [self._draft(db, n) for n in range(4)]
        for d in drafts[:3]:
            assert client.post(f"/api/notifications/{d.id}/approve", cookies=auth_cookies).status_code == 200
        refused = client.post(f"/api/notifications/{drafts[3].id}/approve", cookies=auth_cookies)
        assert refused.status_code == 400 and "Pilot limit reached" in refused.json()["detail"]
        db.refresh(drafts[3])
        assert drafts[3].email_status == "draft"                     # nothing changed
        client.put("/api/roles/pilot-limit", json={"limit": 0}, cookies=auth_cookies)
        assert client.post(f"/api/notifications/{drafts[3].id}/approve", cookies=auth_cookies).status_code == 200

    def test_the_limit_does_not_apply_while_escalation_is_off(self, client, db, auth_cookies, monkeypatch):
        monkeypatch.delenv("NOTIFY_ESCALATION_ENABLED", raising=False)
        monkeypatch.setenv("SINGLE_EMAIL_APPROVE_ENABLED", "true")
        client.put("/api/roles/pilot-limit", json={"limit": 1}, cookies=auth_cookies)
        with patch("send_notification.send_email", return_value={"status": "sent"}):
            for n in range(2):
                assert client.post(f"/api/notifications/{self._draft(db, n).id}/approve", cookies=auth_cookies).status_code == 200


class TestAlertSettings:
    def test_defaults_are_on_and_two_hours(self, client, db, auth_cookies):
        data = client.get("/api/roles", cookies=auth_cookies).json()
        assert data["review_alert_enabled"] is True and data["backup_after_hours"] == 2 and data["staff_alerts_enabled"] is True

    def test_the_switch_and_the_backup_time_are_saved_without_a_deploy(self, client, db, auth_cookies):
        r = client.put("/api/roles/alert-settings", json={"review_alert_enabled": False, "backup_after_hours": 3.5, "staff_alerts_enabled": False}, cookies=auth_cookies)
        assert r.status_code == 200
        data = client.get("/api/roles", cookies=auth_cookies).json()
        assert data["review_alert_enabled"] is False and data["backup_after_hours"] == 3.5 and data["staff_alerts_enabled"] is False

    def test_a_silly_backup_time_is_refused(self, client, db, auth_cookies):
        for hours in (0, -1, 500):
            assert client.put("/api/roles/alert-settings", json={"review_alert_enabled": True, "backup_after_hours": hours}, cookies=auth_cookies).status_code == 422


class TestLiveDeliverySwitch:
    ARM = (("GHL_WRITE_MODE", "live"), ("GHL_WRITE_SHADOW_LOG_ONLY", "false"), ("GHL_WRITE_NOTIFY_FIELDS", "true"))

    def _clear(self, monkeypatch):
        for k, _ in self.ARM:
            monkeypatch.delenv(k, raising=False)

    def test_default_is_shadow_and_not_armed(self, client, db, auth_cookies, monkeypatch):
        self._clear(monkeypatch)
        live = client.get("/api/roles", cookies=auth_cookies).json()["live_delivery"]
        assert live["armed"] is False and live["switch_on"] is False and live["live"] is False

    def test_it_cannot_be_turned_on_while_the_server_is_not_armed(self, client, db, auth_cookies, monkeypatch):
        self._clear(monkeypatch)
        r = client.put("/api/roles/live-delivery", json={"enabled": True, "confirm_text": "GO LIVE"}, cookies=auth_cookies)
        assert r.status_code == 422 and "not armed" in r.json()["detail"]
        assert client.get("/api/roles", cookies=auth_cookies).json()["live_delivery"]["switch_on"] is False

    def test_turning_it_on_needs_the_typed_words(self, client, db, auth_cookies, monkeypatch):
        for k, v in self.ARM:
            monkeypatch.setenv(k, v)
        assert client.put("/api/roles/live-delivery", json={"enabled": True}, cookies=auth_cookies).status_code == 422
        assert client.put("/api/roles/live-delivery", json={"enabled": True, "confirm_text": "yes"}, cookies=auth_cookies).status_code == 422
        assert client.get("/api/roles", cookies=auth_cookies).json()["live_delivery"]["live"] is False

    def test_on_then_off_and_who_changed_it_is_recorded(self, client, db, auth_cookies, monkeypatch):
        for k, v in self.ARM:
            monkeypatch.setenv(k, v)
        on = client.put("/api/roles/live-delivery", json={"enabled": True, "confirm_text": "go live"}, cookies=auth_cookies).json()
        assert on["armed"] and on["switch_on"] and on["live"] and on["changed_by"] and on["changed_at"].endswith("Z")
        off = client.put("/api/roles/live-delivery", json={"enabled": False}, cookies=auth_cookies).json()      # off needs no confirmation
        assert off["switch_on"] is False and off["live"] is False

    def test_armed_with_the_switch_off_is_not_live(self, client, db, auth_cookies, monkeypatch):
        for k, v in self.ARM:
            monkeypatch.setenv(k, v)
        live = client.get("/api/roles", cookies=auth_cookies).json()["live_delivery"]
        assert live["armed"] is True and live["live"] is False

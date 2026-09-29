"""Tests for /api/schedule/* endpoints."""

from unittest.mock import patch

from conftest import make_system_config

_UPDATE_TASK = "routers.schedule.update_scheduled_task"


class TestGetScheduleConfig:
    def test_get_defaults_when_no_config(self, client, db, auth_cookies):
        resp = client.get("/api/schedule/config", cookies=auth_cookies)
        assert resp.status_code == 200
        data = resp.json()
        assert data["interval_minutes"] == 120  # default = real cron (0 */2 * * *)
        assert data["batch_size"] == 20          # default
        assert data["last_updated"] is None

    def test_get_config_from_db(self, client, db, auth_cookies):
        make_system_config(db, "processing_interval_minutes", "120")
        make_system_config(db, "email_batch_size", "50")

        resp = client.get("/api/schedule/config", cookies=auth_cookies)
        assert resp.status_code == 200
        data = resp.json()
        assert data["interval_minutes"] == 120
        assert data["batch_size"] == 50
        assert data["last_updated"] is not None

    def test_requires_auth(self, client, db):
        resp = client.get("/api/schedule/config")
        assert resp.status_code == 401


class TestUpdateScheduleConfig:
    def test_update_interval(self, client, db, auth_cookies):
        with patch(_UPDATE_TASK):
            resp = client.post(
                "/api/schedule/config",
                json={"interval_minutes": 60},
                cookies=auth_cookies,
            )
        assert resp.status_code == 200
        assert resp.json()["interval_minutes"] == 60

        # Verify it persists
        get_resp = client.get("/api/schedule/config", cookies=auth_cookies)
        assert get_resp.json()["interval_minutes"] == 60

    def test_update_batch_size(self, client, db, auth_cookies):
        with patch(_UPDATE_TASK):
            resp = client.post(
                "/api/schedule/config",
                json={"batch_size": 50},
                cookies=auth_cookies,
            )
        assert resp.status_code == 200
        assert resp.json()["batch_size"] == 50

    def test_update_both(self, client, db, auth_cookies):
        with patch(_UPDATE_TASK):
            resp = client.post(
                "/api/schedule/config",
                json={"interval_minutes": 30, "batch_size": 30},
                cookies=auth_cookies,
            )
        assert resp.status_code == 200

        get_resp = client.get("/api/schedule/config", cookies=auth_cookies)
        data = get_resp.json()
        assert data["interval_minutes"] == 30
        assert data["batch_size"] == 30

    def test_invalid_interval_rejected(self, client, db, auth_cookies):
        resp = client.post(
            "/api/schedule/config",
            json={"interval_minutes": 7},  # not in [5, 10, 15, 30, 60, 120]
            cookies=auth_cookies,
        )
        assert resp.status_code == 400

    def test_invalid_batch_size_rejected(self, client, db, auth_cookies):
        resp = client.post(
            "/api/schedule/config",
            json={"batch_size": 99},  # not in [10, 20, 30, 50, 75, 100]
            cookies=auth_cookies,
        )
        assert resp.status_code == 400

    def test_empty_body_rejected(self, client, db, auth_cookies):
        resp = client.post("/api/schedule/config", json={}, cookies=auth_cookies)
        assert resp.status_code == 400

    def test_task_failure_returns_warning(self, client, db, auth_cookies):
        with patch(_UPDATE_TASK, side_effect=Exception("PowerShell failed")):
            resp = client.post(
                "/api/schedule/config",
                json={"interval_minutes": 60},
                cookies=auth_cookies,
            )
        # Config should still save despite task update failure
        assert resp.status_code == 200
        assert "task_warning" in resp.json()

    def test_requires_auth(self, client, db):
        resp = client.post("/api/schedule/config", json={"interval_minutes": 60})
        assert resp.status_code == 401

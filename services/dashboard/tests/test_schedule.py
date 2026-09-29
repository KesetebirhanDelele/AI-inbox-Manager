"""Tests for /api/schedule/* (read-only: reports the real cron interval and email cap)."""

import pytest


class TestGetScheduleConfig:
    def test_interval_matches_real_cron(self, client, db, auth_cookies):
        """0 */2 * * * in execution/crontab.server == 120 minutes."""
        resp = client.get("/api/schedule/config", cookies=auth_cookies)
        assert resp.status_code == 200
        data = resp.json()
        assert data["interval_minutes"] == 120
        assert data["last_updated"] is None
        assert data["updated_by"] is None

    def test_batch_size_defaults_to_pipeline_default(self, client, db, auth_cookies, monkeypatch):
        monkeypatch.delenv("MAX_EMAILS_PER_RUN", raising=False)
        resp = client.get("/api/schedule/config", cookies=auth_cookies)
        assert resp.json()["batch_size"] == 100

    def test_batch_size_from_env(self, client, db, auth_cookies, monkeypatch):
        monkeypatch.setenv("MAX_EMAILS_PER_RUN", "150")
        resp = client.get("/api/schedule/config", cookies=auth_cookies)
        assert resp.json()["batch_size"] == 150

    @pytest.mark.parametrize("bad", ["", "  ", "abc", "0", "-5", "1.5"])
    def test_bad_env_falls_back_to_default(self, client, db, auth_cookies, monkeypatch, bad):
        monkeypatch.setenv("MAX_EMAILS_PER_RUN", bad)
        resp = client.get("/api/schedule/config", cookies=auth_cookies)
        assert resp.status_code == 200
        assert resp.json()["batch_size"] == 100

    def test_requires_auth(self, client, db):
        resp = client.get("/api/schedule/config")
        assert resp.status_code == 401


class TestScheduleIsNotEditable:
    """The old save endpoint (and its Windows PowerShell call) was removed."""

    def test_post_is_not_allowed(self, client, db, auth_cookies):
        resp = client.post(
            "/api/schedule/config",
            json={"interval_minutes": 60},
            cookies=auth_cookies,
        )
        assert resp.status_code == 405

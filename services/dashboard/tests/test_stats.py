"""Tests for /api/stats/* endpoints."""

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from conftest import make_email, make_classification, make_approval, make_process_run


class TestSummaryStats:
    def test_summary_empty_db(self, client, db, auth_cookies):
        resp = client.get("/api/stats/summary", cookies=auth_cookies)
        assert resp.status_code == 200
        data = resp.json()
        assert data["today_total_emails"] == 0
        assert data["today_interview_requests"] == 0
        assert data["week_total_emails"] == 0
        assert data["pending_approvals"] == 0
        assert data["last_run_timestamp"] is None

    def test_summary_with_process_runs(self, client, db, auth_cookies):
        make_process_run(db, total_emails=30)
        make_process_run(db, total_emails=20)

        resp = client.get("/api/stats/summary", cookies=auth_cookies)
        assert resp.status_code == 200
        data = resp.json()
        assert data["today_total_emails"] == 50
        assert data["last_run_timestamp"] is not None

    def test_summary_pending_approvals_count(self, client, db, auth_cookies):
        email = make_email(db)
        clf = make_classification(db, email, confidence=0.60)
        make_approval(db, email, clf, status="pending")

        resp = client.get("/api/stats/summary", cookies=auth_cookies)
        assert resp.status_code == 200
        assert resp.json()["pending_approvals"] == 1

    def test_summary_excludes_old_runs(self, client, db, auth_cookies):
        old_date = datetime.utcnow() - timedelta(days=10)
        make_process_run(db, total_emails=100, run_timestamp=old_date)

        resp = client.get("/api/stats/summary", cookies=auth_cookies)
        assert resp.status_code == 200
        assert resp.json()["week_total_emails"] == 0

    def test_summary_requires_auth(self, client, db):
        resp = client.get("/api/stats/summary")
        assert resp.status_code == 401


class TestCategoryBreakdown:
    def test_categories_empty(self, client, db, auth_cookies):
        resp = client.get("/api/stats/categories", cookies=auth_cookies)
        assert resp.status_code == 200
        assert resp.json() == []

    def test_categories_with_data(self, client, db, auth_cookies):
        make_process_run(db, total_emails=10)

        resp = client.get("/api/stats/categories", cookies=auth_cookies)
        assert resp.status_code == 200
        data = resp.json()
        categories = [item["category"] for item in data]
        # "Job Alert" and "Application Notification" are deliberately hidden from
        # the breakdown chart (job-board noise; see EXCLUDED_CATEGORIES in
        # routers/stats.py) -- only meaningful categories should appear.
        assert "Job Alert" not in categories
        assert "Application Notification" not in categories
        assert "Interview Request" in categories

    def test_categories_date_filter(self, client, db, auth_cookies):
        old_date = datetime.utcnow() - timedelta(days=30)
        make_process_run(db, run_timestamp=old_date)

        resp = client.get(
            "/api/stats/categories",
            params={"start_date": "2099-01-01"},
            cookies=auth_cookies,
        )
        assert resp.status_code == 200
        assert resp.json() == []


class TestAccuracyMetrics:
    def test_accuracy_empty_db(self, client, db, auth_cookies):
        resp = client.get("/api/stats/accuracy", cookies=auth_cookies)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_approvals"] == 0
        assert data["override_rate"] == 0.0

    def test_accuracy_with_approvals(self, client, db, auth_cookies):
        email = make_email(db, email_id="msg001")
        clf = make_classification(db, email, confidence=0.65)
        make_approval(db, email, clf, status="approved")

        email2 = make_email(db, email_id="msg002")
        clf2 = make_classification(db, email2, confidence=0.60)
        make_approval(db, email2, clf2, status="overridden")

        resp = client.get("/api/stats/accuracy", cookies=auth_cookies)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_approvals"] == 2
        assert data["approved"] == 1
        assert data["overridden"] == 1
        assert data["override_rate"] == 0.5


class TestEngineeringKPIs:
    def test_kpis_empty_db(self, client, db, auth_cookies):
        resp = client.get("/api/stats/engineering-kpis", cookies=auth_cookies)
        assert resp.status_code == 200
        data = resp.json()
        assert data["run_count_7d"] == 0
        assert data["failure_rate_7d"] == 0.0
        assert data["ai_cost_today_usd"] == 0.0
        # The "days until storage is full" estimate was removed (2026-09-29).
        assert "db_storage_days_remaining" not in data

    def test_kpis_with_runs(self, client, db, auth_cookies):
        make_process_run(db, status="success", gpt_cost=0.05)
        make_process_run(db, status="failure", gpt_cost=0.02)

        resp = client.get("/api/stats/engineering-kpis", cookies=auth_cookies)
        assert resp.status_code == 200
        data = resp.json()
        assert data["run_count_7d"] == 2
        assert data["failed_run_count_7d"] == 1
        assert data["failure_rate_7d"] == 50.0
        assert data["ai_cost_today_usd"] == round(0.07, 4)


class TestRunNowInProduction:
    """In production Run Now QUEUES a request; the server's watcher starts the same run the scheduler does."""

    def _setup(self, monkeypatch, tmp_path, lock=None):
        import integration.process_runner as pr
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setattr(pr, "_project_root", lambda: tmp_path)
        monkeypatch.setattr(pr, "get_run_lock_status", lambda: lock)
        return pr

    def test_a_request_file_is_written_and_the_answer_says_it_is_queued(self, monkeypatch, tmp_path):
        pr = self._setup(monkeypatch, tmp_path)
        result = pr.run_email_processing(db=None, triggered_by="tester")  # db unused: returns first
        assert result["status"] == "queued" and "within a minute" in result["message"]
        import json
        data = json.loads((tmp_path / "tmp" / "run_now.request").read_text())
        assert data["requested_by"] == "tester"

    def test_a_second_click_does_not_stack_requests(self, monkeypatch, tmp_path):
        pr = self._setup(monkeypatch, tmp_path)
        pr.run_email_processing(db=None, triggered_by="a")
        again = pr.run_email_processing(db=None, triggered_by="b")
        assert again["status"] == "queued" and "already requested" in again["message"]
        import json
        assert json.loads((tmp_path / "tmp" / "run_now.request").read_text())["requested_by"] == "a"

    def test_a_run_in_progress_is_reported_and_nothing_is_queued(self, monkeypatch, tmp_path):
        pr = self._setup(monkeypatch, tmp_path, lock={"pid": 1, "triggered_by": "scheduled", "elapsed_seconds": 42.0})
        result = pr.run_email_processing(db=None, triggered_by="tester")
        assert result["status"] == "locked" and "already active" in result["message"]
        assert not (tmp_path / "tmp" / "run_now.request").exists()

    def test_an_unwritable_location_is_an_error_not_a_crash(self, monkeypatch, tmp_path):
        pr = self._setup(monkeypatch, tmp_path / "missing" / "deeper")
        monkeypatch.setattr(pr.Path, "mkdir", lambda *a, **k: (_ for _ in ()).throw(OSError("read-only")))
        result = pr.run_email_processing(db=None, triggered_by="tester")
        assert result["status"] == "error" and "read-only" in result["message"]


class TestDbStorageCap:
    """DB_STORAGE_CAP_MB drives the storage-countdown card's cap."""

    def test_default_is_neon_free_tier(self, monkeypatch):
        from routers.stats import _db_storage_cap_bytes
        monkeypatch.delenv("DB_STORAGE_CAP_MB", raising=False)
        assert _db_storage_cap_bytes() == 512 * 1024 * 1024

    def test_env_override(self, monkeypatch):
        from routers.stats import _db_storage_cap_bytes
        monkeypatch.setenv("DB_STORAGE_CAP_MB", "40960")
        assert _db_storage_cap_bytes() == 40960 * 1024 * 1024

    @pytest.mark.parametrize("bad", ["", "  ", "abc", "0", "-5"])
    def test_bad_values_fall_back_to_default(self, monkeypatch, bad):
        from routers.stats import _db_storage_cap_bytes
        monkeypatch.setenv("DB_STORAGE_CAP_MB", bad)
        assert _db_storage_cap_bytes() == 512 * 1024 * 1024


class TestProcessingRuns:
    def test_processing_runs_empty(self, client, db, auth_cookies):
        resp = client.get("/api/stats/processing-runs", cookies=auth_cookies)
        assert resp.status_code == 200
        assert resp.json() == []

    def test_processing_runs_returns_data(self, client, db, auth_cookies):
        make_process_run(db, total_emails=42)

        resp = client.get("/api/stats/processing-runs", cookies=auth_cookies)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["total_emails"] == 42
        assert data[0]["status"] == "success"

    def test_processing_runs_limit(self, client, db, auth_cookies):
        for i in range(5):
            make_process_run(db, total_emails=i)

        resp = client.get("/api/stats/processing-runs?limit=3", cookies=auth_cookies)
        assert resp.status_code == 200
        assert len(resp.json()) == 3


class TestTrends:
    def test_trends_empty(self, client, db, auth_cookies):
        resp = client.get("/api/stats/trends", cookies=auth_cookies)
        assert resp.status_code == 200
        assert resp.json() == {"trends": []}

    def test_trends_with_data(self, client, db, auth_cookies):
        make_process_run(db, total_emails=10)

        resp = client.get("/api/stats/trends?days=7", cookies=auth_cookies)
        assert resp.status_code == 200
        trends = resp.json()["trends"]
        assert len(trends) == 1
        assert trends[0]["total_emails"] == 10


class TestRunProcessingStatus:
    def test_run_status_not_locked(self, client, db, auth_cookies):
        with patch("routers.stats.get_run_lock_status", return_value=None):
            resp = client.get("/api/stats/run-processing/status", cookies=auth_cookies)
        assert resp.status_code == 200
        assert resp.json()["locked"] is False

    def test_run_status_locked(self, client, db, auth_cookies):
        lock_info = {"pid": 1234, "triggered_by": "admin", "elapsed_seconds": 30.0, "started_at": "2026-01-01T00:00:00"}
        with patch("routers.stats.get_run_lock_status", return_value=lock_info):
            resp = client.get("/api/stats/run-processing/status", cookies=auth_cookies)
        assert resp.status_code == 200
        data = resp.json()
        assert data["locked"] is True
        assert data["lock_info"]["pid"] == 1234


class TestOffersDetail:
    """The dashboard's "Offers Today" drill-through: who was offered and the details."""

    def _offer(self, db, body, subject="Offer of employment"):
        from conftest import make_email, make_classification
        email = make_email(db, subject=subject)
        email.full_body = body
        db.commit()
        make_classification(db, email, category="Offer", company="Acme Corp")
        return email

    def test_offer_names_the_student_whose_email_is_in_the_message(self, client, db, auth_cookies):
        from conftest import make_student
        make_student(db, username="kenya", full_name="Kenya Smith", personal_email="kenya@example.com")
        self._offer(db, "We are pleased to offer the role. Reply to kenya@example.com")
        row = client.get("/api/stats/offers", cookies=auth_cookies).json()[0]
        assert row["student_name"] == "Kenya Smith" and "email" in row["student_match"]
        assert row["company_name"] == "Acme Corp" and "pleased to offer" in row["full_body"]

    def test_offer_uses_the_greeting_name_only_when_exactly_one_student_fits(self, client, db, auth_cookies):
        from conftest import make_student
        make_student(db, username="kenya", full_name="Kenya Smith", personal_email="k@example.com")
        self._offer(db, "Dear Kenya, we would like to offer you the position.")
        assert client.get("/api/stats/offers", cookies=auth_cookies).json()[0]["student_name"] == "Kenya Smith"

    def test_offer_with_two_possible_students_or_none_is_not_guessed(self, client, db, auth_cookies):
        from conftest import make_student
        make_student(db, username="k1", full_name="Kenya Smith", personal_email="k1@example.com")
        make_student(db, username="k2", full_name="Kenya Jones", personal_email="k2@example.com")
        self._offer(db, "Dear Kenya, we would like to offer you the position.")
        row = client.get("/api/stats/offers", cookies=auth_cookies).json()[0]
        assert row["student_name"] is None and row["student_match"] is None

"""Date filters: the Dashboard's upcoming interviews and the Reports weekly summary take a range the user chooses."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from conftest import make_email, make_interview_event, make_process_run


def _central_today():
    return datetime.now(ZoneInfo("America/Chicago")).date()


class TestUpcomingStartDate:
    def test_start_date_can_look_back(self, client, db, auth_cookies):
        email = make_email(db)
        make_interview_event(db, email, interview_date="2020-01-15")
        assert client.get("/api/interviews/upcoming", cookies=auth_cookies).json() == []                    # default: today onward
        resp = client.get("/api/interviews/upcoming?start_date=2020-01-01", cookies=auth_cookies)
        assert [i["interview_date"] for i in resp.json()] == ["2020-01-15"]

    def test_start_date_is_inclusive_and_hides_earlier_days(self, client, db, auth_cookies):
        make_interview_event(db, make_email(db, email_id="a"), interview_date="2099-05-01")
        make_interview_event(db, make_email(db, email_id="b"), interview_date="2099-05-02")
        resp = client.get("/api/interviews/upcoming?start_date=2099-05-02", cookies=auth_cookies)
        assert [i["interview_date"] for i in resp.json()] == ["2099-05-02"]


class TestWeeklySummaryRange:
    def test_defaults_to_the_current_week_monday_to_sunday(self, client, db, auth_cookies):
        data = client.get("/api/stats/weekly-summary", cookies=auth_cookies).json()
        today = _central_today()
        monday = today - timedelta(days=today.weekday())
        assert data["week_start"] == monday.isoformat()
        assert data["week_end"] == (monday + timedelta(days=6)).isoformat()

    def test_counts_only_runs_inside_the_chosen_range(self, client, db, auth_cookies):
        make_process_run(db, total_emails=10, run_timestamp=datetime(2026, 10, 5, 18, 0))     # 1 PM Central, Oct 5
        make_process_run(db, total_emails=20, run_timestamp=datetime(2026, 10, 7, 18, 0))
        make_process_run(db, total_emails=40, run_timestamp=datetime(2026, 10, 20, 18, 0))
        data = client.get("/api/stats/weekly-summary?start_date=2026-10-05&end_date=2026-10-07", cookies=auth_cookies).json()
        assert data["total_emails_processed"] == 30 and data["processing_runs"] == 2
        assert (data["week_start"], data["week_end"]) == ("2026-10-05", "2026-10-07")
        wide = client.get("/api/stats/weekly-summary?start_date=2026-10-01&end_date=2026-10-31", cookies=auth_cookies).json()
        assert wide["total_emails_processed"] == 70

    def test_the_end_day_is_included_through_its_last_hour(self, client, db, auth_cookies):
        make_process_run(db, total_emails=5, run_timestamp=datetime(2026, 10, 8, 4, 30))      # 11:30 PM Central, Oct 7
        data = client.get("/api/stats/weekly-summary?start_date=2026-10-07&end_date=2026-10-07", cookies=auth_cookies).json()
        assert data["total_emails_processed"] == 5

    def test_a_backwards_or_huge_range_is_refused_with_a_plain_message(self, client, db, auth_cookies):
        back = client.get("/api/stats/weekly-summary?start_date=2026-10-08&end_date=2026-10-01", cookies=auth_cookies)
        assert back.status_code == 400 and "before" in back.json()["detail"]
        huge = client.get("/api/stats/weekly-summary?start_date=2020-01-01&end_date=2026-01-01", cookies=auth_cookies)
        assert huge.status_code == 400

"""Tests for /api/interviews/* endpoints."""

from conftest import make_email, make_classification, make_student, make_interview_event


class TestGetInterviewRequests:
    def test_empty_db(self, client, db, auth_cookies):
        resp = client.get("/api/interviews/", cookies=auth_cookies)
        assert resp.status_code == 200
        assert resp.json() == []

    def test_the_list_answers_without_a_trailing_slash_and_never_redirects(self, client, db, auth_cookies):
        # behind the Caddy proxy a 307 pointed at http:// and the browser showed an empty page
        email = make_email(db, subject="Interview - Data Analyst")
        make_classification(db, email, category="Interview Request", confidence=0.9)
        resp = client.get("/api/interviews?limit=200&offset=0", cookies=auth_cookies, follow_redirects=False)
        assert resp.status_code == 200 and len(resp.json()) == 1

    def test_returns_interview_requests(self, client, db, auth_cookies):
        email = make_email(db, subject="Phone Screen - Data Analyst at Acme")
        make_classification(db, email, category="Interview Request", confidence=0.95)

        resp = client.get("/api/interviews/", cookies=auth_cookies)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["subject"] == "Phone Screen - Data Analyst at Acme"
        assert data[0]["confidence"] == 0.95

    def test_ignores_non_interview_emails(self, client, db, auth_cookies):
        email = make_email(db)
        make_classification(db, email, category="Job Alert", confidence=0.90)

        resp = client.get("/api/interviews/", cookies=auth_cookies)
        assert resp.status_code == 200
        assert resp.json() == []

    def test_pagination_limit(self, client, db, auth_cookies):
        for i in range(5):
            email = make_email(db, email_id=f"msg{i:03d}", subject=f"Interview {i}")
            make_classification(db, email, category="Interview Request")

        resp = client.get("/api/interviews/?limit=3", cookies=auth_cookies)
        assert resp.status_code == 200
        assert len(resp.json()) == 3

    def test_pagination_offset(self, client, db, auth_cookies):
        for i in range(4):
            email = make_email(db, email_id=f"msg{i:03d}", subject=f"Interview {i}")
            make_classification(db, email, category="Interview Request")

        resp = client.get("/api/interviews/?limit=10&offset=2", cookies=auth_cookies)
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_includes_interview_event_details(self, client, db, auth_cookies):
        student = make_student(db)
        email = make_email(db, subject="Phone Screen")
        make_classification(db, email, category="Interview Request")
        make_interview_event(db, email, student=student, sub_type="Phone Screen", company="TechCorp")

        resp = client.get("/api/interviews/", cookies=auth_cookies)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["interview_date"] == "2099-04-15"
        assert data[0]["interview_event_id"] is not None

    def test_requires_auth(self, client, db):
        resp = client.get("/api/interviews/")
        assert resp.status_code == 401


class TestGetInterviewCount:
    def test_count_empty(self, client, db, auth_cookies):
        resp = client.get("/api/interviews/count", cookies=auth_cookies)
        assert resp.status_code == 200
        assert resp.json()["count"] == 0

    def test_count_with_interviews(self, client, db, auth_cookies):
        for i in range(3):
            email = make_email(db, email_id=f"msg{i:03d}")
            make_classification(db, email, category="Interview Request")

        resp = client.get("/api/interviews/count", cookies=auth_cookies)
        assert resp.status_code == 200
        assert resp.json()["count"] == 3

    def test_count_excludes_non_interviews(self, client, db, auth_cookies):
        email = make_email(db)
        make_classification(db, email, category="Job Alert")

        resp = client.get("/api/interviews/count", cookies=auth_cookies)
        assert resp.status_code == 200
        assert resp.json()["count"] == 0


class TestGetUpcomingInterviews:
    def test_upcoming_empty(self, client, db, auth_cookies):
        resp = client.get("/api/interviews/upcoming", cookies=auth_cookies)
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_future_interviews(self, client, db, auth_cookies):
        student = make_student(db)
        email = make_email(db)
        event = make_interview_event(db, email, student=student, interview_date="2099-12-31")

        resp = client.get("/api/interviews/upcoming", cookies=auth_cookies)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["interview_date"] == "2099-12-31"
        assert data[0]["company_name"] == "Acme Corp"

    def test_excludes_past_interviews(self, client, db, auth_cookies):
        email = make_email(db)
        make_interview_event(db, email, interview_date="2020-01-01")

        resp = client.get("/api/interviews/upcoming", cookies=auth_cookies)
        assert resp.status_code == 200
        assert resp.json() == []

    def test_ordered_by_date_ascending(self, client, db, auth_cookies):
        email1 = make_email(db, email_id="msg001")
        email2 = make_email(db, email_id="msg002")
        make_interview_event(db, email1, interview_date="2099-06-01")
        make_interview_event(db, email2, interview_date="2099-05-01")

        resp = client.get("/api/interviews/upcoming", cookies=auth_cookies)
        assert resp.status_code == 200
        data = resp.json()
        assert data[0]["interview_date"] == "2099-05-01"
        assert data[1]["interview_date"] == "2099-06-01"


class TestGetInterviewDetail:
    def test_get_by_id_success(self, client, db, auth_cookies):
        email = make_email(db, subject="Technical Interview at BigCo", email_id="msgABC")
        clf = make_classification(db, email, category="Interview Request", confidence=0.88)

        resp = client.get(f"/api/interviews/{email.id}", cookies=auth_cookies)
        assert resp.status_code == 200
        data = resp.json()
        assert data["subject"] == "Technical Interview at BigCo"
        assert data["confidence"] == 0.88

    def test_get_by_id_not_found(self, client, db, auth_cookies):
        resp = client.get("/api/interviews/99999", cookies=auth_cookies)
        assert resp.status_code == 200
        assert "error" in resp.json()

    def test_get_by_id_wrong_category(self, client, db, auth_cookies):
        email = make_email(db)
        make_classification(db, email, category="Job Alert")  # not an interview

        resp = client.get(f"/api/interviews/{email.id}", cookies=auth_cookies)
        assert resp.status_code == 200
        assert "error" in resp.json()


class TestInterviewEventsList:
    """/api/interviews/events feeds the merged Interviews page (the Events Report was retired)."""

    def test_each_event_carries_student_email_draft_and_status(self, client, db, auth_cookies):
        from conftest import make_notification_draft
        student = make_student(db)
        email = make_email(db, subject="Phone screen - Acme", from_address="rohit.s@acme.com")
        event = make_interview_event(db, email, student=student, company="Acme Corp")
        draft = make_notification_draft(db, event)

        rows = client.get("/api/interviews/events", cookies=auth_cookies).json()
        assert len(rows) == 1
        row = rows[0]
        assert row["event_id"] == event.id and row["student_name"] == student.full_name
        assert row["subject"] == "Phone screen - Acme" and row["from_address"] == "rohit.s@acme.com"
        assert row["draft_id"] == draft.id and row["notification_status"] == "draft" and row["email_id"] == email.id
        assert row["received_date"] is not None and "confidence" in row

    def test_an_event_with_no_student_or_draft_still_appears(self, client, db, auth_cookies):
        event = make_interview_event(db, make_email(db), student=None)
        row = client.get("/api/interviews/events", cookies=auth_cookies).json()[0]
        assert row["event_id"] == event.id and row["student_name"] == "Unknown"
        assert row["draft_id"] is None and row["notification_status"] is None

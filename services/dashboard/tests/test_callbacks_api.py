"""The callback list, "Called back", and the flags on the approval screen and Interviews."""
from datetime import datetime, timedelta

from conftest import make_email, make_interview_event, make_notification_draft, make_student


def add_callback(db, student=None, minutes_ago=10, status="open", call_id="c1"):
    from models import CallbackRequest
    req = CallbackRequest(ghl_call_id=call_id, received_at=datetime.utcnow() - timedelta(minutes=minutes_ago), status=status,
                          caller_number="+19725550100", said="returning a call about an interview", student_id=student.id if student else None)
    db.add(req)
    db.commit()
    return req


class TestCallbacks:
    def test_open_callbacks_are_listed_with_the_student_and_their_interviews(self, client, db, auth_cookies):
        student = make_student(db)
        make_interview_event(db, make_email(db), student=student, company="Acme Corp")
        add_callback(db, student)
        rows = client.get("/api/callbacks", cookies=auth_cookies).json()
        assert len(rows) == 1 and rows[0]["student_name"] == student.full_name and rows[0]["status"] == "open"
        assert rows[0]["interviews"] == ["Acme Corp, Data Analyst"] and rows[0]["caller_number"] == "+19725550100" and "due_at" in rows[0]

    def test_an_unknown_caller_is_listed_without_a_student(self, client, db, auth_cookies):
        add_callback(db, None)
        row = client.get("/api/callbacks", cookies=auth_cookies).json()[0]
        assert row["student_id"] is None and row["student_name"] is None

    def test_called_back_closes_it_records_who_and_hides_it(self, client, db, auth_cookies):
        req = add_callback(db, make_student(db))
        resp = client.post(f"/api/callbacks/{req.id}/done", cookies=auth_cookies)
        assert resp.status_code == 200 and resp.json()["status"] == "done" and resp.json()["done_by"]
        assert client.get("/api/callbacks", cookies=auth_cookies).json() == []
        assert len(client.get("/api/callbacks?include_done=true", cookies=auth_cookies).json()) == 1
        assert client.post("/api/callbacks/999/done", cookies=auth_cookies).status_code == 404

    def test_the_approval_screen_carries_the_open_callbacks(self, client, db, auth_cookies):
        student = make_student(db)
        make_notification_draft(db, make_interview_event(db, make_email(db), student=student))
        add_callback(db, student)
        data = client.get("/api/notifications/review-queue", cookies=auth_cookies).json()
        assert len(data["callbacks"]) == 1 and data["callbacks"][0]["student_id"] == student.id

    def test_interviews_flag_a_student_with_an_open_callback_only(self, client, db, auth_cookies):
        waiting, quiet = make_student(db, username="a", full_name="A"), make_student(db, username="b", full_name="B")
        make_interview_event(db, make_email(db, email_id="1"), student=waiting)
        make_interview_event(db, make_email(db, email_id="2"), student=quiet)
        add_callback(db, waiting)
        flags = {r["student_name"]: r["callback_open"] for r in client.get("/api/interviews/events", cookies=auth_cookies).json()}
        assert flags == {"A": True, "B": False}

    def test_requires_login(self, client):
        assert client.get("/api/callbacks").status_code == 401

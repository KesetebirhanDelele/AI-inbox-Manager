"""Tests for /api/checklist/* endpoints."""

from conftest import make_email, make_interview_event, make_student


# "Phone Screen" sub_type normalizes to "phone_screen"
# Valid step keys from checklist_steps.py:
#   Main: "phone_screen.1", "phone_screen.2", ...
#   Sub:  "phone_screen.1.1", "phone_screen.2.1", ...
_VALID_STEP = "phone_screen.1.1"
_MAIN_STEP = "phone_screen.1"


class TestGetChecklist:
    def test_returns_checklist_for_event(self, client, db, auth_cookies):
        email = make_email(db)
        event = make_interview_event(db, email, sub_type="Phone Screen")

        resp = client.get(f"/api/checklist/{event.id}", cookies=auth_cookies)
        assert resp.status_code == 200
        data = resp.json()
        assert data["interview_event_id"] == event.id
        assert data["sub_type"] == "phone_screen"
        assert data["total_steps"] > 0
        assert data["completed_steps"] == 0
        assert data["progress_percent"] == 0.0
        assert len(data["steps"]) > 0

    def test_event_not_found(self, client, db, auth_cookies):
        resp = client.get("/api/checklist/99999", cookies=auth_cookies)
        assert resp.status_code == 404

    def test_unknown_sub_type_gets_the_generic_three_step_checklist(self, client, db, auth_cookies):
        email = make_email(db)
        event = make_interview_event(db, email, sub_type="Unknown Type")

        resp = client.get(f"/api/checklist/{event.id}", cookies=auth_cookies)
        assert resp.status_code == 200
        data = resp.json()
        assert data["sub_type"] == "other" and [s["label"] for s in data["steps"]] == [
            "Check the email", "Notify the student (call, text and email)", "Make sure the student knows"]

    def test_every_interview_type_uses_the_current_wording(self):
        from checklist_steps import CHECKLIST_DEFINITIONS
        for name, defn in CHECKLIST_DEFINITIONS.items():
            labels = " ".join(s["label"] for s in defn["steps"]) + " " + " ".join(
                sub["label"] for s in defn["steps"] for sub in s["sub_steps"])
            assert "personal email" not in labels and "Notify the student (call, text and email)" in labels, name
            assert [s["key"] for s in defn["steps"]] == [f"{name}.1", f"{name}.2", f"{name}.3"]

    def test_requires_auth(self, client, db):
        resp = client.get("/api/checklist/1")
        assert resp.status_code == 401


class TestToggleChecklistStep:
    def test_mark_step_completed(self, client, db, auth_cookies):
        email = make_email(db)
        event = make_interview_event(db, email, sub_type="Phone Screen")

        resp = client.put(
            f"/api/checklist/{event.id}/toggle",
            json={"step_key": _VALID_STEP, "is_completed": True},
            cookies=auth_cookies,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_completed"] is True
        assert data["step_key"] == _VALID_STEP

    def test_step_appears_completed_in_get(self, client, db, auth_cookies):
        email = make_email(db)
        event = make_interview_event(db, email, sub_type="Phone Screen")

        client.put(
            f"/api/checklist/{event.id}/toggle",
            json={"step_key": _VALID_STEP, "is_completed": True},
            cookies=auth_cookies,
        )

        get_resp = client.get(f"/api/checklist/{event.id}", cookies=auth_cookies)
        assert get_resp.status_code == 200
        data = get_resp.json()
        assert data["completed_steps"] == 1
        assert data["progress_percent"] > 0

    def test_unmark_step(self, client, db, auth_cookies):
        email = make_email(db)
        event = make_interview_event(db, email, sub_type="Phone Screen")

        # Mark completed
        client.put(
            f"/api/checklist/{event.id}/toggle",
            json={"step_key": _VALID_STEP, "is_completed": True},
            cookies=auth_cookies,
        )
        # Unmark
        resp = client.put(
            f"/api/checklist/{event.id}/toggle",
            json={"step_key": _VALID_STEP, "is_completed": False},
            cookies=auth_cookies,
        )
        assert resp.status_code == 200
        assert resp.json()["is_completed"] is False

        get_resp = client.get(f"/api/checklist/{event.id}", cookies=auth_cookies)
        assert get_resp.json()["completed_steps"] == 0

    def test_invalid_step_key_rejected(self, client, db, auth_cookies):
        email = make_email(db)
        event = make_interview_event(db, email, sub_type="Phone Screen")

        resp = client.put(
            f"/api/checklist/{event.id}/toggle",
            json={"step_key": "phone_screen.99.99", "is_completed": True},
            cookies=auth_cookies,
        )
        assert resp.status_code == 400

    def test_toggle_event_not_found(self, client, db, auth_cookies):
        resp = client.put(
            "/api/checklist/99999/toggle",
            json={"step_key": _VALID_STEP, "is_completed": True},
            cookies=auth_cookies,
        )
        assert resp.status_code == 404

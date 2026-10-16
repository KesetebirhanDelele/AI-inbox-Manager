"""Every open interview notice shows whether the student is on the roster and found in GHL. Flags warn; they never block or hide anything."""
import sys
from pathlib import Path

from conftest import make_email, make_interview_event, make_notification_draft, make_student

_EXEC = str(Path(__file__).resolve().parents[3] / "execution")
if _EXEC not in sys.path:
    sys.path.insert(0, _EXEC)


def _item(client, auth_cookies, student):
    items = client.get("/api/notifications/review-queue", cookies=auth_cookies).json()["items"]
    return next(i for i in items if i["student"] and i["student"]["id"] == student.id)


def test_a_student_off_the_roster_and_not_in_ghl_is_flagged_but_still_listed_and_approvable(client, db, auth_cookies, monkeypatch):
    import student_flags
    monkeypatch.setattr(student_flags, "roster_status", lambda s, roster=None: "unlisted")
    monkeypatch.setattr(student_flags, "ghl_status", lambda s, **k: "not_found")
    student = make_student(db, username="stray", full_name="Stray Person")
    event = make_interview_event(db, make_email(db), student=student)
    make_notification_draft(db, event, email_status="draft")

    item = _item(client, auth_cookies, student)
    assert item["flags"] == {"roster": "unlisted", "ghl": "not_found"}
    assert item["warnings"][0].startswith("NOT ON THE ROSTER") and any(w.startswith("NOT IN GHL") for w in item["warnings"])
    assert not any("ROSTER" in b or "GHL" in b for b in item["blockers"])         # a person decides; the flag never blocks Approve


def test_a_listed_student_found_in_ghl_has_no_roster_or_ghl_warning(client, db, auth_cookies, monkeypatch):
    import student_flags
    monkeypatch.setattr(student_flags, "roster_status", lambda s, roster=None: "listed")
    monkeypatch.setattr(student_flags, "ghl_status", lambda s, **k: "found")
    student = make_student(db, username="fine", full_name="Fine Person")
    make_notification_draft(db, make_interview_event(db, make_email(db), student=student), email_status="draft")
    item = _item(client, auth_cookies, student)
    assert item["flags"] == {"roster": "listed", "ghl": "found"}
    assert not any(w.startswith(("NOT ON THE ROSTER", "NOT IN GHL", "On the roster by NAME", "GHL lookup")) for w in item["warnings"])


def test_unreachable_roster_or_ghl_shows_unknown_and_changes_nothing(client, db, auth_cookies, monkeypatch):
    import student_flags

    def boom(*a, **k):
        raise RuntimeError("sheet down")
    monkeypatch.setattr(student_flags, "roster_status", boom)
    student = make_student(db, username="quiet", full_name="Quiet Person")
    make_notification_draft(db, make_interview_event(db, make_email(db), student=student), email_status="draft")
    item = _item(client, auth_cookies, student)
    assert item["flags"] == {"roster": "unknown", "ghl": "unknown"} and not any(w.startswith("NOT ON THE ROSTER") for w in item["warnings"])


def test_decided_notices_leave_the_main_list_and_show_under_show_finished(client, db, auth_cookies):
    waiting = make_student(db, username="waiting", full_name="Waiting Person")
    decided = make_student(db, username="decided", full_name="Decided Person")
    make_notification_draft(db, make_interview_event(db, make_email(db), student=waiting), email_status="draft")
    make_notification_draft(db, make_interview_event(db, make_email(db), student=decided), email_status="approved")

    def students(url):
        items = client.get(url, cookies=auth_cookies).json()["items"]
        return {i["student"]["id"] for i in items if i["student"]}
    assert students("/api/notifications/review-queue") == {waiting.id}                          # only what still needs a decision
    assert students("/api/notifications/review-queue?include_done=true") == {waiting.id, decided.id}


def test_a_follow_up_leaves_the_main_list_and_shows_under_show_finished_labelled(client, db, auth_cookies):
    from models import InterviewFollowUp
    student = make_student(db, username="rem", full_name="Reminded Person")
    original = make_interview_event(db, make_email(db), student=student)
    make_notification_draft(db, original, email_status="approved")
    reminder = make_interview_event(db, make_email(db), student=student)            # no draft: a reminder about the same interview
    db.add(InterviewFollowUp(event_id=reminder.id, original_event_id=original.id, reason="same interview, same time"))
    db.commit()

    open_items = client.get("/api/notifications/review-queue", cookies=auth_cookies).json()["items"]
    assert reminder.id not in [i["event_id"] for i in open_items]
    done = client.get("/api/notifications/review-queue?include_done=true", cookies=auth_cookies).json()["items"]
    item = next(i for i in done if i["event_id"] == reminder.id)
    assert item["state"] == "follow_up" and item["follow_up_of"] == original.id and item["blockers"] == []

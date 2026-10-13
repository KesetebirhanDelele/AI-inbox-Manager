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

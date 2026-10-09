"""One-off backfill: label (and move) the emails of unverified students 'Verify Student'. Never touches a verified student's mail."""
import sys
from datetime import datetime
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "execution"))

import label_verify_students as lvs  # noqa: E402


@pytest.fixture
def db_models(monkeypatch):
    monkeypatch.syspath_prepend(str(_ROOT / "services" / "dashboard" / "api"))
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import models
    engine = create_engine("sqlite://")
    models.Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)(), models


def _add(db, M, n, verified, draft_status="draft", folder="INBOX"):
    student = M.Student(username=f"s{n}", full_name=f"Student {n}", is_active=True)
    db.add(student); db.flush()
    db.add(M.StudentVerification(student_id=student.id, status="verified" if verified else "unverified", basis="gmail_guess"))
    email = M.Email(email_id=str(n), message_id=f"<m{n}@x>", subject="s", from_address="a@b.com", received_date=datetime(2026, 10, n),
                    current_folder=folder)
    db.add(email); db.flush()
    event = M.InterviewEvent(email_id=email.id, student_id=student.id, sub_type="Interview Request", confidence=0.9)
    db.add(event); db.flush()
    db.add(M.NotificationDraft(interview_event_id=event.id, template_id="t", email_subject="s", email_body="b",
                               recipient_email="a@b.com", email_status=draft_status))
    db.commit()
    return email


def test_plan_picks_only_unverified_students_with_a_pending_draft(db_models):
    db, M = db_models
    a = _add(db, M, 1, verified=False)
    _add(db, M, 2, verified=True)                              # verified: never touched
    _add(db, M, 3, verified=False, draft_status="rejected")    # draft already closed
    _add(db, M, 4, verified=False, folder="Verify Student")    # already there
    c = _add(db, M, 5, verified=False, folder="Phone Screen (HR or Recruiter)")
    items = lvs.plan(db)
    assert {i["email_id"] for i in items} == {a.id, c.id}
    assert {i["folder"] for i in items} == {"INBOX", "Phone Screen (HR or Recruiter)"}
    assert {i["email_id"] for i in lvs.plan(db, all_drafts=True)} >= {a.id, c.id}


class FakeImap:
    """Just enough IMAP: folders hold {uid: message_id}; All Mail holds everything."""

    def __init__(self, folders):
        self.folders = folders
        self.selected = None
        self.labels, self.flags, self.expunged = [], [], []

    def select(self, name):
        name = name.strip('"')
        if name not in self.folders:
            return "NO", []
        self.selected = name
        return "OK", []

    def uid(self, cmd, *args):
        box = self.folders[self.selected]
        if cmd == "SEARCH":
            mid = args[-1]
            hit = [u for u, m in box.items() if m == mid]
            return "OK", [" ".join(hit).encode()]
        if cmd == "STORE":
            uid, op, val = args
            (self.labels if "LABELS" in op else self.flags).append((self.selected, uid, val))
            return "OK", []
        if cmd == "EXPUNGE":
            self.expunged.append((self.selected, args[0]))
            return "OK", []
        raise AssertionError(cmd)


def test_apply_labels_in_all_mail_then_removes_from_the_old_folder_only():
    imap = FakeImap({
        "[Gmail]/All Mail": {"900": "<m1@x>", "901": "<m5@x>"},
        "INBOX": {"11": "<m1@x>", "12": "<other@x>"},
        "Phone Screen (HR or Recruiter)": {"3": "<m5@x>"},
    })
    items = [{"email_id": 1, "message_id": "<m1@x>", "folder": "INBOX"},
             {"email_id": 5, "message_id": "<m5@x>", "folder": "Phone Screen (HR or Recruiter)"}]
    out = lvs.apply_items(imap, items, move=True)
    assert out["labelled"] == [1, 5] and out["moved"] == [1, 5] and out["skipped"] == []
    assert [x[0] for x in imap.labels] == ["[Gmail]/All Mail", "[Gmail]/All Mail"]
    # only the target message is flagged and expunged, in its own folder, by UID: the other INBOX message is untouched
    assert ("INBOX", "11", "(\Deleted)") in imap.flags and all(f[1] != "12" for f in imap.flags)
    assert ("INBOX", "11") in imap.expunged and ("Phone Screen (HR or Recruiter)", "3") in imap.expunged


def test_a_message_that_cannot_be_found_is_skipped_not_deleted():
    imap = FakeImap({"[Gmail]/All Mail": {"1": "<other@x>"}, "INBOX": {"2": "<other@x>"}})
    out = lvs.apply_items(imap, [{"email_id": 1, "message_id": "<missing@x>", "folder": "INBOX"}])
    assert out["skipped"] == [1] and out["labelled"] == [] and imap.flags == [] and imap.expunged == []


def test_keep_in_place_only_labels():
    imap = FakeImap({"[Gmail]/All Mail": {"900": "<m1@x>"}, "INBOX": {"11": "<m1@x>"}})
    out = lvs.apply_items(imap, [{"email_id": 1, "message_id": "<m1@x>", "folder": "INBOX"}], move=False)
    assert out["labelled"] == [1] and out["moved"] == [] and imap.flags == [] and imap.expunged == []

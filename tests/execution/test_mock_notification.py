"""The mock-notification tool: a clearly marked, open card for one existing student; nothing else."""
import sys
from datetime import datetime
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "execution"))

import mock_notification as mn  # noqa: E402


@pytest.fixture
def db(monkeypatch):
    monkeypatch.syspath_prepend(str(_ROOT / "services" / "dashboard" / "api"))
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import models
    engine = create_engine("sqlite://")
    models.Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    s.models = models
    s.student = models.Student(username="kes", full_name="Kes Tester", personal_email="kes@example.com", phone_number="+15551230000", is_active=True)
    s.add(s.student)
    s.commit()
    return s


def test_it_creates_one_marked_open_card_for_the_chosen_student(db):
    event, draft = mn.create_mock(db, db.student.id, now=datetime(2026, 10, 20, 18, 0))
    assert event.student_id == db.student.id and event.company_name == mn.MOCK_COMPANY and event.interview_date == "2026-10-21"
    assert draft.email_status == "draft" and draft.recipient_email == "kes@example.com" and "[TEST]" in draft.email_subject
    assert db.query(db.models.Email).one().subject.startswith("[TEST]")
    assert db.query(db.models.NotificationSequence).count() == 0                     # nothing started: only approving does that


def test_a_student_with_no_way_to_be_reached_is_refused(db):
    s = db.models.Student(username="x", full_name="No Contact", is_active=True)
    db.add(s); db.commit()
    with pytest.raises(SystemExit):
        mn.create_mock(db, s.id)


def test_an_unknown_student_is_refused(db):
    with pytest.raises(SystemExit):
        mn.create_mock(db, 9999)


def test_find_matches_name_username_or_email_and_masks_contacts(db):
    assert [s.id for s in mn.find_students(db, "KES")] == [db.student.id]
    assert mn.find_students(db, "nobody") == []
    assert mn._mask("kes@example.com") == "ke***@example.com" and mn._mask("+15551230000") == "***0000"


def test_the_card_is_a_normal_open_card_the_approver_alert_would_announce(db):
    import review_alerts as ra
    db.add(db.models.RoleAssignment(role="approver", email="kes@example.com", active=True)); db.commit()
    ra.run(db, alerts=type("C", (), {"review_needed": lambda self, s, b: True})())   # baseline
    mn.create_mock(db, db.student.id)
    sent = []
    cap = type("C", (), {"review_needed": lambda self, s, b: sent.append(b) or True})()
    assert ra.run(db, alerts=cap)["alerted"] == 1 and "TEST Company (mock)" in sent[0] and "/approve/" in sent[0]


def test_a_student_row_is_made_from_exactly_one_roster_entry_only_when_asked(db):
    from student_roster import RosterRow
    rows = [RosterRow(name="Kesetebirhan Yirdaw", status="Active", agent="Karthik", emails=["app@example.com", "me@example.com"]),
            RosterRow(name="Someone Else", status="Active", emails=["x@example.com"])]
    student, row = mn.student_from_roster(db, "kesetebirhan", rows, create=False)
    assert student is None and row.name == "Kesetebirhan Yirdaw"                               # dry run writes nothing
    assert db.query(db.models.Student).filter_by(username="kesetebirhan.yirdaw").count() == 0
    student, _ = mn.student_from_roster(db, "kesetebirhan", rows, create=True)
    assert student.full_name == "Kesetebirhan Yirdaw" and student.personal_email == "me@example.com" and student.assigned_gmail == "app@example.com"
    again, _ = mn.student_from_roster(db, "kesetebirhan", rows, create=True)
    assert again.id == student.id                                                              # twice does not duplicate


def test_zero_or_several_roster_matches_are_refused(db):
    from student_roster import RosterRow
    rows = [RosterRow(name="Ann Lee", status="Active", emails=["a@example.com"]), RosterRow(name="Ann Lo", status="Active", emails=["b@example.com"])]
    for fragment in ("nobody", "ann", ""):
        with pytest.raises(SystemExit):
            mn.student_from_roster(db, fragment, rows, create=True)

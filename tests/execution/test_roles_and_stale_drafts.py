"""Roles instead of people, business-hours arithmetic, and the once-only stale-draft alert to the escalation role."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_EXEC = Path(__file__).resolve().parents[2] / "execution"
sys.path.insert(0, str(_EXEC))

import business_hours as bh  # noqa: E402
import roles  # noqa: E402

CHI = bh.BusinessHours()          # Mon-Fri 09:00-17:00 America/Chicago


def utc(y, mo, d, h, mi=0):
    """A Chicago wall-clock time (CDT in October) as naive UTC."""
    return (datetime(y, mo, d, h, mi) + timedelta(hours=5))


# ── business hours ────────────────────────────────────────────────────────────────────────────

def test_a_morning_and_an_afternoon_inside_one_day_count_fully():
    assert bh.business_minutes_between(utc(2026, 10, 6, 10), utc(2026, 10, 6, 12, 30), CHI) == 150


def test_nights_and_weekends_do_not_count():
    # Friday 16:00 -> Monday 10:00 = 1h Friday + 1h Monday
    assert bh.business_minutes_between(utc(2026, 10, 2, 16), utc(2026, 10, 5, 10), CHI) == 120
    assert bh.business_minutes_between(utc(2026, 10, 3, 9), utc(2026, 10, 4, 17), CHI) == 0       # Sat -> Sun


def test_overnight_runs_from_close_to_open():
    # Tuesday 16:30 -> Wednesday 09:30 = 30 min + 30 min
    assert bh.business_minutes_between(utc(2026, 10, 6, 16, 30), utc(2026, 10, 7, 9, 30), CHI) == 60


def test_end_before_start_is_zero_and_is_business_time():
    assert bh.business_minutes_between(utc(2026, 10, 6, 12), utc(2026, 10, 6, 10), CHI) == 0
    assert bh.is_business_time(utc(2026, 10, 6, 9), CHI) and not bh.is_business_time(utc(2026, 10, 6, 17), CHI)
    assert not bh.is_business_time(utc(2026, 10, 3, 11), CHI)                                    # Saturday


def test_hours_come_from_the_environment_and_bad_values_fall_back():
    h = bh.BusinessHours.from_env({"BUSINESS_HOURS_TZ": "America/New_York", "BUSINESS_HOURS_START": "8", "BUSINESS_HOURS_END": "18", "BUSINESS_DAYS": "0,1,2"})
    assert (h.tz, h.start_hour, h.end_hour, h.days) == ("America/New_York", 8, 18, (0, 1, 2))
    assert bh.BusinessHours.from_env({"BUSINESS_HOURS_START": "20", "BUSINESS_HOURS_END": "9"}) == CHI
    assert bh.BusinessHours.from_env({"BUSINESS_DAYS": "x"}) == CHI


# ── roles ─────────────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def db(monkeypatch):
    monkeypatch.syspath_prepend(str(_EXEC.parents[0] / "services" / "dashboard" / "api"))
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import models
    engine = create_engine("sqlite://")
    models.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.models = models
    return session


def test_a_role_resolves_from_the_database_then_the_environment(db):
    assert roles.role_email(db, "escalation_target", {}) == ""
    assert roles.role_email(db, "escalation_target", {"ESCALATION_ALERT_EMAIL": "env@example.com"}) == "env@example.com"
    db.add(db.models.RoleAssignment(role="escalation_target", email="holder@example.com", active=True))
    db.commit()
    assert roles.role_email(db, "escalation_target", {"ESCALATION_ALERT_EMAIL": "env@example.com"}) == "holder@example.com"


def test_an_inactive_assignment_is_ignored_and_the_newest_wins(db):
    M = db.models
    db.add_all([M.RoleAssignment(role="approver", email="old@example.com", active=True),
                M.RoleAssignment(role="approver", email="off@example.com", active=False)])
    db.commit()
    assert roles.role_email(db, "approver", {}) == "old@example.com"
    db.add(M.RoleAssignment(role="approver", email="new@example.com", active=True))
    db.commit()
    assert roles.role_email(db, "approver", {}) == "new@example.com"


def test_an_unknown_role_is_an_error_and_the_copy_list_follows_the_escalation_role(db):
    with pytest.raises(ValueError):
        roles.role_email(db, "rob", {})
    assert roles.notice_copy_emails(db, {}) == []
    db.add(db.models.RoleAssignment(role="escalation_target", email="holder@example.com", active=True))
    db.commit()
    assert roles.notice_copy_emails(db, {}) == ["holder@example.com"]


def test_no_person_is_written_into_the_code():
    import re
    pattern = re.compile(r"\b(rob|jackie|shemika|mika)\b", re.I)
    for path in list((_EXEC).glob("*.py")) + list((_EXEC.parents[0] / "services" / "dashboard" / "api").glob("*.py")) + \
            list((_EXEC.parents[0] / "services" / "dashboard" / "api" / "routers").glob("*.py")) + [_EXEC.parents[0] / "config" / "students.py"]:
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "Rob / Robert" in line:
                continue
            assert not pattern.search(line), f"{path.name}:{n} names a person: {line.strip()[:80]}"


# ── stale drafts ──────────────────────────────────────────────────────────────────────────────

def make_draft(db, created_at, status="draft"):
    M = db.models
    student = M.Student(username=f"s{created_at.timestamp()}", full_name="Student One", is_active=True)
    mail = M.Email(email_id=str(created_at.timestamp()), subject="s", from_address="hr@acme.com", received_date=created_at)
    db.add_all([student, mail])
    db.flush()
    event = M.InterviewEvent(email_id=mail.id, student_id=student.id, sub_type="Interview Request", company_name="Acme", confidence=0.9)
    db.add(event)
    db.flush()
    draft = M.NotificationDraft(interview_event_id=event.id, email_subject="s", email_body="b", recipient_email="x@example.com",
                                email_status=status, created_at=created_at)
    db.add(draft)
    db.commit()
    return draft


class Capture:
    def __init__(self):
        self.calls = []

    def __call__(self, **kw):
        self.calls.append(kw)
        return {"status": "sent"}


def alerts_for(db, cap):
    from escalation_engine import RoleAlerts
    return RoleAlerts(db=db, send_fn=cap)


def assign_escalation(db, email="holder@example.com"):
    db.add(db.models.RoleAssignment(role="escalation_target", email=email, active=True))
    db.commit()


def test_the_first_run_records_a_backlog_without_emailing_anyone(db):
    import stale_draft_alerts as sda
    assign_escalation(db)
    make_draft(db, utc(2026, 10, 5, 9))
    make_draft(db, utc(2026, 10, 5, 9, 5))
    cap = Capture()
    out = sda.run(db, utc(2026, 10, 6, 15), alerts_for(db, cap), CHI, env={})
    assert out["status"] == "baseline" and out["recorded"] == 2 and cap.calls == []
    assert sda.run(db, utc(2026, 10, 6, 15), alerts_for(db, cap), CHI, env={})["status"] == "nothing stale"      # the backlog is never reported


def test_a_new_draft_older_than_two_business_hours_goes_to_the_escalation_role_once(db):
    import stale_draft_alerts as sda
    assign_escalation(db)
    sda.run(db, utc(2026, 10, 6, 9), alerts_for(db, Capture()), CHI, env={})                       # baseline (empty)
    make_draft(db, utc(2026, 10, 6, 10))
    cap = Capture()
    assert sda.run(db, utc(2026, 10, 6, 11, 30), alerts_for(db, cap), CHI, env={})["status"] == "nothing stale"      # 1.5 h
    out = sda.run(db, utc(2026, 10, 6, 12, 5), alerts_for(db, cap), CHI, env={})                                       # 2.08 h
    assert out == {"status": "sent", "alerted": 1}
    assert len(cap.calls) == 1 and cap.calls[0]["recipient_email"] == "holder@example.com" and "Student One" in cap.calls[0]["body"]
    assert sda.run(db, utc(2026, 10, 6, 13), alerts_for(db, cap), CHI, env={})["status"] == "nothing stale"           # once only
    assert len(cap.calls) == 1


def test_the_approver_is_never_the_recipient(db):
    import stale_draft_alerts as sda
    db.add(db.models.RoleAssignment(role="approver", email="approver@example.com", active=True))
    assign_escalation(db, "escalation@example.com")
    sda.run(db, utc(2026, 10, 6, 9), alerts_for(db, Capture()), CHI, env={})
    make_draft(db, utc(2026, 10, 6, 9, 30))
    cap = Capture()
    sda.run(db, utc(2026, 10, 6, 12), alerts_for(db, cap), CHI, env={})
    assert [c["recipient_email"] for c in cap.calls] == ["escalation@example.com"]


def test_nothing_is_sent_or_marked_while_nobody_holds_the_role(db):
    import stale_draft_alerts as sda
    sda.run(db, utc(2026, 10, 6, 9), alerts_for(db, Capture()), CHI, env={})
    make_draft(db, utc(2026, 10, 6, 9, 30))
    cap = Capture()
    assert sda.run(db, utc(2026, 10, 6, 12), alerts_for(db, cap), CHI, env={})["status"] == "no escalation role assigned"
    assert cap.calls == []
    assign_escalation(db)
    assert sda.run(db, utc(2026, 10, 6, 12, 15), alerts_for(db, cap), CHI, env={})["alerted"] == 1      # as soon as someone is assigned


def test_nothing_is_sent_outside_business_hours_and_approved_drafts_are_ignored(db):
    import stale_draft_alerts as sda
    assign_escalation(db)
    sda.run(db, utc(2026, 10, 6, 9), alerts_for(db, Capture()), CHI, env={})
    make_draft(db, utc(2026, 10, 6, 9, 30))
    make_draft(db, utc(2026, 10, 6, 9, 31), status="approved")
    cap = Capture()
    assert sda.run(db, utc(2026, 10, 6, 21), alerts_for(db, cap), CHI, env={})["status"] == "outside business hours"      # 4 PM... 21:00 UTC = 16:00? no: after close
    # a weekday morning: only the unapproved draft is listed
    out = sda.run(db, utc(2026, 10, 7, 10), alerts_for(db, cap), CHI, env={})
    assert out["alerted"] == 1 and len(cap.calls) == 1


def test_the_threshold_is_configurable(db):
    import stale_draft_alerts as sda
    assert sda.stale_minutes({}) == 120 and sda.stale_minutes({"STALE_DRAFT_BUSINESS_MINUTES": "30"}) == 30
    assert sda.stale_minutes({"STALE_DRAFT_BUSINESS_MINUTES": "x"}) == 120

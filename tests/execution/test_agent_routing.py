"""A new card goes to the student's agent first; the approver is told straight away when a person must sort the card out first,
and is the backup when the agent has not decided in time."""
import sys
from datetime import datetime
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "execution"))

import agent_routing as ar  # noqa: E402
import review_alerts as ra  # noqa: E402
import stale_draft_alerts as sd  # noqa: E402
import student_roster as sr  # noqa: E402


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
    s.student = models.Student(username="sehrish", full_name="Sehrish Khan", personal_email="sehrish@gmail.com", is_active=True)
    s.add(s.student)
    s.add(models.RoleAssignment(role="approver", email="approver@example.com", active=True))
    s.add(models.RoleAssignment(role="escalation_target", email="backup@example.com", active=True))
    s.commit()
    return s


def _roster(agent="Karthik", email="sehrish@gmail.com"):
    rows = [sr.RosterRow(name=f"Filler {i}", status="Active", agent="X", emails=[f"f{i}@x.com"]) for i in range(6)]
    rows.append(sr.RosterRow(name="Sehrish Khan", status="Active", agent=agent, emails=[email]))
    return rows


def _card(db, student=None, confidence=0.9, company="Acme", n=[0]):
    M = db.models
    n[0] += 1
    mail = M.Email(email_id=f"m{n[0]}", subject="x", from_address="a@b.com", received_date=datetime.utcnow())
    db.add(mail); db.flush()
    ev = M.InterviewEvent(email_id=mail.id, student_id=(student or db.student).id if (student or db.student) else None, sub_type="Phone Screen",
                          company_name=company, interview_date="2026-10-21", interview_time="10:00", interview_timezone="CST", confidence=confidence)
    db.add(ev); db.flush()
    d = M.NotificationDraft(interview_event_id=ev.id, recipient_email="s@x.com", email_subject="s", email_body="b", email_status="draft")
    db.add(d); db.commit()
    return ev, d


def _agent(db, name="Karthik", email="karthik@example.com"):
    ar.set_agent_email(db, name, email)


FOUND = lambda student: "found"  # noqa: E731


def _route(db, d, roster=None, ghl=FOUND):
    return ar.route_cards(db, [d], roster=roster if roster is not None else _roster(), ghl_status=ghl)[d.id]


# ── routing ──────────────────────────────────────────────────────────────────

def test_no_agent_email_set_up_means_everything_goes_to_the_approver_without_reading_the_roster(db, monkeypatch):
    monkeypatch.setattr(sr, "cached_roster", lambda *a, **k: pytest.fail("roster must not be read"))
    _, d = _card(db)
    assert ar.route_cards(db, [d])[d.id] == ar.Route("approver", "")


def test_a_clean_card_goes_to_the_agent(db):
    _agent(db)
    _, d = _card(db)
    assert _route(db, d) == ar.Route("agent", "", "Karthik", "karthik@example.com")


def test_agent_name_matches_loosely(db):
    _agent(db, "  karthik. ")
    _, d = _card(db)
    assert _route(db, d).to == "agent"


@pytest.mark.parametrize("ghl", ["not_found", "check"])
def test_not_in_ghl_with_an_agent_goes_to_the_agent_for_verification(db, ghl):
    _agent(db)
    _, d = _card(db)
    assert _route(db, d, ghl=lambda s: ghl) == ar.Route("agent", ar.VERIFY, "Karthik", "karthik@example.com")


def test_ghl_that_cannot_be_checked_goes_to_the_approver(db):
    _agent(db)
    _, d = _card(db)
    assert _route(db, d, ghl=lambda s: "unknown") == ar.Route("approver", "ghl_unknown")


def test_ghl_lookup_error_goes_to_the_approver(db):
    _agent(db)
    _, d = _card(db)

    def boom(student):
        raise RuntimeError("down")
    assert _route(db, d, ghl=boom).reason == "ghl_unknown"


def test_not_in_ghl_and_no_agent_goes_to_the_approver(db):
    _agent(db)
    _, d = _card(db)
    assert _route(db, d, roster=_roster(agent=""), ghl=lambda s: "not_found") == ar.Route("approver", "not_in_ghl")


def test_not_in_ghl_and_agent_without_email_goes_to_the_approver(db):
    _agent(db, "Someone Else", "else@example.com")
    _, d = _card(db)
    r = _route(db, d, ghl=lambda s: "not_found")
    assert r.to == "approver" and r.reason == "agent_no_email"


def test_not_in_ghl_and_doubtful_classification_goes_to_the_approver(db):
    _agent(db)
    _, d = _card(db, confidence=0.5)
    assert _route(db, d, ghl=lambda s: "not_found").reason == "low_confidence"


def test_student_not_on_roster_or_by_name_only_goes_to_the_approver(db):
    _agent(db)
    _, d = _card(db)
    assert _route(db, d, roster=_roster(email="other@x.com")).reason == "not_on_roster"      # same name, different email = name only
    db.student.full_name, db.student.personal_email = "Somebody Else", "else@x.com"; db.commit()
    assert _route(db, d).reason == "not_on_roster"


def test_unreadable_roster_goes_to_the_approver(db, monkeypatch):
    _agent(db)
    _, d = _card(db)
    monkeypatch.setattr(sr, "cached_roster", lambda *a, **k: None)
    assert ar.route_cards(db, [d], ghl_status=FOUND)[d.id].reason == "roster_unknown"


def test_unverified_student_goes_to_the_approver(db):
    _agent(db)
    db.add(db.models.StudentVerification(student_id=db.student.id, status="unverified", basis="no_ghl_contact")); db.commit()
    _, d = _card(db)
    assert _route(db, d).reason == "unverified"


def test_card_with_no_student_goes_to_the_approver(db):
    _agent(db)
    M = db.models
    mail = M.Email(email_id="mx", subject="x", from_address="a@b.com", received_date=datetime.utcnow()); db.add(mail); db.flush()
    ev = M.InterviewEvent(email_id=mail.id, student_id=None, sub_type="Phone Screen", company_name="Acme", confidence=0.9); db.add(ev); db.flush()
    d = M.NotificationDraft(interview_event_id=ev.id, recipient_email="s@x.com", email_subject="s", email_body="b", email_status="draft"); db.add(d); db.commit()
    assert _route(db, d).reason == "no_student"


def test_doubtful_classification_goes_to_the_approver(db):
    _agent(db)
    _, d = _card(db, confidence=0.69)
    assert _route(db, d).reason == "low_confidence"
    _, ok = _card(db, confidence=0.70)
    assert _route(db, ok).to == "agent"


def test_blank_agent_on_the_sheet_goes_to_the_approver(db):
    _agent(db)
    _, d = _card(db)
    assert _route(db, d, roster=_roster(agent="")).reason == "no_agent"


def test_agent_without_an_email_goes_to_the_approver(db):
    _agent(db, "Someone Else", "else@example.com")             # agents exist, but not Karthik
    _, d = _card(db)
    r = _route(db, d)
    assert r.to == "approver" and r.reason == "agent_no_email" and r.agent == "Karthik"


def test_setting_an_agent_email_replaces_and_clears(db):
    _agent(db, "Karthik", "a@example.com")
    _agent(db, "Karthik", "b@example.com")
    assert ar.agent_emails(db) == {"karthik": "b@example.com"}
    ar.set_agent_email(db, "Karthik", "")
    assert ar.agent_emails(db) == {}


# ── the alerts ───────────────────────────────────────────────────────────────

class Cap:
    def __init__(self):
        self.agent, self.approver, self.stale_approver, self.stale_escalation = [], [], [], []

    def agent_review(self, to, subject, body):
        self.agent.append((to, subject, body)); return True

    def review_needed(self, subject, body):
        self.approver.append((subject, body)); return True

    def stale_for_approver(self, subject, body):
        self.stale_approver.append(body); return True

    def stale_drafts(self, subject, body):
        self.stale_escalation.append(body); return True


@pytest.fixture
def routed(db, monkeypatch):
    """Roster and GHL are faked; Karthik has an email."""
    _agent(db)
    monkeypatch.setattr(sr, "cached_roster", lambda *a, **k: _roster())
    import student_flags
    monkeypatch.setattr(student_flags, "ghl_status", FOUND)
    ra.run(db, alerts=Cap())                                   # baseline
    return db


def test_new_card_emails_the_agent_not_the_approver(routed):
    db = routed
    _, d = _card(db)
    cap = Cap()
    out = ra.run(db, alerts=cap, env={"DASHBOARD_BASE_URL": "https://example.test"})
    assert out["agent_alerted"] == 1 and cap.approver == []
    to, subject, body = cap.agent[0]
    assert to == "karthik@example.com" and "Sehrish Khan" in body and "https://example.test/approve/" in body
    link = db.query(db.models.ApprovalLink).one()
    assert (link.role, link.recipient_email) == ("agent", "karthik@example.com")       # the code goes to the AGENT's mailbox
    assert ar.agent_of_alert(db, d.id) == "Karthik"
    assert ra.run(db, alerts=cap)["status"] == "nothing new"                            # once


def test_card_needing_a_person_emails_the_approver_with_the_reason(routed, monkeypatch):
    db = routed
    _card(db, confidence=0.5)
    cap = Cap()
    out = ra.run(db, alerts=cap)
    assert out["alerted"] == 1 and cap.agent == []
    assert "Needs a person first: the email classification is uncertain" in cap.approver[0][1]
    assert ar.agent_of_alert(db, 1) == ""


def test_mixed_cards_split_between_agent_and_approver(routed):
    db = routed
    _card(db, company="Clean Co")
    _card(db, company="Doubtful Co", confidence=0.5)
    cap = Cap()
    out = ra.run(db, alerts=cap)
    assert out["alerted"] == 1 and out["agent_alerted"] == 1
    assert "Clean Co" in cap.agent[0][2] and "Doubtful Co" not in cap.agent[0][2]
    assert "Doubtful Co" in cap.approver[0][1] and "Clean Co" not in cap.approver[0][1]


def test_failed_agent_email_is_retried_next_run(routed):
    db = routed
    _card(db)

    class Fail(Cap):
        def agent_review(self, *a):
            return False
    assert ra.run(db, alerts=Fail())["status"] == "send failed"
    cap = Cap()
    assert ra.run(db, alerts=cap)["agent_alerted"] == 1


def test_agent_card_not_decided_in_time_goes_to_the_approver_not_the_escalation_role(routed):
    db = routed
    sd.run(db, datetime(2026, 10, 6, 15, 0), alerts=Cap())                                       # stale baseline
    _, d = _card(db)
    ra.run(db, alerts=Cap())
    d.created_at = datetime(2026, 10, 6, 14, 0); db.commit()
    cap = Cap()
    out = sd.run(db, datetime(2026, 10, 6, 18, 0), alerts=cap, env={"DASHBOARD_BASE_URL": "https://example.test"})
    assert out["status"] == "sent" and len(cap.stale_approver) == 1 and cap.stale_escalation == []
    assert "agent has not acted" in cap.stale_approver[0]
    assert {r.role for r in db.query(db.models.ApprovalLink).all()} >= {"approver"}


def test_approver_card_not_decided_in_time_still_goes_to_the_escalation_role(routed, monkeypatch):
    db = routed
    sd.run(db, datetime(2026, 10, 6, 15, 0), alerts=Cap())
    _, d = _card(db, confidence=0.5)
    ra.run(db, alerts=Cap())
    d.created_at = datetime(2026, 10, 6, 14, 0); db.commit()
    cap = Cap()
    sd.run(db, datetime(2026, 10, 6, 18, 0), alerts=cap)
    assert len(cap.stale_escalation) == 1 and cap.stale_approver == []


def test_agent_who_is_also_the_approver_is_backed_up_by_the_escalation_role(routed):
    db = routed
    db.add(db.models.RoleAssignment(role="approver", email="karthik@example.com", active=True))
    db.commit()
    sd.run(db, datetime(2026, 10, 6, 15, 0), alerts=Cap())
    _, d = _card(db)
    ra.run(db, alerts=Cap())
    d.created_at = datetime(2026, 10, 6, 14, 0); db.commit()
    cap = Cap()
    sd.run(db, datetime(2026, 10, 6, 18, 0), alerts=cap)
    assert len(cap.stale_escalation) == 1 and cap.stale_approver == []


def test_not_yet_two_hours_nobody_is_told_again(routed):
    db = routed
    sd.run(db, datetime(2026, 10, 6, 15, 0), alerts=Cap())
    _, d = _card(db)
    ra.run(db, alerts=Cap())
    d.created_at = datetime(2026, 10, 6, 17, 0); db.commit()                                     # 12:00 CDT, one hour before
    cap = Cap()
    assert sd.run(db, datetime(2026, 10, 6, 18, 0), alerts=cap)["status"] == "nothing stale"


# ── verification: not in GHL, the agent confirms the candidate ───────────────

def test_verification_card_emails_the_agent_with_a_verify_link(routed, monkeypatch):
    db = routed
    import student_flags
    monkeypatch.setattr(student_flags, "ghl_status", lambda s: "not_found")
    _, d = _card(db)
    cap = Cap()
    out = ra.run(db, alerts=cap, env={"DASHBOARD_BASE_URL": "https://example.test"})
    assert out["agent_alerted"] == 1 and cap.approver == []
    to, _, body = cap.agent[0]
    assert to == "karthik@example.com" and "NOT IN GHL" in body and "actively applying for" in body
    link = db.query(db.models.ApprovalLink).one()
    assert (link.role, link.recipient_email) == ("agent_verify", "karthik@example.com")
    assert ar.agent_of_alert(db, d.id) == "Karthik"


def test_a_clean_card_and_a_verification_card_in_one_agent_email_get_different_links(routed, monkeypatch):
    db = routed
    import student_flags
    seen = iter(["found", "not_found"])
    monkeypatch.setattr(student_flags, "ghl_status", lambda s: next(seen))
    _card(db, company="Clean Co")
    _card(db, company="Missing Co")
    cap = Cap()
    ra.run(db, alerts=cap)
    assert len(cap.agent) == 1
    assert sorted(l.role for l in db.query(db.models.ApprovalLink).all()) == ["agent", "agent_verify"]

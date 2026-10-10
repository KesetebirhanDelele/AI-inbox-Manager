"""Filing the Classification-review items that a deterministic rule already classifies: job links go to Job Alerts, interviews stay for a person."""
import sys
from datetime import datetime
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "execution"))

import file_review_items as fri  # noqa: E402


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


def _pending(db, M, n, subject, sender="student@gmail.com", status="pending"):
    email = M.Email(email_id=str(n), message_id=f"<m{n}@x>", subject=subject, from_address=sender,
                    received_date=datetime(2026, 10, 1), current_folder="INBOX")
    db.add(email); db.flush()
    cls = M.Classification(email_id=email.id, category="Other", confidence=0.65)
    db.add(cls); db.flush()
    db.add(M.Approval(email_id=email.id, classification_id=cls.id, status=status))
    db.commit()
    return email


def test_plan_picks_only_rule_certain_non_interview_items(db_models):
    db, M = db_models
    _pending(db, M, 1, "https://www.linkedin.com/jobs/view/4465614631/")
    _pending(db, M, 2, "https://www.indeed.com/viewjob?jk=abc")
    _pending(db, M, 3, "Interview request: Data Analyst", sender="recruiter@acme.com")      # a person decides this
    _pending(db, M, 4, "https://www.linkedin.com/jobs/view/9/", status="approved")           # already closed
    _pending(db, M, 5, "1 event happening tomorrow", sender="noreply@skool.com")             # not job related: Spam Review
    items = fri.plan(db)
    assert sorted(i["email_id"] for i in items) == [1, 2, 5]
    assert {i["email_id"]: i["target"] for i in items} == {1: "Job Alerts", 2: "Job Alerts", 5: "Spam Review"}


def test_apply_closes_the_approval_and_records_the_folder(db_models, monkeypatch):
    db, M = db_models
    e1 = _pending(db, M, 1, "https://www.linkedin.com/jobs/view/1/")
    e2 = _pending(db, M, 2, "https://www.linkedin.com/jobs/view/2/")
    items = fri.plan(db)

    import label_verify_students as lvs

    def fake_apply(imap, group, move=True, label=None):
        assert label == "Job Alerts" and move is True
        return {"labelled": [g["email_id"] for g in group], "moved": [e1.id], "skipped": []}   # Gmail only found the first one

    monkeypatch.setattr(lvs, "apply_items", fake_apply)
    out = fri.apply_plan(db, imap=object(), items=items)
    assert out == {"filed": 1, "skipped": 1}
    assert db.get(M.Email, e1.id).current_folder == "Job Alerts"
    ap1 = db.query(M.Approval).filter_by(email_id=e1.id).one()
    assert (ap1.status, ap1.human_action, ap1.target_folder, ap1.reviewed_by) == ("approved", "move_to_folder", "Job Alerts", "rule-filing")
    assert db.query(M.Approval).filter_by(email_id=e2.id).one().status == "pending"            # not found in Gmail: left for a person
    assert db.get(M.Email, e2.id).current_folder == "INBOX"

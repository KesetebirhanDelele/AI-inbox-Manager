"""Re-reading the pending Classification-review items: what gets filed, what gets closed, what stays for a person."""
import sys
from datetime import datetime
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "execution"))

import reclassify_review_items as rri  # noqa: E402


@pytest.mark.parametrize("category, confidence, expected", [
    ("Job Alert", 0.85, "file"),
    ("Job Alert", 0.60, "keep"),                  # not sure enough to file
    ("Application Notification", 0.90, "file"),
    ("Other", 0.55, "close"),
    ("Other", 0.40, "keep"),
    ("Other", 0.0, "close"),                      # the model's normal answer for plain junk
    ("Interview Request", 0.99, "keep"),          # a person always decides interviews
    ("Offer", 0.99, "keep"),
    ("Rejection", 0.95, "keep"),
    ("More Information Request", 0.95, "keep"),
])
def test_decide(category, confidence, expected):
    assert rri.decide(category, confidence) == expected


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


def _pending(db, M, n, subject, body="", sender="x@y.com"):
    e = M.Email(email_id=str(n), message_id=f"<m{n}@x>", subject=subject, from_address=sender, full_body=body,
                received_date=datetime(2026, 10, 1), current_folder="Needs Review")
    db.add(e); db.flush()
    c = M.Classification(email_id=e.id, category="Other", confidence=0.6)
    db.add(c); db.flush()
    db.add(M.Approval(email_id=e.id, classification_id=c.id, status="pending"))
    db.commit()
    return e


def test_analyse_reads_the_cleaned_text_and_maps_to_folders(db_models):
    db, M = db_models
    _pending(db, M, 1, "Weekly jobs", body="<html><body><p>New jobs for you</p></body></html>")
    _pending(db, M, 2, "Call me", body="Can you interview Friday?")
    _pending(db, M, 3, "Promo", body="Big sale")
    seen = {}

    def fake(email_data):
        seen[email_data["subject"]] = email_data["body_content"]
        return {"Weekly jobs": {"category": "Job Alert", "confidence": 0.9},
                "Call me": {"category": "Interview Request", "confidence": 0.95},
                "Promo": {"category": "Other", "confidence": 0.6}}[email_data["subject"]]

    rows = {r["subject"]: r for r in rri.analyse(db, fake)}
    assert "<" not in seen["Weekly jobs"]                                     # the classifier is given text, not markup
    assert (rows["Weekly jobs"]["action"], rows["Weekly jobs"]["target"]) == ("file", "Job Alerts")
    assert rows["Call me"]["action"] == "keep" and rows["Call me"]["target"] is None
    assert (rows["Promo"]["action"], rows["Promo"]["target"]) == ("close", "Spam Review")


def test_one_failing_classification_does_not_stop_the_rest(db_models):
    db, M = db_models
    _pending(db, M, 1, "boom")
    _pending(db, M, 2, "fine")

    def fake(email_data):
        if email_data["subject"] == "boom":
            raise RuntimeError("api down")
        return {"category": "Other", "confidence": 0.8}

    rows = {r["subject"]: r["action"] for r in rri.analyse(db, fake)}
    assert rows == {"boom": "keep", "fine": "close"}


def test_new_answers_are_recorded_as_new_rows(db_models):
    db, M = db_models
    e = _pending(db, M, 1, "Weekly jobs")
    rri.record_new_answers(db, [{"email_id": e.id, "category": "Job Alert", "confidence": 0.9, "raw": {"category": "Job Alert"}}])
    cats = [c.category for c in db.query(M.Classification).filter_by(email_id=e.id).order_by(M.Classification.id)]
    assert cats == ["Other", "Job Alert"]                                      # the old answer is kept


@pytest.mark.parametrize("sender, subject, expected", [
    ("news@hiringourheroes.org", "Week Ahead", "close"),
    ("kenyasbogans@gmail.com", "Audio", "keep"),                          # a person, not a mailer
    ("cai@colaberry.com", "Logging Interviews", "keep"),                  # Colaberry staff
    ("jgosa@aum.edu", "Re: [EXTERNAL] Kenya Means Transcripts", "keep"),  # a reply
    ("<charliezinger@aol.com>", "Join Us Thursday", "keep"),
    ("ashwin@mobiusengine.ai", "Fwd: New roles", "keep"),
])
def test_mail_from_a_person_is_left_for_a_person(sender, subject, expected):
    assert rri.decide("Other", 0.85, sender, subject) == expected

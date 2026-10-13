"""Tests for health_check: pure logic plus one database-backed run. No network, no email."""
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

_EXECUTION_DIR = Path(__file__).resolve().parents[2] / "execution"
if str(_EXECUTION_DIR) not in sys.path:
    sys.path.insert(0, str(_EXECUTION_DIR))

import health_check as hc  # noqa: E402

NOW = datetime(2026, 10, 2, 7, 30)


def healthy(**over):
    m = {"permanent_deletes": 0, "approvals_missing": 0, "last_run_age_hours": 1.0,
         "runs_partial_failure": 0, "drafts_failed": 0, "drafts_stuck": 0,
         "events": 10, "events_fallback": 0, "events_no_student": 1}
    m.update(over)
    return m


def checks(m):
    return {(f.severity, f.check) for f in hc.evaluate(m)}


def test_healthy_metrics_give_no_findings():
    assert hc.evaluate(healthy()) == []


@pytest.mark.parametrize("override, expected", [
    ({"permanent_deletes": 3}, ("CRITICAL", "permanent deletion")),
    ({"approvals_missing": 1}, ("CRITICAL", "review-queue gap")),
    ({"last_run_age_hours": 3.5}, ("CRITICAL", "run health")),
    ({"last_run_age_hours": None}, ("CRITICAL", "run health")),
    ({"runs_partial_failure": 1}, ("CRITICAL", "run health")),
    ({"drafts_failed": 1}, ("CRITICAL", "notification sends")),
    ({"drafts_stuck": 2}, ("CRITICAL", "notification sends")),
    ({"attempts_failed": 1}, ("CRITICAL", "escalation attempts")),
    ({"events": 10, "events_fallback": 4}, ("WARNING", "sub-classifier fallback")),
    ({"events": 10, "events_no_student": 6}, ("WARNING", "student matching")),
])
def test_each_failure_is_reported(override, expected):
    assert expected in checks(healthy(**override))


def test_rates_ignored_when_too_few_events():
    assert checks(healthy(events=2, events_fallback=2, events_no_student=2)) == set()


def test_run_age_at_the_limit_is_still_healthy():
    assert hc.evaluate(healthy(last_run_age_hours=hc.MAX_RUN_AGE_HOURS)) == []


LOG = (
    "2026-10-01 12:00:43,742 - __main__ - INFO - Spam review: permanently deleted 6 confirmed spam email(s)\n"
    "2026-10-01 13:55:00,000 - __main__ - INFO - Spam review: permanently deleted 4 confirmed spam email(s)\n"
    "2026-10-01 14:01:31,376 - __main__ - INFO - Spam review: moved 15 unclear email(s) to Quarantine\n"
    "2026-10-02 02:00:10,000 - __main__ - INFO - Spam review: permanently deleted 2 confirmed spam email(s)\n"
    "garbage line\n"
)


def test_count_permanent_deletes_respects_the_cutoff():
    assert hc.count_permanent_deletes(LOG, datetime(2026, 10, 1, 0, 0)) == 12
    assert hc.count_permanent_deletes(LOG, hc.NO_DELETE_SINCE) == 2     # only the post-fix line
    assert hc.count_permanent_deletes("", hc.NO_DELETE_SINCE) == 0


def test_report_leads_with_the_verdict():
    bad = hc.format_report(hc.evaluate(healthy(permanent_deletes=2)), healthy(permanent_deletes=2), NOW)
    assert bad.startswith("UNHEALTHY") and "permanent deletion" in bad
    good = hc.format_report([], healthy(), NOW)
    assert good.startswith("HEALTHY")


def test_collect_metrics_against_a_real_database(monkeypatch):
    api_dir = _EXECUTION_DIR.parents[0] / "services" / "dashboard" / "api"
    monkeypatch.syspath_prepend(str(api_dir))
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import models

    engine = create_engine("sqlite://")
    models.Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    recent = NOW - timedelta(hours=1)

    def add_email(n):
        e = models.Email(email_id=str(n), subject="s", from_address="a@b.com", received_date=recent)
        db.add(e); db.flush()
        return e

    # one low-confidence classification WITH an approval, one WITHOUT, one junk "Other" at 0.0
    queued, unqueued, junk = add_email(1), add_email(2), add_email(3)
    for e, cat, conf in ((queued, "Other", 0.6), (unqueued, "Job Alert", 0.5), (junk, "Other", 0.0)):
        c = models.Classification(email_id=e.id, category=cat, confidence=conf, classification_timestamp=recent)
        db.add(c); db.flush()
        if e is queued:
            db.add(models.Approval(email_id=e.id, classification_id=c.id, status="pending"))
    db.add(models.ProcessRun(run_timestamp=NOW - timedelta(minutes=90), status="success"))
    for i, (src, student) in enumerate((("subclassifier", 1), ("category_fallback", None), ("subclassifier", None))):
        db.add(models.InterviewEvent(email_id=queued.id, sub_type="Interview Request", student_id=student,
                                     confidence=0.9, raw_extraction={"sub_type_source": src}, created_at=recent))
    db.commit()

    m = hc.collect_metrics(db, "", NOW)
    assert m["approvals_missing"] == 1            # only the un-queued Job Alert
    assert m["events"] == 3 and m["events_fallback"] == 1 and m["events_no_student"] == 2
    assert m["runs_partial_failure"] == 0
    assert 1.4 < m["last_run_age_hours"] < 1.6


def test_classifications_before_the_queue_existed_are_not_counted(monkeypatch):
    api_dir = _EXECUTION_DIR.parents[0] / "services" / "dashboard" / "api"
    monkeypatch.syspath_prepend(str(api_dir))
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import models

    engine = create_engine("sqlite://")
    models.Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    before = hc.QUEUE_ACTIVE_SINCE - timedelta(hours=2)
    e = models.Email(email_id="1", subject="s", from_address="a@b.com", received_date=before)
    db.add(e); db.flush()
    db.add(models.Classification(email_id=e.id, category="Job Alert", confidence=0.5,
                                 classification_timestamp=before))
    db.commit()
    now = hc.QUEUE_ACTIVE_SINCE + timedelta(hours=1)
    assert hc.collect_metrics(db, "", now)["approvals_missing"] == 0


def test_weekly_all_clear_is_sent_on_monday_even_when_healthy():
    monday, tuesday = datetime(2026, 10, 5, 7, 30), datetime(2026, 10, 6, 7, 30)
    assert monday.weekday() == hc.WEEKLY_ALL_CLEAR_WEEKDAY
    assert hc.should_email([], monday) is True
    assert hc.should_email([], tuesday) is False          # healthy and not Monday: stay quiet


def test_problems_and_explicit_requests_always_email():
    tuesday = datetime(2026, 10, 6, 7, 30)
    assert hc.should_email([hc.Finding("CRITICAL", "x", "y")], tuesday) is True
    assert hc.should_email([], tuesday, always=True) is True


# --- shadow mode and retired-category fallbacks (2026-10-10) -------------------------------------------------------------------------

def test_an_approved_draft_that_is_not_delivered_is_critical_only_when_delivery_is_live():
    assert ("CRITICAL", "notification sends") in checks(healthy(drafts_stuck=1))
    assert ("CRITICAL", "notification sends") in checks(healthy(drafts_stuck=1, shadow=False))
    assert checks(healthy(drafts_stuck=1, shadow=True)) == set()          # shadow: nothing is delivered on purpose


def test_failed_attempts_stay_critical_even_in_shadow_mode():
    assert ("CRITICAL", "escalation attempts") in checks(healthy(attempts_failed=3, shadow=True))


def test_the_report_explains_shadow_mode_and_the_retired_category_events():
    m = healthy(drafts_stuck=1, shadow=True, events_retired_fallback=3)
    text = hc.format_report(hc.evaluate(m), m, NOW)
    assert "SHADOW MODE" in text and "not counted as a problem" in text and "retired interview categories" in text
    assert text.startswith("HEALTHY")


def test_shadow_mode_detection_follows_the_switches(monkeypatch):
    for k in ("GHL_WRITE_MODE", "GHL_WRITE_SHADOW_LOG_ONLY", "GHL_WRITE_NOTIFY_FIELDS"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.delenv("NOTIFY_ESCALATION_ENABLED", raising=False)
    assert hc._shadow_mode() is False                                      # flow off: not "shadow", just off
    monkeypatch.setenv("NOTIFY_ESCALATION_ENABLED", "true")
    assert hc._shadow_mode() is True
    monkeypatch.setenv("GHL_WRITE_MODE", "live")
    monkeypatch.setenv("GHL_WRITE_SHADOW_LOG_ONLY", "false")
    monkeypatch.setenv("GHL_WRITE_NOTIFY_FIELDS", "true")
    assert hc._shadow_mode() is False


def test_retired_category_events_are_not_counted_as_the_subclassifier_failing(monkeypatch):
    api_dir = _EXECUTION_DIR.parents[0] / "services" / "dashboard" / "api"
    monkeypatch.syspath_prepend(str(api_dir))
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import models

    engine = create_engine("sqlite://")
    models.Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    recent = NOW - timedelta(hours=1)
    e = models.Email(email_id="1", subject="s", from_address="a@b.com", received_date=recent)
    db.add(e); db.flush()
    for sub_type, src in (("confirmed", "category_fallback"), ("confirmed", "category_fallback"), ("interview_request", "category_fallback"),
                          ("Phone Screen", "subclassifier")):
        db.add(models.InterviewEvent(email_id=e.id, sub_type=sub_type, confidence=0.9, raw_extraction={"sub_type_source": src}, created_at=recent))
    db.commit()
    m = hc.collect_metrics(db, "", NOW)
    assert m["events"] == 4 and m["events_fallback"] == 1 and m["events_retired_fallback"] == 2


def test_failed_attempts_that_a_later_step_recovered_are_not_counted(monkeypatch):
    api_dir = _EXECUTION_DIR.parents[0] / "services" / "dashboard" / "api"
    monkeypatch.syspath_prepend(str(api_dir))
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import models

    engine = create_engine("sqlite://")
    models.Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    t = NOW - timedelta(hours=2)

    def attempt(seq, step, status):
        db.add(models.NotificationAttempt(sequence_id=seq, channel="sms", step=step, planned_for=t, scheduled_for=t,
                                          status=status, created_at=t))
        db.flush()

    # plan 1: failed, then a later step worked (cause fixed) -> not counted
    attempt(1, "start", "failed"); attempt(1, "d1_4h", "dry_run")
    # plan 2: failed and nothing after it worked -> counted
    attempt(2, "start", "failed"); attempt(2, "d1_4h", "pending")
    # plan 3: a step that worked BEFORE the failure does not excuse it -> counted
    attempt(3, "start", "sent"); attempt(3, "d1_4h", "failed")
    db.commit()
    assert hc.collect_metrics(db, "", NOW)["attempts_failed"] == 2

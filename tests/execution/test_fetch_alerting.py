"""
Pipeline-side tests for the 2026-09-29 22:00 UTC incident (see
test_fetch_resilience.py): a run whose IMAP fetch left emails behind must not look
like a normal success.

Covers process_inbox_auto: the partial_failure status decision, the "every fetch
failed" case that used to be reported as an empty inbox, and the failure alert.
Fakes only -- no IMAP, no network, no database, no real email.
"""

import sys
from pathlib import Path

import pytest

_EXECUTION_DIR = Path(__file__).resolve().parents[2] / "execution"
if str(_EXECUTION_DIR) not in sys.path:
    sys.path.insert(0, str(_EXECUTION_DIR))

import alert  # noqa: E402
import process_inbox_auto as pia  # noqa: E402
import run_lock  # noqa: E402
from fetch_emails import FetchedEmails  # noqa: E402


# ── status decision ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("stats, problems", [
    ({}, False),
    ({"fetch_errors": 0, "fetch_abandoned": 0, "fetch_reconnects": 0}, False),
    # recovered by reconnecting -> not a problem
    ({"fetch_errors": 0, "fetch_abandoned": 0, "fetch_reconnects": 2}, False),
    # one corrupt email (recurs every run) -> below the threshold, no alert spam
    ({"fetch_errors": 1, "fetch_abandoned": 0}, False),
    ({"fetch_errors": pia._FETCH_ERROR_ALERT_THRESHOLD - 1, "fetch_abandoned": 0}, False),
    # many per-message failures
    ({"fetch_errors": pia._FETCH_ERROR_ALERT_THRESHOLD, "fetch_abandoned": 0}, True),
    # gave up after connection loss: always a problem, even for one email
    ({"fetch_errors": 1, "fetch_abandoned": 1}, True),
])
def test_fetch_had_problems(stats, problems):
    assert pia._fetch_had_problems(stats) is problems


def test_run_status_values():
    assert pia._run_status({}) == "success"
    assert pia._run_status({"fetch_abandoned": 3, "fetch_errors": 3}) == "partial_failure"


# ── all fetches failed must not read as "no unread emails" ────────────────────

def test_total_fetch_failure_is_reported_not_treated_as_empty_inbox(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)                       # run output dir lands here
    monkeypatch.setenv("EMAIL_SERVER", "imap.test")
    monkeypatch.setenv("EMAIL_ADDRESS", "a@test")
    monkeypatch.setenv("EMAIL_PASSWORD", "x")
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setattr(pia, "_run_spam_review_pass", lambda *a, **k: {})
    monkeypatch.setattr(
        pia, "fetch_emails",
        lambda **k: FetchedEmails(skipped=4, abandoned=4, reconnects=3),
    )
    monkeypatch.setattr(pia, "close_db_session", lambda: None)

    result = pia.process_unread_emails()

    assert result["total_emails"] == 0
    assert result["fetch_errors"] == 4
    assert result["fetch_abandoned"] == 4
    assert result["fetch_reconnects"] == 3
    assert pia._fetch_had_problems(result)


def test_genuinely_empty_inbox_has_no_fetch_problems(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("EMAIL_SERVER", "imap.test")
    monkeypatch.setenv("EMAIL_ADDRESS", "a@test")
    monkeypatch.setenv("EMAIL_PASSWORD", "x")
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setattr(pia, "_run_spam_review_pass", lambda *a, **k: {})
    monkeypatch.setattr(pia, "fetch_emails", lambda **k: FetchedEmails())
    monkeypatch.setattr(pia, "close_db_session", lambda: None)

    result = pia.process_unread_emails()

    assert result["total_emails"] == 0
    assert result["fetch_errors"] == 0 and result["fetch_abandoned"] == 0
    assert not pia._fetch_had_problems(result)


# ── ProcessRun rows for runs that go wrong before/without processing emails ──

def _arm_run(monkeypatch, tmp_path, fetch):
    """Fake everything external for process_unread_emails(); capture ProcessRun logs."""
    logged = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("EMAIL_SERVER", "imap.test")
    monkeypatch.setenv("EMAIL_ADDRESS", "a@test")
    monkeypatch.setenv("EMAIL_PASSWORD", "x")
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setattr(pia, "_run_spam_review_pass", lambda *a, **k: {})
    monkeypatch.setattr(pia, "fetch_emails", fetch)
    monkeypatch.setattr(pia, "close_db_session", lambda: None)
    monkeypatch.setattr(
        pia, "_log_process_run",
        lambda stats, summary_file=None, status="success": logged.append(status),
    )
    return logged


def test_crash_before_any_email_is_fetched_still_records_a_failed_run(monkeypatch, tmp_path):
    """e.g. Gmail auth failure: used to leave no dashboard trace at all."""
    from fetch_emails import EmailConnectionError

    def boom(**k):
        raise EmailConnectionError("Authentication failed")

    logged = _arm_run(monkeypatch, tmp_path, boom)
    with pytest.raises(EmailConnectionError):
        pia.process_unread_emails()
    assert logged == ["failed"]


def test_total_fetch_failure_records_a_partial_failure_run(monkeypatch, tmp_path):
    logged = _arm_run(
        monkeypatch, tmp_path,
        lambda **k: FetchedEmails(skipped=4, abandoned=4, reconnects=3),
    )
    result = pia.process_unread_emails()
    assert result["total_emails"] == 0
    assert logged == ["partial_failure"]


def test_clean_empty_run_still_writes_no_row(monkeypatch, tmp_path):
    """Unchanged behaviour: nothing to process and nothing went wrong -> no row."""
    logged = _arm_run(monkeypatch, tmp_path, lambda **k: FetchedEmails())
    pia.process_unread_emails()
    assert logged == []


def test_recovered_reconnect_with_no_emails_writes_no_row(monkeypatch, tmp_path):
    logged = _arm_run(monkeypatch, tmp_path, lambda **k: FetchedEmails(reconnects=1))
    pia.process_unread_emails()
    assert logged == []


# ── main(): alert on a partly failed fetch ───────────────────────────────────

def _run_main(monkeypatch, stats):
    """Run pia.main() with everything external faked; return the alerts sent."""
    sent = []
    monkeypatch.setattr(sys, "argv", ["process_inbox_auto.py"])
    monkeypatch.setattr(alert, "is_configured", lambda: True)
    monkeypatch.setattr(
        alert, "send_failure_alert",
        lambda subject, body, exc=None: sent.append((subject, body)) or True,
    )
    monkeypatch.setattr(run_lock, "acquire_lock", lambda **k: True)
    monkeypatch.setattr(run_lock, "release_lock", lambda: None)
    monkeypatch.setattr(pia, "process_unread_emails", lambda **k: stats)
    with pytest.raises(SystemExit) as exit_info:
        pia.main()
    assert exit_info.value.code == 0                  # still always exits 0
    return sent


def test_alert_sent_when_fetch_gave_up(monkeypatch):
    sent = _run_main(monkeypatch, {
        "interview_requests": 0, "total_emails": 2,
        "fetch_errors": 176, "fetch_abandoned": 174, "fetch_reconnects": 3,
    })
    assert len(sent) == 1
    subject, body = sent[0]
    assert "fetch incomplete" in subject.lower()
    assert "176" in body and "174" in body
    assert "partial_failure" in body


def test_no_alert_for_clean_run(monkeypatch):
    sent = _run_main(monkeypatch, {
        "interview_requests": 0, "total_emails": 50,
        "fetch_errors": 0, "fetch_abandoned": 0, "fetch_reconnects": 0,
    })
    assert sent == []


def test_no_alert_when_connection_recovered(monkeypatch):
    """Reconnected and fetched everything: warn in the log, don't page anyone."""
    sent = _run_main(monkeypatch, {
        "interview_requests": 0, "total_emails": 50,
        "fetch_errors": 0, "fetch_abandoned": 0, "fetch_reconnects": 1,
    })
    assert sent == []


def test_no_alert_for_a_single_bad_email(monkeypatch):
    """One corrupt email recurs every run -- must not alert every 2 hours."""
    sent = _run_main(monkeypatch, {
        "interview_requests": 0, "total_emails": 50,
        "fetch_errors": 1, "fetch_abandoned": 0, "fetch_reconnects": 0,
    })
    assert sent == []

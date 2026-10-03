"""The authenticity check: advisory verdicts with readable reasons, deterministic."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "execution"))
import email_authenticity as ea  # noqa: E402

JOB_BOARD_A = (
    "YOUR INTERVIEW REQUEST · REF 8AF221A8 Your request is still open Sehrish, you asked to be considered for Business "
    "Intelligence Analyst work near Houston, TX. That request is still sitting open on your file — confirm it and we can "
    "continue to move forward. Reference8AF221A8 AreaHouston, TX 77001 StatusAwaiting your confirmation "
    "Confirm My Interview Request (https://dd.job-assist-now.com/c/AQic1RUQ7sU8GOzBuLcCIMXXoQ8ourmYGJX9U4_un2SVbVqw-JWgo68K0JbGBizTurNrH_fyA2qH) "
    "Changed your mind? See other openings near you instead (https://dd.job-assist-now.com/x)"
)
JOB_BOARD_B = (
    "[Reference ID: 4A67F9] Hi Sehrish, A hiring advisor reviewing Business Intelligence Analyst candidates asked if you're "
    "still available for roles in your area. We're preparing the next group of candidates to send forward. You can confirm "
    "your availability here (https://dd.job-assist-now.com/c/AQic1RUQ7cU8GOzBuLcCIMPXoQ8otLmYGFj52h1h6lj5dVGCeGkiwx_i3SZ8uCnxgs7IpTQBRq_S"
)
RECRUITER = (
    "Hi Sehrish, I'm Rohit from Synchrony Systems. We would like to schedule an interview with our hiring manager for the "
    "Data Engineer role (Full-Time, Jacksonville, FL) on Tuesday, October 6 at 2:00 PM CT. Join here: https://teams.microsoft.com/l/meetup-join/abc"
)


def test_a_job_board_mailer_is_flagged_with_readable_reasons():
    for body in (JOB_BOARD_A, JOB_BOARD_B):
        r = ea.assess("Business Intelligence Analyst, confirm your availability", "info@dd.job-assist-now.com", body, "Job-Assist-Now")
        assert r["verdict"] == "likely_job_board"
        assert any("click-tracking" in x for x in r["against"]) and any("jobs-site" in x for x in r["against"])
        assert r["for"] == []


def test_a_named_recruiter_with_a_date_and_meeting_link_looks_genuine():
    r = ea.assess("Interview: Data Engineer - Full-Time - Jacksonville, FL", "rohit.s@synchronycorp.com", RECRUITER, "Synchrony Systems Inc")
    assert r["verdict"] == "looks_genuine" and r["against"] == [] and "named person" in " ".join(r["for"])
    assert any("domain matches the company" in x for x in r["for"]) and any("specific date" in x for x in r["for"])


def test_html_bodies_are_read_as_text():
    html = "<!DOCTYPE html><html><body><p>Please confirm your availability</p><a href='https://x.example/u'>Unsubscribe</a></body></html>"
    r = ea.assess("hi", "team@example.com", html, None)
    assert any("job-board" in x for x in r["against"])


def test_too_little_to_tell_is_needs_check_not_a_verdict():
    r = ea.assess("Interview", "someone@gmail.com", "Please call me back", "Acme")
    assert r["verdict"] == "needs_check" and r["against"] == [] and r["for"] == []
    assert "not a decision" in r["note"] and "start of the email" in r["note"]


def test_mixed_signals_need_a_check():
    r = ea.assess("Interview", "hr@acme.com", "Please confirm your availability: https://click.mailer.example/abc. Call us Tuesday, October 6 at 2 PM.", "Acme")
    assert r["verdict"] == "needs_check"


def test_the_verdict_is_always_one_of_the_three_and_deterministic():
    a = ea.assess("s", "info@jobs-now.com", JOB_BOARD_A, None)
    assert a == ea.assess("s", "info@jobs-now.com", JOB_BOARD_A, None) and a["verdict"] in ea.VERDICTS
    assert ea.assess("", "", "", None)["verdict"] == "needs_check"

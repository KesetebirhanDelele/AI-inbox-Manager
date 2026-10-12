"""The outbound-content audit: nothing on the flagged list, and the notification wording stays inside the rules."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "execution"))

import content_audit as audit  # noqa: E402
import notification_messages as nm  # noqa: E402


@pytest.mark.parametrize("term", audit.FLAGGED_TERMS)
def test_every_flagged_term_is_caught_as_a_whole_word_in_any_case(term):
    assert term in audit.find_flagged(f"Hello. We use {term.upper()} here.")
    assert term in audit.find_flagged(f"{term.title()}, then more")


def test_whole_words_only_and_hyphen_or_space_both_match():
    assert audit.find_flagged("The excellent excelsior team") == []            # not "excel"
    assert audit.find_flagged("a sequel and pre-sqlite") == []                  # not "sql"
    assert audit.find_flagged("Full Stack developer") != []
    assert audit.find_flagged("full-stack developer") != []
    assert audit.find_flagged("Cyber   Security") == ["cyber security"]


@pytest.mark.parametrize("word", audit.SMS_BANNED_TERMS)
def test_marketing_wording_is_refused_in_a_text(word):
    assert word in audit.find_sms_banned(f"Join us, {word}!")


def test_a_dollar_amount_is_refused_in_a_text():
    assert "$ amount" in audit.find_sms_banned("It pays $50")


FACTS = {"first_name": "Kes", "employer": "Acme Corp", "date": "Thu Oct 8", "time": "2:00 PM CT", "format": "video",
         "link": "", "employer_contact": "Jane Recruiter", "status": ""}


def test_the_text_follows_every_rule(monkeypatch):
    monkeypatch.setenv("NOTIFY_CONTACT_NUMBER", "972-555-0100")
    text = nm.sms(FACTS, "", "12")
    assert text.startswith("[Interview Notification]") and len(text) <= 320
    assert audit.sms_problem(text) is None
    for needed in ("Kes", "Acme Corp", "Thu Oct 8", "2:00 PM CT", "972-555-0100", "the position you applied for"):
        assert needed in text
    assert "http" not in text


def test_a_reminder_keeps_the_tag_first_and_the_text_unique(monkeypatch):
    monkeypatch.delenv("NOTIFY_CONTACT_NUMBER", raising=False)
    a, b = nm.sms(FACTS, "", "12"), nm.sms(FACTS, "Reminder 1: ", "12")
    assert b.startswith("[Interview Notification] Reminder 1: ") and a != b
    assert audit.sms_problem(b) is None


def test_a_long_employer_name_still_fits_in_320_characters(monkeypatch):
    monkeypatch.setenv("NOTIFY_CONTACT_NUMBER", "972-555-0100")
    f = {**FACTS, "employer": "A" * 80 + " International Holdings Group", "link": "https://x.example/j"}
    text = nm.sms(f, "Final reminder: ", "123456")
    assert len(text) <= 320 and audit.sms_problem(text) is None


def test_an_employer_name_on_the_flagged_list_is_replaced_not_sent():
    assert nm.safe_employer("Excel Staffing") == "the employer"
    assert nm.safe_employer("Tableau Software") == "the employer"
    assert nm.safe_employer("Acme Corp") == "Acme Corp"
    assert nm.safe_employer("") == "the employer"
    event = type("E", (), {"company_name": "SQL Systems", "interview_date": "2026-10-08", "interview_time": "2:00 PM",
                           "interview_timezone": "CT"})()
    assert audit.sms_problem(nm.sms(nm.facts_from_event(event, None))) is None


def test_an_unscheduled_interview_says_the_employer_will_confirm():
    text = nm.sms({**FACTS, "date": "", "time": ""})
    assert "being scheduled" in text and "The employer will confirm the date and time" in text
    assert audit.sms_problem(text) is None


def test_the_email_follows_every_rule(monkeypatch):
    monkeypatch.setenv("NOTIFY_CONTACT_NUMBER", "972-555-0100")
    body = nm.email_body({**FACTS, "link": "https://meet.example/abc"})
    assert body.splitlines()[0] == "[Interview Notification]"
    assert audit.email_problem(body) is None
    for needed in ("Hello Kes", "Acme Corp", "Date: Thu Oct 8", "Time: 2:00 PM CT", "Join link: https://meet.example/abc",
                   "How to prepare", "972-555-0100"):
        assert needed in body
    assert "the position you applied for" in body and "arranged this interview" in body       # Colaberry is not the employer
    assert nm.email_subject(FACTS) == "Your interview on Thu Oct 8"


def test_the_checks_reject_a_missing_tag_or_a_flagged_word():
    assert "must begin" in audit.sms_problem("Hello there")
    assert "first line" in audit.email_problem("Hello\n[Interview Notification]")
    assert "sql" in audit.email_problem("[Interview Notification]\n\nYour SQL interview")
    assert audit.email_problem("[Interview Notification]\n\nYour interview") is None


def test_a_flagged_text_is_blocked_before_it_is_sent(monkeypatch):
    """The send-time gate: even an approver-edited draft cannot carry a flagged word out."""
    import notify_channels as nc
    ctx = type("Ctx", (), {})()
    ctx.attempt = type("A", (), {"step": "start"})()
    ctx.sequence = type("S", (), {"id": 7})()
    ctx.draft = type("D", (), {"email_subject": "Your interview", "email_body": "[Interview Notification]\n\nYour SQL interview"})()
    ctx.event, ctx.student, ctx.ack_url = None, None, ""
    assert "sql" in nc.audit_problem("email", ctx)
    result = nc.DryRunChannel("email").send(ctx)
    assert result.status == nc.FAILED and "content audit" in result.detail

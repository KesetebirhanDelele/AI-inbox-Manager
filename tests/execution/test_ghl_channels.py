"""GHL channels: what gets written where, the opt-out and text gates, shadow versus live. No network."""
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

_EXECUTION_DIR = Path(__file__).resolve().parents[2] / "execution"
if str(_EXECUTION_DIR) not in sys.path:
    sys.path.insert(0, str(_EXECUTION_DIR))

import ghl_client as gc  # noqa: E402
import notify_channels as nc  # noqa: E402

NOW = datetime(2026, 10, 5, 20, 0)


class FakeGhl:
    """Stands in for GhlClient: same config, scripted contact, records writes."""
    def __init__(self, contact=None, live=False, creds=True, lookup_error=None, write_error=None, by_email=None):
        self.config = gc.GhlConfig(
            api_key="tok" if creds else "", location_id="loc" if creds else "",
            write_mode="live" if live else "shadow", shadow_log_only=not live, write_notify_fields=live)
        self.contact = ({"id": "contact-1", "phone": "+19725550100", "email": "s@example.com", "firstName": "Test"}
                        if contact is None else contact)
        self.by_email = by_email                      # {email: contact} for the email-first lookup
        self.lookup_error, self.write_error = lookup_error, write_error
        self.lookups, self.writes, self.email_lookups = [], [], []

    def search_contact_by_phone(self, phone):
        self.lookups.append(phone)
        if self.lookup_error:
            raise self.lookup_error
        return self.contact or None

    def search_contact_by_email(self, email):
        self.email_lookups.append(email)
        if self.lookup_error:
            raise self.lookup_error
        return (self.by_email or {}).get(email.lower())

    def write_fields(self, contact_id, updates):
        if self.write_error:
            raise self.write_error
        self.writes.append((contact_id, dict(updates)))
        return {"live": self.config.is_live, "fields": sorted(updates)}


def ctx(step="start", seq_id=7, phone="(972) 555-0100", company="Acme", email_subject="Interview", now=NOW):
    return nc.SendContext(
        attempt=SimpleNamespace(step=step, channel="x"), sequence=SimpleNamespace(id=seq_id),
        draft=SimpleNamespace(email_subject=email_subject, email_body="Details here", recipient_email="s@example.com"),
        event=SimpleNamespace(company_name=company), student=SimpleNamespace(full_name="Test Student", phone_number=phone),
        ack_url="https://x.example/ack/tok", now=now, db=None)


def channel(kind, ghl):
    return nc.GhlChannel(kind, ghl)


# -- what is written where --------------------------------------------------------

def test_email_writes_ticket_2_as_subject_and_message_as_body_with_no_link():
    g = FakeGhl(live=True)
    r = channel("email", g).send(ctx())
    contact_id, updates = g.writes[0]
    assert contact_id == "contact-1" and set(updates) == {"Support Issue Ticket #2", "Message:"}
    assert updates["Support Issue Ticket #2"] == "Your interview notification (Ref 7)"
    assert updates["Message:"].startswith("[Interview Notification]")
    assert "http" not in updates["Message:"] and "ack/tok" not in updates["Message:"]         # no confirmation link: the student replies YES
    assert r.status == nc.SENT


def test_sms_writes_only_ticket_4_and_it_has_no_link_and_fits_one_segment():
    g = FakeGhl(live=True)
    channel("sms", g).send(ctx())
    _, updates = g.writes[0]
    assert list(updates) == ["Support issue Ticket #4"]
    text = updates["Support issue Ticket #4"]
    assert "http" not in text and "Reply YES" in text and "Ref 7" in text and "Acme" in text
    assert text.startswith("[Interview Notification]") and len(text) <= 320
    assert nc.sms_segments(text) <= 2


def test_call_writes_only_the_interview_notification_field():
    g = FakeGhl(live=True)
    channel("call", g).send(ctx())
    _, updates = g.writes[0]
    assert list(updates) == ["interview_notification"]
    value = updates["interview_notification"]
    assert "Candidate first name: Test" in value and "Attempt: first notice" in value and "Reference: 7" in value


def full_event(**over):
    base = dict(sub_type="Phone Screen", company_name="Acme", position_title="Data Analyst",
                interview_date="2026-10-08", interview_time="2:00 PM", interview_timezone="CT",
                interview_format="video", contact_name="Jane Recruiter", num_interviewers=2)
    base.update(over)
    return SimpleNamespace(**base)


def test_the_call_value_carries_the_interview_details_for_the_voice_agent():
    c = ctx()
    c.event = full_event()
    script = nc.call_script(c)
    for fact in ("Interview type: Phone Screen", "Company: Acme", "Position: Data Analyst", "Date: 2026-10-08",
                 "Time: 2:00 PM CT", "Format: video", "Contact at the company: Jane Recruiter",
                 "Number of interviewers: 2"):
        assert fact in script
    assert "Candidate first name: Test" in script and "Reference: 7" in script
    assert "say yes" not in script and "Tell them" not in script           # instructions live in the agent prompt, not the value


def test_the_call_value_only_states_facts_we_have_and_says_when_the_date_is_unknown():
    c = ctx()
    c.event = full_event(interview_date=None, interview_time=None, interview_timezone=None,
                         position_title=None, interview_format=None, contact_name=None, num_interviewers=None)
    script = nc.call_script(c)
    assert "Company: Acme" in script and "Position" not in script and "Format" not in script
    assert "not confirmed yet" in script
    c.event = None
    assert "a new interview request (no details available)" in nc.call_script(c)


def test_the_second_and_third_call_values_differ_so_the_workflow_triggers_again():
    values = []
    for step in ("start", "d1_2h", "day2", "day3", "day4"):
        c = ctx(step=step)
        c.event = full_event()
        values.append(nc.call_script(c))
    assert len(set(values)) == 5


def test_every_write_differs_so_a_field_change_trigger_always_fires():
    """GHL workflows fire when a field CHANGES; an identical reminder would silently send nothing."""
    texts = set()
    for step in ("start", "d1_4h", "day2", "day3", "day4"):
        g = FakeGhl(live=True)
        channel("sms", g).send(ctx(step=step))
        texts.add(g.writes[0][1]["Support issue Ticket #4"])
    assert len(texts) == 5
    other = FakeGhl(live=True)
    channel("sms", other).send(ctx(step="start", seq_id=8))
    assert other.writes[0][1]["Support issue Ticket #4"] not in texts          # another interview, same step
    subjects = set()
    for step in ("start", "d1_2h", "d1_4h"):
        g = FakeGhl(live=True)
        channel("email", g).send(ctx(step=step))
        subjects.add(g.writes[0][1]["Support Issue Ticket #2"])
    assert len(subjects) == 3


# -- failures and opt-outs ----------------------------------------------------------

def test_no_usable_phone_is_a_failure_that_can_be_seen():
    g = FakeGhl(live=True)
    for bad in (None, "", "12345"):
        assert channel("sms", g).send(ctx(phone=bad)).status == nc.FAILED
    assert g.lookups == [] and g.writes == []


def test_a_student_with_no_ghl_contact_fails_loudly_instead_of_skipping_quietly():
    g = FakeGhl(contact={}, live=True)
    r = channel("call", g).send(ctx())
    assert r.status == nc.FAILED and "no GHL contact" in r.detail and r.detail.startswith(nc.UNREACHABLE) and g.writes == []


@pytest.mark.parametrize("contact, kind, blocked", [
    ({"id": "c", "dndSettings": {"SMS": {"status": "active"}}}, "sms", True),
    ({"id": "c", "dndSettings": {"SMS": {"status": "active"}}}, "email", False),
    ({"id": "c", "dndSettings": {"SMS": {"status": "active"}}}, "call", False),
    ({"id": "c", "dndSettings": {"Call": {"status": "active"}}}, "call", True),
    ({"id": "c", "tags": ["Do Not Call"]}, "call", True),
    ({"id": "c", "dnd": True}, "email", True),
])
def test_opted_out_contacts_are_skipped_and_nothing_is_written(contact, kind, blocked):
    contact = {"phone": "+19725550100", "email": "s@example.com", "firstName": "Test", **contact}
    g = FakeGhl(contact=contact, live=True)
    r = channel(kind, g).send(ctx())
    assert (r.status == nc.SKIPPED) is blocked
    assert bool(g.writes) is (not blocked)


def test_ghl_errors_become_failed_attempts_not_crashes():
    assert channel("call", FakeGhl(live=True, lookup_error=gc.GhlError("boom"))).send(ctx()).status == nc.FAILED
    r = channel("call", FakeGhl(live=True, write_error=gc.GhlError("422"))).send(ctx())
    assert r.status == nc.FAILED and "write failed" in r.detail


# -- shadow versus live ---------------------------------------------------------------

def test_shadow_without_credentials_is_a_dry_run_that_touches_nothing():
    g = FakeGhl(creds=False)
    r = channel("sms", g).send(ctx())
    assert r.status == nc.DRY_RUN and g.lookups == [] and g.writes == []


def test_live_without_credentials_is_a_failure():
    g = FakeGhl(creds=False, live=True)
    assert channel("call", g).send(ctx()).status == nc.FAILED


def test_shadow_with_credentials_rehearses_the_lookup_and_checks_but_is_dry_run():
    g = FakeGhl(live=False)
    r = channel("call", g).send(ctx())
    assert r.status == nc.DRY_RUN and g.lookups == ["+19725550100"] and g.email_lookups == []
    assert channel("call", FakeGhl(contact={"id": "c", "tags": ["do not call"]}, live=False)).send(ctx()).status == nc.SKIPPED


def test_live_reports_handed_to_ghl_not_delivered():
    r = channel("call", FakeGhl(live=True)).send(ctx())
    assert r.status == nc.SENT and r.provider_id == "contact-1" and "not yet confirmed delivered" in r.detail


# -- the text gate ---------------------------------------------------------------------

@pytest.mark.parametrize("text, problem", [
    ("Colaberry: you have a new interview. Reply YES to confirm.", None),
    ("Yes now", "fewer than 3 words"),
    ("See https://example.com for your interview details", "link"),
    ("Visit www.example.com for your interview details", "link"),
    ("Hello {{first_name}} you have an interview", "template"),
    ("Hello None you have an interview", "template"),
    ("word " * 200, "longer than 4 segments"),
])
def test_sms_content_gate(text, problem):
    got = nc.sms_content_problem(text)
    assert (got is None) if problem is None else (problem in got)


def test_curly_quotes_are_normalised_so_a_text_stays_in_one_encoding():
    fancy = "Colaberry: you’ve got a new interview from O’Neil Group. Reply YES. Ref 7"
    assert nc.sms_segments(fancy) == 2                                  # curly quote pushes it into UCS-2: 70 per segment
    assert nc.sms_segments(nc.normalize_sms(fancy)) == 1                # normalised, it is plain GSM-7 again
    long_fancy = ("“" + "a" * 100 + "” ") * 2
    assert nc.sms_segments(long_fancy) > nc.sms_segments(nc.normalize_sms(long_fancy))
    assert "’" not in nc.normalize_sms(fancy)


def test_segment_counts():
    assert nc.sms_segments("a" * 160) == 1 and nc.sms_segments("a" * 161) == 2 and nc.sms_segments("a" * 306) == 2
    assert nc.sms_segments("é" * 70) == 1 and nc.sms_segments("é" * 71) == 2     # non-ASCII: 70 per single segment


def test_the_daily_budget_defers_to_8_05_am_pacific_tomorrow_and_never_exceeds_the_hard_cap(monkeypatch):
    monkeypatch.setattr(nc, "sms_budget_used", lambda c: 148)
    g = FakeGhl(live=True)
    r = nc.GhlChannel("sms", g, {"NOTIFY_SMS_DAILY_SEGMENT_CAP": "150"}).send(ctx())     # needs 2 segments: 150 total, fits
    assert r.status == nc.SENT
    monkeypatch.setattr(nc, "sms_budget_used", lambda c: 150)
    g = FakeGhl(live=True)
    r = nc.GhlChannel("sms", g, {"NOTIFY_SMS_DAILY_SEGMENT_CAP": "150"}).send(ctx())
    assert r.status == nc.DEFERRED and g.writes == []
    assert r.retry_at == datetime(2026, 10, 6, 15, 5)                    # 08:05 PDT on the 6th
    assert nc.sms_daily_cap({"NOTIFY_SMS_DAILY_SEGMENT_CAP": "5000"}) == 999
    assert nc.sms_daily_cap({"NOTIFY_SMS_DAILY_SEGMENT_CAP": "junk"}) == 150
    assert nc.sms_daily_cap({}) == 150


def test_the_budget_day_resets_at_midnight_pacific_in_summer_and_winter():
    assert nc.pacific_day_start_utc(datetime(2026, 10, 2, 17, 0)) == datetime(2026, 10, 2, 7, 0)    # PDT
    assert nc.pacific_day_start_utc(datetime(2026, 12, 1, 10, 0)) == datetime(2026, 12, 1, 8, 0)    # PST
    assert nc.next_pacific_day_start_utc(datetime(2026, 10, 2, 17, 0)) == datetime(2026, 10, 3, 7, 0)


def test_budget_counts_only_real_sends_since_midnight_pacific(monkeypatch):
    api_dir = _EXECUTION_DIR.parents[0] / "services" / "dashboard" / "api"
    monkeypatch.syspath_prepend(str(api_dir))
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import models
    engine = create_engine("sqlite://")
    models.Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    day = datetime(2026, 10, 5, 20, 0)                                   # 13:00 PDT; budget day began 07:00 UTC
    for status, sent_at, seg in (("sent", datetime(2026, 10, 5, 8, 0), 2), ("sent", datetime(2026, 10, 5, 6, 0), 5),
                                 ("dry_run", datetime(2026, 10, 5, 9, 0), 9), ("failed", datetime(2026, 10, 5, 9, 0), 9)):
        db.add(models.NotificationAttempt(sequence_id=1, channel="sms", step=f"s{seg}{status}", planned_for=day,
                                          scheduled_for=day, status=status, sent_at=sent_at, segments=seg))
    db.add(models.NotificationAttempt(sequence_id=1, channel="call", step="c", planned_for=day, scheduled_for=day,
                                      status="sent", sent_at=datetime(2026, 10, 5, 10, 0), segments=4))
    db.commit()
    c = ctx(now=day)
    c.db = db
    assert nc.sms_budget_used(c) == 2                                    # only today's real texts


# -- choosing channels -------------------------------------------------------------------

def test_default_is_dry_run_everywhere():
    assert {k: type(v).__name__ for k, v in nc.channels_from_env({}).items()} == {
        "email": "DryRunChannel", "sms": "DryRunChannel", "call": "DryRunChannel"}


def test_ghl_for_all_three_shares_one_client_and_smtp_is_email_only():
    chosen = nc.channels_from_env({"NOTIFY_CHANNEL_EMAIL": "ghl", "NOTIFY_CHANNEL_SMS": "ghl", "NOTIFY_CHANNEL_CALL": "ghl"})
    assert all(isinstance(c, nc.GhlChannel) for c in chosen.values())
    assert chosen["email"].client is chosen["sms"].client is chosen["call"].client
    assert isinstance(nc.channels_from_env({"NOTIFY_CHANNEL_EMAIL": "smtp"})["email"], nc.SmtpEmailChannel)
    with pytest.raises(ValueError):
        nc.channels_from_env({"NOTIFY_CHANNEL_SMS": "smtp"})
    with pytest.raises(ValueError):
        nc.channels_from_env({"NOTIFY_CHANNEL_CALL": "carrier pigeon"})


def test_going_live_without_credentials_fails_at_startup_not_at_the_first_send():
    live = {"NOTIFY_CHANNEL_CALL": "ghl", "GHL_WRITE_MODE": "live", "GHL_WRITE_SHADOW_LOG_ONLY": "false",
            "GHL_WRITE_NOTIFY_FIELDS": "true"}
    with pytest.raises(ValueError, match="GHL_API_KEY"):
        nc.channels_from_env(live)
    nc.channels_from_env({**live, "GHL_API_KEY": "t", "GHL_LOCATION_ID": "l"})


def test_to_e164():
    assert nc.to_e164("(972) 555-0100") == "+19725550100" and nc.to_e164("1-972-555-0100") == "+19725550100"
    assert nc.to_e164("+1 972 555 0100") == "+19725550100" and nc.to_e164("555-0100") is None and nc.to_e164(None) is None


def test_a_recorded_opt_out_blocks_the_send_before_ghl_is_even_asked():
    import models
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    eng = create_engine("sqlite://")
    models.Base.metadata.create_all(eng)
    db = sessionmaker(bind=eng)()
    db.add(models.NotificationOptOut(phone_tail="5551234567", channel="call", source="stop_call"))
    db.commit()
    assert nc.opted_out_in_app(db, "+15551234567", "call") is True
    assert nc.opted_out_in_app(db, "+15551234567", "sms") is False          # per channel
    assert nc.opted_out_in_app(db, "+15559999999", "call") is False
    assert nc.opted_out_in_app(None, "+15551234567", "call") is False        # no session = not checked


def test_the_channel_skips_a_student_who_asked_us_to_stop_and_makes_no_ghl_call():
    import models
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    eng = create_engine("sqlite://")
    models.Base.metadata.create_all(eng)
    db = sessionmaker(bind=eng)()
    db.add(models.NotificationOptOut(phone_tail="9725550100", channel="call", source="stop_call"))
    db.commit()
    g = FakeGhl(live=True)
    c = ctx()
    c.db = db
    r = channel("call", g).send(c)
    assert r.status == nc.SKIPPED and "asked us to stop" in r.detail
    assert g.lookups == [] and g.writes == []
    assert channel("email", g).send(c).status == nc.SENT          # only the call channel was opted out


# ── email-first contact lookup ────────────────────────────────────────────────────────────────
def student(**kw):
    base = dict(full_name="Test Student", phone_number=None, personal_email=None, assigned_gmail=None)
    base.update(kw)
    return SimpleNamespace(**base)


def with_student(c, **kw):
    c.student = student(**kw)
    return c


def test_a_student_is_found_by_email_first_even_with_no_phone_on_our_side():
    contact = {"id": "e1", "phone": "+15551230000", "email": "t@example.com", "firstName": "Test"}
    g = FakeGhl(live=True, by_email={"t@example.com": contact})
    r = channel("call", g).send(with_student(ctx(), personal_email="T@Example.com"))
    assert r.status == nc.SENT and g.writes[0][0] == "e1" and g.lookups == []      # no phone to search with


def test_the_assigned_gmail_is_tried_when_the_personal_email_finds_nothing():
    contact = {"id": "e2", "phone": "+15551230000", "email": "g@example.com", "firstName": "Test"}
    g = FakeGhl(live=True, by_email={"g@example.com": contact})
    r = channel("sms", g).send(with_student(ctx(), personal_email="old@example.com", assigned_gmail="g@example.com"))
    assert r.status == nc.SENT and g.email_lookups == ["old@example.com", "g@example.com"]


def test_email_and_phone_agreeing_on_one_contact_is_fine():
    contact = {"id": "contact-1", "phone": "+19725550100", "email": "t@example.com", "firstName": "Test"}
    g = FakeGhl(contact=contact, live=True, by_email={"t@example.com": contact})
    assert channel("email", g).send(with_student(ctx(), personal_email="t@example.com", phone_number="(972) 555-0100")).status == nc.SENT


def test_email_and_phone_pointing_at_different_contacts_is_refused_not_guessed():
    other = {"id": "other", "phone": "+15559999999", "email": "t@example.com", "firstName": "Test"}
    g = FakeGhl(live=True, by_email={"t@example.com": other})        # the phone search finds contact-1
    r = channel("call", g).send(with_student(ctx(), personal_email="t@example.com", phone_number="(972) 555-0100"))
    assert r.status == nc.FAILED and r.detail.startswith(nc.UNREACHABLE) and "different GHL contacts" in r.detail and g.writes == []


def test_a_contact_found_only_by_phone_must_have_the_same_first_name():
    c = {"id": "p1", "phone": "+19725550100", "email": "x@example.com", "firstName": "Someone"}
    g = FakeGhl(contact=c, live=True)
    r = channel("call", g).send(with_student(ctx(), full_name="Alisha Khan", phone_number="(972) 555-0100"))
    assert r.status == nc.FAILED and "different first name" in r.detail and g.writes == []
    # nickname-style prefix and a blank GHL name are accepted
    assert channel("call", FakeGhl(contact=dict(c, firstName="Ali"), live=True)).send(
        with_student(ctx(), full_name="Alisha Khan", phone_number="(972) 555-0100")).status == nc.SENT
    assert channel("call", FakeGhl(contact=dict(c, firstName=""), live=True)).send(
        with_student(ctx(), full_name="Alisha Khan", phone_number="(972) 555-0100")).status == nc.SENT


def test_nothing_found_by_email_or_phone_tells_a_human_what_to_fix():
    g = FakeGhl(contact={}, live=True)
    r = channel("email", g).send(with_student(ctx(), personal_email="gone@example.com", phone_number="(972) 555-0100"))
    assert r.status == nc.FAILED and r.detail.startswith(nc.UNREACHABLE) and "changed their email or phone" in r.detail


def test_a_student_with_no_email_gmail_or_phone_is_unreachable_without_calling_ghl():
    g = FakeGhl(live=True)
    r = channel("call", g).send(with_student(ctx(), phone_number=None))
    assert r.status == nc.FAILED and "no email or phone number on file" in r.detail
    assert g.lookups == [] and g.email_lookups == [] and g.writes == []


def test_a_found_contact_with_no_phone_cannot_take_a_call_or_text_but_can_take_an_email():
    c = {"id": "e3", "email": "t@example.com", "firstName": "Test"}
    g = FakeGhl(live=True, by_email={"t@example.com": c})
    assert channel("call", g).send(with_student(ctx(), personal_email="t@example.com")).detail.startswith(nc.UNREACHABLE)
    assert channel("sms", g).send(with_student(ctx(), personal_email="t@example.com")).status == nc.FAILED
    assert channel("email", g).send(with_student(ctx(), personal_email="t@example.com")).status == nc.SENT


def test_when_no_contact_matches_the_message_suggests_near_matches_by_name():
    class WithNames(FakeGhl):
        def search_contacts_by_name(self, query):
            return [{"id": "c9", "firstName": "kwadjossan", "lastName": "issac kpakpavi", "email": "isaackpakpavi@gmail.com", "phone": "+12404869243"}]
    student = type("S", (), {"full_name": "Kwadjossan Isaac", "personal_email": "wrong@example.com", "assigned_gmail": "", "phone_number": "2404869244"})()
    contact, how, problem = nc.find_ghl_contact(WithNames(contact=False), student)
    assert contact is None and "no GHL contact matches" in problem
    assert "Possible matches in GHL by name" in problem and "isaackpakpavi@gmail.com" in problem and "phone ending 9243" in problem


def test_a_failing_name_search_never_changes_the_result():
    class Broken(FakeGhl):
        def search_contacts_by_name(self, query):
            raise RuntimeError("GHL down")
    student = type("S", (), {"full_name": "Kwadjossan Isaac", "personal_email": "a@example.com", "assigned_gmail": "", "phone_number": ""})()
    contact, how, problem = nc.find_ghl_contact(Broken(contact=False), student)
    assert contact is None and "no GHL contact matches" in problem and "Possible matches" not in problem

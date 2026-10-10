"""Escalation schedule and quiet-hours rules. Pure logic: no database, no network."""
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

_EXECUTION_DIR = Path(__file__).resolve().parents[2] / "execution"
if str(_EXECUTION_DIR) not in sys.path:
    sys.path.insert(0, str(_EXECUTION_DIR))

import escalation_schedule as es  # noqa: E402

CHI, LA = "America/Chicago", "America/Los_Angeles"


# -- time zone from the phone number ------------------------------------------

@pytest.mark.parametrize("phone, zone, source", [
    ("972-992-1024", CHI, "area_code"),
    ("(213) 401-5256", LA, "area_code"),
    ("+1 212 555 0100", "America/New_York", "area_code"),
    ("1-303-555-0100", "America/Denver", "area_code"),
    ("555", CHI, "fallback"),                 # unreadable
    (None, CHI, "fallback"),
    ("800-555-0100", CHI, "fallback"),        # toll-free has no zone
])
def test_timezone_from_phone(phone, zone, source):
    assert es.timezone_for_phone(phone) == (zone, source)


def test_stored_zone_wins_but_a_bad_one_is_ignored():
    assert es.timezone_for_phone("972-992-1024", stored=LA) == (LA, "stored")
    assert es.timezone_for_phone("213-401-5256", stored="Not/AZone") == (LA, "area_code")


# -- quiet hours: 9 PM to 8 AM, student-local ---------------------------------

@pytest.mark.parametrize("utc, tz, quiet", [
    (datetime(2026, 10, 5, 2, 0), CHI, True),      # 21:00 CDT
    (datetime(2026, 10, 5, 1, 59), CHI, False),    # 20:59 CDT
    (datetime(2026, 10, 5, 12, 59), CHI, True),    # 07:59 CDT
    (datetime(2026, 10, 5, 13, 0), CHI, False),    # 08:00 CDT
    (datetime(2026, 10, 5, 13, 0), LA, True),      # 06:00 PDT: Ali's own example
    (datetime(2026, 10, 5, 15, 0), LA, False),     # 08:00 PDT
])
def test_in_quiet_hours(utc, tz, quiet):
    assert es.in_quiet_hours(utc, tz) is quiet                       # the text rule: 9 PM to 8 AM


@pytest.mark.parametrize("utc, call_quiet, sms_quiet", [
    (datetime(2026, 10, 5, 0, 59), False, False),    # 19:59 CDT
    (datetime(2026, 10, 5, 1, 0), True, False),      # 20:00 CDT: calls are done for the day, texts are not
    (datetime(2026, 10, 5, 1, 59), True, False),     # 20:59 CDT
    (datetime(2026, 10, 5, 2, 0), True, True),       # 21:00 CDT: both quiet
    (datetime(2026, 10, 5, 13, 0), False, False),    # 08:00 CDT: both open
])
def test_calls_stop_at_8pm_because_ghl_only_places_calls_8am_to_8pm_but_texts_run_to_9pm(utc, call_quiet, sms_quiet):
    assert es.in_quiet_hours(utc, CHI, "call") is call_quiet
    assert es.in_quiet_hours(utc, CHI, "sms") is sms_quiet


def test_a_held_call_or_text_is_released_at_8am_local():
    evening = datetime(2026, 10, 5, 3, 30)          # 22:30 CDT on the 4th
    assert es.release_time(evening, CHI, "call") == datetime(2026, 10, 5, 13, 0)    # 8 AM CDT on the 5th
    small_hours = datetime(2026, 10, 5, 8, 0)       # 03:00 CDT on the 5th
    assert es.release_time(small_hours, CHI, "sms") == datetime(2026, 10, 5, 13, 0)  # same morning
    assert es.release_time(datetime(2026, 10, 5, 13, 0), LA, "call") == datetime(2026, 10, 5, 15, 0)


def test_a_call_after_8pm_is_held_to_8am_but_a_text_at_the_same_time_is_not():
    evening = datetime(2026, 10, 5, 1, 30)           # 20:30 CDT on the 4th
    assert es.release_time(evening, CHI, "call") == datetime(2026, 10, 5, 13, 0)      # 8 AM CDT on the 5th
    assert es.release_time(evening, CHI, "sms") == evening


def test_email_is_never_held_and_daytime_calls_are_not_moved():
    night = datetime(2026, 10, 5, 3, 30)
    assert es.release_time(night, CHI, "email") == night
    noon = datetime(2026, 10, 5, 17, 0)
    assert es.release_time(noon, CHI, "call") == noon


# -- the plan -----------------------------------------------------------------

START = datetime(2026, 10, 5, 20, 0)                # 15:00 CDT, a Monday


def test_plan_has_the_approved_shape():
    plan = es.build_plan(START, CHI)
    assert len(plan) == 6 + 9
    by_step = {}
    for p in plan:
        by_step.setdefault(p.step, {})[p.channel] = p.planned_for
    assert set(by_step["start"]) == {"call", "sms", "email"}
    assert set(by_step["d1_2h"]) == {"email"}                         # GHL: one call per phone number per day
    assert set(by_step["d1_4h"]) == {"sms", "email"}
    assert by_step["d1_2h"]["email"] == START + timedelta(hours=2)
    assert by_step["d1_4h"]["sms"] == START + timedelta(hours=4)
    for day in ("day2", "day3", "day4"):
        assert set(by_step[day]) == {"call", "sms", "email"}
    assert "day5" not in by_step                    # three follow-up days after day 1, no more


def test_ghls_one_call_per_number_per_day_and_14_in_14_days_are_never_exceeded():
    calls = [p for p in es.build_plan(START, CHI) if p.channel == "call"]
    assert len(calls) == 4                                           # day 1 plus days 2-4, well under 14
    days = [es._to_local(es.scheduled_time(p, CHI), CHI).date() for p in calls]
    assert len(set(days)) == len(days)                               # never two calls on one local day


def test_follow_up_days_are_9am_student_local():
    plan = es.build_plan(START, CHI)
    day2 = next(p for p in plan if p.step == "day2" and p.channel == "call")
    assert day2.planned_for == datetime(2026, 10, 6, 14, 0)          # 9 AM CDT on the 6th
    day4 = next(p for p in plan if p.step == "day4" and p.channel == "sms")
    assert day4.planned_for == datetime(2026, 10, 8, 14, 0)
    la_day2 = next(p for p in es.build_plan(START, LA) if p.step == "day2" and p.channel == "call")
    assert la_day2.planned_for == datetime(2026, 10, 6, 16, 0)        # 9 AM PDT


def test_follow_up_time_stays_9am_across_the_clocks_going_back():
    start = datetime(2026, 10, 31, 20, 0)            # day 1 is Saturday 31 Oct (CDT)
    day2 = next(p for p in es.build_plan(start, CHI) if p.step == "day2" and p.channel == "email")
    assert day2.planned_for == datetime(2026, 11, 1, 15, 0)          # 9 AM CST (UTC-6) on 1 Nov


def test_rob_is_told_after_day_one_and_the_end_comes_after_the_last_attempt():
    assert es.no_response_due(START) == START + timedelta(hours=6)
    plan = es.build_plan(START, CHI)
    last = max(es.scheduled_time(p, CHI) for p in plan)
    assert es.sequence_ended_due(plan, CHI) == last + timedelta(hours=3)


def test_scheduled_time_applies_quiet_hours_to_the_plan():
    late_start = datetime(2026, 10, 6, 1, 0)         # 20:00 CDT on the 5th
    plan = es.build_plan(late_start, CHI)
    d1_4h_sms = next(p for p in plan if p.step == "d1_4h" and p.channel == "sms")          # 00:00 CDT
    assert es.scheduled_time(d1_4h_sms, CHI) == datetime(2026, 10, 6, 13, 0)               # held to 8 AM
    d1_4h_email = next(p for p in plan if p.step == "d1_4h" and p.channel == "email")
    assert es.scheduled_time(d1_4h_email, CHI) == d1_4h_email.planned_for                  # email goes anyway


def test_collision_rule():
    t = datetime(2026, 10, 6, 13, 0)
    assert es.collides_with_neighbour(t, [t + timedelta(hours=2, minutes=59)]) is True
    assert es.collides_with_neighbour(t, [t + timedelta(hours=3)]) is False
    assert es.collides_with_neighbour(t, []) is False


# --- the plan stops at the interview (2026-10-10) -----------------------------------------------------------------------------------

from datetime import datetime as _dt, timedelta as _td  # noqa: E402

_CHI = "America/Chicago"


def _utc(y, mo, d, h, mi=0):
    return _dt(y, mo, d, h, mi)


def test_interview_when_reads_the_zone_written_on_the_interview_and_a_missing_time_means_end_of_day():
    assert es.interview_when("2026-10-14", "11:00", "CT", "America/New_York") == (_utc(2026, 10, 14, 16), True)
    assert es.interview_when("2026-10-14", "2:30 PM", "EDT", _CHI) == (_utc(2026, 10, 14, 18, 30), True)
    when, known = es.interview_when("2026-10-14", None, None, _CHI)
    assert known is False and when == _utc(2026, 10, 15, 4, 59)
    assert es.interview_when(None, "11:00", "CT", _CHI) == (None, False)
    assert es.interview_when("not a date", "11:00", "CT", _CHI) == (None, False)


def test_no_interview_date_keeps_the_four_day_plan():
    start = _utc(2026, 10, 12, 20)
    assert len(es.build_plan(start, _CHI)) == len(es.build_plan(start, _CHI, None)) == 15


def test_a_far_interview_keeps_the_four_day_plan_and_adds_no_final_reminder():
    start = _utc(2026, 10, 12, 20)
    plan = es.build_plan(start, _CHI, _utc(2026, 10, 24, 16), True)
    assert len(plan) == 15 and not any(p.step == "final" for p in plan)


def test_interview_tomorrow_stops_at_the_interview_and_adds_a_final_text_and_email():
    start = _utc(2026, 10, 12, 20)                       # Monday 3 PM Central
    interview = _utc(2026, 10, 13, 19)                   # Tuesday 2 PM Central
    plan = es.build_plan(start, _CHI, interview, True)
    assert all(p.planned_for < interview for p in plan)
    assert not any(p.step in ("day3", "day4") for p in plan)
    finals = [(p.channel, p.planned_for) for p in plan if p.step == "final"]
    assert sorted(c for c, _ in finals) == ["email", "sms"] and all(t == interview - _td(hours=2) for _, t in finals)
    assert len(plan) == 11


def test_interview_in_three_hours_gets_the_first_notice_and_an_email_only():
    start = _utc(2026, 10, 12, 20)
    plan = es.build_plan(start, _CHI, start + _td(hours=3), True)
    assert [(p.step, p.channel) for p in plan] == [("start", "call"), ("start", "email"), ("start", "sms"), ("d1_2h", "email")] or \
        sorted((p.step, p.channel) for p in plan) == sorted([("start", "call"), ("start", "sms"), ("start", "email"), ("d1_2h", "email")])


def test_an_interview_that_is_already_over_plans_nothing():
    start = _utc(2026, 10, 12, 20)
    assert es.build_plan(start, _CHI, start - _td(minutes=1), True) == []


def test_an_interview_with_no_time_of_day_gets_no_timed_reminder_but_still_stops_at_the_end_of_that_day():
    start = _utc(2026, 10, 12, 20)
    interview, known = es.interview_when("2026-10-13", None, None, _CHI)
    plan = es.build_plan(start, _CHI, interview, known)
    assert not any(p.step == "final" for p in plan) and all(p.planned_for < interview for p in plan)


def test_the_no_response_alert_comes_before_a_near_interview_not_after_it():
    start = _utc(2026, 10, 12, 20)
    assert es.no_response_due(start) == start + _td(hours=6)
    assert es.no_response_due(start, start + _td(hours=3)) == start + _td(hours=2)
    assert es.no_response_due(start, start + _td(days=5)) == start + _td(hours=6)

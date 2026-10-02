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
    assert es.in_quiet_hours(utc, tz) is quiet


def test_a_held_call_or_text_is_released_at_8am_local():
    evening = datetime(2026, 10, 5, 3, 30)          # 22:30 CDT on the 4th
    assert es.release_time(evening, CHI, "call") == datetime(2026, 10, 5, 13, 0)    # 8 AM CDT on the 5th
    small_hours = datetime(2026, 10, 5, 8, 0)       # 03:00 CDT on the 5th
    assert es.release_time(small_hours, CHI, "sms") == datetime(2026, 10, 5, 13, 0)  # same morning
    assert es.release_time(datetime(2026, 10, 5, 13, 0), LA, "call") == datetime(2026, 10, 5, 15, 0)


def test_email_is_never_held_and_daytime_calls_are_not_moved():
    night = datetime(2026, 10, 5, 3, 30)
    assert es.release_time(night, CHI, "email") == night
    noon = datetime(2026, 10, 5, 17, 0)
    assert es.release_time(noon, CHI, "call") == noon


# -- the plan -----------------------------------------------------------------

START = datetime(2026, 10, 5, 20, 0)                # 15:00 CDT, a Monday


def test_plan_has_the_approved_shape():
    plan = es.build_plan(START, CHI)
    assert len(plan) == 7 + 9
    by_step = {}
    for p in plan:
        by_step.setdefault(p.step, {})[p.channel] = p.planned_for
    assert set(by_step["start"]) == {"call", "sms", "email"}
    assert set(by_step["d1_2h"]) == {"call", "email"}
    assert set(by_step["d1_4h"]) == {"sms", "email"}
    assert by_step["d1_2h"]["call"] == START + timedelta(hours=2)
    assert by_step["d1_4h"]["sms"] == START + timedelta(hours=4)
    for day in ("day2", "day3", "day4"):
        assert set(by_step[day]) == {"call", "sms", "email"}
    assert "day5" not in by_step                    # three follow-up days after day 1, no more


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
    assert es.rob_no_response_due(START) == START + timedelta(hours=6)
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

"""
Student notification escalation: the schedule and the quiet-hours rules.

Pure logic, no database, no network (so it is fast to test). The approved design is in
directives/student-notification-escalation.md.

Times passed in and out are NAIVE UTC datetimes, the same convention the rest of the
database uses. Time zones are only applied to decide local hours.

Schedule (T0 = the moment Rob approves):
    T0        call + text + email
    T0 + 2h   email                (no second call: GHL Voice AI allows ONE call per phone number per day)
    T0 + 4h   text + email
    day 2-4   one call + one text + one email at 9:00 AM student-local time
Quiet hours, student-local: calls only 8 AM to 8 PM (GHL Voice AI itself places calls only in that window and
silently reschedules the rest, so we match it); texts 9 PM to 8 AM is quiet (Ali). Email goes at any time.
An attempt that lands in quiet hours is held and released at 8 AM.
"""

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import List, Optional, Tuple
from zoneinfo import ZoneInfo

from area_code_timezones import AREA_CODE_TIMEZONES

FALLBACK_TIMEZONE = "America/Chicago"      # Ali: only when the area code lookup fails
QUIET_START_HOUR = 21                      # 9 PM: texts (Ali)
CALL_QUIET_START_HOUR = 20                 # 8 PM: calls. GHL Voice AI only calls 8 AM-8 PM in the contact's zone
QUIET_END_HOUR = 8                         # 8 AM
DAILY_ATTEMPT_HOUR = 9                     # days 2-4, student-local
FOLLOW_UP_DAYS = 3                         # days 2, 3 and 4 (Kes: "3 days after day 1")
ROB_NO_RESPONSE_AFTER = timedelta(hours=6)  # day 1 round 2 sent at +4h, plus a 2h response window
ENDED_ALERT_AFTER_LAST_ATTEMPT = timedelta(hours=3)
MIN_SAME_CHANNEL_GAP = timedelta(hours=3)  # applies to held (quiet-hours) attempts only

PHONE_CHANNELS = ("call", "sms")           # the channels quiet hours bind


@dataclass(frozen=True)
class Planned:
    step: str
    channel: str
    planned_for: datetime       # naive UTC, before quiet-hours adjustment


# ── time zone ────────────────────────────────────────────────────────────────

def area_code(phone: Optional[str]) -> Optional[int]:
    """The 3-digit NANP area code of a US/Canada number, or None if it cannot be read."""
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return None
    return int(digits[:3])


def timezone_for_phone(phone: Optional[str], stored: Optional[str] = None) -> Tuple[str, str]:
    """
    The student's own time zone and where it came from.

    Order (Ali): a stored zone, else the phone's area code, else America/Chicago.
    Returns (zone_name, source) with source in stored | area_code | fallback.
    """
    if stored:
        try:
            ZoneInfo(stored)
            return stored, "stored"
        except Exception:
            pass
    code = area_code(phone)
    if code is not None and code in AREA_CODE_TIMEZONES:
        return AREA_CODE_TIMEZONES[code], "area_code"
    return FALLBACK_TIMEZONE, "fallback"


# ── conversions ──────────────────────────────────────────────────────────────

def _to_local(utc_naive: datetime, tz_name: str) -> datetime:
    return utc_naive.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(tz_name))


def _to_utc_naive(local_aware: datetime) -> datetime:
    return local_aware.astimezone(timezone.utc).replace(tzinfo=None)


def quiet_start_hour(channel: str) -> int:
    return CALL_QUIET_START_HOUR if channel == "call" else QUIET_START_HOUR


def in_quiet_hours(utc_naive: datetime, tz_name: str, channel: str = "sms") -> bool:
    """True from the channel's quiet start (8 PM calls, 9 PM texts) up to, not including, 8 AM student-local."""
    hour = _to_local(utc_naive, tz_name).hour
    return hour >= quiet_start_hour(channel) or hour < QUIET_END_HOUR


def release_time(utc_naive: datetime, tz_name: str, channel: str) -> datetime:
    """
    When an attempt may actually go out. Emails are never held. A call or text that falls in
    quiet hours is held until 8 AM local: the same morning if it is after midnight, otherwise
    the next morning.
    """
    if channel not in PHONE_CHANNELS or not in_quiet_hours(utc_naive, tz_name, channel):
        return utc_naive
    local = _to_local(utc_naive, tz_name)
    morning = datetime.combine(local.date(), time(QUIET_END_HOUR), tzinfo=ZoneInfo(tz_name))
    if local.hour >= quiet_start_hour(channel):
        morning += timedelta(days=1)
    return _to_utc_naive(morning)


# ── the plan ─────────────────────────────────────────────────────────────────

def build_plan(start_utc: datetime, tz_name: str) -> List[Planned]:
    """Every attempt of one sequence, in order, before quiet-hours adjustment."""
    plan: List[Planned] = [
        Planned("start", "call", start_utc),
        Planned("start", "sms", start_utc),
        Planned("start", "email", start_utc),
        Planned("d1_2h", "email", start_utc + timedelta(hours=2)),
        Planned("d1_4h", "sms", start_utc + timedelta(hours=4)),
        Planned("d1_4h", "email", start_utc + timedelta(hours=4)),
    ]
    zone = ZoneInfo(tz_name)
    first_day = _to_local(start_utc, tz_name).date()
    for offset in range(1, FOLLOW_UP_DAYS + 1):
        local_nine = datetime.combine(first_day + timedelta(days=offset), time(DAILY_ATTEMPT_HOUR), tzinfo=zone)
        due = _to_utc_naive(local_nine)
        for channel in ("call", "sms", "email"):
            plan.append(Planned(f"day{offset + 1}", channel, due))
    return plan


def scheduled_time(planned: Planned, tz_name: str) -> datetime:
    """The planned time after quiet hours are applied."""
    return release_time(planned.planned_for, tz_name, planned.channel)


def rob_no_response_due(start_utc: datetime) -> datetime:
    """Rob is told the student has not responded after day 1's rounds. This does NOT end the sequence."""
    return start_utc + ROB_NO_RESPONSE_AFTER


def sequence_ended_due(plan: List[Planned], tz_name: str) -> datetime:
    """After the final day's attempts have had time to land, the sequence ends and Rob is told."""
    last = max(scheduled_time(p, tz_name) for p in plan)
    return last + ENDED_ALERT_AFTER_LAST_ATTEMPT


def collides_with_neighbour(candidate: datetime, others: List[datetime]) -> bool:
    """True if another same-channel attempt falls within MIN_SAME_CHANNEL_GAP of `candidate`."""
    return any(abs(o - candidate) < MIN_SAME_CHANNEL_GAP for o in others)

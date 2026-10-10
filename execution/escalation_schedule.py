"""
Student notification escalation: the schedule and the quiet-hours rules.

Pure logic, no database, no network (so it is fast to test). The approved design is in
directives/student-notification-escalation.md.

Times passed in and out are NAIVE UTC datetimes, the same convention the rest of the
database uses. Time zones are only applied to decide local hours.

Schedule (T0 = the moment the approver approves):
    T0        call + text + email
    T0 + 2h   email                (no second call: GHL Voice AI allows ONE call per phone number per day)
    T0 + 4h   text + email
    day 2-4   one call + one text + one email at 9:00 AM student-local time
Quiet hours, student-local: calls only 8 AM to 8 PM (GHL Voice AI itself places calls only in that window and
silently reschedules the rest, so we match it); texts 9 PM to 8 AM is quiet (Ali). Email goes at any time.
An attempt that lands in quiet hours is held and released at 8 AM.

The plan stops at the interview (2026-10-10): nothing is planned for after the interview time, the 9 AM follow-ups on later days only exist
when the interview is still at least an hour away, and when the interview is within SHORT_NOTICE_HOURS a final text and email go out two hours
before it. With no interview date the four-day plan above is used unchanged.
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

REMINDER_MARGIN = timedelta(hours=1)       # nothing is planned within an hour of the interview, except the final reminder
SHORT_NOTICE_HOURS = 36                    # interview this close to approval: close-spaced reminders plus a final one
FINAL_REMINDER_BEFORE = timedelta(hours=2)
MIN_REMINDER_GAP = timedelta(hours=2)      # two reminders on the same channel are never closer than this (final reminders excepted)
TZ_ABBREVIATIONS = {
    "CT": "America/Chicago", "CST": "America/Chicago", "CDT": "America/Chicago",
    "ET": "America/New_York", "EST": "America/New_York", "EDT": "America/New_York",
    "MT": "America/Denver", "MST": "America/Denver", "MDT": "America/Denver",
    "PT": "America/Los_Angeles", "PST": "America/Los_Angeles", "PDT": "America/Los_Angeles",
    "UTC": "UTC", "GMT": "UTC",
}


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

def interview_when(date_text: Optional[str], time_text: Optional[str], tz_text: Optional[str], fallback_tz: str) -> Tuple[Optional[datetime], bool]:
    """
    When the interview is, as (naive UTC, time_is_known). (None, False) when there is no usable date.
    A date with no time counts as the END of that day (so nothing is sent after the day, and no timed reminder is planned).
    The zone is the one written on the interview (CT, EDT ...) else the student's own.
    """
    import re
    date_text = (date_text or "").strip()
    try:
        day = datetime.strptime(date_text[:10], "%Y-%m-%d").date()
    except ValueError:
        return None, False
    zone_name = TZ_ABBREVIATIONS.get((tz_text or "").strip().upper()) or fallback_tz
    try:
        zone = ZoneInfo(zone_name)
    except Exception:
        zone = ZoneInfo(FALLBACK_TIMEZONE)
    clock = None
    match = re.match(r"^\s*(\d{1,2}):(\d{2})(?::\d{2})?\s*([AaPp][Mm])?\s*$", time_text or "")
    if match:
        hour, minute, ampm = int(match.group(1)), int(match.group(2)), (match.group(3) or "").lower()
        if ampm == "pm" and hour < 12:
            hour += 12
        if ampm == "am" and hour == 12:
            hour = 0
        if 0 <= hour < 24 and 0 <= minute < 60:
            clock = time(hour, minute)
    if clock is None:
        return _to_utc_naive(datetime.combine(day, time(23, 59), tzinfo=zone)), False
    return _to_utc_naive(datetime.combine(day, clock, tzinfo=zone)), True


def build_plan(start_utc: datetime, tz_name: str, interview_utc: Optional[datetime] = None, time_known: bool = True) -> List[Planned]:
    """
    Every attempt of one sequence, in order, before quiet-hours adjustment.

    With an interview time the plan stops there: an interview already past plans nothing; a follow-up that would land less than an hour
    before it (or after it) is dropped; and a short-notice interview (within 36 hours of approval, time known) gets a final text and email two
    hours before it, with no two same-channel reminders closer than two hours.
    """
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
    if interview_utc is None:
        return plan

    if interview_utc <= start_utc:
        return []                                   # the interview has already happened: nothing to send
    latest = interview_utc - REMINDER_MARGIN
    kept: List[Planned] = [p for p in plan if p.step == "start" or p.planned_for <= latest]
    short_notice = time_known and (interview_utc - start_utc) <= timedelta(hours=SHORT_NOTICE_HOURS)
    if short_notice:
        kept = [p for p in kept if p.step == "start" or not any(
            q is not p and q.channel == p.channel and q.planned_for < p.planned_for and p.planned_for - q.planned_for < MIN_REMINDER_GAP for q in kept)]
        final_at = interview_utc - FINAL_REMINDER_BEFORE
        if final_at > start_utc + timedelta(hours=1):
            for channel in ("sms", "email"):
                if not any(q.channel == channel and abs(q.planned_for - final_at) < MIN_REMINDER_GAP for q in kept):
                    kept.append(Planned("final", channel, final_at))
    return sorted(kept, key=lambda p: (p.planned_for, p.channel))


def scheduled_time(planned: Planned, tz_name: str) -> datetime:
    """The planned time after quiet hours are applied."""
    return release_time(planned.planned_for, tz_name, planned.channel)


def no_response_due(start_utc: datetime, interview_utc: Optional[datetime] = None) -> datetime:
    """
    the approver is told the student has not responded after day 1's rounds. This does NOT end the sequence.
    With an interview coming up sooner than that, the approver is told an hour before it (never earlier than 30 minutes in).
    """
    due = start_utc + ROB_NO_RESPONSE_AFTER
    if interview_utc is not None and interview_utc - REMINDER_MARGIN < due:
        due = max(start_utc + timedelta(minutes=30), interview_utc - REMINDER_MARGIN)
    return due


def sequence_ended_due(plan: List[Planned], tz_name: str) -> datetime:
    """After the final day's attempts have had time to land, the sequence ends and the approver is told."""
    last = max(scheduled_time(p, tz_name) for p in plan)
    return last + ENDED_ALERT_AFTER_LAST_ATTEMPT


def collides_with_neighbour(candidate: datetime, others: List[datetime]) -> bool:
    """True if another same-channel attempt falls within MIN_SAME_CHANNEL_GAP of `candidate`."""
    return any(abs(o - candidate) < MIN_SAME_CHANNEL_GAP for o in others)

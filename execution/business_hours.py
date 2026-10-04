"""
Business-hours arithmetic for the "within one business hour" and "unapproved for 2 business hours" rules.

Pure functions, no I/O. The working week is configurable (environment, or the Settings screen's values passed in):
  BUSINESS_HOURS_TZ      time zone name, default America/Chicago (the company's working zone)
  BUSINESS_HOURS_START   first working hour, default 9
  BUSINESS_HOURS_END     last working hour (exclusive), default 17
  BUSINESS_DAYS          working weekdays, 0=Monday ... 6=Sunday, default 0,1,2,3,4
No public holidays are modelled: a holiday counts as a working day.
"""
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Tuple
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class BusinessHours:
    tz: str = "America/Chicago"
    start_hour: int = 9
    end_hour: int = 17
    days: Tuple[int, ...] = (0, 1, 2, 3, 4)

    @classmethod
    def from_env(cls, env: Optional[Dict[str, str]] = None) -> "BusinessHours":
        env = os.environ if env is None else env
        try:
            days = tuple(int(d) for d in (env.get("BUSINESS_DAYS") or "0,1,2,3,4").split(",") if d.strip() != "")
            start = int(env.get("BUSINESS_HOURS_START") or 9)
            end = int(env.get("BUSINESS_HOURS_END") or 17)
        except ValueError:
            return cls()
        if not (0 <= start < end <= 24) or not days or any(d < 0 or d > 6 for d in days):
            return cls()
        return cls(tz=(env.get("BUSINESS_HOURS_TZ") or "America/Chicago").strip(), start_hour=start, end_hour=end, days=days)


def _local(moment: datetime, tz: str) -> datetime:
    """A naive-UTC or aware datetime as aware local time."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(ZoneInfo(tz))


def is_business_time(moment: datetime, hours: BusinessHours) -> bool:
    local = _local(moment, hours.tz)
    return local.weekday() in hours.days and hours.start_hour <= local.hour < hours.end_hour


def add_business_minutes(start: datetime, minutes: float, hours: BusinessHours) -> datetime:
    """The moment `minutes` working minutes after `start` (naive UTC in, naive UTC out). Skips nights and weekends."""
    remaining = float(minutes)
    cur = _local(start, hours.tz)
    for _ in range(30):
        if cur.weekday() in hours.days:
            open_at = cur.replace(hour=hours.start_hour, minute=0, second=0, microsecond=0)
            midnight = cur.replace(hour=0, minute=0, second=0, microsecond=0)
            close_at = midnight + timedelta(days=1) if hours.end_hour >= 24 else cur.replace(hour=hours.end_hour, minute=0, second=0, microsecond=0)
            lo = max(cur, open_at)
            if lo < close_at:
                room = (close_at - lo).total_seconds() / 60.0
                if remaining <= room:
                    return (lo + timedelta(minutes=remaining)).astimezone(timezone.utc).replace(tzinfo=None)
                remaining -= room
        cur = cur.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    return start + timedelta(minutes=minutes)


def business_minutes_between(start: datetime, end: datetime, hours: BusinessHours) -> float:
    """Working minutes between two moments (0 when end <= start). Walks day by day, so it is exact across weekends and nights."""
    if end <= start:
        return 0.0
    s, e = _local(start, hours.tz), _local(end, hours.tz)
    total = 0.0
    day = s.replace(hour=0, minute=0, second=0, microsecond=0)
    while day <= e:
        if day.weekday() in hours.days:
            open_at = day.replace(hour=hours.start_hour) if hours.start_hour < 24 else day + timedelta(days=1)
            close_at = day + timedelta(days=1) if hours.end_hour >= 24 else day.replace(hour=hours.end_hour)
            lo, hi = max(open_at, s), min(close_at, e)
            if hi > lo:
                total += (hi - lo).total_seconds() / 60.0
        day += timedelta(days=1)
        day = day.replace(hour=0, minute=0, second=0, microsecond=0)
    return total

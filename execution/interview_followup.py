"""
Follow-ups on an interview the student was already told about.

A reminder, a reply or a second confirmation of the SAME interview (same moment) must not become a new student notice. Only a
cancellation, or an interview at a different moment, is news. Pure matching rules, no LLM: the model's "Rescheduled" label proved
unreliable (a plain reply was labelled "Rescheduled", 2026-10-15), so a change is decided by comparing times, not by the label.

Every doubt fails towards showing a card: no date or time, an unreadable time zone with different clock times, or two different named
companies all mean "not a follow-up".
"""
import calendar
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Hours from UTC. US zones are read by the DATE, not by the S/D letter: mail says "PST" in October when it means Pacific time on that day.
_FIXED_OFFSETS = {"UTC": 0, "GMT": 0, "Z": 0, "IST": 5.5}
_US_STANDARD_OFFSETS = {"E": -5, "C": -6, "M": -7, "P": -8}               # EST/EDT/ET -> E, and so on

ANNOUNCED_STATUSES = ("draft", "approved", "sent")                       # a notice a person has not rejected


def _nth_sunday(year: int, month: int, n: int) -> datetime:
    sundays = [d for d in range(1, calendar.monthrange(year, month)[1] + 1) if datetime(year, month, d).weekday() == 6]
    return datetime(year, month, sundays[n - 1])


def _us_daylight_saving(day: datetime) -> bool:
    """US rule: from the second Sunday of March to the first Sunday of November (by date)."""
    return _nth_sunday(day.year, 3, 2) <= day.replace(hour=0, minute=0) < _nth_sunday(day.year, 11, 1)


def interview_instant(date: Optional[str], time: Optional[str], tz: Optional[str]) -> Optional[datetime]:
    """The interview as a naive UTC datetime, or None when the date, the time or the time zone cannot be read."""
    try:
        wall = datetime.strptime(f"{(date or '').strip()} {(time or '').strip()[:5]}", "%Y-%m-%d %H:%M")
    except ValueError:
        return None
    zone = re.sub(r"[^A-Za-z]", "", tz or "").upper()
    if zone in _FIXED_OFFSETS:
        offset = _FIXED_OFFSETS[zone]
    elif zone in {f"{z}{d}" for z in _US_STANDARD_OFFSETS for d in ("T", "ST", "DT")}:
        offset = _US_STANDARD_OFFSETS[zone[0]] + (1 if _us_daylight_saving(wall) else 0)
    else:
        return None
    return wall - timedelta(hours=offset)


def same_moment(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    """True when two interviews are at the same time. A missing date or time is never "the same"."""
    ia = interview_instant(a.get("interview_date"), a.get("interview_time"), a.get("interview_timezone"))
    ib = interview_instant(b.get("interview_date"), b.get("interview_time"), b.get("interview_timezone"))
    if ia is not None and ib is not None:
        return ia == ib
    # A time zone is missing or unreadable on one side: only identical wall-clock date and time count.
    da, ta = (a.get("interview_date") or "").strip(), (a.get("interview_time") or "").strip()[:5]
    db_, tb = (b.get("interview_date") or "").strip(), (b.get("interview_time") or "").strip()[:5]
    return bool(da and ta) and (da, ta) == (db_, tb)


def _company_key(name: Optional[str]) -> str:
    n = re.sub(r"[^a-z0-9 ]+", "", (name or "").lower().replace("&", " and "))
    return " ".join(w for w in n.split() if w not in ("inc", "llc", "corp", "corporation", "co", "ltd", "company", "the"))


def companies_compatible(a: Optional[str], b: Optional[str]) -> bool:
    """Two different NAMED companies are different interviews; an email that names no company can still be about either."""
    ka, kb = _company_key(a), _company_key(b)
    return not ka or not kb or ka == kb


def _fields(event) -> Dict[str, Any]:
    return {"company_name": event.company_name, "interview_date": event.interview_date,
            "interview_time": event.interview_time, "interview_timezone": event.interview_timezone}


def find_scheduled_interview(db, student_id: Optional[int], fields: Dict[str, Any], before_event_id: Optional[int] = None) -> Optional[int]:
    """
    The id of the OLDEST earlier event of this student that already announced the same interview, or None.

    "Announced" = the event has a notice that is pending, approved or sent (a rejected notice was a person's decision not to tell the student,
    so a later email about it is asked again). A cancellation is never a follow-up. Grouping under the oldest means a pile of pending cards
    about one interview leaves the approver one card to decide.
    """
    from models import InterviewEvent, NotificationDraft, InterviewFollowUp

    if not student_id or (fields.get("interview_sub_type") or fields.get("sub_type")) == "Interview Cancelled":
        return None
    if not (fields.get("interview_date") and fields.get("interview_time")):
        return None
    query = (db.query(InterviewEvent)
             .join(NotificationDraft, NotificationDraft.interview_event_id == InterviewEvent.id)
             .filter(InterviewEvent.student_id == student_id, NotificationDraft.email_status.in_(ANNOUNCED_STATUSES),
                     InterviewEvent.sub_type != "Interview Cancelled")
             .order_by(InterviewEvent.id))
    if before_event_id is not None:
        query = query.filter(InterviewEvent.id < before_event_id)
    already_follow_ups = {row.event_id for row in db.query(InterviewFollowUp.event_id).all()}
    for earlier in query.all():
        if earlier.id in already_follow_ups:
            continue
        if companies_compatible(fields.get("company_name"), earlier.company_name) and same_moment(fields, _fields(earlier)):
            return earlier.id
    return None


def record_follow_up(db, event_id: int, original_event_id: int, reason: str = "same interview, same time") -> None:
    from models import InterviewFollowUp
    if db.query(InterviewFollowUp).filter(InterviewFollowUp.event_id == event_id).first() is None:
        db.add(InterviewFollowUp(event_id=event_id, original_event_id=original_event_id, reason=reason))
        db.commit()


def link_existing_follow_ups(db, dry_run: bool = True) -> list:
    """
    Clean the queue that exists today: every pending notice that repeats an earlier announced interview is linked and closed
    (rejected, reviewed_by 'follow-up'). Oldest first, so a pile collapses onto its first card. Dry run by default; nothing is sent either way.
    """
    from models import InterviewEvent, NotificationDraft
    from datetime import datetime as _dt

    out = []
    pending = (db.query(InterviewEvent, NotificationDraft)
               .join(NotificationDraft, NotificationDraft.interview_event_id == InterviewEvent.id)
               .filter(NotificationDraft.email_status == "draft").order_by(InterviewEvent.id).all())
    for event, draft in pending:
        fields = {**_fields(event), "sub_type": event.sub_type}
        original = find_scheduled_interview(db, event.student_id, fields, before_event_id=event.id)
        if original is None:
            continue
        out.append({"event_id": event.id, "draft_id": draft.id, "original_event_id": original})
        if not dry_run:
            record_follow_up(db, event.id, original)
            draft.email_status, draft.reviewed_by, draft.reviewed_at = "rejected", "follow-up", _dt.utcnow()
            db.commit()
    return out


def main(argv=None) -> int:
    """Usage (inside the cron container): python execution/interview_followup.py [--apply]  (lists only by default)."""
    import argparse
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    for p in (root / "execution", root, root / "services" / "dashboard" / "api"):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    ap = argparse.ArgumentParser(description="Link pending notices that repeat an already announced interview, and close them.")
    ap.add_argument("--apply", action="store_true", help="link and close them (default: list only)")
    args = ap.parse_args(argv)
    from process_inbox_auto import get_db_session
    db = get_db_session()
    if db is None:
        print("No database connection.")
        return 1
    rows = link_existing_follow_ups(db, dry_run=not args.apply)
    for r in rows:
        print(f"event {r['event_id']} draft {r['draft_id']} repeats the interview announced in event {r['original_event_id']}")
    print(f"{len(rows)} notice(s) " + ("linked and closed." if args.apply else "would be closed. List only: nothing changed."))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
